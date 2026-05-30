# Plan: Follow-up Deal Prioritization (Replied Leads First)

## Phase 1: Implementation

- [x] Task: Refactor `_next_followup_deal` with two-phase query (55ce9d3)
  - [ ] Add lazy imports for `ChatMessage`, `Lead`, `ContentType`, `OuterRef`, `Q`, `Subquery` inside the function body (consistent with existing import style)
  - [ ] Build annotated `base` queryset with `last_msg_is_outgoing` subquery: `ChatMessage` filtered by `content_type_id` (Lead ContentType) + `object_id=OuterRef("lead_id")`, ordered `-creation_date`, first `is_outgoing` value
  - [ ] Hot path: filter `base` where `last_msg_is_outgoing=False`, order `update_date ASC`, return `.first()` immediately if found
  - [ ] Cold path: filter `base` where `last_msg_is_outgoing=True` or `IS NULL`, loop with existing `_too_soon_to_nudge` + sync-to-unblock logic unchanged
  - [ ] Remove the old single-pass `order_by("update_date")` queryset and loop

- [ ] Task: Conductor - User Manual Verification 'Phase 1: Implementation' (Protocol in workflow.md)
