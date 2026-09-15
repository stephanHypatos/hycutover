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
  14_Bulk_Upload_and_Process.py          # Upload a folder of documents and process them into
                                         # documents in app-driven batches: upload -> process-file
                                         # -> poll states until each batch settles, then the next.
                                         # Live per-file status; resumable. Uses POST /files,
                                         # POST /documents/process-file, GET /documents.
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
  12_Export_Configuration_as_Markdown.py # Pick a company + projects, fetch their project
                                         # schema + config, composite enrichment workflows,
                                         # dynamic agent workflows, referenced agents and routing
                                         # rules, and download a ZIP of one Markdown file per
                                         # artefact.
  13_Deploy_OOTB_Setup.py                # One-click clone of a pre-defined OOTB setup (projects,
                                         # routings, composite enrichment, agentic workflows +
                                         # agents) from the template company (secrets creds) to a
                                         # target company. Setup->projectIds mapping in secrets
                                         # ([ootb.setups.*]). Pre-flight blocks on agent name:
                                         # version collisions in the target.
requirements.txt
```

## API

- Base URLs: `https://api.cloud.hypatos.ai/v2` (EU), `https://api.cloud.hypatos.com/v2` (US)
- Auth: OAuth 2.0 Client Credentials Grant via `POST /auth/token`
- Key endpoints: `/projects`, `/projects/{id}`, `/projects/{id}/schema`,
  `/routings`, `/agents`, `/agents/{id}`, `/agent-workflows`,
  `/agent-workflows/{id}`, `/users`, `/users/{id}`,
  `/enrichment-workflows`, `/enrichment-workflows/{id}`,
  `/files`, `/documents`, `/documents/{id}`, `/documents/process-file`,
  `/cases/process-file-batch`
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
- The Compare Agents & Workflows page (`cmp_*`) diffs prompts/text via
  `_text_diff`, driven by a page-level whitespace mode (`cmp_ws_mode`):
  "Highlight" renders a character-level inline HTML diff (`_inline_char_diff`)
  with spaces/tabs made visible (`_vis_ws`); "Ignore whitespace" collapses runs
  (`_norm_ws`) before diffing so whitespace-only edits vanish; "Exact" is the
  strict line diff. `_text_differs` applies the same rule to the divergence
  summary / icons so an agent that differs only in whitespace is not flagged as
  changed in Ignore mode. A whitespace-only delta always shows an explicit note.
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
  side for reference only). The definition YAML itself also carries a
  "duplicate projects" section whose project ids are company-specific; the
  compare page parses the YAML (`yaml.safe_load`), structurally drops any
  section matching a configurable name (default `duplicate projects`, matched
  tolerantly via `_norm_key` against both mapping keys and a step's
  name/title), then re-serialises both sides canonically (`safe_dump`,
  `sort_keys=False`) so only meaningful content differences remain. It falls
  back to the raw text diff if a side is not valid YAML, and shows exactly what
  was excluded. Requires `pyyaml`.
- The Export Configuration page (`exp_*`) links projects to artefacts by their
  native binding: each project's schema (`get_project_schema`) + config
  (`get_project_by_id`), enrichment workflows via `projectIds`, agent workflows
  via `list_agent_workflows(project_id=...)`, referenced agents via UUID +
  `name:version` scan of `workflowConfiguration`, and routing rules via
  `fromProjectId` / `toProjectId`. It renders one Markdown file per artefact
  and zips them in memory (`zipfile` + `io.BytesIO`) for `st.download_button`.
  Prompts/definitions are wrapped in a code fence sized longer than any backtick
  run they contain (`_fence`).
- The Bulk Upload & Process page (`bup_*`) uploads a whole folder and processes
  it in app-driven batches so neither Streamlit memory nor the API is
  overwhelmed. Per batch of `batch_size` (default 50): upload each file
  (`upload_file` → `POST /files`), request processing
  (`process_file_into_document` → `POST /documents/process-file`), then poll
  until every document leaves `new`/`processing`. Two modes (`wait_per_batch`):
  "wait for each batch" polls a batch to completion before the next (caps
  concurrency at ≈ batch size); "submit everything, then track" submits all
  files first and polls once (far less wall-clock, since the async processing
  wait is paid once, not per batch). The whole run is one blocking button
  handler that streams live updates to `st.empty()` placeholders; closing the
  tab / sleeping ends the session and loses the in-session id map (already
  submitted documents still process server-side). Polling is bulk: one/two
  `list_documents(states=["new","processing"])` calls per round match by
  documentId, and only a newly-settled doc costs a `get_document_by_id` for its
  final state; a doc reported settled but not yet indexed is re-confirmed and
  kept pending. Per-file tracking lives in `st.session_state["bup_items"]`
  (rebuilt when the selection changes), so a rerun resumes and finished files
  are not redone; failed files are retried on the next Start. File bytes are
  read just-in-time via `UploadedFile.getvalue()` and dropped — the app keeps no
  second copy. `.streamlit/config.toml` raises `maxUploadSize`/`maxMessageSize`
  (defaults 200 MB) so large folders are accepted. Terminal states other than
  `failed`/`rejected` count as done; the exact `state` is always shown.
- The Deploy OOTB Setup page (`ootb_*`) is the template-clone flow extended to
  routings + enrichment + agent workflows. Each setup in
  `st.secrets["ootb"]["setups"]` (with a `DEFAULT_SETUPS` fallback shape) names
  its artefacts by template id: `project_ids`, `enrichment_workflow_ids` and
  `agent_workflow_ids`. The workflow ids are explicit because template workflows
  are not reliably bound to the setup projects; when the id lists are empty the
  page falls back to project-binding discovery (enrichment `projectIds` /
  `list_agent_workflows(project_id=...)`). Template creds are the same
  `CLIENT_ID` / `CLIENT_SECRET` as page 1. Deploy
  order is projects -> routings -> enrichment -> agents -> agent workflows;
  `project_id_map` (source->target) remaps enrichment `projectIds`, routing
  `from/toProjectId`, and each workflow's `projects` / `trainingProjects`
  (`_remap_project_ref`), while `agent_id_map` rewrites `workflowConfiguration`
  UUIDs (`_rewrite_uuids`). A read-only pre-flight blocks the deploy on agent
  `name:version` collisions in the target and skips same-named enrichment
  workflows. Reuses page 4's `AGENT_STRIP` / `WORKFLOW_STRIP` sanitize sets.

## Required API Scopes

- `projects.read`, `projects.write`
- `routings.read`, `routings.write`
- `companies.read`
- `agents.read`, `agents.write` (Copy Agent Workflow, Compare Agents & Workflows)
- `users.read` (Manage Project Users)
- `enrichment-workflows.read`, `enrichment-workflows.write` (Copy and Compare
  Composite Enrichment Workflows)
- `agents.read`, `enrichment-workflows.read`, `routings.read` (Export
  Configuration as Markdown)
- `projects.read/write`, `routings.read/write`, `agents.read/write`,
  `enrichment-workflows.read/write`, `companies.read` (Deploy new OOTB Setup —
  read on the template, write on the target)
- `files.write`, `documents.read`, `documents.write` (Bulk Upload & Process —
  in addition to `projects.read`, `companies.read`)
