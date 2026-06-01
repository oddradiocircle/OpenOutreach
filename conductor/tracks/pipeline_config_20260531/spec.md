# Spec: Configurable Pipeline Prompts, Conditions & Message Regeneration

## Overview

Two related features that give operators full control over the outreach pipeline
and the message approval flow:

1. **Configurable prompts & conditions** — All LLM prompts and pipeline
   parameters (timing, thresholds, limits) become editable in Django Admin,
   with global defaults and per-campaign overrides.

2. **Message rejection with regeneration** — When a follow-up draft is pending
   approval, the operator can reject it with free-text feedback; the system
   regenerates immediately incorporating the instructions and re-queues the new
   draft for approval.

## Functional Requirements

### FR1 — PromptTemplate model (global defaults)

- New model `PromptTemplate` with fields: `key` (unique slug, e.g.
  `follow_up_agent`), `name` (human label), `description` (explains purpose
  and available Jinja2 variables), `body` (large textarea), `updated_at`.
- Five prompt keys: `qualification`, `follow_up_agent`,
  `profile_fact_extraction`, `chat_fact_reconciliation`,
  `connection_message`.
- A data migration pre-populates each row from the current hardcoded `.j2`
  templates and vendored strings in `linkedin/db/summaries.py`.
- Django Admin page for `PromptTemplate` with a clean list view showing key,
  name, and last-updated date.
- Prompt bodies support Jinja2 syntax; validated on save.

### FR2 — Per-campaign prompt overrides

- New model `CampaignPromptOverride`: `campaign` FK, `prompt_key`, `body`.
  One row per (campaign, key) pair.
- `CampaignAdmin` shows a `CampaignPromptOverrideInline`; each override
  textarea displays the global prompt text as a placeholder/help_text
  reference.
- Resolution order at runtime: campaign override → global PromptTemplate →
  hardcoded default (safety fallback).

### FR3 — Configurable pipeline conditions (global)

`SiteConfig` singleton gains new fields (with sensible hardcoded defaults):

| Field | Type | Description |
|---|---|---|
| `follow_up_cooldown_hours` | int | Min hours between nudges |
| `reengagement_greeting_days` | int | Days of silence before greeting |
| `gpr_qualification_threshold` | float | Min GPR score to qualify |
| `connect_daily_limit` | int | Max connection requests/day |
| `follow_up_daily_limit` | int | Max follow-ups/day |
| `check_pending_daily_cap` | int | Max check_pending tasks/day |
| `max_followups_without_reply` | int | Follow-ups before auto-FAILED |

### FR4 — Per-campaign pipeline condition overrides

- `Campaign` model gets nullable versions of the same fields. `null` = inherit
  from SiteConfig.
- In `CampaignAdmin`, these fields appear in a collapsible fieldset **"Pipeline
  Conditions (overrides)"**. Each field's `help_text` shows the current global
  default value dynamically.
- Helper `get_campaign_config(campaign)` resolves effective config (campaign →
  SiteConfig → hardcoded fallback) and returns a typed dataclass.
- All pipeline code currently reading from `CAMPAIGN_CONFIG` dict migrates to
  use `get_campaign_config(campaign)`.

### FR5 — Message rejection with regeneration

- `Deal` model gets two new fields: `rejection_feedback` (TextField, nullable),
  `regeneration_count` (IntegerField, default 0).
- In `DealAdmin`, deals in `PENDING` state show a **"Reject & Regenerate"**
  action alongside the existing approve/reject actions.
- The action opens an intermediate Django Admin page with a free-text feedback
  field (e.g. *"Too formal. Mention their recent post about AI."*).
- On submission:
  - Feedback saved to `Deal.rejection_feedback`.
  - `regeneration_count` incremented.
  - An immediate regeneration task is dispatched.
  - Deal remains `PENDING`.
- The follow-up generator accepts an optional `regeneration_feedback` param;
  when present, it is injected as an additional instruction block into the
  prompt before generation.
- After regeneration the new draft replaces the old pending draft; deal stays
  `PENDING` awaiting approval.
- `DealAdmin` detail view shows `rejection_feedback` and `regeneration_count`
  as read-only fields for context.
- `oo crm reject <deal-id> --feedback "..."` CLI flag triggers the same
  regeneration flow from the terminal.

## Non-Functional Requirements

- All new fields go through Django migrations (no manual schema changes).
- No breaking changes to existing approve/reject flows.
- No external JS dependencies — Django built-in form widgets only.
- Regeneration dispatches an immediate task (non-blocking web request).

## Acceptance Criteria

- [ ] `PromptTemplate` admin page shows all 5 prompt types, editable.
- [ ] Editing a global prompt affects subsequent message generation.
- [ ] A campaign-level prompt override takes precedence over the global one.
- [ ] Pipeline conditions in `SiteConfig` are respected by the daemon.
- [ ] `Campaign`-level overrides take precedence over `SiteConfig` defaults.
- [ ] `CampaignAdmin` shows current global default as hint for each override field.
- [ ] A PENDING deal shows "Reject & Regenerate" action in Django Admin.
- [ ] Submitting feedback triggers immediate regeneration; deal stays PENDING.
- [ ] The new draft reflects the operator's feedback instructions.
- [ ] Approve/reject of the regenerated draft works normally.
- [ ] `oo crm reject <id> --feedback "..."` triggers regeneration from CLI.

## Out of Scope

- Prompt version history / audit log (future track).
- A/B testing different prompts across leads within a campaign (future track).
- Live prompt preview / dry-run output (future track).
- Any frontend outside Django Admin.
