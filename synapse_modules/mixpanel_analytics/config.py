"""Configuration handling for Mixpanel analytics module."""

import os
from typing import Any, Dict


class MixpanelConfig:
    """Configuration for Mixpanel analytics module."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize configuration.

        Expected config structure:
        {
            "mixpanel_token": "your-mixpanel-project-token",  # Optional if MIXPANEL_PROJECT_TOKEN env var is set
            "enabled": true,  # Optional, defaults to true
            "debug": false    # Optional, defaults to false
        }

        The mixpanel_token is read from the MIXPANEL_PROJECT_TOKEN environment variable first,
        falling back to the config value if not set.
        """
        # Read from environment variable first, fall back to config
        self.mixpanel_token = os.environ.get("MIXPANEL_PROJECT_TOKEN") or config.get("mixpanel_token")
        if not self.mixpanel_token:
            raise ValueError(
                "mixpanel_token is required: set MIXPANEL_PROJECT_TOKEN environment variable "
                "or provide mixpanel_token in module config"
            )

        self.enabled = config.get("enabled", True)
        self.debug = config.get("debug", False)

    def __repr__(self) -> str:
        return f"<MixpanelConfig enabled={self.enabled} debug={self.debug}>"
