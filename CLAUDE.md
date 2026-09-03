# CLAUDE.md

## Project Overview

HyCutOver is a Streamlit multi-page web application for managing Hypatos
cutover operations: schema comparison, project cloning, config/schema updates,
agent workflow copy, agent/workflow drift comparison, composite enrichment
workflow copy, file batch processing, document copy, polling, and bulk
project-user management.

## Tech Stack

- **Python** with **Streamlit** (multi-page app)
- **requests** for HTTP/API calls
- **pandas** + **openpyxl** for Excel handling
- **deepdiff** for schema comparison

## Project Structure

```
Home.py                                  # Main entry point / landing page
auth.py                                  # HypatosAPI class - OAuth 2.0 auth + all API methods
setup_api.py                             # SetupAPI class - cookie-based setup.cloud API
config.py                                # API base URLs (EU/US) + setup base URL
helpers.py                               # Shared UI helpers (credentials input, project selection)
pages/
  0_Compare_Projects.py                  # Schema comparison (datapoints + metadata)
  1_Clone_Projects.py                    # Project cloning + routing rules + model ID
  2_Bulk_Schema_Comparison.py            # Bulk comparison via Excel upload
  3_Config_Clone_Update.py               # Config update, config clone, schema clone
  4_Copy_Agent_Workflow.py               # Copy an agent workflow (and referenced agents) between
                                         # companies, or duplicate within one company, using
                                         # /agents and /agent-workflows
  5_Copy_Composite_Enrichment_Workflow.py# Copy/duplicate composite enrichment workflow
                                         # definitions (YAML) via /enrichment-workflows on the
                                         # main v2 API. Conflict handling + projectIds re-mapping.
  6_File_Batch.py                        # Upload files and trigger batch processing
  7_Copy_Documents.py                    # Replay documents from one project into another
  8_Polling.py                           # Inspect long-running operations
  9_Compare_Agents_and_Workflows.py      # Side-by-side diff of two agents, OR two workflows plus
                                         # every agent they reference (prod-vs-test drift check).
                                         # Uses /agents/{id} and /agent-workflows/{id}.
  10_Manage_Project_Users.py             # Inspect and bulk-edit project member access for one
                                         # company. Session-local "user groups" are resolved to
                                         # user ids. Uses /users and PATCH /projects/{id}.
  11_Compare_Composite_Enrichment_Workflows.py
                                         # Side-by-side, line-level diff of two enrichment
                                         # workflow definitions (name, description, YAML
                                         # definition). projectIds are excluded from the
                                         # comparison (company-specific). Prod-vs-test drift.
requirements.txt
```

## API

- Base URLs: `https://api.cloud.hypatos.ai/v2` (EU), `https://api.cloud.hypatos.com/v2` (US)
- Auth: OAuth 2.0 Client Credentials Grant via `POST /auth/token`
- Key endpoints: `/projects`, `/projects/{id}`, `/projects/{id}/schema`,
  `/routings`, `/agents`, `/agents/{id}`, `/agent-workflows`,
  `/agent-workflows/{id}`, `/users`, `/users/{id}`,
  `/enrichment-workflows`, `/enrichment-workflows/{id}`
- All REST API methods live in `auth.py` → `HypatosAPI` class
- `setup_api.py` → `SetupAPI` covers the cookie-authenticated
  `setup.cloud.hypatos.ai` API. It is now legacy: the composite enrichment
  pages were migrated to the OAuth2 `/enrichment-workflows` endpoints on the
  main v2 API (`HypatosAPI`), so `SetupAPI` is no longer used by them.

## Running

```bash
pip install -r requirements.txt
streamlit run Home.py
```

## Key Patterns

- Each page handles its own authentication flow (source + target companies).
- Auth objects are stored in per-page `st.session_state` keys (e.g. `caw_*`
  on the Copy Agent Workflow page, `cmp_*` on the Compare page).
- Projects are identified by `(id, name)` tuples throughout the UI.
- `update_project()` uses `PATCH /projects/{id}` for partial updates
  (config, schema, or both).
- Name-based matching is used in "Clone Schema to Target" to find
  corresponding projects across companies.
- Agent / workflow copy strips server-managed and OOTB / source-provenance
  fields (`isOotb`, `sourceTemplateAgent*`, `sourceWorkflow*`, timestamps,
  ids, `companyId`) before POST — the API returns 422 otherwise.
- `workflowConfiguration` references agents by UUID and by
  `name:version` string; the copy and compare pages scan for both when
  resolving referenced agents.
- Project member access is the discriminated union
  `{"allow": "all"}` or `{"allow": "members", "members": [<userId>, ...]}`.
  `update_project_members()` PATCHes only that field. Switching a project
  from `all` to an explicit list *restricts* access, so the Manage Project
  Users page requires a confirmation for that case.
- There is no group concept in the API. Groups on the Manage Project Users
  page live in `st.session_state` (`mpu_groups`) and are resolved to user ids
  at assignment time; they can be exported / imported as JSON.
- An enrichment workflow `definition` is a YAML string. Create (POST) and
  update (PUT) accept only `name` (required), `definition` (required),
  `description` and `projectIds`; PUT is a full replace. The copy page
  (`cew_*`) re-fetches the source `definition` fresh before writing to avoid
  stale cached YAML; the compare page (`ccew_*`) diffs `definition` with
  `difflib.unified_diff`. `projectIds` are company-specific, so the copy page
  either drops them, keeps them (same-company only) or re-maps by project name,
  and the compare page excludes them from the comparison entirely (shown per
  side for reference only).

## Required API Scopes

- `projects.read`, `projects.write`
- `routings.read`, `routings.write`
- `companies.read`
- `agents.read`, `agents.write` (Copy Agent Workflow, Compare Agents & Workflows)
- `users.read` (Manage Project Users)
- `enrichment-workflows.read`, `enrichment-workflows.write` (Copy and Compare
  Composite Enrichment Workflows)
