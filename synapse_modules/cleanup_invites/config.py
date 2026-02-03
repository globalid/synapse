"""Configuration for cleanup invites module."""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


class CleanupInvitesConfig:
    """Configuration for the cleanup invites module."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize configuration.

        Args:
            config: Module configuration dictionary
        """
        # Enable/disable the API (default: true)
        self.enabled = config.get("enabled", True)

        logger.info(f"CleanupInvites config: enabled={self.enabled}")

    @staticmethod
    def parse_config(config: Dict[str, Any]) -> "CleanupInvitesConfig":
        """
        Parse and validate configuration.

        Args:
            config: Raw configuration dictionary

        Returns:
            Parsed configuration object
        """
        return CleanupInvitesConfig(config)
