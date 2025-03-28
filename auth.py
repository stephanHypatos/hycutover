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

    def get_projects(self):
        """
        Retrieves the list of projects.
        """
        projects_url = f"{self.base_url}/projects"
        headers = self.get_headers()
        query = {
            "limit": "200"
            }
        
        try:
            response = requests.get(projects_url, headers=headers, params=query)
            response.raise_for_status()
            
            return response.json()
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