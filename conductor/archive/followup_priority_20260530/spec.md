# Spec: Follow-up Deal Prioritization (Replied Leads First)

## Overview

Currently, `_next_followup_deal` in `linkedin/tasks/follow_up.py` selects the next
eligible CONNECTED deal ordered purely by `update_date ASC` (oldest first), with no
distinction between deals where the lead has already replied and deals where we sent
the last message and are waiting.

This means a lead who is actively engaged (replied and waiting for our response) can
sit behind older deals where the lead never replied, delaying responses to warm
conversations.

This track replaces the single-pass loop with a two-phase query that processes
"hot" deals (lead replied) before "cold" deals (we sent last).

## Functional Requirements

### Phase 1 — Hot Path (lead replied)
- Query all eligible CONNECTED deals where the last ChatMessage for the lead has
  `is_outgoing=False` (the lead spoke last).
- These deals are never blocked by `_too_soon_to_nudge` — skip the check entirely.
- Return the oldest by `update_date ASC` via a single `.first()` call (no loop).
- If a hot deal is found, return it immediately without entering the cold path.

### Phase 2 — Cold Path (we sent last, or no messages)
- Only entered if Phase 1 returns nothing.
- Queries deals where the last ChatMessage has `is_outgoing=True` or there are no
  messages (`last_msg_is_outgoing IS NULL`).
- Applies the existing `_too_soon_to_nudge` check and sync-to-unblock logic
  unchanged: if a deal is blocked, sync the conversation with LinkedIn to catch
  unsynced replies, then re-evaluate.
- Returns the first eligible deal in `update_date ASC` order.

### Implementation approach
- Annotate the base queryset with a `last_msg_is_outgoing` subquery
  (Django `Subquery` + `OuterRef`) referencing `ChatMessage` filtered by
  `content_type_id` (Lead ContentType) and `object_id=lead_id`, ordered by
  `-creation_date`, taking the first `is_outgoing` value.
- Split into two filtered querysets from the same annotated base.

## Scope

### In Scope
- `_next_followup_deal` in `linkedin/tasks/follow_up.py` only.

### Out of Scope
- `_next_approved_deal` — already handles replied leads via stale-draft detection;
  no prioritization needed there.
- `plan_follow_up_window` and the scheduler — slot planning is unchanged.
- Tests — behavior verified manually.
- Daily rate limits, sync logic, or any other follow-up behavior.

## Acceptance Criteria

- A CONNECTED deal where the lead replied is drafted before an older CONNECTED deal
  where we sent the last message, even if it has a more recent `update_date`.
- Cold path behavior (time gate, sync-to-unblock) is identical to current behavior.
- No regression in deals with no messages or deals followed up in other campaigns.
