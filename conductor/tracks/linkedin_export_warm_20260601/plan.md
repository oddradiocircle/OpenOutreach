# Plan: LinkedIn Export Warm Lead Import & Campaign Lead Queue

## Phase 1: Campaign Lead Foundation [checkpoint: c2fd8c4]

Create the durable campaign-specific lead queue and make it visible to
operators.

- [x] Task 1.1: Define `CampaignLead` model with source, relationship status, priority, metadata, timestamps, and uniqueness constraint d367b3f
- [x] Task 1.2: Create and run Django migration for `CampaignLead` 315f04b
- [x] Task 1.3: Register `CampaignLead` in Django Admin with filters and searchable lead/campaign fields 222e323
- [x] Task 1.4: Add tests for `CampaignLead` uniqueness and basic creation 7078403
- [x] Task: Conductor - User Manual Verification 'Phase 1' (Protocol in workflow.md)

---

## Phase 2: LinkedIn Export Importer [checkpoint: d231fc3]

Add a ZIP importer that can safely ingest LinkedIn export data without browser
automation.

- [x] Task 2.1: Create `linkedin/importers/linkedin_export.py` with CSV helpers for ZIP reads and LinkedIn note/header handling ba981af
- [x] Task 2.2: Implement `Connections.csv` import to create/reuse `Lead` and create/update `CampaignLead` c3d68fa
- [x] Task 2.3: Implement `Invitations.csv` import with direction/status metadata and deduplication 9e014bb
- [x] Task 2.4: Implement `messages.csv` import to deduplicate `ChatMessage` rows using stable synthetic `linkedin_urn` values cccb25b
- [x] Task 2.5: Add importer unit tests with small in-memory ZIP fixtures for parsing, idempotency, and skipped invalid URLs f33cf9f
- [x] Task: Conductor - User Manual Verification 'Phase 2' (Protocol in workflow.md)

---

## Phase 3: CLI Import Command [checkpoint: 37900bc]

Expose the importer through the existing operator CLI and make the operation
auditable from terminal output.

- [x] Task 3.1: Add `oo linkedin import-export <zip-path> --campaign "<campaign>"` command 1c16a62
- [x] Task 3.2: Validate campaign lookup, file existence, ZIP readability, and missing expected CSV files 979f64f
- [x] Task 3.3: Print a concise import summary with created/reused/skipped counts e79108e
- [x] Task 3.4: Add CLI tests for success, missing campaign, missing file, and idempotent rerun behavior 17818d4
- [x] Task: Conductor - User Manual Verification 'Phase 3' (Protocol in workflow.md)

---

## Phase 4: Qualification Priority and Warm Connected Flow [checkpoint: 339d696]

Make imported campaign leads drive qualification order and prevent already
connected people from entering the cold connect path.

- [x] Task 4.1: Update `get_leads_for_qualification(session)` to prioritize pending `CampaignLead` rows before generic global leads b02d378
- [x] Task 4.2: Add helper to resolve a lead's campaign relationship status for the active campaign d92b4e9
- [x] Task 4.3: Update positive qualification deal creation so `relationship_status=connected` creates `CONNECTED` deals directly 558dc66
- [x] Task 4.4: Verify already-connected campaign leads are excluded from `READY_TO_CONNECT` and connect-slot consumption a0f7a72
- [x] Task 4.5: Add tests for candidate ordering, connected warm lead state, and fallback to global leads 65694d3
- [x] Task: Conductor - User Manual Verification 'Phase 4' (Protocol in workflow.md)

---

## Phase 5: Pre-Connect Guard and Feedback Labels [checkpoint: b01a3c2]

Prevent cold connects before the model has enough observations and make manual
`wrong_fit` feedback train the model correctly.

- [x] Task 5.1: Add site/campaign config fields for `min_qualification_observations_before_connect` and `preconnect_qualification_batch_size` 474f8d1
- [x] Task 5.2: Update `PipelineConfig`, admin help text, CLI config parsing, and tests for the new fields dbdfc6f
- [x] Task 5.3: Add bounded pre-connect qualification guard in `ready_source()` or adjacent pool helper 0c2baff
- [x] Task 5.4: Update `Lead.get_labeled_arrays()` so any `outcome=wrong_fit` labels negative regardless of state b029ad7
- [x] Task 5.5: Add tests for bounded guard behavior and `CONNECTED`/`COMPLETED` wrong-fit negative labels 67210e7
- [x] Task: Conductor - User Manual Verification 'Phase 5' (Protocol in workflow.md)

---

## Phase 6: Documentation and End-to-End Verification

Document the warm import workflow and verify the whole path against the local
LinkedIn export fixture.

- [x] Task 6.1: Update `ARCHITECTURE.md` and relevant docs with `CampaignLead`, import command, and warm lead lifecycle 114fad2
- [x] Task 6.2: Add a small documented manual test plan for importing a LinkedIn export into the Red Warm campaign 351c275
- [ ] Task 6.3: Run targeted tests and full `pytest`
- [ ] Task 6.4: Confirm no import path triggers browser automation, connection requests, or message sends
- [ ] Task: Conductor - User Manual Verification 'Phase 6' (Protocol in workflow.md)
