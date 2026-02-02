"""
Auto-leave rejected DM invitations module for Synapse.

This module automatically removes 1:1 DM rooms from the inviter's room list
when the invitee declines the invitation without ever joining.
"""

from synapse_modules.auto_leave_rejected_dm.module import AutoLeaveRejectedDM

__all__ = ["AutoLeaveRejectedDM"]
