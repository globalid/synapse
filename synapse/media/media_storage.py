#
# This file is licensed under the Affero General Public License (AGPL) version 3.
#
# Copyright 2018-2021 The Matrix.org Foundation C.I.C.
# Copyright (C) 2023 New Vector, Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# See the GNU Affero General Public License for more details:
# <https://www.gnu.org/licenses/agpl-3.0.html>.
#
# Originally licensed under the Apache License, Version 2.0:
# <http://www.apache.org/licenses/LICENSE-2.0>.
#
# [This file includes modifications made by New Vector Limited]
#
#
import contextlib
import logging
import os
import shutil
from types import TracebackType
from typing import (
    IO,
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    BinaryIO,
    Callable,
    Optional,
    Sequence,
    Tuple,
    Type,
)

import attr

from twisted.internet.defer import Deferred
from twisted.internet.interfaces import IConsumer
from twisted.protocols.basic import FileSender

from synapse.api.errors import NotFoundError
from synapse.logging.context import defer_to_thread, make_deferred_yieldable
from synapse.logging.opentracing import start_active_span, trace, trace_with_opname
from synapse.util import Clock
from synapse.util.file_consumer import BackgroundFileConsumer

from ._base import FileInfo, Responder
from .filepath import MediaFilePaths

if TYPE_CHECKING:
    from synapse.media.storage_provider import StorageProvider
    from synapse.server import HomeServer

logger = logging.getLogger(__name__)


class MediaStorage:
    """Responsible for storing/fetching files from local sources.

    Args:
        hs
        local_media_directory: Base path where we store media on disk
        filepaths
        storage_providers: List of StorageProvider that are used to fetch and store files.
    """

    def __init__(
        self,
        hs: "HomeServer",
        local_media_directory: str,
        filepaths: MediaFilePaths,
        storage_providers: Sequence["StorageProvider"],
    ):
        self.hs = hs
        self.reactor = hs.get_reactor()
        self.local_media_directory = local_media_directory
        self.filepaths = filepaths
        self.storage_providers = storage_providers
        self._spam_checker_module_callbacks = hs.get_module_api_callbacks().spam_checker
        self.clock = hs.get_clock()

    @trace_with_opname("MediaStorage.store_file")
    async def store_file(self, source: IO, file_info: FileInfo) -> str:
        """Write `source` to the on disk media store, and also any other
        configured storage providers

        Args:
            source: A file like object that should be written
            file_info: Info about the file to store

        Returns:
            the file path written to in the primary media store
        """

        async with self.store_into_file(file_info) as (f, fname):
            # Write to the main media repository
            await self.write_to_file(source, f)

        return fname

    @trace_with_opname("MediaStorage.write_to_file")
    async def write_to_file(self, source: IO, output: IO) -> None:
        """Asynchronously write the `source` to `output`."""
        await defer_to_thread(self.reactor, _write_file_synchronously, source, output)

    @trace_with_opname("MediaStorage.store_into_file")
    @contextlib.asynccontextmanager
    async def store_into_file(
        self, file_info: FileInfo
    ) -> AsyncIterator[Tuple[BinaryIO, str]]:
        """Async Context manager used to get a file like object to write into, as
        described by file_info.

        Actually yields a 2-tuple (file, fname,), where file is a file
        like object that can be written to and fname is the absolute path of file
        on disk.

        fname can be used to read the contents from after upload, e.g. to
        generate thumbnails.

        Args:
            file_info: Info about the file to store

        Example:

            async with media_storage.store_into_file(info) as (f, fname,):
                # .. write into f ...
        """

        path = self._file_info_to_path(file_info)
        fname = os.path.join(self.local_media_directory, path)

        dirname = os.path.dirname(fname)
        os.makedirs(dirname, exist_ok=True)

        try:
            with start_active_span("writing to main media repo"):
                with open(fname, "wb") as f:
                    yield f, fname

            with start_active_span("writing to other storage providers"):
                spam_check = (
                    await self._spam_checker_module_callbacks.check_media_file_for_spam(
                        ReadableFileWrapper(self.clock, fname), file_info
                    )
                )
                if spam_check != self._spam_checker_module_callbacks.NOT_SPAM:
                    logger.info("Blocking media due to spam checker")
                    # Note that we'll delete the stored media, due to the
                    # try/except below. The media also won't be stored in
                    # the DB.
                    # We currently ignore any additional field returned by
                    # the spam-check API.
                    raise SpamMediaException(errcode=spam_check[0])

                for provider in self.storage_providers:
                    with start_active_span(str(provider)):
                        await provider.store_file(path, file_info)

        except Exception as e:
            try:
                os.remove(fname)
            except Exception:
                pass

            raise e from None

    async def fetch_media(self, file_info: FileInfo) -> Optional[Responder]:
        """Attempts to fetch media described by file_info from the local cache
        and configured storage providers.

        Args:
            file_info

        Returns:
            Returns a Responder if the file was found, otherwise None.
        """
        paths = [self._file_info_to_path(file_info)]

        # fallback for remote thumbnails with no method in the filename
        if file_info.thumbnail and file_info.server_name:
            paths.append(
                self.filepaths.remote_media_thumbnail_rel_legacy(
                    server_name=file_info.server_name,
                    file_id=file_info.file_id,
                    width=file_info.thumbnail.width,
                    height=file_info.thumbnail.height,
                    content_type=file_info.thumbnail.type,
                )
            )

        for path in paths:
            local_path = os.path.join(self.local_media_directory, path)
            if os.path.exists(local_path):
                logger.debug("responding with local file %s", local_path)
                return FileResponder(open(local_path, "rb"))
            logger.debug("local file %s did not exist", local_path)

        for provider in self.storage_providers:
            for path in paths:
                res: Any = await provider.fetch(path, file_info)
                if res:
                    logger.debug("Streaming %s from %s", path, provider)
                    return res
                logger.debug("%s not found on %s", path, provider)

        return None

    @trace
    async def ensure_media_is_in_local_cache(self, file_info: FileInfo) -> str:
        """Ensures that the given file is in the local cache. Attempts to
        download it from storage providers if it isn't.

        Args:
            file_info

        Returns:
            Full path to local file
        """
        path = self._file_info_to_path(file_info)
        local_path = os.path.join(self.local_media_directory, path)
        if os.path.exists(local_path):
            return local_path

        # Fallback for paths without method names
        # Should be removed in the future
        if file_info.thumbnail and file_info.server_name:
            legacy_path = self.filepaths.remote_media_thumbnail_rel_legacy(
                server_name=file_info.server_name,
                file_id=file_info.file_id,
                width=file_info.thumbnail.width,
                height=file_info.thumbnail.height,
                content_type=file_info.thumbnail.type,
            )
            legacy_local_path = os.path.join(self.local_media_directory, legacy_path)
            if os.path.exists(legacy_local_path):
                return legacy_local_path

        dirname = os.path.dirname(local_path)
        os.makedirs(dirname, exist_ok=True)

        for provider in self.storage_providers:
            res: Any = await provider.fetch(path, file_info)
            if res:
                with res:
                    consumer = BackgroundFileConsumer(
                        open(local_path, "wb"), self.reactor
                    )
                    await res.write_to_consumer(consumer)
                    await consumer.wait()
                return local_path

        raise NotFoundError()

    @trace
    def _file_info_to_path(self, file_info: FileInfo) -> str:
        """Converts file_info into a relative path.

        The path is suitable for storing files under a directory, e.g. used to
        store files on local FS under the base media repository directory.
        """
        if file_info.url_cache:
            if file_info.thumbnail:
                return self.filepaths.url_cache_thumbnail_rel(
                    media_id=file_info.file_id,
                    width=file_info.thumbnail.width,
                    height=file_info.thumbnail.height,
                    content_type=file_info.thumbnail.type,
                    method=file_info.thumbnail.method,
                )
            return self.filepaths.url_cache_filepath_rel(file_info.file_id)

        if file_info.server_name:
            if file_info.thumbnail:
                return self.filepaths.remote_media_thumbnail_rel(
                    server_name=file_info.server_name,
                    file_id=file_info.file_id,
                    width=file_info.thumbnail.width,
                    height=file_info.thumbnail.height,
                    content_type=file_info.thumbnail.type,
                    method=file_info.thumbnail.method,
                )
            return self.filepaths.remote_media_filepath_rel(
                file_info.server_name, file_info.file_id
            )

        if file_info.thumbnail:
            return self.filepaths.local_media_thumbnail_rel(
                media_id=file_info.file_id,
                width=file_info.thumbnail.width,
                height=file_info.thumbnail.height,
                content_type=file_info.thumbnail.type,
                method=file_info.thumbnail.method,
            )
        return self.filepaths.local_media_filepath_rel(file_info.file_id)


@trace
def _write_file_synchronously(source: IO, dest: IO) -> None:
    """Write `source` to the file like `dest` synchronously. Should be called
    from a thread.

    Args:
        source: A file like object that's to be written
        dest: A file like object to be written to
    """
    source.seek(0)  # Ensure we read from the start of the file
    shutil.copyfileobj(source, dest)


class FileResponder(Responder):
    """Wraps an open file that can be sent to a request.

    Args:
        open_file: A file like object to be streamed ot the client,
            is closed when finished streaming.
    """

    def __init__(self, open_file: IO):
        self.open_file = open_file

    def write_to_consumer(self, consumer: IConsumer) -> Deferred:
        return make_deferred_yieldable(
            FileSender().beginFileTransfer(self.open_file, consumer)
        )

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        self.open_file.close()


class SpamMediaException(NotFoundError):
    """The media was blocked by a spam checker, so we simply 404 the request (in
    the same way as if it was quarantined).
    """


@attr.s(slots=True, auto_attribs=True)
class ReadableFileWrapper:
    """Wrapper that allows reading a file in chunks, yielding to the reactor,
    and writing to a callback.

    This is simplified `FileSender` that takes an IO object rather than an
    `IConsumer`.
    """

    CHUNK_SIZE = 2**14

    clock: Clock
    path: str

    async def write_chunks_to(self, callback: Callable[[bytes], object]) -> None:
        """Reads the file in chunks and calls the callback with each chunk."""

        with open(self.path, "rb") as file:
            while True:
                chunk = file.read(self.CHUNK_SIZE)
                if not chunk:
                    break

                callback(chunk)

                # We yield to the reactor by sleeping for 0 seconds.
                await self.clock.sleep(0)
