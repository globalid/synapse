import logging
import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, Optional

from synapse.api.constants import EventTypes, Membership
from synapse.events import EventBase
from synapse.types import StateMap, UserID

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

            logger.info(f"got this event type {event.type}")
            #if event.type not in [EventTypes.Message, EventTypes.Member]:
            #    logger.info(f"not interested in event type {event.type}")
            #    return

            props = {
                "identity_id": "unknown",
                "uns_name": "unknown",
                "platform": "unknown",
                "timestamp":  datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%SZ'),
            }

            sender = event.sender
            user_id = UserID.from_string(sender)
            device_id = event.internal_metadata.device_id

            profile_info = await self._store.get_profileinfo(user_id)
            props["uns_name"] = profile_info.display_name
            # user id is "@<identity id>:<USBC chat domain>"
            props["identity_id"] = re.split(r'[@:]', sender)[1]

            device = await self._store.db_pool.simple_select_one(
                table="devices",
                keyvalues={"user_id": sender, "device_id": device_id},
                #retcols=("display_name", "user_agent", "last_seen", "ip"),
                retcols=["user_agent"],
                desc="get_device_info_for_mixpanel",
                allow_none=True,
            )

            user_agent = device[0]

            if re.search("android", user_agent, re.I):
                props["platform"] = "android"
            elif re.search("ios", user_agent, re.I):
                props["platform"] = "ios"
            elif re.search("chrome|gecko|safari|khtml|webkit", user_agent, re.I):
                props["platform"] = "web"

            logger.info(f"Got event : {props}")

            if event.type not in ["foo"]:
                logger.info(f"not interested in event type {event.type}")
                return


            # Determine event type and track
            #if event.type == EventTypes.Message:
            #    await self._handle_message_event(event, props)
            #elif event.type == EventTypes.Member:
            #    await self._handle_member_event(event, props)

        except Exception as e:
            logger.error(f"Error handling event for Mixpanel: {e}", exc_info=True)


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
            await self._track_event("payment_card_sent", event, user_props)
            return

        # Check for attachments
        if msgtype in ["m.image", "m.file", "m.video", "m.audio"]:
            await self._track_event("attachment_sent", event, user_props)
            return

        # Regular text message
        if msgtype in ["m.text", "m.notice", "m.emote"]:
            await self._track_event("message_sent", event, user_props)
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
        prev_membership = event.unsigned.get("prev_content", {}).get("membership")

        logger.info(f"membership: {membership}, content: {content}")

        # Invite sent: someone invited this user
        # We track from the inviter's perspective
        if membership == Membership.INVITE and prev_membership != Membership.INVITE:
            # The sender is the inviter, state_key is the invitee
            # We want to track this from the inviter's perspective
            await self._track_event("chat_room_request_sent", event, user_props)

        # Invite accepted: user moved from invite to join
        elif membership == Membership.JOIN and prev_membership == Membership.INVITE:
            await self._track_event("chat_room_request_accepted", event, user_props)

        # Invite rejected: user moved from invite to leave/ban
        elif (
            membership in [Membership.LEAVE, Membership.BAN]
            and prev_membership == Membership.INVITE
        ):
            await self._track_event("chat_room_request_rejected", event, user_props)

    def _is_payment_card(
        self, msgtype: str, body: str, content: Dict[str, Any]
    ) -> bool:
        """
        Determine if a message is a payment card.

        This is a heuristic that can be adjusted based on how payment cards
        are implemented in the GID messaging system.

        Args:
            msgtype: Message type
            body: Message body
            content: Full message content

        Returns:
            True if this is a payment card message
        """
        # Check for custom payment message type
        if msgtype in ["m.payment", "m.payment.request", "m.payment.send"]:
            return True

        # Check for payment-related custom fields
        if "payment" in content or "payment_card" in content:
            return True

        # Check body for payment keywords (if payment cards use regular messages)
        payment_keywords = ["payment", "pay request", "payment card", "$"]
        if any(keyword in body.lower() for keyword in payment_keywords):
            # Additional validation could be added here
            # For now, being conservative
            pass

        return False

    async def _track_event(
        self, event_name: str, event: EventBase, user_props: Dict[str, Any]
    ) -> None:
        """
        Track an event in Mixpanel.

        Args:
            event_name: Name of the event to track
            event: The Matrix event
            user_props: User properties
        """
        properties = {
            **user_props,
            "timestamp": event.origin_server_ts / 1000,  # Convert to seconds
            "room_id": event.room_id,
            "event_id": event.event_id,
        }

        await self.mixpanel_client.track(event_name, properties)
        logger.info(f"Tracked {event_name} for user {user_props['distinct_id']}")
