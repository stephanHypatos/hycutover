import json

import pandas as pd
import streamlit as st

from auth import HypatosAPI
from config import BASE_URL_EU, BASE_URL_US

st.set_page_config(page_title="Manage Project Users", layout="wide")
st.title("Manage Project Users")
st.caption(
    "Inspect and bulk-edit project member access for one company. "
    "Build reusable user groups and assign them to many projects at once, "
    "instead of clicking through the UI project by project."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _reset(prefix: str = "mpu_"):
    for k in list(st.session_state.keys()):
        if k.startswith(prefix):
            st.session_state.pop(k, None)


def _members_mode(project: dict) -> str:
    """'all' (every company user) or 'members' (explicit list)."""
    members = project.get("members") or {}
    return members.get("allow") or "?"


def _member_ids(project: dict) -> list:
    """Explicit member ids of a project; empty list when access is 'all'."""
    members = project.get("members") or {}
    if members.get("allow") == "members":
        return [m for m in (members.get("members") or []) if m]
    return []


def _has_company_access(user: dict, company_id: str) -> bool:
    for access in user.get("companiesAccess") or []:
        if access.get("companyId") == company_id:
            return True
    return False


def _user_label(user_id: str, directory: dict) -> str:
    user = directory.get(user_id)
    if not user:
        return f"(unknown user) {user_id}"
    name = user.get("name") or "(no name)"
    email = user.get("email")
    return f"{name} <{email}>" if email else name


def _user_roles(user: dict, company_id: str) -> list:
    for access in user.get("companiesAccess") or []:
        if access.get("companyId") == company_id:
            return access.get("roles") or []
    return []


col_reset_l, col_reset_r = st.columns([5, 1])
with col_reset_r:
    if st.button("Reset", key="mpu_reset"):
        _reset()
        st.rerun()


# ---------------------------------------------------------------------------
# Step 1 — Credentials
# ---------------------------------------------------------------------------
st.header("Step 1: Credentials")

if not st.session_state.get("mpu_authed"):
    env = st.selectbox(
        "Region",
        (BASE_URL_EU, BASE_URL_US),
        key="mpu_env",
        format_func=lambda u: "EU - api.cloud.hypatos.ai" if u == BASE_URL_EU else "US - api.cloud.hypatos.com",
    )
    client_id = st.text_input("client_id", key="mpu_client_id")
    client_secret = st.text_input("client_secret", type="password", key="mpu_client_secret")
    st.caption("Required scopes: `projects.read`, `projects.write`, `users.read`, `companies.read`.")

    if st.button("Authenticate", key="mpu_auth"):
        if not (client_id and client_secret):
            st.error("Please provide client_id and client_secret.")
        else:
            api = HypatosAPI(client_id.strip(), client_secret.strip(), env)
            if not api.authenticate():
                st.error(f"Authentication failed. {api.last_error or ''}")
                st.stop()
            company = api.get_company()
            if not company:
                st.error(f"Authenticated but could not fetch the company. {api.last_error or ''}")
                st.stop()
            st.session_state["mpu_api"] = api
            st.session_state["mpu_company"] = company
            st.session_state["mpu_authed"] = True
            st.rerun()
    st.stop()

api: HypatosAPI = st.session_state["mpu_api"]
company = st.session_state["mpu_company"]
company_id = company.get("id")
st.success(f"Company: **{company.get('name', '?')}** (`{company_id}`)")


# ---------------------------------------------------------------------------
# Step 2 — Load users and projects
# ---------------------------------------------------------------------------
st.header("Step 2: Load users and projects")

if "mpu_users" not in st.session_state:
    if st.button("Load users & projects", key="mpu_load"):
        with st.spinner("Loading users and projects..."):
            users = api.list_users()
            if not users and api.last_error:
                st.error(f"Could not load users. {api.last_error}")
                st.stop()
            projects_data = api.get_projects() or {}
            st.session_state["mpu_users"] = users
            st.session_state["mpu_projects"] = projects_data.get("data", [])
        st.rerun()
    st.stop()

all_users = st.session_state["mpu_users"]
projects = st.session_state["mpu_projects"]

col_f1, col_f2 = st.columns([3, 1])
with col_f1:
    only_this_company = st.checkbox(
        "Only show users with access to this company",
        value=True,
        key="mpu_only_company",
    )
with col_f2:
    if st.button("Reload directory", key="mpu_reload"):
        for key in ("mpu_users", "mpu_projects", "mpu_project_details"):
            st.session_state.pop(key, None)
        st.rerun()

visible_users = [u for u in all_users if _has_company_access(u, company_id)] if only_this_company else list(all_users)
if only_this_company and not visible_users:
    st.warning(
        "No user reports access to this company — falling back to every user returned by the API."
    )
    visible_users = list(all_users)

# id -> user, for label lookups (built from the full response so member ids
# outside the current filter still resolve to a name).
directory = {u.get("id"): u for u in all_users if u.get("id")}
visible_users.sort(key=lambda u: (u.get("name") or "").lower())

st.caption(
    f"{len(visible_users)} user(s) selectable · {len(all_users)} returned by the API · "
    f"{len(projects)} project(s) in this company."
)

with st.expander("User directory"):
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "name": u.get("name"),
                    "email": u.get("email"),
                    "roles": ", ".join(_user_roles(u, company_id)),
                    "internal": u.get("isInternal"),
                    "id": u.get("id"),
                }
                for u in visible_users
            ]
        ),
        width="stretch",
        hide_index=True,
    )

if not projects:
    st.error("No projects found for these credentials.")
    st.stop()

project_options = [(p.get("id"), p.get("name")) for p in projects]
project_options.sort(key=lambda p: (p[1] or "").lower())


# ---------------------------------------------------------------------------
# Step 3 — Current assignments
# ---------------------------------------------------------------------------
st.header("Step 3: Inspect current assignments")

selected_projects = st.multiselect(
    "Projects to inspect",
    project_options,
    format_func=lambda p: p[1] or p[0],
    key="mpu_inspect_projects",
)

details = st.session_state.setdefault("mpu_project_details", {})


def _project_detail(project_id: str, force: bool = False) -> dict:
    """GET /projects/{id}, cached per session so reruns don't re-fetch."""
    if force or project_id not in details:
        detail = api.get_project_by_id(project_id)
        if detail:
            details[project_id] = detail
    return details.get(project_id)


if selected_projects:
    if st.button("Refresh selected projects", key="mpu_refresh_details"):
        for pid, _ in selected_projects:
            _project_detail(pid, force=True)
        st.rerun()

    rows = []
    matrix_ids = set()
    for pid, pname in selected_projects:
        detail = _project_detail(pid)
        if not detail:
            st.error(f"Could not load project `{pid}`. {api.last_error or ''}")
            continue
        mode = _members_mode(detail)
        ids = _member_ids(detail)
        matrix_ids.update(ids)
        rows.append(
            {
                "project": pname or pid,
                "access": "all company users" if mode == "all" else "explicit members",
                "members": len(ids) if mode == "members" else "—",
                "users": ", ".join(sorted(_user_label(i, directory) for i in ids)) if ids else "",
                "project id": pid,
            }
        )

    if rows:
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    if matrix_ids:
        st.subheader("Assignment matrix")
        matrix_rows = []
        for uid in sorted(matrix_ids, key=lambda i: _user_label(i, directory).lower()):
            row = {"user": _user_label(uid, directory)}
            for pid, pname in selected_projects:
                detail = details.get(pid) or {}
                if _members_mode(detail) == "all":
                    row[pname or pid] = "all"
                else:
                    row[pname or pid] = "✓" if uid in _member_ids(detail) else ""
            matrix_rows.append(row)
        matrix_df = pd.DataFrame(matrix_rows)
        st.dataframe(matrix_df, width="stretch", hide_index=True)
        st.download_button(
            "Download matrix as CSV",
            matrix_df.to_csv(index=False).encode("utf-8"),
            file_name="project_user_matrix.csv",
            mime="text/csv",
            key="mpu_matrix_csv",
        )
else:
    st.info("Select one or more projects to see who has access.")


# ---------------------------------------------------------------------------
# Step 4 — User groups (session-local)
# ---------------------------------------------------------------------------
st.header("Step 4: User groups")
st.caption(
    "Groups exist only in this browser session — the API has no group concept, so a group "
    "is resolved to its user ids at assignment time. Export them to reuse them later."
)

groups: dict = st.session_state.setdefault("mpu_groups", {})

with st.form("mpu_group_form", clear_on_submit=True):
    group_name = st.text_input("Group name", placeholder="e.g. AP Team Germany")
    group_members = st.multiselect(
        "Users in this group",
        [u.get("id") for u in visible_users],
        format_func=lambda uid: _user_label(uid, directory),
    )
    submitted = st.form_submit_button("Save group")
    if submitted:
        if not group_name.strip():
            st.warning("Please give the group a name.")
        elif not group_members:
            st.warning("Please select at least one user.")
        else:
            groups[group_name.strip()] = list(group_members)
            st.success(f"Saved group **{group_name.strip()}** with {len(group_members)} user(s).")

if groups:
    for name in list(groups.keys()):
        with st.expander(f"{name} — {len(groups[name])} user(s)"):
            for uid in groups[name]:
                st.write(f"- {_user_label(uid, directory)}")
            if st.button("Delete group", key=f"mpu_del_{name}"):
                groups.pop(name, None)
                st.rerun()

    st.download_button(
        "Export groups as JSON",
        json.dumps(groups, indent=2).encode("utf-8"),
        file_name="user_groups.json",
        mime="application/json",
        key="mpu_groups_export",
    )
else:
    st.info("No groups yet.")

uploaded = st.file_uploader("Import groups from JSON", type=["json"], key="mpu_groups_import")
# Only import once per uploaded file — otherwise every rerun would re-add the
# groups and undo a deletion made afterwards.
if uploaded is not None and st.session_state.get("mpu_imported_file") != uploaded.file_id:
    st.session_state["mpu_imported_file"] = uploaded.file_id
    try:
        imported = json.load(uploaded)
        if not isinstance(imported, dict) or not all(isinstance(v, list) for v in imported.values()):
            st.error("Expected a JSON object mapping group name to a list of user ids.")
        else:
            for name, ids in imported.items():
                groups[str(name)] = [str(i) for i in ids]
            unknown = {i for ids in imported.values() for i in ids if i not in directory}
            if unknown:
                st.warning(
                    f"Imported, but {len(unknown)} user id(s) are not in this company's directory: "
                    + ", ".join(sorted(unknown))
                )
            st.success(f"Imported {len(imported)} group(s).")
    except json.JSONDecodeError as err:
        st.error(f"Could not parse the file: {err}")


# ---------------------------------------------------------------------------
# Step 5 — Assign
# ---------------------------------------------------------------------------
st.header("Step 5: Assign users to projects")

col_who, col_where = st.columns(2)

with col_who:
    st.subheader("Who")
    chosen_groups = st.multiselect(
        "Groups",
        sorted(groups.keys()),
        key="mpu_assign_groups",
    )
    chosen_users = st.multiselect(
        "Individual users",
        [u.get("id") for u in visible_users],
        format_func=lambda uid: _user_label(uid, directory),
        key="mpu_assign_users",
    )
    target_user_ids = {uid for g in chosen_groups for uid in groups.get(g, [])} | set(chosen_users)
    if target_user_ids:
        st.caption(f"{len(target_user_ids)} distinct user(s) resolved.")

with col_where:
    st.subheader("Where")
    target_projects = st.multiselect(
        "Target projects",
        project_options,
        default=selected_projects,
        format_func=lambda p: p[1] or p[0],
        key="mpu_assign_projects",
    )
    action = st.radio(
        "Action",
        (
            "Add users to the current members",
            "Remove users from the current members",
            "Replace members with this selection",
            "Grant access to all company users",
        ),
        key="mpu_action",
    )

grant_all = action == "Grant access to all company users"

if not target_projects or (not target_user_ids and not grant_all):
    st.info("Pick at least one target project, and the users to apply (unless granting access to all).")
    st.stop()

# Build the plan, fetching current state for any project not inspected yet.
plan = []
needs_conversion = []
for pid, pname in target_projects:
    detail = _project_detail(pid)
    if not detail:
        st.error(f"Could not load project `{pname or pid}`. {api.last_error or ''}")
        st.stop()
    mode = _members_mode(detail)
    current = _member_ids(detail)

    if grant_all:
        new_members = {"allow": "all"}
        after_ids = None
    else:
        if action == "Add users to the current members":
            after = sorted(set(current) | target_user_ids)
        elif action == "Remove users from the current members":
            after = sorted(set(current) - target_user_ids)
        else:
            after = sorted(target_user_ids)
        new_members = {"allow": "members", "members": after}
        after_ids = after
        if mode == "all":
            needs_conversion.append(pname or pid)

    plan.append(
        {
            "project": pname or pid,
            "project_id": pid,
            "before": "all company users" if mode == "all" else f"{len(current)} member(s)",
            "after": "all company users" if after_ids is None else f"{len(after_ids)} member(s)",
            "changed": (
                mode != "all" if grant_all else (mode == "all" or sorted(current) != after_ids)
            ),
            "members": new_members,
        }
    )

st.subheader("Preview")
st.dataframe(
    pd.DataFrame([{k: v for k, v in row.items() if k != "members"} for row in plan]),
    width="stretch",
    hide_index=True,
)

if needs_conversion:
    st.warning(
        "These projects currently allow **all company users**. Applying an explicit member "
        "list will restrict access to only the selected users: "
        + ", ".join(needs_conversion)
    )
    convert_ok = st.checkbox(
        "I understand — convert these projects to an explicit member list",
        key="mpu_convert_ok",
    )
else:
    convert_ok = True

empty_lists = [
    row["project"]
    for row in plan
    if row["members"].get("allow") == "members" and not row["members"].get("members")
]
if empty_lists:
    st.warning(
        "The resulting member list is empty for: "
        + ", ".join(empty_lists)
        + ". Nobody but company admins would keep access."
    )

if st.button("Apply changes", type="primary", key="mpu_apply", disabled=not convert_ok):
    results = []
    progress = st.progress(0.0)
    for i, row in enumerate(plan, start=1):
        if not row["changed"]:
            results.append({"project": row["project"], "result": "skipped (no change)"})
        else:
            updated = api.update_project_members(row["project_id"], row["members"])
            if updated:
                details[row["project_id"]] = updated
                results.append({"project": row["project"], "result": "✅ updated"})
            else:
                results.append({"project": row["project"], "result": f"❌ {api.last_error or 'failed'}"})
        progress.progress(i / len(plan))
    st.dataframe(pd.DataFrame(results), width="stretch", hide_index=True)
    failed = [r for r in results if r["result"].startswith("❌")]
    if failed:
        st.error(f"{len(failed)} project(s) failed to update.")
    else:
        st.success("Done. Re-inspect in Step 3 to confirm.")
