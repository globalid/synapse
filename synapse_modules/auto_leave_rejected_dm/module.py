"""Main module implementation for auto-leave rejected DM."""

import logging
from typing import Any, Dict, Optional, Tuple

from synapse.api.constants import EventTypes, Membership
from synapse.events import EventBase
from synapse.module_api import ModuleApi
from synapse.types import StateMap

from synapse_modules.auto_leave_rejected_dm.config import AutoLeaveConfig

logger = logging.getLogger(__name__)


class AutoLeaveRejectedDM:
    """
    Synapse module that auto-removes rejected DM invitations.

    When a user declines a 1:1 DM invitation (goes from 'invite' to 'leave'
    without ever joining), this module automatically makes the inviter leave
    the room as well, removing it from their room list.
    """

    def __init__(self, config: Dict[str, Any], api: ModuleApi):
        """
        Initialize the module.

        Args:
            config: Module configuration
            api: Synapse module API
        """
        self.api = api
        self.config = AutoLeaveConfig(config)
        self._store = api._store

        # Register event callback
        if self.config.enabled:
            self.api.register_third_party_rules_callbacks(
                on_new_event=self.on_new_event,
            )
            logger.info("AutoLeaveRejectedDM module initialized and enabled")
        else:
            logger.info("AutoLeaveRejectedDM module initialized but disabled")

    async def on_new_event(
        self, event: EventBase, state_events: StateMap[EventBase]
    ) -> None:
        """
        Handle new events.

        Args:
            event: The new event
            state_events: Current room state
        """
        try:
            # Only process member events
            if event.type != EventTypes.Member:
                return

            # Only process leave events
            membership = event.content.get("membership")
            if membership not in [Membership.LEAVE, Membership.BAN]:
                return

            # Check if this was a rejection of an invite (never joined)
            # Try to get previous membership from replaces_state
            prev_membership = await self._get_prev_membership(event)

            if prev_membership != Membership.INVITE:
                # User was a member before leaving, not a rejection
                return

            logger.info(
                f"Detected invite rejection: user {event.state_key} "
                f"rejected invite in room {event.room_id}"
            )

            # Get room members to check if it's a 1:1 DM
            room_members = await self._get_room_members(event.room_id)

            if not self._should_auto_leave(room_members):
                logger.info(
                    f"Room {event.room_id} has {len(room_members)} members, "
                    "not auto-leaving"
                )
                return

            # Find the inviter (the other user who is still in the room)
            inviter = self._find_inviter(room_members, event.state_key)

            if not inviter:
                logger.warning(
                    f"Could not find inviter in room {event.room_id}, "
                    f"members: {room_members}"
                )
                return

            # Force the inviter to leave the room
            await self._force_leave(inviter, event.room_id)

            logger.info(
                f"Auto-removed room {event.room_id} for inviter {inviter} "
                f"after {event.state_key} rejected invitation"
            )

        except Exception as e:
            logger.error(
                f"Error in AutoLeaveRejectedDM.on_new_event: {e}", exc_info=True
            )

    async def _get_prev_membership(self, event: EventBase) -> Optional[str]:
        """
        Get the previous membership status from the event.

        Args:
            event: Membership event

        Returns:
            Previous membership status, or None if not found
        """
        # Try replaces_state first (newer approach)
        replaces_state_id = event.unsigned.get("replaces_state")
        if replaces_state_id:
            try:
                prev_event = await self._store.get_event(
                    replaces_state_id, allow_none=True
                )
                if prev_event:
                    return prev_event.content.get("membership")
            except Exception as e:
                logger.debug(f"Could not fetch previous event: {e}")

        # Fallback to prev_content (older approach)
        prev_content = event.unsigned.get("prev_content", {})
        return prev_content.get("membership")

    async def _get_room_members(self, room_id: str) -> Dict[str, str]:
        """
        Get current room members and their membership status.

        Args:
            room_id: Room ID

        Returns:
            Dictionary mapping user_id to membership status
        """
        # Get current room state using the state handler
        state_ids = await self._store.get_partial_current_state_ids(room_id)

        members = {}
        for (event_type, state_key), event_id in state_ids.items():
            if event_type == EventTypes.Member:
                event = await self._store.get_event(event_id, allow_none=True)
                if event:
                    membership = event.content.get("membership")
                    # Only count users who are joined or invited
                    # (exclude users who already left)
                    if membership in [Membership.JOIN, Membership.INVITE]:
                        members[state_key] = membership

        return members

    def _should_auto_leave(self, members: Dict[str, str]) -> bool:
        """
        Check if we should auto-leave based on room membership.

        Args:
            members: Dictionary of user_id to membership status

        Returns:
            True if we should auto-leave, False otherwise
        """
        if not self.config.enabled:
            return False

        # Check if room is within size limits
        if len(members) > self.config.max_room_members:
            return False

        # If only_dms is enabled, require exactly 1 member left
        # (the inviter - the invitee just left)
        if self.config.only_dms:
            return len(members) == 1

        return True

    def _find_inviter(
        self, members: Dict[str, str], invitee: str
    ) -> Optional[str]:
        """
        Find the inviter (the remaining user in the room).

        Args:
            members: Dictionary of user_id to membership status
            invitee: User ID of the person who rejected the invite

        Returns:
            User ID of the inviter, or None if not found
        """
        # The inviter is the one remaining joined member
        # (not the invitee who just left)
        for user_id, membership in members.items():
            if user_id != invitee and membership == Membership.JOIN:
                return user_id

        return None

    async def _force_leave(self, user_id: str, room_id: str) -> None:
        """
        Force a user to leave a room.

        Args:
            user_id: User to remove
            room_id: Room to remove them from
        """
        try:
            # Use the module API to make the user leave
            # This will create a leave event as if the user left themselves
            await self.api.update_room_membership(
                sender=user_id,
                target=user_id,
                room_id=room_id,
                new_membership=Membership.LEAVE,
                content={"reason": "Other user declined chat invitation"},
            )

            logger.info(f"Successfully removed {user_id} from room {room_id}")

        except Exception as e:
            logger.error(
                f"Failed to remove {user_id} from room {room_id}: {e}", exc_info=True
            )
