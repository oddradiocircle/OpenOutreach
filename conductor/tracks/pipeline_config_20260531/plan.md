# Plan: Configurable Pipeline Prompts, Conditions & Message Regeneration

## Phase 1: PromptTemplate Model & Global Admin

- [x] Task 1.1: Define `PromptTemplate` model (c125f0f)
  - [ ] Add model to `linkedin/models.py` with fields: `key` (unique slug),
        `name`, `description`, `body` (TextField), `updated_at` (auto)
  - [ ] Write and run migration

- [x] Task 1.2: Data migration — pre-populate defaults (2286721)
  - [ ] Identify all 5 prompt keys and their current hardcoded sources
        (`.j2` files + vendored strings in `summaries.py`)
  - [ ] Write data migration that inserts one `PromptTemplate` row per key
        with the existing text as initial `body`

- [x] Task 1.3: Register in Django Admin (08415d6)
  - [ ] `PromptTemplateAdmin` with `list_display`: key, name, updated_at
  - [ ] Large `Textarea` widget for `body` field
  - [ ] `description` field as read-only hint in change form

- [x] Task 1.4: Jinja2 syntax validation on save (c125f0f)

- [x] Task 1.5: `get_prompt()` resolver (9a75169)
  - [ ] Create `linkedin/prompts.py` with
        `get_prompt(key, campaign=None) -> str`
  - [ ] Resolution order: campaign override (Phase 2) → global
        `PromptTemplate` row → hardcoded `.j2` file fallback
  - [ ] Wire existing `.j2` template loaders to call `get_prompt()`

- [x] Task 1.6: Tests (1955fe2)
  - [ ] Global DB prompt is returned when present
  - [ ] Falls back to hardcoded `.j2` when DB row is missing

- [x] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md) (079740e)

## Phase 1: PromptTemplate Model & Global Admin [checkpoint: 079740e]

---

## Phase 2: Per-Campaign Prompt Overrides

- [x] Task 2.1: Define `CampaignPromptOverride` model (f904041)
  - [ ] Fields: `campaign` (FK → Campaign), `prompt_key` (CharField,
        choices from prompt keys), `body` (TextField)
  - [ ] Unique constraint on `(campaign, prompt_key)`
  - [ ] Write and run migration

- [x] Task 2.2: `CampaignPromptOverrideInline` in `CampaignAdmin` (f42a1e6)
  - [ ] Tabular inline limited to existing prompt keys
  - [ ] Override `body` textarea shows current global prompt text as
        `help_text` (loaded dynamically from `PromptTemplate`)

- [x] Task 2.3: Update `get_prompt()` — campaign override resolution (a7b6b7e)
  - [ ] When `campaign` arg provided, query `CampaignPromptOverride` first
  - [ ] Fall through to global `PromptTemplate` if no override found

- [x] Task 2.4: Tests (ee37223)

- [x] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md) (036c7b9)

## Phase 2: Per-Campaign Prompt Overrides [checkpoint: 036c7b9]

---

## Phase 3: Configurable Pipeline Conditions

- [x] Task 3.1: Add condition fields to `SiteConfig` (3ab839a)
  - [ ] `follow_up_cooldown_hours` (int)
  - [ ] `reengagement_greeting_days` (int)
  - [ ] `gpr_qualification_threshold` (float, 0.0–1.0)
  - [ ] `connect_daily_limit` (int)
  - [ ] `follow_up_daily_limit` (int)
  - [ ] `check_pending_daily_cap` (int)
  - [ ] `max_followups_without_reply` (int)
  - [ ] Migration with defaults matching current `CAMPAIGN_CONFIG` values

- [x] Task 3.2: Add nullable override fields to `Campaign` (37cf845)
  - [ ] Same 7 fields, all nullable (null = inherit from SiteConfig)
  - [ ] Write and run migration

- [x] Task 3.3: `CampaignAdmin` fieldset "Pipeline Conditions (overrides)" (6948d33)
  - [ ] Collapsible fieldset with all 7 override fields
  - [ ] Each field's `help_text` shows current `SiteConfig` global value
        dynamically (override `get_form()` in admin)

- [x] Task 3.4: `get_campaign_config(campaign)` helper (5ef44ce)
  - [ ] Create `linkedin/pipeline_config.py`
  - [ ] `PipelineConfig` dataclass with all 7 fields
  - [ ] Resolution: campaign field (if not null) → SiteConfig singleton →
        hardcoded fallback constant

- [x] Task 3.5: Migrate pipeline code to `get_campaign_config()` (4964640)
  - [ ] Replace `CAMPAIGN_CONFIG` reads in `linkedin/tasks/follow_up.py`
  - [ ] Replace in `linkedin/tasks/scheduler.py`
  - [ ] Replace in qualification pipeline
  - [ ] Remove `CAMPAIGN_CONFIG` dict from `conf.py` (or keep as fallback
        constants only)

- [x] Task 3.6: Tests (197a5fc)
  - [ ] `SiteConfig` value is respected when no campaign override
  - [ ] Campaign override takes precedence over `SiteConfig`
  - [ ] Hardcoded constant is fallback when SiteConfig row missing

- [x] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md) (1955a6a)

## Phase 3: Configurable Pipeline Conditions [checkpoint: 1955a6a]

---

## Phase 4: Message Rejection with Regeneration

- [x] Task 4.1: `Deal` model fields (9cdc777)
  - [ ] Add `rejection_feedback` (TextField, blank=True, null=True)
  - [ ] Add `regeneration_count` (IntegerField, default=0)
  - [ ] Write and run migration

- [x] Task 4.2: Feedback injection in follow-up generator (f241143)
  - [ ] Add optional `regeneration_feedback: str | None` param to the
        follow-up message generation function
  - [ ] When present, inject as an instruction block in the rendered
        `follow_up_agent.j2` prompt (e.g. under a `## Operator instructions`
        section)

- [x] Task 4.3: "Reject & Regenerate" admin action (d801c16)

- [x] Task 4.4: `DealAdmin` read-only display (d801c16)

- [ ] Task 4.5: CLI `--feedback` flag
  - [ ] Add `--feedback` option to `oo crm reject <deal-id>` command
  - [ ] When provided: trigger regeneration flow instead of hard-reject
  - [ ] When omitted: existing reject behaviour (FAILED) unchanged

- [ ] Task 4.6: Tests
  - [ ] `rejection_feedback` stored on deal after action
  - [ ] `regeneration_count` incremented on each rejection
  - [ ] Regenerated draft leaves deal in PENDING state
  - [ ] Feedback text appears in the regenerated prompt
  - [ ] CLI `--feedback` flag triggers regeneration; omitting it retains
        original hard-reject behaviour

- [ ] Task: Conductor - User Manual Verification 'Phase 4' (Protocol in workflow.md)
