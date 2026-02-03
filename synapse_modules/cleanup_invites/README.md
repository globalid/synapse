# Cleanup Invites Module

## Overview

This Synapse module provides an API endpoint to completely delete 1:1 DM rooms, removing both the inviter and invitee.

## Use Case

When dealing with DM invitations, users can use the standard Matrix decline/leave endpoints, but those leave the room in the database. This module provides a **delete** endpoint that:

- Completely removes the room from the database
- Works for both inviter (cancel invitation) and invitee (decline invitation)
- Cleans up for both parties at once

## Configuration

Add to your `homeserver.yaml`:

```yaml
modules:
  - module: synapse_modules.cleanup_invites.CleanupInvitesModule
    config:
      # Enable/disable the API (default: true)
      enabled: true
```

## API Usage

### Endpoint

```
POST /_synapse/client/delete_dm
```

### Authentication

Include access token in one of:
- **Header**: `Authorization: Bearer <access_token>`
- **Query param**: `?access_token=<access_token>`

### Request Body

```json
{
  "room_id": "!abc123:server.com"
}
```

### Response

**Success (200)**:
```json
{
  "success": true,
  "message": "Room deleted successfully"
}
```

**Error (4xx/5xx)**:
```json
{
  "error": "Not a DM room. Has 5 active members (max 2 expected)",
  "errcode": "M_ERROR"
}
```

## How It Works

1. User (inviter or invitee) calls API with room_id
2. API authenticates the user
3. API validates:
   - Room is a DM (max 2 active members)
   - Requester is a member of the room
4. API calls `delete_room()` to completely purge the room
5. Both users are removed, room is deleted from database

**Note**: If validation fails (e.g., can't fetch room state), the deletion proceeds anyway since the room is likely in an inconsistent state.

## Client Integration Example

```javascript
async function deleteDM(accessToken, roomId) {
  const response = await fetch('https://your-server.com/_synapse/client/delete_dm', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      room_id: roomId
    })
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error);
  }

  return await response.json();
}
```

## Testing

### Test Scenario 1: Inviter Cancels

1. User A invites User B to 1:1 chat
2. User A calls delete API with room_id
3. Room is deleted, both users removed

### Test Scenario 2: Invitee Declines

1. User A invites User B to 1:1 chat
2. User B calls delete API with room_id
3. Room is deleted, both users removed

Check logs:
```bash
docker compose logs -f | grep -i "DELETE_DM"
```

Expected log messages:
```
[DELETE_DM] User @alice:domain requesting to delete room !room:domain
[DELETE_DM] Room !room:domain memberships: [('@alice:domain', 'join'), ('@bob:domain', 'invite')]
[DELETE_DM] Active members: {'@alice:domain': 'join', '@bob:domain': 'invite'}
[DELETE_DM] Validation passed: DM with 2 members, requester @alice:domain is a member
[DELETE_DM] Deleting room !room:domain
[DELETE_DM] Successfully deleted room !room:domain by user @alice:domain
```

## Features

- Works for both inviter and invitee
- Validates DM rooms (max 2 members)
- Validates requester is a member
- Complete room deletion (not just leave)
- Graceful handling of edge cases
- Detailed logging for debugging

## Comparison with Standard Matrix Endpoints

| Action | Standard Matrix | This Module |
|--------|----------------|-------------|
| Invitee declines | Room stays in DB, inviter still sees it | Room completely deleted for both |
| Inviter cancels | Must leave room, invitee keeps invite | Room completely deleted for both |
| Cleanup | Manual for each user | Automatic for both users |
