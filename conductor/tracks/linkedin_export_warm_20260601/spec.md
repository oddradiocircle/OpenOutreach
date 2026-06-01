# Spec: LinkedIn Export Warm Lead Import & Campaign Lead Queue

## Overview

Use LinkedIn's complete member data export as a first-party data source for
warm outreach. The system should import existing connections, invitations, and
message history into OpenOutreach, attach those leads explicitly to a campaign,
and make the qualification/follow-up pipeline treat already-connected people
as warm leads instead of cold connection targets.

This track also fixes a model feedback issue: operator feedback marked as
`wrong_fit` must train the campaign model as a negative example even when the
deal has already reached `CONNECTED` or `COMPLETED`.

## Functional Requirements

### FR1 - CampaignLead queue model

- Add a `CampaignLead` model representing a lead intentionally assigned to a
  campaign before a `Deal` exists.
- Fields:
  - `campaign` FK to `Campaign`
  - `lead` FK to `crm.Lead`
  - `source` enum/string for `linkedin_connection`, `linkedin_invitation`,
    `imported_contact`, `linkedin_search`, and `manual`
  - `relationship_status` enum/string for `connected`, `invited`, and
    `unknown`
  - `priority` integer where lower numbers are processed first
  - `connected_on` optional date
  - `metadata` JSON for import-specific fields
  - timestamps
- Enforce one `CampaignLead` row per `(campaign, lead)`.
- Register `CampaignLead` in Django Admin with useful filters for campaign,
  source, relationship status, and priority.

### FR2 - LinkedIn export importer

- Add an importer module for LinkedIn member export ZIP files.
- Support at minimum:
  - `Connections.csv`
  - `messages.csv`
  - `Invitations.csv`
- The importer must read ZIP files without requiring users to extract them.
- `Connections.csv` import must:
  - skip LinkedIn's leading notes before the real CSV header
  - parse profile URLs into `Lead.public_identifier`
  - create or reuse `Lead` rows
  - create or update `CampaignLead` rows with
    `source=linkedin_connection`, `relationship_status=connected`,
    `priority=10`, and `connected_on` when available
  - preserve company, position, email, and name fields in metadata without
    making them required durable CRM fields
- `Invitations.csv` import must:
  - parse inviter/invitee profile URLs when available
  - create or reuse `Lead` rows
  - create or update `CampaignLead` rows with
    `source=linkedin_invitation`, `relationship_status=invited`, and metadata
    capturing direction, sent timestamp, and message
- `messages.csv` import must:
  - parse sender and recipient profile URLs
  - create or reuse `Lead` rows for matched counterparties
  - create deduplicated `ChatMessage` rows linked to the `Lead`
  - generate stable synthetic `linkedin_urn` values for export-sourced
    messages, e.g. from conversation id, date, direction, and content hash
  - set `is_outgoing` by comparing sender/recipient against the owner profile
    data available in the export

### FR3 - CLI entrypoint

- Add a CLI command to import a LinkedIn export ZIP into a campaign.
- Proposed shape:
  - `oo linkedin import-export <zip-path> --campaign "<campaign name>"`
- The command must print a concise import summary:
  - files processed
  - created/reused leads
  - created/updated campaign leads
  - messages imported/skipped
  - invitations imported/skipped
  - rows skipped due to missing or invalid profile URLs
- The command must be idempotent: running it again on the same ZIP should not
  duplicate leads, campaign leads, or chat messages.

### FR4 - Qualification candidate priority

- Update `get_leads_for_qualification(session)` so campaign-assigned leads are
  selected before generic global leads.
- Priority order:
  1. `CampaignLead` rows for the active campaign without a `Deal`
  2. generic non-disqualified leads without a `Deal` in the active campaign
- Within `CampaignLead`, sort by `priority`, then creation date.
- Existing behavior should remain available as a fallback when a campaign has
  no pending campaign lead rows.

### FR5 - Already-connected lead state

- When a lead qualifies positive and its campaign lead relationship status is
  `connected`, create the campaign deal directly in `CONNECTED` state.
- Already-connected warm leads must not be promoted to `READY_TO_CONNECT` and
  must not consume connect slots.
- The follow-up planner should naturally pick these `CONNECTED` deals through
  the existing follow-up flow.

### FR6 - Pre-connect qualification guard

- Add campaign/site configurable pipeline controls:
  - `min_qualification_observations_before_connect`
  - `preconnect_qualification_batch_size`
- Before a connect candidate can be returned, the pipeline should qualify a
  bounded number of pending leads when the campaign qualifier has fewer than
  the minimum required observations.
- The guard must never run an unbounded batch and must stop cleanly when there
  are no qualification candidates.

### FR7 - Human feedback trains the model correctly

- Update `Lead.get_labeled_arrays(campaign)` so any deal with
  `outcome=wrong_fit` is labeled negative, regardless of state.
- Preserve the rule that operational failures without `wrong_fit` are skipped
  as training data.
- Add tests covering `CONNECTED + wrong_fit` and `COMPLETED + wrong_fit`.

## Non-Functional Requirements

- All schema changes must use Django migrations.
- Importing must be idempotent and safe to rerun.
- The importer must not require browser automation or LinkedIn API calls.
- Do not persist raw ZIP files or unnecessary raw export data.
- Avoid creating embeddings during import; keep embedding generation lazy.
- Avoid sending any messages or connection requests during import.
- Imported message history must integrate with the existing follow-up prompt
  context and cooldown logic.

## Acceptance Criteria

- [ ] `CampaignLead` exists, is migrated, admin-visible, and unique by campaign
      and lead.
- [ ] Running the import command on the LinkedIn ZIP creates/reuses leads from
      `Connections.csv` and attaches them to the selected campaign.
- [ ] Re-running the same import command does not create duplicates.
- [ ] Imported LinkedIn connections with positive qualification become
      `CONNECTED` deals directly.
- [ ] Imported connected leads do not enter `READY_TO_CONNECT` and do not
      consume connect actions.
- [ ] Imported messages appear as `ChatMessage` rows linked to the matching
      lead and are available to follow-up prompt rendering.
- [ ] `CampaignLead` candidates are qualified before generic global lead
      fallback candidates.
- [ ] The pre-connect guard qualifies a bounded batch before allowing cold
      connects when the model has too few observations.
- [ ] `wrong_fit` deals train as negative examples even if their state is
      `CONNECTED` or `COMPLETED`.
- [ ] Tests cover importer parsing/idempotency, candidate priority,
      connected-state promotion, pre-connect guard behavior, and wrong-fit
      labeling.

## Out of Scope

- Building a full contact matching engine for `ImportedContacts.csv` rows that
  do not include LinkedIn profile URLs.
- Importing all LinkedIn export files; this track only requires connections,
  invitations, and messages.
- New frontend screens outside Django Admin and CLI.
- Automatic LLM summarization of all imported historical messages at import
  time. Existing lazy summary generation may process them later.
- Sending outreach during import.
