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
  See [Guide: Manage Project Users](#guide-manage-project-users).
- **Copy composite enrichment workflows** — copy composite enrichment
  workflow definitions (YAML) between companies, or duplicate them within one,
  via the `/enrichment-workflows` REST API. Handles name conflicts (skip /
  overwrite / create) and re-maps or drops the company-specific `projectIds`.
- **Compare composite enrichment workflows** — side-by-side, line-level diff of
  two enrichment workflow definitions plus their name and description. Project
  bindings (`projectIds`) are excluded, since the ids are unique per company and
  always differ. Purpose-built for spotting prod-vs-test drift.
- **Export configuration as Markdown** — pick a company and a set of projects
  and download a ZIP of Markdown files documenting their configuration: the
  composite enrichment workflow(s), the dynamic agent workflow(s), one file per
  referenced agent (name, system prompt, user prompt) and the routing rules.
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
   - `enrichment-workflows.read`, `enrichment-workflows.write` (Copy and
     Compare Composite Enrichment Workflows pages)
   - `agents.read`, `enrichment-workflows.read`, `routings.read` (Export
     Configuration as Markdown page)

Read more:
<https://docs-internal.hypatos.ai/implementation-playbook/introduction-to-implementation-playbook/implementation-playbook/create-or-update-keycloak-credentials>

## Running locally

```bash
pip install -r requirements.txt
streamlit run Home.py
```

Each page collects the source and target credentials it needs at the top and
authenticates them via OAuth 2.0 client-credentials flow.

## Guide: Manage Project Users

Assigning users to projects in the Hypatos UI is one project at a time. This
page does it in bulk: pick the users once, pick every project they belong to,
apply. All work happens on **one company** — there is no source/target here.

### Before you start

You need API v2 credentials for that company with the scopes
`projects.read`, `projects.write`, `users.read` and `companies.read`.
Without `users.read` the page cannot translate user ids into names, and
without `projects.write` the final step will fail.

### Step 1 — Credentials

Choose the region (EU or US), paste `client_id` and `client_secret`, and click
**Authenticate**. On success the company name and id are shown — check that
this is really the company you want to change.

### Step 2 — Load users and projects

Click **Load users & projects**. This fetches the company's projects and the
user directory once, and caches them for the session.

- **Only show users with access to this company** (on by default) hides users
  the API returns who have no access to this company. Turn it off if someone
  you expect is missing.
- **Reload directory** re-fetches everything — use it after users or projects
  were created elsewhere.
- Expand **User directory** to see every selectable user with name, email,
  roles and id.

### Step 3 — Inspect current assignments

Select one or more projects under **Projects to inspect**. For each project
you get:

- **access** — either *all company users* (everyone in the company can see the
  project) or *explicit members* (only a named list).
- **members** / **users** — how many users are assigned and who they are.

Below the table, an **assignment matrix** shows users as rows and the selected
projects as columns: `✓` means assigned, `all` means the project is open to
everyone. **Download matrix as CSV** exports exactly what you see — handy as a
before/after record or for sharing with a customer.

Use **Refresh selected projects** if someone changed access in the UI while
you had the page open.

### Step 4 — User groups

A group is just a named list of users, so you don't have to re-pick the same
ten people for every project. **Groups are not an API concept** — they live in
your browser session only and are resolved into user ids when you apply
changes. Nothing is stored on the Hypatos side.

1. Type a **Group name** (e.g. `AP Team Germany`).
2. Select the users under **Users in this group**.
3. Click **Save group**.

Each saved group appears as an expander showing its members, with a **Delete
group** button. **Export groups as JSON** downloads all your groups so you can
re-use them in a later session or hand them to a colleague; **Import groups
from JSON** loads such a file back in. On import, any user id that is not in
the current company's directory is called out in a warning — that usually
means the file came from a different company.

Note that the **Reset** button at the top of the page clears the groups along
with everything else, so export them if you want to keep them.

### Step 5 — Assign users to projects

Pick **who** on the left and **where** on the right.

- **Groups** and **Individual users** are combined — the page shows how many
  distinct users that adds up to.
- **Target projects** defaults to whatever you selected in Step 3, and can be
  changed freely.
- **Action** decides what happens to each target project:
  - *Add users to the current members* — keeps everyone already assigned and
    adds your selection. This is the usual choice.
  - *Remove users from the current members* — takes your selection away and
    leaves the rest untouched.
  - *Replace members with this selection* — the project ends up with exactly
    the users you selected; anyone else loses access.
  - *Grant access to all company users* — opens the project to everyone in
    the company. No user selection needed.

A **Preview** table then shows, per project, the member count before and
after, and whether anything actually changes. Read it before you continue —
nothing has been written yet. Click **Apply changes** to write, and you get a
per-project result table (`✅ updated`, `skipped (no change)`, or the API error).

### Two things to watch out for

- **A project set to *all company users* has no member list.** Adding users to
  it converts it to an explicit list, which means everyone *not* in that list
  loses access. The page warns you and requires a confirmation checkbox before
  it will do this.
- **Removing or replacing can empty the list.** If the result would be zero
  members, the page warns you. Only company admins would keep access.

Either way, changes are applied per project — if one project fails, the others
still go through, and the result table tells you which was which.

### Troubleshooting

| What you see | What it usually means |
| --- | --- |
| `Could not load users. HTTP 403` | The credentials are missing the `users.read` scope. |
| A member shown as `(unknown user) <id>` | The user is assigned to the project but is not in the directory response — typically a deactivated user, or one without access to this company. |
| `❌ HTTP 403` when applying | The credentials are missing `projects.write`. |
| `❌ HTTP 422` when applying | The API rejected the member list — most often an empty list, or a user id that has no access to this company. |
| A user you expect is not selectable | Turn off **Only show users with access to this company** in Step 2, or check the user's company access in the Hypatos UI. |

## Tech stack

- Python + Streamlit (multi-page app)
- `requests` for HTTP
- `pandas` + `openpyxl` for Excel handling
- `DeepDiff` for schema comparison

## Contact

Open an issue on the GitHub repository for bug reports or feature requests.
