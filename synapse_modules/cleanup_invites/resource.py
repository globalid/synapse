"""HTTP resource for deleting DM rooms."""

import logging
from typing import Dict, Optional, Tuple

from synapse.api.constants import Membership
from synapse.api.errors import AuthError, SynapseError
from synapse.http.server import DirectServeJsonResource
from synapse.http.servlet import parse_json_object_from_request
from synapse.http.site import SynapseRequest
from synapse.module_api import ModuleApi

logger = logging.getLogger(__name__)


class DeleteRoomResource(DirectServeJsonResource):
    """
    HTTP endpoint to delete DM rooms.

    POST /_synapse/client/delete_dm
    Body: {"room_id": "!abc:server"}
    Authorization: Bearer <access_token>

    Can be called by either the inviter or invitee to completely delete
    a 1:1 DM room, removing both users.
    """

    isLeaf = True

    def __init__(self, module_api: ModuleApi, module):
        super().__init__()
        self._api = module_api
        self._auth = module_api._auth
        self._store = module_api._store
        self._module = module

    async def _async_render_POST(
        self, request: SynapseRequest
    ) -> Tuple[int, Dict]:
        """
        Handle POST request to delete room.

        Returns:
            Tuple of (status_code, response_dict)
        """
        # 1. Parse request body
        content = parse_json_object_from_request(request)
        room_id = content.get("room_id")

        if not room_id:
            raise SynapseError(400, "Missing room_id")

        # 2. Authenticate user
        access_token = self._get_access_token(request)
        if not access_token:
            raise AuthError(401, "Missing access token")

        requester = await self._auth.get_user_by_access_token(access_token)
        user_id = requester.user.to_string()

        logger.info(
            f"[DELETE_DM] User {user_id} requesting to delete room {room_id}"
        )

        # 3. Validate room and user membership
        await self._validate_dm_room(room_id, user_id)

        # 4. Delete the room
        logger.info(f"[DELETE_DM] Deleting room {room_id}")
        await self._api.delete_room(room_id)

        logger.info(
            f"[DELETE_DM] Successfully deleted room {room_id} by user {user_id}"
        )

        return 200, {
            "success": True,
            "message": "Room deleted successfully"
        }

    async def _validate_dm_room(self, room_id: str, user_id: str) -> None:
        """
        Validate that:
        1. Room is a DM (has 2 members: inviter + invitee)
        2. User is one of those members

        Args:
            room_id: Room to validate
            user_id: User requesting deletion

        Raises:
            SynapseError if validation fails
        """
        # Try to get room members using room_memberships table
        # This should be more reliable than current_state tables
        def _query_txn(txn):
            # Get the most recent membership event for each user in the room
            txn.execute(
                """
                SELECT DISTINCT user_id, membership
                FROM room_memberships
                WHERE room_id = ?
                AND event_id IN (
                    SELECT MAX(event_id)
                    FROM room_memberships
                    WHERE room_id = ?
                    GROUP BY user_id
                )
                """,
                (room_id, room_id),
            )
            rows = txn.fetchall()
            logger.info(f"[DELETE_DM] Room {room_id} memberships: {rows}")
            return {row[0]: row[1] for row in rows}

        members = await self._store.db_pool.runInteraction(
            "delete_dm_get_members",
            _query_txn
        )

        if not members:
            logger.warning(f"[DELETE_DM] Could not fetch members for room {room_id}")
            raise SynapseError(400, f"Invalid room")


        # Count active members (joined or invited)
        active_members = {
            uid: m for uid, m in members.items()
            if m in [Membership.JOIN, Membership.INVITE]
        }

        logger.info(f"[DELETE_DM] Active members: {active_members}")

        # Check if it's a DM (should have at most 2 active members)
        if len(active_members) > 2:
            logger.warning(
                f"[DELETE_DM] Not a DM room. Has {len(active_members)} active members (max 2 expected)"
            )
            raise SynapseError(400, f"Invalid room")

        # Check if requester is one of the members
        if user_id not in members:
            logger.warning(f"[DELETE_DM] Not a member of DM room.")
            raise SynapseError(403, "You are not a member of this room")

        logger.info(
            f"[DELETE_DM] Validation passed: DM with {len(active_members)} members, "
                f"requester {user_id} is a member: {members}"
        )

    def _get_access_token(self, request: SynapseRequest) -> Optional[str]:
        """Extract access token from request."""
        # Try Authorization header first
        auth_headers = request.requestHeaders.getRawHeaders("Authorization")
        if auth_headers:
            auth_header = auth_headers[0]
            if auth_header.startswith("Bearer "):
                return auth_header[7:]

        # Fall back to query parameter
        if b"access_token" in request.args:
            return request.args[b"access_token"][0].decode("utf-8")

        return None
