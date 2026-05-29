# Technology Stack: OpenOutreach

## Language

- **Python 3** — primary language for all application code, ML pipeline, and automation.

## Web Framework

- **Django 5.2+** — web framework and ORM. Django Admin serves as the primary operator UI (CRM, campaign management, configuration).
- **Django migrations** — all schema changes go through Django migrations for clean upgrades.

## Browser Automation

- **Playwright** — headless browser automation for LinkedIn interaction.
- **playwright-stealth** — stealth plugin to mimic real human behavior and avoid detection.

## ML and Embeddings

- **scikit-learn** — Gaussian Process Regressor (GPR) for Bayesian lead scoring. Per-campaign models serialized to `Campaign.model_blob`.
- **fastembed** — fast, local text embeddings (384-dim). Cached at `.cache/fastembed/`. Used for profile embeddings stored on `Lead.embedding`.
- **HuggingFace Hub** — model registry for fastembed model downloads.

## LLM Integration

- **pydantic-ai-slim** — multi-provider LLM client. Supported providers: OpenAI, Anthropic, Google, Groq, Mistral, Cohere, Bedrock, and any OpenAI-compatible endpoint.
- Provider and model are configured at runtime via `SiteConfig` DB singleton (editable in Django Admin).

## Data Layer

- **SQLite** — primary database, stored at `data/db.sqlite3`. Mounted as a Docker volume for persistence.
- **Pydantic** — data validation and serialization for config, API responses, and task payloads.

## Templating

- **Jinja2** — used for LLM prompt templates (`.j2` files under `linkedin/templates/prompts/`).

## Task Queue

- **Custom Django-based task queue** — `Task` model (persistent). Three task types: `connect`, `check_pending`, `follow_up`. Handlers in `linkedin/tasks/`. Slot creation centralized in `linkedin/tasks/scheduler.py`.

## Testing

- **pytest** — test runner.
- **pytest-cov** — code coverage reporting.

## Containerization and Deployment

- **Docker + Docker Compose** — containerized deployment. Playwright base image.
- **Xvfb + VNC** — virtual display for headless browser; VNC on port 5900 for inspection.
- `BUILD_ENV` arg selects the appropriate requirements file (`local.txt` vs `production.txt`).

## CI/CD

- **GitHub Actions** — `.github/workflows/tests.yml` (pytest on PR), `deploy.yml` (build + push to `ghcr.io`).

## Dependencies

Managed in `requirements/`:
- `base.txt` — core runtime dependencies
- `local.txt` — local dev extras
- `production.txt` — production extras
- `crm.txt` — CRM-specific dependencies

Always use `.venv/bin/python` (not system `python3`).
