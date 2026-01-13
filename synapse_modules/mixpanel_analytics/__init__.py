"""
Synapse module for tracking chat events in Mixpanel.

This module tracks the following events:
- message_sent
- attachment_sent
- chat_room_request_sent
- chat_room_request_accepted
- chat_room_request_rejected
- payment_card_sent
"""

from synapse_modules.mixpanel_analytics.module import MixpanelAnalytics

__all__ = ["MixpanelAnalytics"]
