import json
import logging
from typing import Any, Dict

from mixpanel import Mixpanel

logger = logging.getLogger(__name__)


class MixpanelClient:
    """Client for sending events to Mixpanel using the official SDK."""

    def __init__(self, token: str, debug: bool = False):
        """
        Initialize Mixpanel client.

        Args:
            token: Mixpanel project token
            debug: If True, log events instead of sending to Mixpanel
        """
        self.token = token
        self.debug = debug
        self._mp = Mixpanel(token) if not debug else None

    async def track(
        self, distinct_id: str, event_name: str, properties: Dict[str, Any]
    ) -> None:
        """
        Track an event in Mixpanel.

        Args:
            distinct_id: Unique identifier for the user
            event_name: Name of the event to track
            properties: Properties to include with the event
        """
        if self.debug:
            event_data = {
                "event": event_name,
                "properties": {"distinct_id": distinct_id, **properties},
            }
            logger.info(
                f"[DEBUG MODE] Would send to Mixpanel: {json.dumps(event_data, indent=2)}"
            )
            return

        try:
            self._mp.track(distinct_id, event_name, properties)
            logger.debug(f"Successfully tracked event: {event_name} for user {distinct_id}")

        except Exception as e:
            logger.error(
                f"Failed to track event {event_name} to Mixpanel: {e}",
                exc_info=True,
            )
