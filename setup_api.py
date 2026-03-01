import requests
from config import BASE_URL_SETUP


class SetupAPI:
    """
    Client for the Hypatos Setup API (https://setup.cloud.hypatos.ai).

    Authentication uses a Bearer access_token obtained from an active
    browser session on setup.cloud.hypatos.ai (the 'access_token' cookie).

    Endpoints covered:
      GET  /companies
      GET  /v1/prompting-settings
      PUT  /v1/prompting-settings
      POST /v1/prompting-settings/copy
      GET  /v1/prompting-settings/agents
      POST /v1/prompting-settings/agents
      GET  /v1/composite-enrichment-workflows
      POST /v1/composite-enrichment-workflows
      PUT  /v1/composite-enrichment-workflows/{id}
    """

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.base_url = BASE_URL_SETUP.rstrip("/")
        self.last_error = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> dict:
        return {
            "Cookie": f"access_token={self.access_token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None):
        """Execute a GET request and return parsed JSON, or None on error."""
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                headers=self._headers(),
                params=params,
            )
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as err:
            self.last_error = f"HTTP {err.response.status_code}: {err.response.text}"
            print(f"GET {path} failed: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"GET {path} error: {err}")
        return None

    def _post(self, path: str, payload: dict):
        """Execute a POST request and return parsed JSON, or None on error."""
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as err:
            self.last_error = f"HTTP {err.response.status_code}: {err.response.text}"
            print(f"POST {path} failed: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"POST {path} error: {err}")
        return None

    def _put(self, path: str, payload: dict):
        """Execute a PUT request and return parsed JSON, or None on error."""
        try:
            response = requests.put(
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            self.last_error = None
            return response.json()
        except requests.HTTPError as err:
            self.last_error = f"HTTP {err.response.status_code}: {err.response.text}"
            print(f"PUT {path} failed: {self.last_error}")
        except Exception as err:
            self.last_error = str(err)
            print(f"PUT {path} error: {err}")
        return None

    # ------------------------------------------------------------------
    # Companies
    # ------------------------------------------------------------------

    def get_company(self) -> dict:
        """
        GET /companies
        Returns the first company accessible with the current token, or None.
        """
        data = self._get("/companies")
        if data is None:
            return None
        # Handle both list and {data: [...]} response shapes
        if isinstance(data, list):
            return data[0] if data else None
        companies = data.get("data", [])
        return companies[0] if companies else None

    # ------------------------------------------------------------------
    # Prompting settings
    # ------------------------------------------------------------------

    def get_prompting_settings(self, company_id: str) -> dict:
        """GET /v1/prompting-settings?companyId={company_id}"""
        return self._get("/v1/prompting-settings", params={"companyId": company_id})

    def update_prompting_settings(self, company_id: str, payload: dict) -> dict:
        """PUT /v1/prompting-settings?companyId={company_id}"""
        return self._put(
            "/v1/prompting-settings",
            {**payload, "companyId": company_id},
        )

    def copy_prompting_settings(self, source_company_id: str, target_company_id: str) -> dict:
        """
        POST /v1/prompting-settings/copy
        Copies prompting settings from source to target company.
        """
        return self._post(
            "/v1/prompting-settings/copy",
            {
                "sourceCompanyId": source_company_id,
                "targetCompanyId": target_company_id,
            },
        )

    # ------------------------------------------------------------------
    # Agents
    # ------------------------------------------------------------------

    def get_agents(self, company_id: str) -> list:
        """GET /v1/prompting-settings/agents?companyId={company_id}"""
        data = self._get("/v1/prompting-settings/agents", params={"companyId": company_id})
        if data is None:
            return []
        return data if isinstance(data, list) else data.get("data", [])

    def copy_agent(self, payload: dict) -> dict:
        """
        POST /v1/prompting-settings/agents
        Expected payload keys (adjust to actual API contract):
          sourceCompanyId, targetCompanyId, agentId  (or full agent body)
        """
        return self._post("/v1/prompting-settings/agents", payload)

    # ------------------------------------------------------------------
    # Composite enrichment workflows
    # ------------------------------------------------------------------

    def get_composite_enrichment_workflows(self, company_id: str) -> list:
        """GET /v1/composite-enrichment-workflows?companyId={company_id}"""
        data = self._get(
            "/v1/composite-enrichment-workflows",
            params={"companyId": company_id},
        )
        if data is None:
            return []
        return data if isinstance(data, list) else data.get("data", [])

    def create_composite_enrichment_workflow(self, payload: dict) -> dict:
        """POST /v1/composite-enrichment-workflows"""
        return self._post("/v1/composite-enrichment-workflows", payload)

    def update_composite_enrichment_workflow(self, workflow_id: str, payload: dict) -> dict:
        """PUT /v1/composite-enrichment-workflows/{workflow_id}"""
        return self._put(f"/v1/composite-enrichment-workflows/{workflow_id}", payload)
