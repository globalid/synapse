import logging
from typing import Any, Dict, Optional

from synapse.events import EventBase
from synapse.module_api import ModuleApi
from synapse.types import JsonDict, StateMap
from synapse_modules.mixpanel_analytics.config import MixpanelConfig
from synapse_modules.mixpanel_analytics.event_handlers import EventHandler
from synapse_modules.mixpanel_analytics.mixpanel_client import MixpanelClient

logger = logging.getLogger(__name__)


class MixpanelAnalytics:
    """
    Synapse module for tracking chat events in Mixpanel.

    This module tracks the following events:
    - message_sent: When a user sends a text message
    - attachment_sent: When a user sends an attachment (image, file, video, audio)
    - chat_room_request_sent: When a user invites another user to a room
    - chat_room_request_accepted: When a user accepts a room invitation
    - chat_room_request_rejected: When a user rejects a room invitation
    - payment_card_sent: When a payment-related card is sent
    - user_blocked: When a user blocks another user (future)
    - user_unblocked: When a user unblocks another user (future)

    Configuration example:
    ```yaml
    modules:
      - module: synapse_modules.mixpanel_analytics.MixpanelAnalytics
        config:
          mixpanel_token: "your-mixpanel-project-token"
          enabled: true
          debug: false
    ```
    """

    def __init__(self, config: Dict[str, Any], api: ModuleApi):
        """
        Initialize the Mixpanel analytics module.

        Args:
            config: Module configuration dictionary
            api: Synapse module API
        """
        self._api = api
        self._config = MixpanelConfig(config)

        if not self._config.enabled:
            logger.info("Mixpanel analytics module is disabled")
            return

        logger.info(
            f"Initializing Mixpanel analytics module (debug={self._config.debug})"
        )

        # Initialize Mixpanel client
        self._mixpanel_client = MixpanelClient(
            api,
            token=self._config.mixpanel_token,
            debug=self._config.debug,
        )

        # Initialize event handler
        self._event_handler = EventHandler(api, self._mixpanel_client)

        # Register callbacks
        self._api.register_third_party_rules_callbacks(
            on_new_event=self._on_new_event,
        )

        # Register account data callbacks for tracking block/unblock events
        self._api.register_account_data_callbacks(
            on_account_data_updated=self._on_account_data_updated,
        )

        logger.info("Mixpanel analytics module initialized successfully")

    async def _on_new_event(
        self, event: EventBase, state_events: StateMap[EventBase]
    ) -> None:
        """
        Callback triggered when a new event is created.

        Args:
            event: The new event
            state_events: Current room state
        """
        if not self._config.enabled:
            return

        logger.info(f"Mixpanel analytics - got new event: {event}")

        await self._event_handler.handle_event(event, state_events)

    async def _on_account_data_updated(
        self,
        user_id: str,
        room_id: Optional[str],
        account_data_type: str,
        content: JsonDict,
    ) -> None:
        """
        Callback triggered when account data is updated.

        Args:
            user_id: The user whose account data changed
            room_id: The room ID (None for global account data)
            account_data_type: Type of account data (e.g., "m.ignored_user_list")
            content: The new content
        """
        if not self._config.enabled:
            return

        logger.info(
            f"Mixpanel analytics - account data updated: user={user_id}, "
            f"type={account_data_type}, room={room_id}, content={content}"
        )

        # For now, just log it - we'll add tracking logic next
        if account_data_type == "m.ignored_user_list":
            ignored_users = content.get("ignored_users", {})
            logger.info(
                f"User {user_id} updated block list. Currently blocking: {list(ignored_users.keys())}"
            )

    @staticmethod
    def parse_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and validate the module configuration.

        This is an optional static method that Synapse will call if it exists.

        Args:
            config: Raw configuration dictionary

        Returns:
            Validated configuration dictionary

        Raises:
            ValueError: If configuration is invalid
        """
        # mixpanel_token can come from MIXPANEL_PROJECT_TOKEN environment variable
        return config
