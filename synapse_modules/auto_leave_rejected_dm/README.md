# Auto-Leave Rejected DM Module

## Overview

This Synapse module automatically removes 1:1 DM rooms from the inviter's room list when the invitee declines the invitation without ever joining.

## Problem

When a user invites another user to a 1:1 chat and the invitee declines:
- The invitee successfully leaves the room
- The inviter is left with an empty room showing "user rejected the request"
- The room remains in the inviter's chat list
- Poor UX for the inviter

## Solution

This module detects invitation rejections (membership: `invite` → `leave` without ever being `join`) and automatically makes the inviter leave the room as well.

## Configuration

Add to your `homeserver.yaml`:

```yaml
modules:
  - module: synapse_modules.auto_leave_rejected_dm.AutoLeaveRejectedDM
    config:
      # Enable/disable the module (default: true)
      enabled: true

      # Only process 1:1 DM rooms (default: true)
      only_dms: true

      # Maximum room size to consider (default: 2)
      max_room_members: 2
```

## How It Works

1. Registers callback for new events via `on_new_event`
2. Detects when:
   - Event is `m.room.member`
   - Membership becomes `leave` or `ban`
   - Previous membership was `invite` (rejection, not a regular leave)
   - Room has exactly 1 remaining member
3. Forces inviter to leave with reason: "Other user declined chat invitation"

## Features

- Works with encrypted rooms (only checks state events, not message content)
- Comprehensive error handling
- Configurable room size limits
- Detailed logging for debugging
- Can be disabled via config

## Testing

After enabling the module:

1. User A invites User B to 1:1 chat
2. User B declines the invitation
3. Room is automatically removed from User A's room list

Check logs:
```bash
docker compose logs -f | grep -i "auto.*leave"
```

Expected log messages:
- "Detected invite rejection: user @user:domain rejected invite in room !room:domain"
- "Auto-removed room !room:domain for inviter @inviter:domain"
