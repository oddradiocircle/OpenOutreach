# LinkedIn Export Import Manual Test

This plan verifies importing a first-party LinkedIn member export into the
`Red Warm` campaign.

## Preconditions

- Local database is migrated: `.venv/bin/python manage.py migrate`
- The target campaign exists: `oo campaign show "Red Warm"`
- You have a LinkedIn member export ZIP downloaded from LinkedIn.

## Steps

1. Run the import:

   ```bash
   oo linkedin import-export /path/to/Basic_LinkedInDataExport.zip --campaign "Red Warm"
   ```

2. Confirm terminal output lists processed files and counts for:
   - leads created/reused
   - campaign leads created/updated
   - invitations imported/skipped
   - messages imported/skipped
   - invalid profile URLs skipped

3. Re-run the same command on the same ZIP.

4. Confirm the second run reuses existing leads and updates existing
   campaign leads instead of creating duplicates.

5. Open Django Admin and inspect `Campaign leads` filtered to `Red Warm`.
   Confirm imported connections have `relationship_status=connected` and
   priority `10`.

6. Inspect one imported lead in Admin and confirm linked `ChatMessage` rows
   appear when the export included `messages.csv` rows for that profile.

## Safety Checks

- The import command must not open a browser.
- The import command must not send connection requests.
- The import command must not send messages.
- The import command must not persist the raw ZIP file.
