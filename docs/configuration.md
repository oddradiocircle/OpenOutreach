# Configuration

Configuration is split between environment variables (`.env` file), Django models (managed via interactive
onboarding or Django Admin), and hardcoded defaults in `linkedin/conf.py`.

## LLM Configuration (`.env`)

LLM settings are stored in `.env` (project root). Any
OpenAI-compatible provider works. These are prompted during interactive onboarding if missing.

| Variable | Description | Default |
|:---------|:------------|:--------|
| `LLM_API_KEY` | API key for an OpenAI-compatible provider. | (required) |
| `AI_MODEL` | Model identifier for qualification, follow-up, and search keyword generation. | (required) |
| `LLM_API_BASE` | Base URL for the API endpoint. | (none) |

These can also be set as environment variables directly.

## Campaign Settings (Django Model)

Campaign data is stored in the `Campaign` Django model (with `name` and `users` M2M), managed via
Django Admin (`/admin/`) or created during interactive onboarding.

| Field | Type | Description |
|:------|:-----|:------------|
| `product_docs` | text | Product/service description. Used by LLM qualification, follow-up agent, and search keyword generation. |
| `campaign_objective` | text | Campaign goal. Used by LLM qualification, follow-up agent, and search keyword generation. |
| `booking_link` | string | URL included in follow-up messages when suggesting a meeting. |
| `is_freemium` | boolean | Whether this is a freemium campaign (uses KitQualifier instead of BayesianQualifier). |
| `action_fraction` | float | Target fraction of total connections for freemium campaigns. |

Pipeline condition defaults live in `SiteConfig` and can be overridden per campaign in Django Admin or via `oo config`.

| Field | Default | Description |
|:------|:--------|:------------|
| `min_qualification_observations_before_connect` | `0` | Minimum campaign model labels before returning cold connect candidates. `0` disables the guard. |
| `preconnect_qualification_batch_size` | `1` | Maximum pending leads to qualify in one pre-connect guard pass. |

## LinkedIn Export Import

Use the local CLI to import first-party LinkedIn member data exports:

```bash
oo linkedin import-export /path/to/Basic_LinkedInDataExport.zip --campaign "Campaign Name"
```

The importer reads `Connections.csv`, `Invitations.csv`, and `messages.csv`
directly from the ZIP. It creates or reuses `Lead` rows, attaches warm leads to
the target campaign through `CampaignLead`, imports message history as
`ChatMessage`, and prints created/reused/skipped counts. The command is
idempotent and does not send messages, connection requests, or use browser
automation.

## Account Settings (Django Model)

Account data is stored in the `LinkedInProfile` Django model (1:1 with `auth.User`), managed via
Django Admin or created during interactive onboarding.

| Field | Type | Description | Default |
|:------|:-----|:------------|:--------|
| `linkedin_username` | string | LinkedIn login email. | (required) |
| `linkedin_password` | string | LinkedIn password. | (required) |
| `active` | boolean | Enable/disable this account. | `true` |
| `subscribe_newsletter` | boolean | Receive OpenOutreach updates. | `true` |
| `connect_daily_limit` | integer | Max connection requests per day. | `20` |
| `follow_up_daily_limit` | integer | Max follow-up messages per day. | `30` |
| `legal_accepted` | boolean | Whether the user accepted the legal notice. | `false` |

Rate limiting is enforced by `LinkedInProfile` methods (`can_execute()`, `record_action()`,
`mark_exhausted()`) backed by the `ActionLog` model, surviving daemon restarts.

### GDPR Location Detection

On the first run, the daemon checks the logged-in user's LinkedIn country code against a static set of
ISO-2 codes for jurisdictions with opt-in email marketing laws (EU/EEA, UK, Switzerland, Canada, Brazil,
Australia, Japan, South Korea, New Zealand).

- **Non-GDPR location**: `subscribe_newsletter` is auto-set to `true` for that account.
- **GDPR-protected location**: the existing value is preserved (no override).
- **Unknown/empty location**: defaults to GDPR-protected (errs on the side of caution).

This check runs once per account (a database marker record prevents re-runs).

## Hardcoded Defaults (`conf.py:CAMPAIGN_CONFIG`)

Timing and ML defaults are hardcoded in `linkedin/conf.py`. These are not user-configurable.

| Key | Value | Description |
|:----|:------|:------------|
| `check_pending_recheck_after_hours` | `24` | Base interval (hours) before first pending check. Doubles per profile via exponential backoff. |
| `enrich_min_delay_seconds` | `6` | Min pause (seconds) between enrichment API calls during auto-discovery. |
| `enrich_max_delay_seconds` | `10` | Max pause (seconds) — actual delay is `random.uniform(min, max)`. |
| `enrich_max_per_page` | `10` | Max profiles enriched per discovered page (DOM order, LinkedIn relevance). |
| `burst_min_seconds` | `2700` | Min work burst (45 min) before the daemon takes a human-rhythm break. |
| `burst_max_seconds` | `3900` | Max work burst (65 min). Actual burst is `random.uniform(min, max)`. |
| `break_min_seconds` | `600` | Min break length (10 min) after each burst. |
| `break_max_seconds` | `1200` | Max break length (20 min). |
| `min_action_interval` | `120` | Minimum seconds between major actions. |
| `qualification_n_mc_samples` | `100` | Monte Carlo samples for BALD computation. |
| `min_ready_to_connect_prob` | `0.9` | GP probability threshold for promoting QUALIFIED to READY_TO_CONNECT. |
| `min_positive_pool_prob` | `0.20` | P(f > 0.5) threshold for positive pool check in exploit mode. |
| `embedding_model` | `BAAI/bge-small-en-v1.5` | FastEmbed model for 384-dim profile embeddings. |
| `connect_delay_seconds` | `10` | Delay between connect tasks. |
| `connect_no_candidate_delay_seconds` | `300` | Delay when candidate pool is empty. |
| `check_pending_jitter_factor` | `0.2` | Multiplicative jitter factor for backoff. |

Other constants: `MIN_DELAY` (5s) / `MAX_DELAY` (8s) for human-like wait timing.

See [Templating](./templating.md) for follow-up messaging configuration.
