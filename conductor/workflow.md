# Project Workflow

## Guiding Principles

1. **The Plan is the Source of Truth:** All work must be tracked in `plan.md`
2. **The Tech Stack is Deliberate:** Changes to the tech stack must be documented in `tech-stack.md` _before_ implementation
3. **User Experience First:** Every decision should prioritize user experience
4. **Non-Interactive & CI-Aware:** Prefer non-interactive commands. Use `CI=true` for watch-mode tools (tests, linters) to ensure single execution.

## Task Workflow

All tasks follow a strict lifecycle:

### Standard Task Workflow

1. **Select Task:** Choose the next available task from `plan.md` in sequential order

2. **Mark In Progress:** Before beginning work, edit `plan.md` and change the task from `[ ]` to `[~]`

3. **Implement the Task:**
   - Write the minimum amount of application code necessary to complete the task.
   - Run existing tests to confirm nothing is broken: `pytest`

4. **Document Deviations:** If implementation differs from tech stack:
   - **STOP** implementation
   - Update `tech-stack.md` with new design
   - Add dated note explaining the change
   - Resume implementation

5. **Commit Code Changes:**
   - Stage all code changes related to the task.
   - Propose a clear, concise single-line commit message (e.g., `feat(ui): create basic HTML structure for calculator`).
   - **CRITICAL:** Commit messages must be single-line. No body. No `Co-Authored-By` lines.
   - Perform the commit.

6. **Attach Task Summary with Git Notes:**
   - **Step 6.1: Get Commit Hash:** Obtain the hash of the _just-completed commit_ (`git log -1 --format="%H"`).
   - **Step 6.2: Draft Note Content:** Create a detailed summary for the completed task. This should include the task name, a summary of changes, a list of all created/modified files, and the core "why" for the change.
   - **Step 6.3: Attach Note:** Use the `git notes` command to attach the summary to the commit.
     ```bash
     git notes add -m "<note content>" <commit_hash>
     ```

7. **Get and Record Task Commit SHA:**
   - **Step 7.1: Update Plan:** Read `plan.md`, find the line for the completed task, update its status from `[~]` to `[x]`, and append the first 7 characters of the _just-completed commit's_ commit hash.
   - **Step 7.2: Write Plan:** Write the updated content back to `plan.md`.

8. **Commit Plan Update:**
   - Stage the modified `plan.md` file.
   - Commit with a single-line message (e.g., `conductor(plan): mark task 'Create user model' as complete`).

### Phase Completion Verification and Checkpointing Protocol

**Trigger:** This protocol is executed immediately after a task is completed that also concludes a phase in `plan.md`.

1.  **Announce Protocol Start:** Inform the user that the phase is complete and the verification and checkpointing protocol has begun.

2.  **Execute Automated Tests with Proactive Debugging:**
    - Before execution, announce the exact shell command you will use to run the tests.
    - **Example Announcement:** "I will now run the automated test suite to verify the phase. **Command:** `pytest`"
    - Execute the announced command.
    - If tests fail, inform the user and begin debugging. Attempt a fix a **maximum of two times**. If tests still fail after the second attempt, **stop**, report the persistent failure, and ask the user for guidance.

3.  **Propose a Detailed, Actionable Manual Verification Plan:**
    - Analyze `product.md` and `plan.md` to determine the user-facing goals of the completed phase.
    - Generate a step-by-step plan that walks the user through verification, including any necessary commands and specific expected outcomes.

4.  **Await Explicit User Feedback:**
    - Ask the user: "**Does this meet your expectations? Please confirm with yes or provide feedback on what needs to be changed.**"
    - **PAUSE** and await the user's response. Do not proceed without an explicit yes or confirmation.

5.  **Create Checkpoint Commit:**
    - Stage all changes.
    - Perform a single-line commit (e.g., `conductor(checkpoint): checkpoint end of Phase X`).

6.  **Attach Auditable Verification Report using Git Notes:**
    - Draft a verification report including the test command, manual verification steps, and user confirmation.
    - Attach it to the checkpoint commit using `git notes`.

7.  **Get and Record Phase Checkpoint SHA:**
    - Obtain the hash of the checkpoint commit.
    - Update `plan.md`: find the completed phase heading and append `[checkpoint: <sha>]`.
    - Commit the plan update with a single-line message (e.g., `conductor(plan): mark phase 'Phase Name' as complete`).

8.  **Announce Completion:** Inform the user the phase is complete and the checkpoint has been created.

### Quality Gates

Before marking any task complete, verify:

- [ ] Existing tests pass (`pytest`)
- [ ] Code follows project style guidelines (`conductor/code_styleguides/`)
- [ ] No linting or static analysis errors
- [ ] Documentation updated if needed (CLAUDE.md, ARCHITECTURE.md)
- [ ] No security vulnerabilities introduced

## Development Commands

### Setup

```bash
make setup    # install deps + browsers + migrate + bootstrap CRM
```

### Daily Development

```bash
make run      # run daemon
make admin    # Django Admin at localhost:8000/admin/
make up       # Docker: start all services
make logs     # Docker: tail logs
```

### Testing

```bash
make test                              # run full test suite
pytest tests/api/test_voyager.py       # single file
pytest -k test_name                    # single test
```

### Python Environment

Always use `.venv/bin/python` (never system `python3`).

## Commit Guidelines

### Message Format

```
<type>(<scope>): <description>
```

- **Single line only.** No body. No `Co-Authored-By` lines.

### Types

- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only
- `style`: Formatting
- `refactor`: Code change that neither fixes a bug nor adds a feature
- `test`: Adding or modifying tests
- `chore`: Maintenance tasks
- `conductor`: Conductor metadata (plan updates, checkpoints)

### Examples

```bash
git commit -m "feat(tasks): add follow-up retry on 429 rate limit"
git commit -m "fix(scheduler): correct poisson slot overflow past active window"
git commit -m "conductor(plan): mark task 'Add check_pending handler' as complete"
```

## Definition of Done

A task is complete when:

1. All code implemented to specification
2. Existing tests pass
3. Documentation updated if needed (CLAUDE.md, ARCHITECTURE.md)
4. Changes committed with a single-line message
5. Git note with task summary attached to the commit
6. `plan.md` updated with commit SHA

## Emergency Procedures

### Critical Bug in Production

1. Create hotfix branch from main
2. Write a failing test for the bug (if feasible)
3. Implement minimal fix
4. Test thoroughly
5. Deploy immediately
6. Document in `plan.md`

### Security Breach

1. Rotate all secrets immediately
2. Review access logs
3. Patch vulnerability
4. Notify affected users (if any)
5. Document and update security procedures
