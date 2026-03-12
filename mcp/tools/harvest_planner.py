"""HTTP client for the Harvest Planner REST API with JWT auth."""

import httpx
from datetime import datetime, timezone
from typing import Optional

from .config import CONFIG


class HarvestPlannerAPI:
    """HTTP client for the Harvest Planner REST API with JWT auth."""

    def __init__(self, base_url: str = CONFIG["hp_base_url"],
                 username: str = CONFIG["hp_username"],
                 password: str = CONFIG["hp_password"]):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.token_expires_at: Optional[datetime] = None
        self.client = httpx.Client(timeout=30)

    def _is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.password)

    def _ensure_auth(self) -> Optional[str]:
        if not self._is_configured():
            return "Harvest Planner API not configured. Set HP_BASE_URL, HP_USERNAME, HP_PASSWORD in .env"
        if self.access_token and self.token_expires_at:
            if datetime.now(timezone.utc) < self.token_expires_at:
                return None
            if self.refresh_token:
                err = self._refresh()
                if err is None:
                    return None
        return self._login()

    def _login(self) -> Optional[str]:
        try:
            resp = self.client.post(
                f"{self.base_url}/api/v1/auth/login",
                json={"username": self.username, "password": self.password}
            )
            if resp.status_code == 401:
                return "Harvest Planner login failed: bad credentials"
            if resp.status_code == 423:
                return "Harvest Planner account is locked"
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                return f"Harvest Planner login returned non-JSON ({resp.status_code}): {resp.text[:200]}"
            resp.raise_for_status()
            data = resp.json()
            self.access_token = data["accessToken"]
            self.refresh_token = data["refreshToken"]
            self.token_expires_at = datetime.fromisoformat(
                data["accessTokenExpiresAt"].replace("Z", "+00:00")
            )
            return None
        except Exception as e:
            return f"Harvest Planner login error: {e}"

    def _refresh(self) -> Optional[str]:
        try:
            resp = self.client.post(
                f"{self.base_url}/api/v1/auth/refresh",
                json={"refreshToken": self.refresh_token}
            )
            if resp.status_code != 200:
                return f"Token refresh failed (HTTP {resp.status_code})"
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                return f"Token refresh returned non-JSON: {resp.text[:200]}"
            data = resp.json()
            self.access_token = data["accessToken"]
            self.refresh_token = data["refreshToken"]
            self.token_expires_at = datetime.fromisoformat(
                data["accessTokenExpiresAt"].replace("Z", "+00:00")
            )
            return None
        except Exception as e:
            return f"Token refresh error: {e}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, params: dict = None,
                 json_body: dict = None, auth_required: bool = True) -> dict:
        if auth_required:
            err = self._ensure_auth()
            if err:
                return {"success": False, "error": err}

        url = f"{self.base_url}{path}"
        headers = self._headers() if auth_required and self.access_token else {}

        try:
            resp = self.client.request(method, url, params=params,
                                       json=json_body, headers=headers)
            if resp.status_code == 401 and auth_required:
                err = self._login()
                if err:
                    return {"success": False, "error": err}
                headers = self._headers()
                resp = self.client.request(method, url, params=params,
                                           json=json_body, headers=headers)

            if resp.status_code == 204:
                return {"success": True, "message": "Operation completed successfully"}

            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                snippet = resp.text[:300].strip()
                return {"success": False,
                        "error": f"HTTP {resp.status_code} - expected JSON but got {content_type or 'unknown content type'}",
                        "detail": snippet}

            if resp.status_code >= 400:
                try:
                    body = resp.json()
                except Exception:
                    body = resp.text
                return {"success": False, "error": f"HTTP {resp.status_code}", "detail": body}

            return {"success": True, "data": resp.json()}
        except httpx.ConnectError as e:
            return {"success": False, "error": f"Connection failed to {self.base_url}: {e}"}
        except httpx.TimeoutException:
            return {"success": False, "error": f"Request timed out ({self.client.timeout}s) to {url}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def create_harvest_plan(self, plan_data: dict) -> dict:
        return self._request("POST", "/api/v1/harvestplans", json_body=plan_data)

    def update_harvest_plan(self, plan_id: str, plan_data: dict) -> dict:
        return self._request("PUT", f"/api/v1/harvestplans/{plan_id}", json_body=plan_data)

    def delete_harvest_plan(self, plan_id: str) -> dict:
        return self._request("DELETE", f"/api/v1/harvestplans/{plan_id}")

    def create_contractor(self, contractor_data: dict) -> dict:
        return self._request("POST", "/api/v1/harvestcontractors",
                             json_body=contractor_data, auth_required=False)

    def create_placeholder_grower(self, grower_data: dict) -> dict:
        return self._request("POST", "/api/v1/placeholdergrower", json_body=grower_data)

    def create_production_run(self, run_data: dict) -> dict:
        return self._request("POST", "/api/v1/productionruns", json_body=run_data)


TOOL_DEFINITIONS = [
    {
        "name": "hp_create_harvest_plan",
        "description": "Create a new harvest plan via the Harvest Planner API. Link a grower block (or placeholder grower) with contractors, rates, pool, and scheduling. Fields: grower_block_source_database, grower_block_id (GABLOCKIDX), placeholder_grower_id (GUID, use instead of block if grower not in system), field_representative_id (user ID), planned_bins, contractor_id, harvesting_rate, hauler_id, hauling_rate, forklift_contractor_id, forklift_rate, pool_id (POOLIDX), notes_general, deliver_to, packed_by, date (YYYY-MM-DD), bins.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_data": {"type": "object", "description": "Harvest plan fields to set"}
            },
            "required": ["plan_data"]
        }
    },
    {
        "name": "hp_update_harvest_plan",
        "description": "Update an existing harvest plan via the Harvest Planner API. Pass only the fields to change.",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "The harvest plan GUID to update"},
                "plan_data": {"type": "object", "description": "Fields to update"}
            },
            "required": ["plan_id", "plan_data"]
        }
    },
    {
        "name": "hp_delete_harvest_plan",
        "description": "Delete a harvest plan via the Harvest Planner API by its ID (GUID).",
        "parameters": {
            "type": "object",
            "properties": {
                "plan_id": {"type": "string", "description": "The harvest plan GUID to delete"}
            },
            "required": ["plan_id"]
        }
    },
    {
        "name": "hp_create_contractor",
        "description": "Create a new harvest contractor via the Harvest Planner API. Fields: name (required), primary_contact_name, primary_contact_phone, office_phone, mailing_address, provides_trucking (bool), provides_picking (bool), provides_forklift (bool).",
        "parameters": {
            "type": "object",
            "properties": {
                "contractor_data": {"type": "object", "description": "Contractor fields to set"}
            },
            "required": ["contractor_data"]
        }
    },
    {
        "name": "hp_create_placeholder_grower",
        "description": "Create a placeholder grower via the Harvest Planner API for use in harvest plans when the real block doesn't exist yet. Fields: grower_name (required), commodity_name (required), is_active (default true), notes.",
        "parameters": {
            "type": "object",
            "properties": {
                "grower_data": {"type": "object", "description": "Placeholder grower fields"}
            },
            "required": ["grower_data"]
        }
    },
    {
        "name": "hp_create_production_run",
        "description": "Create a production run via the Harvest Planner API to track processing/packing of harvested fruit. Fields: source_database (required), gablockidx (required, > 0), bins, run_date, pick_date, location, pool, notes, row_order, run_status, batch_id, time_started, time_completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "run_data": {"type": "object", "description": "Production run fields"}
            },
            "required": ["run_data"]
        }
    },
]


def register_handlers(hp: HarvestPlannerAPI) -> dict:
    return {
        "hp_create_harvest_plan": lambda p: hp.create_harvest_plan(p.get("plan_data", {})),
        "hp_update_harvest_plan": lambda p: hp.update_harvest_plan(p.get("plan_id", ""), p.get("plan_data", {})),
        "hp_delete_harvest_plan": lambda p: hp.delete_harvest_plan(p.get("plan_id", "")),
        "hp_create_contractor": lambda p: hp.create_contractor(p.get("contractor_data", {})),
        "hp_create_placeholder_grower": lambda p: hp.create_placeholder_grower(p.get("grower_data", {})),
        "hp_create_production_run": lambda p: hp.create_production_run(p.get("run_data", {})),
    }
