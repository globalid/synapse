import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from synapse.api.constants import EventTypes, Membership
from synapse.events import EventBase
from synapse.types import JsonDict, StateMap, UserID

if TYPE_CHECKING:
    from synapse.module_api import ModuleApi
    from synapse_modules.mixpanel_analytics.mixpanel_client import MixpanelClient

logger = logging.getLogger(__name__)


class EventHandler:
    """Handles detection and processing of events for Mixpanel tracking."""

    def __init__(self, module_api: "ModuleApi", mixpanel_client: "MixpanelClient"):
        """
        Initialize event handler.

        Args:
            module_api: Synapse module API
            mixpanel_client: Mixpanel client for tracking events
        """
        self.module_api = module_api
        self.mixpanel_client = mixpanel_client
        self._store = module_api._store

    async def handle_event(
        self, event: EventBase, state_events: StateMap[EventBase]
    ) -> None:
        """
        Handle a new event and track it in Mixpanel if relevant.

        Args:
            event: The event to process
            state_events: Current room state
        """
        try:
            logger.info(f"got this event {vars(event)}")
            if event.type not in [EventTypes.Message, EventTypes.Member]:
                logger.info(f"not interested in event type {event.type}")
                return

            sender = event.sender
            user_id = UserID.from_string(sender)

            profile_info = await self._store.get_profileinfo(user_id)
            uns_name = profile_info.display_name
            # user id is "@<identity id>:<USBC chat domain>"
            identity_id = re.split(r"[@:]", sender)[1]

            device = await self._get_device(user_id=sender, event=event)

            props = {
                # this is how clients report distinct_id, let's make it unified
                "distinct_id": f"$device:{device["device_id"]}",
                # let's call it gid_uuid until we move to another name like uns/identity..
                "gid_uuid": identity_id,
                "uns_name": uns_name,
                "platform": device["platform"],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
            }

            # Determine event type and track
            if event.type == EventTypes.Message:
                await self._handle_message_event(event, props)
            elif event.type == EventTypes.Member:
                await self._handle_member_event(event, props)

        except Exception as e:
            logger.error(f"Error handling event for Mixpanel: {e}", exc_info=True)

    async def _get_device(
        self, user_id: str, event: Optional[EventBase] = None
    ) -> dict[str, str]:
        """
        Get device info and platform for a user.

        Args:
            event: Event to extract device from (preferred if available)
            user_id: User ID to get most recent device for (fallback)

        Returns:
            Dict with device_id and platform
        """
        try:
            user_agent = ""

            # If we have an event, use the device_id from it
            if event:
                device_id = event.internal_metadata.device_id

                device = await self._store.db_pool.simple_select_one(
                    table="devices",
                    keyvalues={"user_id": user_id, "device_id": device_id},
                    retcols=["user_agent"],
                    desc="get_device_info_for_mixpanel",
                    allow_none=True,
                )

                user_agent = device[0]

            # Otherwise, get the most recent device for the user
            else:
                devices = await self._store.db_pool.simple_select_list(
                    table="devices",
                    keyvalues={"user_id": user_id},
                    retcols=["device_id", "user_agent", "last_seen"],
                    desc="get_last_device_for_mixpanel",
                )

                if not devices:
                    return {"platform": "unknown", "device_id": "unknown"}

                # Sort by last_seen and get the most recent
                devices_sorted = sorted(
                    devices, key=lambda d: d[2] or 0, reverse=True
                )
                most_recent = devices_sorted[0]
                device_id = most_recent[0]
                user_agent = most_recent[1]

            # Detect platform from user agent (same logic for both paths)
            if re.search("android", user_agent, re.I):
                return {"platform": "Android", "device_id": device_id}
            elif re.search("ios", user_agent, re.I):
                return {"platform": "iOS", "device_id": device_id}
            elif re.search("chrome|gecko|safari|khtml|webkit", user_agent, re.I):
                return {"platform": "Web", "device_id": device_id}

            return {"platform": "unknown", "device_id": device_id}

        except Exception as e:
            logger.debug(f"Error determining platform for Mixpanel: {e}", exc_info=True)
            return {"platform": "unknown", "device_id": "unknown"}

    async def _handle_message_event(
        self, event: EventBase, user_props: Dict[str, Any]
    ) -> None:
        """
        Handle room message events.

        Detects:
        - message_sent (regular text messages)
        - attachment_sent (images, files, videos, audio)
        - payment_card_sent (payment-related messages)

        Args:
            event: Message event
            user_props: User properties
        """
        content = event.content
        msgtype = content.get("msgtype", "")
        body = content.get("body", "")

        logger.info(f"message type: {msgtype}, content: {content}, body: {body}")

        # Check for payment cards
        # Payment cards might be identified by custom message type or body content
        if self._is_payment_card(msgtype, body, content):
            await self._track_event("payment_card_sent", user_props)
            return

        # Check for attachments
        if msgtype in ["m.image", "m.file", "m.video", "m.audio"]:
            await self._track_event("attachment_sent", user_props)
            return

        # Regular text message
        if msgtype in ["m.text", "m.notice", "m.emote"]:
            await self._track_event("message_sent", user_props)
            return

        # Log unknown message types
        logger.debug(f"Unknown message type: {msgtype}")

    async def _handle_member_event(
        self, event: EventBase, user_props: Dict[str, Any]
    ) -> None:
        """
        Handle room membership events.

        Detects:
        - chat_room_request_sent (user invites another user)
        - chat_room_request_accepted (user accepts an invite)
        - chat_room_request_rejected (user rejects an invite)

        Args:
            event: Membership event
            user_props: User properties
        """
        content = event.content
        membership = content.get("membership")

        # Get previous membership from replaces_state if available
        prev_membership = None
        replaces_state_id = event.unsigned.get("replaces_state")
        if replaces_state_id:
            try:
                prev_event = await self._store.get_event(
                    replaces_state_id, allow_none=True
                )
                if prev_event:
                    prev_membership = prev_event.content.get("membership")
                    logger.debug(
                        f"Previous membership: {prev_membership} (from event {replaces_state_id})"
                    )
            except Exception as e:
                logger.warning(
                    f"Could not fetch previous event {replaces_state_id}: {e}"
                )

        logger.debug(
            f"Membership event - current: {membership}, previous: {prev_membership}, sender: {event.sender}, state_key: {event.get_state_key()}"
        )

        # Invite sent: someone invited this user
        # The sender is the inviter, state_key is the invitee
        if membership == Membership.INVITE:
            await self._track_event("chat_room_request_sent", user_props)

        # Invite accepted: user moved from invite to join
        elif membership == Membership.JOIN and prev_membership == Membership.INVITE:
            await self._track_event("chat_room_request_accepted", user_props)

        # Invite rejected: user moved from invite to leave
        elif membership == Membership.LEAVE and prev_membership == Membership.INVITE:
            await self._track_event("chat_room_request_rejected", user_props)

    def _is_payment_card(
        self, msgtype: str, body: str, content: Dict[str, Any]
    ) -> bool:
        """
        Determine if a message is a payment card.

        Payment cards are identified by:
        - type=REQUEST_TRANSFER or type=DIRECT_TRANSFER in URL

        Args:
            msgtype: Message type
            body: Message body
            content: Full message content

        Returns:
            True if this is a payment card message
        """
        # Check if it's a text message with custom HTML format
        if msgtype == "m.text":
            # Check both body and formatted_body for transfer type
            check_text = body + content.get("formatted_body", "")

            # Look for payment transfer type parameters
            if (
                "type=REQUEST_TRANSFER" in check_text
                or "type=DIRECT_TRANSFER" in check_text
            ):
                return True

        return False

    async def handle_account_data_update(
        self,
        user_id_str: str,
        room_id: Optional[str],
        account_data_type: str,
        content: JsonDict,
    ) -> None:
        """
        Handle account data updates for Mixpanel tracking.

        Args:
            user_id: The user whose account data changed
            account_data_type: Type of account data
            content: The new content
        """
        try:
            # Only handle ignored_user_list updates for now
            if account_data_type != "m.ignored_user_list":
                return

            # Get display name
            user_id = UserID.from_string(user_id_str)
            profile_info = await self._store.get_profileinfo(user_id)
            uns_name = profile_info.display_name
            # user id is "@<identity id>:<USBC chat domain>"
            identity_id = re.split(r"[@:]", user_id_str)[1]

            # Get device info using the most recent device for this user
            device = await self._get_device(user_id=user_id_str)

            props = {
                "distinct_id": f"$device:{device['device_id']}",
                "gid_uuid": identity_id,
                "uns_name": uns_name,
                "platform": device["platform"],
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
            }

            # Track to Mixpanel
            await self._track_event("user_block_action", props)

        except Exception as e:
            logger.error(
                f"Error handling account data update for Mixpanel: {e}", exc_info=True
            )

    async def _track_event(self, event_name: str, user_props: Dict[str, Any]) -> None:
        """
        Track an event in Mixpanel.

        Args:
            event_name: Name of the event to track
            user_props: User properties
        """
        await self.mixpanel_client.track(
            user_props["distinct_id"], event_name, user_props
        )
        logger.info(f"Tracked {event_name} for user {user_props['distinct_id']}")
