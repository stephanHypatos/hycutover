# CLAUDE.md

## Project Overview

HyCutOver is a Streamlit multi-page web application for managing Hypatos project operations: schema comparison, project cloning, configuration updates, and bulk operations between companies.

## Tech Stack

- **Python** with **Streamlit** (multi-page app)
- **requests** for HTTP/API calls
- **pandas** + **openpyxl** for Excel handling
- **deepdiff** for schema comparison

## Project Structure

```
Home.py                             # Main entry point / landing page
auth.py                             # HypatosAPI class - OAuth 2.0 auth + all API methods
config.py                           # API base URLs (EU/US)
helpers.py                          # Shared UI helpers (credentials input, project selection)
pages/
  0_Compare_Projects.py             # Schema comparison (datapoints + metadata)
  1_Clone_Projects.py               # Project cloning + routing rules + model ID
  2_Bulk_Schema_Comparison.py       # Bulk comparison via Excel upload
  3_Config_Clone_Update.py          # Config update, config clone, schema clone
requirements.txt
```

## API

- Base URLs: `https://api.cloud.hypatos.ai/v2` (EU), `https://api.cloud.hypatos.com/v2` (US)
- Auth: OAuth 2.0 Client Credentials Grant via `POST /auth/token`
- Key endpoints: `/projects`, `/projects/{id}`, `/projects/{id}/schema`, `/routings`
- All API methods live in `auth.py` → `HypatosAPI` class

## Running

```bash
pip install -r requirements.txt
streamlit run Home.py
```

## Key Patterns

- Each page handles its own authentication flow (source + target companies)
- Auth objects are stored in `st.session_state["source_auth"]` and `st.session_state["target_auth"]`
- Projects are identified by `(id, name)` tuples throughout the UI
- The `update_project()` method uses `PATCH /projects/{id}` for partial updates (config, schema, or both)
- Name-based matching is used in "Clone Schema to Target" to find corresponding projects across companies

## Required API Scopes

- `projects.read`, `projects.write`
- `routings.read`, `routings.write`
