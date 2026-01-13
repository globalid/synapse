"""Configuration handling for Mixpanel analytics module."""

from typing import Any, Dict


class MixpanelConfig:
    """Configuration for Mixpanel analytics module."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize configuration.

        Expected config structure:
        {
            "mixpanel_token": "your-mixpanel-project-token",
            "enabled": true,  # Optional, defaults to true
            "debug": false    # Optional, defaults to false
        }
        """
        self.mixpanel_token = config.get("mixpanel_token")
        if not self.mixpanel_token:
            raise ValueError("mixpanel_token is required in module config")

        self.enabled = config.get("enabled", True)
        self.debug = config.get("debug", False)

    def __repr__(self) -> str:
        return f"<MixpanelConfig enabled={self.enabled} debug={self.debug}>"
