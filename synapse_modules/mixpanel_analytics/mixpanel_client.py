import json
import logging
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from synapse.http.client import SimpleHttpClient

logger = logging.getLogger(__name__)


class MixpanelClient:
    """Client for sending events to Mixpanel."""

    MIXPANEL_API_URL = "https://api.mixpanel.com/track"

    def __init__(
        self, token: str, http_client: "SimpleHttpClient", debug: bool = False
    ):
        """
        Initialize Mixpanel client.

        Args:
            token: Mixpanel project token
            http_client: Synapse HTTP client
            debug: If True, log events instead of sending to Mixpanel
        """
        self.token = token
        self.debug = debug
        self._http_client = http_client

    async def track(self, event_name: str, properties: Dict[str, Any]) -> None:
        """
        Track an event in Mixpanel.

        Args:
            event_name: Name of the event to track
            properties: Properties to include with the event
        """
        # Add token to properties
        properties_with_token = {**properties, "token": self.token}

        event_data = {"event": event_name, "properties": properties_with_token}

        if self.debug:
            logger.info(
                f"[DEBUG MODE] Would send to Mixpanel: {json.dumps(event_data, indent=2)}"
            )
            return

        try:
            # Mixpanel expects an array of events
            payload = [event_data]

            # Send to Mixpanel
            # Note: Mixpanel returns "1" as text/plain, not JSON
            # We'll use the raw HTTP client method instead
            response = await self._http_client.post_json_get_json(
                self.MIXPANEL_API_URL, payload
            )

            # Mixpanel returns 1 on success (as a number when parsed)
            if response == 1:
                logger.debug(f"Successfully tracked event: {event_name}")
            else:
                logger.warning(
                    f"Mixpanel returned unexpected response: {response}"
                )

        except Exception as e:
            logger.error(
                f"Failed to track event {event_name} to Mixpanel: {e}",
                exc_info=True,
            )
