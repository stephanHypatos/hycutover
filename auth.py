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
            
            return True
        except requests.HTTPError as http_err:
            print(f"HTTP error during authentication: {http_err}")
        except Exception as err:
            print(f"Unexpected error during authentication: {err}")
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
            return response.json()
        except requests.HTTPError as http_err:
            print(f"HTTP error while updating project {project_id}: {http_err}")
        except Exception as err:
            print(f"Unexpected error while updating project {project_id}: {err}")
        return None

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
            return response.json()
        except requests.HTTPError as http_err:
            print(f"HTTP error while creating routing rule: {http_err}")
        except Exception as err:
            print(f"Unexpected error while creating routing rule: {err}")
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
