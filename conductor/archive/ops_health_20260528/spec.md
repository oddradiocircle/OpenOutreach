# Spec: Operational Health — Set up and verify the runtime

## Goal

Get the OpenOutreach application running locally from a clean state. This is a maintenance/ops track — no new features, no refactoring. Only the minimum actions needed to make the system fully operational.

## Scope

1. Create a Python virtual environment and install all dependencies.
2. Install Playwright browsers.
3. Run Django migrations (apply any pending ones).
4. Bootstrap the CRM (`setup_crm` management command).
5. Verify the existing test suite passes.
6. Confirm the Django Admin server starts correctly.
7. Confirm the daemon (`rundaemon`) starts and enters the task queue loop without crashing.

## Out of Scope

- New features
- Refactoring existing code
- Adding new campaigns or leads (that's done interactively by the user via the daemon's onboarding wizard)

## Success Criteria

- `.venv` exists and all `requirements/local.txt` deps are installed.
- `pytest` runs and all tests pass (or known failures are documented).
- `python manage.py migrate` reports no pending migrations.
- `make admin` starts the Django Admin at `http://localhost:8000/admin/`.
- `make run` starts the daemon without an immediate crash.
