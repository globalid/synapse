"""Configuration for auto-leave rejected DM module."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class AutoLeaveConfig:
    """Configuration for the auto-leave module."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize configuration.

        Args:
            config: Module configuration dictionary
        """
        # Enable/disable the module
        self.enabled = config.get("enabled", True)

        # Only process DMs (rooms with exactly 2 members)
        self.only_dms = config.get("only_dms", True)

        # Maximum room size to consider (safety check)
        self.max_room_members = config.get("max_room_members", 2)

        logger.info(
            f"AutoLeaveRejectedDM config: enabled={self.enabled}, "
            f"only_dms={self.only_dms}, max_room_members={self.max_room_members}"
        )

    @staticmethod
    def parse_config(config: Dict[str, Any]) -> "AutoLeaveConfig":
        """
        Parse and validate configuration.

        Args:
            config: Raw configuration dictionary

        Returns:
            Parsed configuration object
        """
        return AutoLeaveConfig(config)
