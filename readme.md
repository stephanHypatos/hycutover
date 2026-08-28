# HyCutOver

Streamlit multi-page app for managing cutovers between two Hypatos companies
(or duplicating configuration within one company) via the Hypatos REST API.

## Features

- **Compare projects** — data-point and metadata-level schema diffs powered by
  `DeepDiff`.
- **Clone projects** — copy projects from a source company to a target
  company, including routing rules and a configurable extraction model id.
- **Bulk schema comparison** — compare schemas across many projects via an
  Excel upload.
- **Config / schema clone & update** — targeted PATCH updates for a single
  project's config or schema.
- **Copy agent workflows** — copy an agent workflow (and every agent it
  references) between companies, or duplicate one within the same company.
  Sanitizes OOTB / source-provenance fields and remaps agent references in
  `workflowConfiguration`.
- **Compare agents & workflows** — side-by-side diff of two agents' prompt /
  systemPrompt / outputFormat / configuration, or of two full workflows plus
  every agent they reference. Purpose-built for spotting prod-vs-test drift.
- **Manage project users** — inspect who has access to which projects, build
  ad-hoc user groups and assign (or remove) them across many projects in one
  go, resolving names / email addresses to user ids automatically.
- **Copy composite enrichment workflows** — copy composite enrichment
  workflows between companies.
- **File batch processing** — upload files and trigger batch processing.
- **Copy documents** — replay documents from one project into another.
- **Polling** — inspect long-running operations.

## Prerequisites

1. API v2 credentials for the source and target companies.
2. Credential scopes:
   - `projects.read`, `projects.write`
   - `routings.read`, `routings.write`
   - `companies.read`
   - `agents.read`, `agents.write` (Copy Agent Workflow and Compare
     Agents & Workflows pages)
   - `users.read` (Manage Project Users page)

Read more:
<https://docs-internal.hypatos.ai/implementation-playbook/introduction-to-implementation-playbook/implementation-playbook/create-or-update-keycloak-credentials>

## Running locally

```bash
pip install -r requirements.txt
streamlit run Home.py
```

Each page collects the source and target credentials it needs at the top and
authenticates them via OAuth 2.0 client-credentials flow.

## Tech stack

- Python + Streamlit (multi-page app)
- `requests` for HTTP
- `pandas` + `openpyxl` for Excel handling
- `DeepDiff` for schema comparison

## Contact

Open an issue on the GitHub repository for bug reports or feature requests.
