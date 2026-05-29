# Plan: Operational Health — Set up and verify the runtime

## Phase 1: Environment Setup

- [x] Task 1.1: Create Python virtual environment (`uv venv`)
- [x] Task 1.2: Install dependencies (`uv pip install -r requirements/local.txt`)
- [ ] Task 1.3: Install Playwright browsers (`.venv/bin/playwright install --with-deps chromium`)
- [ ] Task 1.4: Run Django migrations (`.venv/bin/python manage.py migrate --no-input`)
- [ ] Task 1.5: Bootstrap CRM (`.venv/bin/python manage.py setup_crm`)
- [ ] Task: Conductor - User Manual Verification 'Phase 1: Environment Setup' (Protocol in workflow.md)

## Phase 2: Verification

- [ ] Task 2.1: Run test suite (`.venv/bin/pytest`) and document results
- [ ] Task 2.2: Start Django Admin and confirm it loads (`make admin`)
- [ ] Task 2.3: Start daemon and confirm it enters the task loop without crashing (`make run`)
- [ ] Task: Conductor - User Manual Verification 'Phase 2: Verification' (Protocol in workflow.md)
