# Architecture

Detailed module documentation for OpenOutreach. See `CLAUDE.md` for rules and quick reference.

## Entry Flow

`manage.py` — stock Django management entrypoint. Bare `python manage.py` (no args) defaults to `rundaemon`.

### `rundaemon` management command (`management/commands/rundaemon.py`)

Startup sequence:
1. **Configure logging** — DEBUG level, suppresses noisy third-party loggers (urllib3, httpx, pydantic_ai, openai, playwright, etc.).
2. **Ensure DB** — `migrate --no-input` + `setup_crm` (idempotent).
3. **Onboard** — checks `missing_keys()`; if incomplete: uses `--onboard <config.json>` (non-interactive), falls back to interactive wizard (TTY), or exits with clear error (no TTY).
4. **Validate** — `LLM_API_KEY`, active `LinkedInProfile`, at least one campaign.
5. **Session** — `get_or_create_session(profile)`, sets default campaign (first non-freemium).
6. **Newsletter** — GDPR override + `ensure_newsletter_subscription()` (marker-guarded, runs once).
7. **Run** — `run_daemon(session)`.

Docker `start` script handles only Xvfb/VNC setup, then `exec python manage.py rundaemon "$@"`.

### Other management commands

- `onboard` — standalone onboarding (interactive or `--non-interactive` with `--config-file` / individual flags).
- `setup_crm` — idempotent CRM bootstrap (default Site).
- `add_seeds` — add seed LinkedIn profile URLs to a campaign.
- `status` — prints a live summary: campaigns, deals by state, task queue (next scheduled action), and today's ActionLog counts.
- `crm` — rich-table CRM browser. Subcommands: `leads`, `deals`, `deal <id>`. Reads only; mutations are in the `oo` CLI.

## `oo` CLI (`oo_cli.py`)

Installable local CLI (`pip install -e .`, entry point `oo`). Bootstraps Django via `django.setup()` at startup, then delegates to ORM queries directly — no subprocess calls to `manage.py`.

Subcommand groups:

| Group | Commands |
|---|---|
| *(root)* | `status`, `run`, `admin [port]` |
| `crm` | `leads`, `disqualify`, `requalify`, `deals`, `deal`, `set-state`, `set-outcome` |
| `campaign` | `list`, `show`, `create`, `update`, `delete` |
| `keyword` | `list`, `add`, `delete` |
| `task` | `list`, `cancel` |
| `linkedin` | `import-export <zip-path> --campaign <name>` |

`campaign create` prompts interactively and adds all existing Django users to the new campaign's M2M. `campaign delete` and `keyword delete` require `--yes / -y` or interactive confirmation. `set-state` / `set-outcome` validate against `ProfileState` / `Outcome` enum values (case-insensitive). `linkedin import-export` ingests a first-party LinkedIn member export ZIP without browser automation, reading `Connections.csv`, `Invitations.csv`, and `messages.csv` directly from the archive. It creates/reuses `Lead` rows, attaches warm queue rows via `CampaignLead`, imports historical messages as `ChatMessage`, prints created/reused/skipped counts, and is safe to rerun.

## Onboarding (`onboarding.py`)

`OnboardConfig` — pure dataclass with all onboarding fields. Two constructors:
- `OnboardConfig.from_json(path)` — from JSON file (cloud / non-interactive).
- `collect_from_wizard()` — interactive questionary wizard (needs TTY), only asks for `missing_keys()`.

Single write path: `apply(config)` — idempotent, creates missing Campaign, LinkedInProfile, env vars, and legal acceptance. Four components:

1. **Campaign** — name, product docs, objective, booking link, seed URLs. Creates `Campaign` with M2M user membership.
2. **LinkedInProfile** — email, password, newsletter, rate limits. Django username from email slug.
3. **LLM config** — `LLM_PROVIDER`, `LLM_API_KEY`, `AI_MODEL`, `LLM_API_BASE` → writes to `SiteConfig` singleton in DB.
4. **Legal notice** — per-account acceptance stored as `LinkedInProfile.legal_accepted`.

## Profile State Machine

`enums.py:ProfileState` (TextChoices) values ARE CRM stage names: QUALIFIED, READY_TO_CONNECT, PENDING, CONNECTED, COMPLETED, FAILED. Pre-Deal states: url_only (Lead row exists but `embedding` is null), enriched (has `embedding`). `Lead.disqualified=True` = permanent account-level exclusion. LLM rejections = FAILED Deals with wrong_fit outcome (campaign-scoped).

`crm/models/deal.py:Outcome` (TextChoices): converted, not_interested, wrong_fit, no_budget, has_solution, bad_timing, unresponsive, unknown. Used by `Deal.outcome`.

## Task Queue

Persistent queue backed by `Task` model. Worker loop in `daemon.py`: `seconds_until_active()` guard pauses outside the daily active-hours window (single contiguous window, no weekend skip) → pop oldest due task → set campaign on session → RUNNING → dispatch via `_HANDLERS` dict → COMPLETED/FAILED. Failures captured by `failure_diagnostics()` context manager.

Task rows are **lazy**: `payload = {"campaign_id": <id>}` only — no `public_id`, no deal reference. The handler resolves a concrete target at execution time via a single eligibility query. Slot creation is centralized in `linkedin/tasks/scheduler.py`; no other module inserts Task rows. The module is organized in three layers:

1. **Per-type planners** — `plan_connect_window`, `plan_follow_up_window`, `plan_check_pending_window`. Each, when no PENDING task of its type exists for a campaign, computes the right slot count `n` for the next 24h and inserts `1 immediate + (n-1) Poisson-spaced` lazy rows. The leading immediate slot kills the cold-start ramp (without it the first action would sit `T/n` away on average — ~72 min for a 20/day campaign).
2. **State-transition hook** — `on_deal_state_entered(deal)`. For PENDING transitions, stamps `deal.next_check_pending_at = now + backoff_hours`. All other transitions (CONNECTED included) are no-ops.
3. **`reconcile(session)`** — Recovers stale RUNNING tasks, then iterates campaigns × planners. Daemon calls it on startup and whenever the queue has no ready task.

Per-type recompute trigger: when a type's PENDING queue is empty for a campaign, the next idle reconcile re-plans only that type's next 24h window. No global rollover, no leftover-slot reconciliation. `AuthenticationError` (401) triggers `session.reauthenticate()` then marks the task FAILED; the planner picks the type back up on the next idle cycle.

Three task types (handlers in `linkedin/tasks/`, signature: `handle_*(task, session, qualifiers)`):

1. **`handle_connect`** — Unified via `ConnectStrategy` dataclass. Regular: `find_candidate()` from `pools.py`; freemium: `find_freemium_candidate()`. Unreachable detection after `MAX_CONNECT_ATTEMPTS` (3). No self-rescheduling — the planner owns timing.
2. **`handle_check_pending`** — Eligibility query: oldest PENDING deal in the campaign with `next_check_pending_at <= now`. If none, mark task DONE. On still-PENDING outcome, double `backoff_hours` and re-stamp `next_check_pending_at`.
3. **`handle_follow_up`** — Two-phase. **Phase 1 (approval drain):** check for a deal with `pending_message_approved=True`; `_next_approved_deal` first discards stale drafts — a draft is stale only if the lead's last ChatMessage is incoming AND its `creation_date > deal.pending_message_created_at` (meaning the lead replied *after* the draft was written). Without this timestamp guard the discard would fire on every hot-path draft (the lead's reply is always the most recent message when we draft a response to them), causing an infinite discard loop. Stale drafts are cleared (`pending_message`/`pending_message_approved`/`pending_message_created_at`) and skipped; if a valid approved deal is found, `_send_approved` sends it and returns. If the send fails, fall through to Phase 2 (so other leads in the campaign are not blocked). **Phase 2 (generate):** `_next_followup_deal` selects a target via a two-phase annotated query. **Hot path first:** annotates the base queryset with `last_msg_is_outgoing` (Django `Subquery` + `OuterRef` on `ChatMessage`), then returns the oldest deal where the lead replied last (`last_msg_is_outgoing=False`) via `.first()` — no cooldown check, a replied lead is never too soon to respond to. **Cold path (fallback):** if the hot path returns nothing, iterates deals where `last_msg_is_outgoing=True` or NULL (we sent last / no messages), applying `_too_soon_to_nudge` and sync-to-unblock unchanged. This guarantees a lead who replied is drafted before any older cold deal. Once a deal is selected, calls `run_follow_up_agent()` (`FollowUpDecision`: `send_message`/`mark_completed`/`wait`). If approval is required and action is `send_message`, write the draft to `Deal.pending_message`, stamp `Deal.pending_message_created_at = now()`, and return (held for human review); otherwise send immediately. **Cooldown + sync:** `_too_soon_to_nudge` blocks a deal when the last ChatMessage is outgoing and `elapsed < nudges × MIN_DAYS_PER_UNANSWERED (3d)`. Because replies are only written to ChatMessage via `sync_conversation`, a deal blocked by cooldown is re-synced against LinkedIn before being skipped — if a reply landed since the last sync the deal unblocks in the same slot. **Message normalization:** `send_raw_message` (and `_send_approved`) normalize all outgoing text via `_normalize_message`: strips `\r` (prevents Playwright double-Enter for `\r\n` paragraph breaks) and replaces Unicode space variants with ASCII space (avoids LinkedIn Messaging API 400).

## Qualification ML Pipeline

GPR (sklearn, ConstantKernel * RBF) inside Pipeline(StandardScaler, GPR) with BALD active learning:

1. **Balance-driven selection** — n_negatives > n_positives → exploit (highest P); otherwise → explore (highest BALD).
2. **LLM decision** — All decisions via LLM (`qualify_lead.j2`). GP only for candidate selection and confidence gate.
3. **READY_TO_CONNECT gate** — P(f > 0.5) above `min_ready_to_connect_prob` (0.9) promotes QUALIFIED → READY_TO_CONNECT.
4. **Warm campaign queue** — `CampaignLead` rows for the active campaign are qualified before generic global leads. If a positively qualified `CampaignLead` has `relationship_status=connected`, its `Deal` is created directly in CONNECTED and bypasses READY_TO_CONNECT/connect slots.
5. **Pre-connect guard** — Before returning a cold connect candidate, `ready_source()` can qualify a bounded batch when the campaign model has fewer than `min_qualification_observations_before_connect` labels.

384-dim FastEmbed embeddings stored directly on Lead model, per-campaign GP models at ``Campaign.model_blob` (BinaryField, joblib-dumped with `compress=3`)`. Cold start returns None until >=2 labels of both classes.

## Django Admin (`crm/admin.py`, `linkedin/admin.py`)

`Lead` and `Deal` are registered with read-only fieldsets. **`DealAdmin`** list annotates the queryset with `_last_msg_is_outgoing` and `_last_msg_date` (Subquery on ChatMessage) to power two new columns: **"Último msg"** — green "← Respondió Xd" badge when the lead replied last (hot), yellow "→ Enviado Xd" when we sent last (cold), grey when no messages; and **"Draft"** — shows "✓ Aprobado" or "⏳ Borrador" based on `pending_message_approved` (replaces the old boolean). Filterable by `state`, `outcome`, `campaign`, `pending_message_approved`. Exposes `pending_message` and `pending_message_approved` as editable fields. `save_model` override creates an immediate `follow_up` task when `pending_message_approved` transitions to `True` (mirrors the CLI `approve` behaviour). **`ActionLogAdmin`**: ordered by `-created_at`; list annotates with `_daily_count` (Subquery counting same profile+type today) for a **"Hoy"** column showing `count / daily_limit` with colour coding (green/orange/red). Detail view shows: lead (with LinkedIn link + deal admin link), the last outgoing ChatMessage for that lead sent at or before `created_at` rendered as a message bubble. Access at `/admin/` (run via `oo admin` or `make admin`, default port 8001).

## Django Apps

Three apps in `INSTALLED_APPS`:

- **`linkedin`** — Main app: Campaign (with users M2M), LinkedInProfile, SearchKeyword, ActionLog, Task models. All automation logic.
- **`crm`** — Lead (with embedding) and Deal models (in `crm/models/lead.py` and `crm/models/deal.py`). Also defines `Outcome` enum.
- **`chat`** — `ChatMessage` model (GenericForeignKey to any object, content, owner, answer_to threading, topic).

## CRM Data Model

- **SiteConfig** (`linkedin/models.py`) — Singleton (pk=1). LLM fields: `llm_provider` (TextChoices: openai/anthropic/google/groq/mistral/cohere/openai_compatible), `llm_api_key`, `ai_model`, `llm_api_base`. LLM generation parameters: `llm_temperature` (float, default 0.7; range 0.0–2.0), `llm_max_tokens` (nullable int; None = provider default). Pipeline condition fields (global defaults, all overridable per-campaign): `follow_up_cooldown_hours` (72), `reengagement_greeting_days` (3), `gpr_qualification_threshold` (0.85), `connect_daily_limit` (20), `follow_up_daily_limit` (25), `check_pending_daily_cap` (100), `max_followups_without_reply` (10), `min_qualification_observations_before_connect` (0), `preconnect_qualification_batch_size` (1). Accessed via `SiteConfig.load()`; `linkedin/llm.py:get_llm_model()` is the single factory that turns it into a `pydantic_ai.models.Model`. LLM generation parameters are read via `linkedin/llm.py:get_model_settings(campaign)` — never hardcoded. Pipeline conditions are read via `get_campaign_config(campaign)` in `linkedin/pipeline_config.py`, never directly.
- **Campaign** (`linkedin/models.py`) — `name` (unique), `users` (M2M to User), `product_docs`, `campaign_objective`, `booking_link`, `website_url`, `require_message_approval` (BooleanField, default False — when True, generated follow-up messages are held as drafts and must be approved via `oo crm approve` before sending), `action_fraction`, `seed_public_ids` (JSONField). LLM generation parameter overrides (nullable — null = inherit from SiteConfig): `llm_temperature`, `llm_max_tokens`. Pipeline condition overrides (all nullable — null = inherit from SiteConfig): `follow_up_cooldown_hours`, `reengagement_greeting_days`, `gpr_qualification_threshold`, `connect_daily_limit`, `follow_up_daily_limit`, `check_pending_daily_cap`, `max_followups_without_reply`, `min_qualification_observations_before_connect`, `preconnect_qualification_batch_size`. Prompt overrides via `CampaignPromptOverride` related objects.
- **LinkedInProfile** (`linkedin/models.py`) — 1:1 with User. `self_lead` FK to Lead (nullable, set on first self-profile discovery). Credentials, rate limits (`connect_daily_limit`, `follow_up_daily_limit` — daily-only; LinkedIn's own weekly ceiling surfaces at the handler boundary via `ReachedConnectionLimit`). Methods: `can_execute`/`record_action`/`mark_exhausted`. In-memory `_exhausted` dict for daily rate limit caching.
- **SearchKeyword** (`linkedin/models.py`) — FK to Campaign. `keyword`, `used`, `used_at`. Unique on `(campaign, keyword)`.
- **ActionLog** (`linkedin/models.py`) — FK to LinkedInProfile + Campaign + Lead (nullable — set to the target lead at action time; NULL for records created before the FK was added). `action_type` (connect/follow_up), `created_at`. `record_action(action_type, campaign, lead=None)` is the single write path. Composite index on `(linkedin_profile, action_type, created_at)`.
- **Lead** (`crm/models/lead.py`) — Per LinkedIn URL (`linkedin_url` = unique). `public_identifier` (unique). `urn` (unique, cached on first scrape). Profile snapshot fields persisted at creation and refreshed lazily on scrape: `full_name`, `first_name`, `headline`, `industry`, `current_company`, `current_title` (from `positions[0]`), `location` (from `locationName`), `country_code` (from `location.countryCode`), `languages` (JSONField list, from `supportedLocales`). `embedding` = 384-dim float32 BinaryField (nullable). `disqualified` = permanent exclusion. `get_profile` lazily updates all snapshot fields as side-effects when they change. `embedding_array` property for numpy access. `embed_from_profile(profile)` computes + persists the embedding from an in-hand dict (skips the scrape). `get_labeled_arrays(campaign)` classmethod returns (X, y) for GP warm start. Labels: non-FAILED state → 1, FAILED+wrong_fit → 0, other FAILED → skipped.
- **CampaignLead** (`crm/models/campaign_lead.py`) — Queue row assigning a `Lead` to a `Campaign` before a `Deal` exists. Unique on `(campaign, lead)`. Stores source (`linkedin_connection` priority=10, `linkedin_invitation` priority=20, `linkedin_search` priority=50, `manual` priority=100), relationship status (`connected`, `invited`, `unknown`), optional `connected_on`, and import metadata. `get_leads_for_qualification()` consumes these rows before generic global leads. `discover_and_enrich()` creates a `CampaignLead` with `source=linkedin_search` for every newly enriched profile so active-search leads also enter the campaign queue with explicit priority.
- **Deal** (`crm/models/deal.py`) — Per campaign (campaign-scoped via FK). `state` = CharField (ProfileState choices). `outcome` = CharField (Outcome choices: converted/not_interested/wrong_fit/no_budget/has_solution/bad_timing/unresponsive/unknown). `reason` = qualification reason (free text). `connect_attempts` = retry count. `backoff_hours` = check_pending backoff. `next_check_pending_at` = DateTimeField (indexed) stamped by `on_deal_state_entered(PENDING)`; the `check_pending` eligibility query and `plan_check_pending_window` both read it. `profile_summary` / `chat_summary` = JSONField fact lists (lazy, mem0-style, campaign-scoped). `pending_message` = TextField (draft follow-up message awaiting human approval; empty string when no draft). `pending_message_approved` = BooleanField (set to True via `oo crm approve <id>` or Admin; cleared after send). `pending_message_created_at` = DateTimeField (nullable; set to `now()` when the draft is written — used by `_next_approved_deal` to distinguish a lead reply that arrived before the draft from one that arrived after, avoiding false-stale discards). `rejection_feedback`, `regeneration_count`. `creation_date`, `update_date`.
- **Task** (`linkedin/models.py`) — `task_type` (connect/check_pending/follow_up), `status` (pending/running/completed/failed), `scheduled_at`, `payload` (JSONField), `error`, `started_at`, `completed_at`. Composite index on `(status, scheduled_at)`.
- **ChatMessage** (`chat/models.py`) — GenericForeignKey to any object. `content`, `owner`, `answer_to` (self FK), `topic` (self FK), `recipients`, `to` (M2M to User).

## Key Modules

- **`daemon.py`** — Worker loop with active-hours guard (`ENABLE_ACTIVE_HOURS` flag, `seconds_until_active()`), `_build_qualifiers()`, freemium import, `_CloudPromoRotator`. Calls `scheduler.reconcile()` when the queue has no ready task. Handles `AuthenticationError` (reauthenticate + retry) and Playwright `TargetClosedError` (close + relaunch browser + mark FAILED) as distinct recovery paths before the general `Exception` fallback.
- **`diagnostics.py`** — `failure_diagnostics()` context manager, `capture_failure()` saves page HTML/screenshot/traceback to `/tmp/openoutreach-diagnostics/`.
- **`tasks/scheduler.py`** — Single owner of Task row creation. Per-type planners (`plan_connect_window` / `plan_follow_up_window` / `plan_check_pending_window`) emit lazy slots with `1 immediate + (n-1) Poisson-spaced`; `poisson_slot_times(now, n, horizon_hours)` + `working_seconds_in_window(start, end)` are the spacing primitives. State-transition hook `on_deal_state_entered` only stamps `Deal.next_check_pending_at` for PENDING. `reconcile()` recovers stale RUNNING + dispatches the per-type planners.
- **`tasks/connect.py`** — `handle_connect`, `ConnectStrategy`.
- **`tasks/check_pending.py`** — `handle_check_pending`, exponential backoff.
- **`tasks/follow_up.py`** — `handle_follow_up` (approval drain → draft generation), `_next_approved_deal`, `_next_followup_deal`, `_send_approved`, `_leads_followed_up_elsewhere`.
- **`pipeline/qualify.py`** — `run_qualification()`, `fetch_qualification_candidates()`.
- **`pipeline/search.py`** — `run_search()`, keyword management.
- **`pipeline/search_keywords.py`** — `generate_search_keywords()` via LLM.
- **`pipeline/ready_pool.py`** — GP confidence gate, `promote_to_ready()`.
- **`pipeline/pools.py`** — Composable generators: `search_source` → `qualify_source` → `ready_source`.
- **`pipeline/freemium_pool.py`** — Seed priority + undiscovered pool, ranked by qualifier.
- **`ml/qualifier.py`** — `Qualifier` protocol, `BayesianQualifier`, `KitQualifier`, `qualify_with_llm()`.
- **`ml/embeddings.py`** — FastEmbed utilities, `embed_text()`, `embed_texts()`.
- **`ml/profile_text.py`** — `build_profile_text()`. Concatenates `full_name`, headline, summary, location, industry, positions, and educations into a single lowercased string for embedding. `full_name` is prepended first so fact-extraction LLMs see the lead's name and include it in `profile_summary` facts (without it, follow-up greetings had no name to use).
- **`ml/hub.py`** — HuggingFace kit loader (`fetch_kit()`).
- **`browser/session.py`** — `AccountSession`: linkedin_profile, page, context, browser, playwright. `campaigns` cached_property (list, via Campaign.users M2M). `ensure_browser()` launches/recovers browser. `self_profile` cached_property (re-discovers via Voyager on first access per session — no DB cache; one extra scrape per daemon restart). Cookie expiry check via `_maybe_refresh_cookies()`. `reauthenticate()` forces fresh login (close browser, clear saved cookies, re-launch).
- **`browser/registry.py`** — `get_or_create_session()`, `get_first_active_profile()`, `resolve_profile()`, `cli_parser()`/`cli_session()` (shared CLI bootstrap for `__main__` scripts).
- **`browser/login.py`** — `start_browser_session()` — browser launch + LinkedIn login.
- **`browser/nav.py`** — Navigation, auto-discovery, `goto_page()`.
- **`db/leads.py`** — Lead CRUD, `get_leads_for_qualification()`, `disqualify_lead()`, `_cache_urn_from_profile()`.
- **`db/deals.py`** — Deal/state ops, `set_profile_state()`, `increment_connect_attempts()`, `create_freemium_deal()`.
- **`db/chat.py`** — `sync_conversation()`, `_sync_from_api()`, folds newly-synced messages into `Deal.chat_summary` via `update_chat_summary`.
- **`db/summaries.py`** — Single mem0-style LLM boundary. `materialize_profile_summary_if_missing(deal, session)` fires on first follow-up touch (one Voyager re-scrape per `(lead, campaign)` lifetime); `update_chat_summary(deal, new_messages, *, seller_name)` folds newly-synced ChatMessages incrementally via `reconcile_facts`, which routes new facts through mem0's UPDATE prompt to apply ADD/UPDATE/DELETE/NONE events (mirrors `mem0/memory/main.py::Memory._add_to_vector_store` lines 594-700, with vector-store ops replaced by an in-memory dict because `Deal.chat_summary` is a flat list). `_format_messages_for_extraction` filters to incoming messages only, so `chat_summary` holds facts about the lead and a one-sided outgoing burst is a noop. `extract_facts(text, *, seller_name, context)` runs `pydantic_ai.Agent(get_llm_model(), output_type=FactList)` against the vendored `_FACT_EXTRACTION_PROMPT` plus an unconditional identity-binding block (`_build_identity_binding`) telling the LLM that `[Me]` is `seller_name`, so seller-name greetings in `[Lead]` messages don't get misattributed to the lead. **Paraphrase trap:** `_FACT_EXTRACTION_PROMPT` includes an explicit rule to skip sentences where the lead paraphrases or summarises what `[Me]` said ("Por lo que entiendo, estás tratando de…", "I understand you're building…") — without this, the model strips the attribution and stores the seller's pitch as a lead goal. `reconcile_facts(existing, new, *, seller_name)` prepends the same binding to mem0's UPDATE prompt with an explicit "DELETE contamination" instruction — previously-stored facts that describe the seller as the lead *should* clean up on the next sync that produces a conflicting fact, though this is best-effort (the upstream mem0 prompt is example-heavy and the cleanup hint is one prepended sentence; dormant deals stay contaminated). `seller_name_from(session)` is the single derivation point — `first_name` from `session.self_profile` with username fallback. mem0's `DEFAULT_UPDATE_MEMORY_PROMPT` and `get_update_memory_messages` live under `linkedin/vendor/mem0/configs/prompts.py` (mirrors upstream path so future syncs are a clean diff; pinned commit recorded in the file header).
- **`url_utils.py`** — `url_to_public_id()`, `public_id_to_url()` — LinkedIn URL ↔ public identifier conversion. Pure utility, no DB dependency.
- **`prompts.py`** — `get_prompt(key, campaign=None) -> str` resolver. Resolution order: `CampaignPromptOverride` (if campaign given) → global `PromptTemplate` DB row → hardcoded fallback (`.j2` file or inline constant). Five keys: `qualification`, `follow_up_agent`, `profile_fact_extraction`, `chat_fact_reconciliation`, `connection_message`. All pipeline LLM call sites go through this; `.j2` files remain as hardcoded fallbacks only. `_load_fallback(key)` is the fallback loader (used by `oo prompt reset`).
- **`pipeline_config.py`** — `get_campaign_config(campaign) -> PipelineConfig`. `PipelineConfig` frozen dataclass with the 7 condition fields. Resolution: campaign override (non-null) → SiteConfig singleton → hardcoded constant. All pipeline code reads conditions through this; direct `CAMPAIGN_CONFIG` reads are replaced.
- **`conf.py`** — Config constants. `CAMPAIGN_CONFIG` keys that are now DB-backed (timing/limits/thresholds) remain as hardcoded fallback constants only; active-hours, PROMPTS_DIR, and browser/ML constants live here. LLM construction lives in `llm.py`.
- **`llm.py`** — `get_llm_model()` factory + `get_model_settings(campaign, *, temperature_override)` + `run_agent_sync(coro)` sync boundary. `get_llm_model()` reads `SiteConfig` and dispatches via per-provider builders to the right `pydantic_ai.models.Model`. `get_model_settings(campaign)` resolves `temperature` and `max_tokens` from SiteConfig → campaign override cascade; pass `temperature_override=0.0` for deterministic extraction tasks. All generation agents use `get_model_settings(campaign)` — temperature is never hardcoded in agent call sites. Call sites build `Agent(get_llm_model(), model_settings=get_model_settings(campaign), ...)` and invoke `run_agent_sync(agent.run(prompt))` — never `Agent.run_sync`.
- **`exceptions.py`** — `AuthenticationError`, `TerminalStateError`, `SkipProfile`, `ReachedConnectionLimit`.
- **`onboarding.py`** — Interactive setup.
- **`agents/follow_up.py`** — Follow-up agent. Single LLM call with structured output (`FollowUpDecision`). Conversation is read in Python and injected into the prompt. No tool-calling loop.
- **`actions/`** — `connect.py` (`send_connection_request`), `status.py` (`get_connection_status`), `message.py` (`send_raw_message`), `profile.py` (profile extraction), `search.py` (LinkedIn search), `conversations.py` (`get_conversation`).
- **`api/client.py`** — `PlaywrightLinkedinAPI`: browser-context fetch (runs JS `fetch()` inside Playwright page for authentic headers). `timeout_ms` constructor param (default 30s). `get_profile()` with tenacity retry.
- **`api/voyager.py`** — `LinkedInProfile` dataclass (url, urn, full_name, headline, positions, educations, country_code, supported_locales, connection_distance/degree). `parse_linkedin_voyager_response()`.
- **`api/newsletter.py`** — `subscribe_to_newsletter()` via Brevo form, `ensure_newsletter_subscription()`. No config parsing — subscribe_newsletter is a BooleanField.
- **`api/messaging/send.py`** — Send messages via Voyager messaging API.
- **`api/messaging/conversations.py`** — Fetch conversations/messages.
- **`api/messaging/utils.py`** — Shared helpers: `encode_urn()`, `check_response()`.
- **`setup/freemium.py`** — `import_freemium_campaign()`, `seed_profiles()`.
- **`setup/gdpr.py`** — `apply_gdpr_newsletter_override()`.
- **`setup/self_profile.py`** — `discover_self_profile()` — fetches self profile via Voyager API, sets `linkedin_profile.self_lead`.
- **`setup/seeds.py`** — User-provided seed profiles: parse URLs, create Leads + QUALIFIED Deals.
- **`management/setup_crm.py`** — Idempotent CRM bootstrap (Site creation).
- **`admin.py`** — Django Admin: SiteConfig (LLM provider fields + generation parameter fields `llm_temperature`/`llm_max_tokens` with interactive slider widget + pipeline condition fields), Campaign (LLM parameter overrides fieldset with `TemperatureWidget` slider + global default hints + pipeline override fieldset + `CampaignPromptOverrideInline`), PromptTemplate, LinkedInProfile, SearchKeyword, ActionLog, Task, ChatMessage. `TemperatureWidget` renders a synced range slider + number input with JavaScript that updates a contextual description as the user drags. Deal admin has "Reject & Regenerate" action for PENDING deals (opens intermediate form for free-text feedback).
- **`django_settings.py`** — Django settings (SQLite at `data/db.sqlite3`). Apps: crm, chat, linkedin.


## Configuration

- **`SiteConfig`** (DB singleton) — LLM: `llm_provider` (required, defaults to `openai`; choices: `openai`/`anthropic`/`google`/`groq`/`mistral`/`cohere`/`openai_compatible`), `llm_api_key` (required), `ai_model` (required), `llm_api_base` (required only for `openai_compatible`). Generation parameters (overridable per-campaign): `llm_temperature` (default 0.7), `llm_max_tokens` (nullable, default = provider limit). Pipeline conditions (all overridable per-campaign): `follow_up_cooldown_hours`, `reengagement_greeting_days`, `gpr_qualification_threshold`, `connect_daily_limit`, `follow_up_daily_limit`, `check_pending_daily_cap`, `max_followups_without_reply`. Editable via Django Admin or `oo config set/show`.
- **`conf.py` schedule** — `ENABLE_ACTIVE_HOURS` (`False`), `ACTIVE_START_HOUR` (9), `ACTIVE_END_HOUR` (19), `ACTIVE_TIMEZONE` (system-local IANA name, falls back to "UTC"). Daemon sleeps outside this window. No weekend/rest-day handling — humans use LinkedIn 7 days a week.
- **`conf.py` planner cap** — `CHECK_PENDING_DAILY_CAP` (100). Maximum `check_pending` slots planned per 24h window per campaign; overflow rolls into the next planning cycle.
- **`conf.py:CAMPAIGN_CONFIG`** — `min_ready_to_connect_prob` (0.9), `min_positive_pool_prob` (0.20), `check_pending_recheck_after_hours` (24), `qualification_n_mc_samples` (100), `enrich_min_delay_seconds` (6), `enrich_max_delay_seconds` (10), `enrich_max_per_page` (10), `burst_min_seconds` (2700), `burst_max_seconds` (3900), `break_min_seconds` (600), `break_max_seconds` (1200), `min_action_interval` (120), `embedding_model` ("BAAI/bge-small-en-v1.5"), `reengagement_greeting_days` (3 — days of silence after which a follow-up nudge re-opens with a greeting; below this threshold the LLM continues without one).
- **Prompt templates** — Stored as `PromptTemplate` DB rows (editable via Django Admin or `oo prompt set <key>`). Five keys: `qualification`, `follow_up_agent`, `profile_fact_extraction`, `chat_fact_reconciliation`, `connection_message`. `.j2` files at `linkedin/templates/prompts/` remain as hardcoded fallbacks only. Per-campaign overrides via `CampaignPromptOverride` model (`oo prompt override-set <campaign> <key>`). The `follow_up_agent` template enforces: (a) Discovery-first strategy via Mom Test, (b) a hard rule to answer direct product questions before pivoting to discovery, (c) greeting rules — greeting only on opening message or after `{{ reengagement_greeting_days }}` days of silence. When a draft is rejected with feedback, an `## Operator instructions` block is appended to the prompt before regeneration.
- **`requirements/`** — `base.txt`, `local.txt`, `production.txt`, `crm.txt` (empty — DjangoCRM installed via `--no-deps`).

## Docker

Base image: `mcr.microsoft.com/playwright/python:v1.55.0-noble`. VNC on port 5900. `BUILD_ENV` arg selects requirements. Dockerfile at `compose/linkedin/Dockerfile`. Install: uv pip → DjangoCRM `--no-deps` → requirements → Playwright chromium.

## CI/CD

- `tests.yml` — pytest in Docker on push to `master` and PRs.
- `deploy.yml` — Tests → build + push to `ghcr.io/eracle/openoutreach`. Tags: `latest`, `sha-<commit>`, semver.

## Dependencies

`requirements/` files. DjangoCRM's `mysqlclient` excluded via `--no-deps`. `uv pip install` for fast installs.

Core: `playwright`, `playwright-stealth`, `Django`, `django-crm-admin`, `pandas`, `pydantic-ai-slim` (with `openai`/`anthropic`/`google`/`groq`/`mistral`/`cohere`/`bedrock` extras), `jinja2`, `pydantic`, `jsonpath-ng`, `tendo`, `termcolor`, `tenacity`
ML: `scikit-learn`, `numpy`, `fastembed`, `joblib`
