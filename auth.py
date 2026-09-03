import unicodedata
import urllib.parse
import requests
from requests.auth import HTTPBasicAuth

class HypatosAPI:
    """
    Handles authentication with the Hypatos API using OAuth 2.0 Client Credentials Grant.
    """

    def __init__(self, client_id: str, client_secret: str, base_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.access_token = None
        self.token_type = None
        self.expires_in = None
        self.scopes = []
        self.last_error = None

    def authenticate(self) -> bool:
        """
        Authenticates with the Hypatos API to obtain an access token.
        """
        token_url = f"{self.base_url}/auth/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {"grant_type": "client_credentials"}

        try:
            response = requests.post(
                token_url,
                headers=headers,
                data=data,
                auth=HTTPBasicAuth(self.client_id, self.client_secret)
            )
            response.raise_for_status()
            token_data = response.json()
            self.access_token = token_data.get("access_token")
            self.token_type = token_data.get("token_type")
            self.expires_in = token_data.get("expires_in")
            
            # Extract scopes from token data
            scopes_str = token_data.get("scope", "")
            self.scopes = scopes_str.split() if scopes_str else []
            
            self.last_error = None
            return True
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text if http_err.response.text else str(http_err)}"
            print(f"HTTP error during authentication: {self.last_error}")
        except requests.ConnectionError as conn_err:
            self.last_error = f"Connection error: Unable to reach the API server. Please check the API URL."
            print(f"Connection error during authentication: {self.last_error}")
        except requests.Timeout as timeout_err:
            self.last_error = f"Timeout error: The API server took too long to respond."
            print(f"Timeout error during authentication: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error during authentication: {self.last_error}")
        return False

    def get_headers(self) -> dict:
        """
        Returns the headers required for authenticated API requests.
        """
        if not self.access_token or not self.token_type:
            raise ValueError("Authentication is required before making API requests.")
        return {"Authorization": f"{self.token_type} {self.access_token}"}

    def has_required_scopes(self, required_scopes: list) -> bool:
        """
        Validates if the authenticated client has all required scopes.
        
        Args:
            required_scopes: List of required scope strings (e.g., ["projects.read", "projects.write"])
        
        Returns:
            bool: True if all required scopes are present, False otherwise.
        """
        return all(scope in self.scopes for scope in required_scopes)

    def get_missing_scopes(self, required_scopes: list) -> list:
        """
        Returns a list of missing scopes.
        
        Args:
            required_scopes: List of required scope strings
        
        Returns:
            list: List of scopes that are missing from the authenticated token.
        """
        return [scope for scope in required_scopes if scope not in self.scopes]

 
    def get_projects(self):
        """
        Retrieves ALL projects using pagination.
        Automatically loops until all projects from the API are fetched.
        """
        projects_url = f"{self.base_url}/projects"
        headers = self.get_headers()
    
        limit = 50   # API returns max 50 per page
        offset = 0
        all_projects = []
    
        try:
            while True:
                params = {
                    "limit": limit,
                    "offset": offset
                }
    
                response = requests.get(projects_url, headers=headers, params=params)
                response.raise_for_status()
                res_json = response.json()
    
                # Extract this batch
                batch = res_json.get("data", [])
                total_count = res_json.get("totalCount", len(batch))
    
                all_projects.extend(batch)
    
                # Check if we've fetched everything
                if len(all_projects) >= total_count:
                    break
    
                # Increase offset for next batch
                offset += limit
    
            return {"data": all_projects, "totalCount": len(all_projects)}
    
        except requests.HTTPError as http_err:
            print(f"HTTP error while fetching projects: {http_err}")
        except Exception as err:
            print(f"Unexpected error while fetching projects: {err}")
    
        return None

    def get_project_schema(self, project_id):
        """
        Retrieves the schema for a specific project.
        """
        schema_url = f"{self.base_url}/projects/{project_id}/schema"
        headers = self.get_headers()

        try:
            response = requests.get(schema_url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            print(f"HTTP error while fetching schema: {http_err}")
        except Exception as err:
            print(f"Unexpected error while fetching schema: {err}")
        return None

    def get_project_by_id(self, project_id):
        """
        Retrieves the details of a specific project by its ID.
        """
        project_url = f"{self.base_url}/projects/{project_id}"
        headers = self.get_headers()

        try:
            response = requests.get(project_url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            print(f"HTTP error while fetching project by ID: {http_err}")
        except Exception as err:
            print(f"Unexpected error while fetching project by ID: {err}")
        return None


        
    def get_all_routing_rule_ids(self, limit=20):
        """
        Retrieves all routing rule IDs using the routingsList endpoint (/v2/routings).
        This method uses pagination to fetch all rules and returns a list of their IDs.
        """
        all_ids = []
        offset = 0

        while True:
            query = {
                "limit": str(limit),
                "offset": str(offset)
            }
            response = requests.get(
                f"{self.base_url}/routings",
                headers=self.get_headers(),
                params=query
            )
            if response.status_code != 200:
                print(f"Failed to retrieve routing rules. Status code: {response.status_code}")
                break

            data = response.json()
            rules = data.get("data", [])
            if not rules:
                break

            for rule in rules:
                rule_id = rule.get("id")
                if rule_id:
                    all_ids.append(rule_id)

            # If fewer than 'limit' rules were returned, we've reached the end.
            if len(rules) < limit:
                break

            offset += limit

        return all_ids

    def get_routing_by_id(self, routing_id):
        """
        Retrieves a single routing rule by its ID using the /v2/routings/{routingId} endpoint.
        Returns a dictionary with the routing rule details.
        """
        url = f"{self.base_url}/routings/{routing_id}"
        headers = self.get_headers()
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            print(f"HTTP error while fetching routing rule {routing_id}: {http_err}")
        except Exception as err:
            print(f"Unexpected error while fetching routing rule {routing_id}: {err}")
        return None

    def update_project(self, project_id, payload):
        """
        Updates a project configuration using PATCH /projects/{id}.
        Accepts a partial payload with any combination of: name, note, ocr,
        extractionModelId, completion, duplicates, retentionDays, isLive, members, schema.
        Returns the updated project on success, or None on failure.
        """
        url = f"{self.base_url}/projects/{project_id}"
        headers = self.get_headers()
        try:
            response = requests.patch(url, json=payload, headers=headers)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while updating project {project_id}: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while updating project {project_id}: {err}")
        return None

    # ------------------------------------------------------------------
    # Users (/users)
    # ------------------------------------------------------------------

    def list_users(self, search: str = None, active: bool = None, roles: list = None) -> list:
        """
        GET /users — paginated. Returns all users visible to the credentials,
        each with id, email, name, companiesAccess and isInternal.
        """
        url = f"{self.base_url}/users"
        headers = self.get_headers()
        limit = 50
        offset = 0
        results = []
        try:
            while True:
                params = {"limit": limit, "offset": offset}
                if search:
                    params["search"] = search
                if active is not None:
                    params["active"] = str(active).lower()
                if roles:
                    params["roles"] = roles
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                body = response.json()
                batch = body.get("data", []) if isinstance(body, dict) else []
                results.extend(batch)
                total = body.get("totalCount", len(results))
                if len(results) >= total or not batch:
                    break
                offset += limit
            self.last_error = None
            return results
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while listing users: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while listing users: {err}")
        return []

    def get_user(self, user_id: str) -> dict:
        """GET /users/{id} — a single user (id, email, name, companiesAccess)."""
        url = f"{self.base_url}/users/{user_id}"
        headers = self.get_headers()
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while fetching user {user_id}: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while fetching user {user_id}: {err}")
        return None

    def update_project_members(self, project_id: str, members: dict) -> dict:
        """
        Updates only the project member access via PATCH /projects/{id}.

        `members` is the discriminated union from the API:
          {"allow": "all"} — every company user has access
          {"allow": "members", "members": [<userId>, ...]} — explicit list
        """
        return self.update_project(project_id, {"members": members})

    def create_routing_rule(self, rule_payload):
        """
        Creates a new routing rule using the /routings endpoint.
        Expects a payload containing the necessary fields (name, fromProjectId, toProjectId, postRoutingAction, active, routingNode, createdBy, etc.).
        Returns the created rule details on success.
        """
        url = f"{self.base_url}/routings"
        headers = self.get_headers()
        try:
            response = requests.post(url, json=rule_payload, headers=headers)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while creating routing rule: {http_err}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while creating routing rule: {err}")
        return None

    def get_company(self) -> dict:
        """
        Returns the company associated with the current credentials.
        Calls GET /companies and returns the first (authenticated) company object,
        or None on failure.
        """
        headers = self.get_headers()
        try:
            response = requests.get(f"{self.base_url}/companies", headers=headers)
            response.raise_for_status()
            data = response.json()
            companies = data.get("data", []) if isinstance(data, dict) else []
            return companies[0] if companies else None
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while fetching company: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while fetching company: {err}")
        return None

    def get_document_by_id(self, document_id: str):
        """
        Retrieves a document by ID via GET /documents/{id}.
        Returns the document dict on success, or None on failure.
        """
        url = f"{self.base_url}/documents/{document_id}"
        try:
            response = requests.get(url, headers=self.get_headers())
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while fetching document {document_id}: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while fetching document {document_id}: {err}")
        return None

    def upload_file(self, file_bytes: bytes, content_type: str, filename: str = None):
        """
        Uploads a file via POST /files using raw binary body.
        Returns the response dict (contains 'id') on success, or None on failure.
        """
        url = f"{self.base_url}/files"
        headers = self.get_headers()
        headers["Content-Type"] = content_type
        if filename:
            # Normalize to NFC so composed characters (e.g. ü = ü) are used
            # instead of NFD decomposed forms that fall outside Latin-1.
            nfc_name = unicodedata.normalize("NFC", filename)
            try:
                nfc_name.encode("latin-1")
                headers["X-Hy-Filename"] = nfc_name
            except UnicodeEncodeError:
                headers["X-Hy-Filename"] = urllib.parse.quote(nfc_name)
        try:
            response = requests.post(url, data=file_bytes, headers=headers)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while uploading file: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while uploading file: {err}")
        return None

    def process_file_batch(self, file_ids: list, project_id: str):
        """
        Triggers batch processing via POST /cases/process-file-batch.
        Returns the response dict on success, or None on failure.
        """
        url = f"{self.base_url}/cases/process-file-batch"
        headers = self.get_headers()
        payload = {"fileIds": file_ids, "projectId": project_id}
        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response.json() if response.content else {"status": "accepted"}
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while processing file batch: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while processing file batch: {err}")
        return None

    # ------------------------------------------------------------------
    # Agent management (/agents, /agent-workflows)
    # ------------------------------------------------------------------

    def list_agents(self, editor: str = None) -> list:
        """
        GET /agents — paginated. Returns the full list of agents
        (summary projection: prompt/configuration empty, toolIds null).
        """
        url = f"{self.base_url}/agents"
        headers = self.get_headers()
        limit = 50
        offset = 0
        results = []
        try:
            while True:
                params = {"limit": limit, "offset": offset}
                if editor:
                    params["editor"] = editor
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                body = response.json()
                batch = body.get("data", []) if isinstance(body, dict) else []
                results.extend(batch)
                total = body.get("totalCount", len(results))
                if len(results) >= total or not batch:
                    break
                offset += limit
            self.last_error = None
            return results
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return []

    def get_agent(self, agent_id: str, with_versions: bool = False) -> dict:
        """GET /agents/{id} — full agent detail (prompt, configuration, toolIds populated)."""
        url = f"{self.base_url}/agents/{agent_id}"
        headers = self.get_headers()
        params = {}
        if with_versions:
            params["withVersions"] = "true"
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return None

    def create_agent(self, payload: dict) -> dict:
        """POST /agents — create a custom agent. Payload must not carry OOTB / source provenance fields."""
        url = f"{self.base_url}/agents"
        headers = self.get_headers()
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return None

    def list_agent_workflows(self, project_id: str = None, editor: str = None) -> list:
        """GET /agent-workflows — paginated."""
        url = f"{self.base_url}/agent-workflows"
        headers = self.get_headers()
        limit = 50
        offset = 0
        results = []
        try:
            while True:
                params = {"limit": limit, "offset": offset}
                if project_id:
                    params["projectId"] = project_id
                if editor:
                    params["editor"] = editor
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                body = response.json()
                batch = body.get("data", []) if isinstance(body, dict) else []
                results.extend(batch)
                total = body.get("totalCount", len(results))
                if len(results) >= total or not batch:
                    break
                offset += limit
            self.last_error = None
            return results
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return []

    def get_agent_workflow(self, workflow_id: str) -> dict:
        """GET /agent-workflows/{id} — full workflow detail with workflowConfiguration."""
        url = f"{self.base_url}/agent-workflows/{workflow_id}"
        headers = self.get_headers()
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return None

    def create_agent_workflow(self, payload: dict) -> dict:
        """POST /agent-workflows — create a custom workflow."""
        url = f"{self.base_url}/agent-workflows"
        headers = self.get_headers()
        try:
            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
        except Exception as err:
            self.last_error = str(err)
        return None

    # ------------------------------------------------------------------
    # Composite enrichment workflows (/enrichment-workflows)
    # ------------------------------------------------------------------

    def list_enrichment_workflows(self) -> list:
        """
        GET /enrichment-workflows — paginated (the API caps `limit` at 50).
        Each item already carries the full YAML `definition`.
        """
        url = f"{self.base_url}/enrichment-workflows"
        headers = self.get_headers()
        limit = 50
        offset = 0
        results = []
        try:
            while True:
                params = {"limit": limit, "offset": offset}
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                body = response.json()
                batch = body.get("data", []) if isinstance(body, dict) else []
                results.extend(batch)
                total = body.get("totalCount", len(results))
                if len(results) >= total or not batch:
                    break
                offset += limit
            self.last_error = None
            return results
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while listing enrichment workflows: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while listing enrichment workflows: {err}")
        return []

    def get_enrichment_workflow(self, workflow_id: str) -> dict:
        """GET /enrichment-workflows/{workflowId}."""
        url = f"{self.base_url}/enrichment-workflows/{workflow_id}"
        try:
            response = requests.get(url, headers=self.get_headers())
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while fetching enrichment workflow {workflow_id}: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while fetching enrichment workflow {workflow_id}: {err}")
        return None

    def create_enrichment_workflow(self, payload: dict) -> dict:
        """
        POST /enrichment-workflows — payload accepts name (required),
        definition (required, YAML string), description and projectIds.
        Server-managed fields (id, companyId, version, timestamps) must not be sent.
        """
        url = f"{self.base_url}/enrichment-workflows"
        try:
            response = requests.post(url, headers=self.get_headers(), json=payload)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while creating enrichment workflow: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while creating enrichment workflow: {err}")
        return None

    def update_enrichment_workflow(self, workflow_id: str, payload: dict) -> dict:
        """
        PUT /enrichment-workflows/{workflowId} — full replace, so `name` and
        `definition` always have to be present in the payload.
        """
        url = f"{self.base_url}/enrichment-workflows/{workflow_id}"
        try:
            response = requests.put(url, headers=self.get_headers(), json=payload)
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as http_err:
            self.last_error = f"HTTP {http_err.response.status_code}: {http_err.response.text}"
            print(f"HTTP error while updating enrichment workflow {workflow_id}: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"Unexpected error while updating enrichment workflow {workflow_id}: {err}")
        return None

    def get_company_info(self, company_id: str = None):
        """
        Retrieves company information using the authenticated client's credentials.
        If company_id is provided, fetches that specific company.
        If company_id is None, fetches the list of companies (usually returns the authenticated company).
        Returns a dictionary with company details including name, id, active status, and createdAt.
        """
        headers = self.get_headers()
        try:
            if company_id:
                url = f"{self.base_url}/companies/{company_id}"
                response = requests.get(url, headers=headers)
            else:
                # Fetch the list of companies - typically returns the authenticated company
                url = f"{self.base_url}/companies"
                response = requests.get(url, headers=headers)
            
            response.raise_for_status()
            data = response.json()
            
            # If fetching list, return the first company (authenticated one)
            if not company_id and isinstance(data, dict) and "data" in data:
                companies = data.get("data", [])
                if companies:
                    return companies[0]
            
            return data
        except requests.HTTPError as http_err:
            print(f"HTTP error while fetching company info: {http_err}")
        except Exception as err:
            print(f"Unexpected error while fetching company info: {err}")
        return None
