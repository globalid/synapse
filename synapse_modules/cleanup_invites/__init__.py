"""
Cleanup invites module for Synapse.

Provides an API endpoint to completely delete 1:1 DM rooms.
Can be called by either the inviter (to cancel invitation) or invitee (to decline).
Removes both users and purges the room from the database.
"""

from synapse_modules.cleanup_invites.module import CleanupInvitesModule

__all__ = ["CleanupInvitesModule"]
