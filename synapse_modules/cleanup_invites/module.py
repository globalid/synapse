"""Main module implementation for cleanup invites."""

import logging
from typing import Any, Dict

from synapse.module_api import ModuleApi

from synapse_modules.cleanup_invites.config import CleanupInvitesConfig

logger = logging.getLogger(__name__)


class CleanupInvitesModule:
    """
    Synapse module providing a delete room API for cleaning up DM invitations.

    Provides an API endpoint that allows either the inviter or invitee to
    completely delete a 1:1 DM room, removing both users.
    """

    def __init__(self, config: Dict[str, Any], api: ModuleApi):
        """
        Initialize the module.

        Args:
            config: Module configuration
            api: Synapse module API
        """
        self.api = api
        self.config = CleanupInvitesConfig(config)
        self._store = api._store

        if not self.config.enabled:
            logger.info("CleanupInvites module is disabled")
            return

        # Register delete room API endpoint
        from synapse_modules.cleanup_invites.resource import DeleteRoomResource
        resource = DeleteRoomResource(api, self)
        api.register_web_resource("/_synapse/client/delete_dm", resource)
        logger.info(
            "CleanupInvites module initialized. "
            "Endpoint available at: POST /_synapse/client/delete_dm"
        )

    @staticmethod
    def parse_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and validate the module configuration.

        Args:
            config: Raw configuration dictionary

        Returns:
            Validated configuration dictionary
        """
        return config
