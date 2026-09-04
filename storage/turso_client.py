"""
Turso LibSQL HTTP Pipeline Client (Pure Python, Zero C-Dependencies)
Works in any serverless environment (Vercel, AWS Lambda, Cloudflare) without binary wheels.
"""

import json
import requests
from typing import Optional, Dict, Any, List, Union


class TursoClient:
    def __init__(self, database_url: str, auth_token: str):
        # Normalize URL: libsql://xxx.turso.io -> https://xxx.turso.io
        clean_url = database_url.strip()
        if clean_url.startswith("libsql://"):
            clean_url = "https://" + clean_url[len("libsql://"):]
        elif clean_url.startswith("http://"):
            clean_url = "https://" + clean_url[len("http://"):]
        elif not clean_url.startswith("https://"):
            clean_url = f"https://{clean_url}"

        self.base_url = clean_url.rstrip("/")
        self.pipeline_url = f"{self.base_url}/v2/pipeline"
        self.auth_token = auth_token.strip()
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json"
        })

    def _format_arg(self, arg: Any) -> Dict[str, Any]:
        """Convert Python value to Turso value type."""
        if arg is None:
            return {"type": "null"}
        elif isinstance(arg, bool):
            return {"type": "integer", "value": "1" if arg else "0"}
        elif isinstance(arg, int):
            return {"type": "integer", "value": str(arg)}
        elif isinstance(arg, float):
            return {"type": "float", "value": arg}
        elif isinstance(arg, (dict, list)):
            return {"type": "text", "value": json.dumps(arg)}
        else:
            return {"type": "text", "value": str(arg)}

    def execute(self, sql: str, params: Union[tuple, list] = ()) -> List[Dict[str, Any]]:
        """Execute a single SQL statement and return rows as list of dicts."""
        formatted_args = [self._format_arg(p) for p in params]
        payload = {
            "requests": [
                {
                    "type": "execute",
                    "stmt": {
                        "sql": sql,
                        "args": formatted_args
                    }
                },
                {"type": "close"}
            ]
        }

        try:
            r = self.session.post(self.pipeline_url, json=payload, timeout=15)
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            if not results:
                return []
            exec_res = results[0]
            if exec_res.get("type") == "error":
                raise RuntimeError(f"Turso Error: {exec_res.get('error', {}).get('message')}")

            response_data = exec_res.get("response", {}).get("result", {})
            cols = [col.get("name") for col in response_data.get("cols", [])]
            rows = []
            for row in response_data.get("rows", []):
                record = {}
                for idx, cell in enumerate(row):
                    val = cell.get("value")
                    # Handle cell types
                    if cell.get("type") == "null":
                        val = None
                    elif cell.get("type") == "integer":
                        try:
                            val = int(val)
                        except (ValueError, TypeError):
                            pass
                    elif cell.get("type") == "float":
                        try:
                            val = float(val)
                        except (ValueError, TypeError):
                            pass
                    record[cols[idx]] = val
                rows.append(record)
            return rows
        except Exception as e:
            raise RuntimeError(f"Failed to execute Turso query: {e}")

    def execute_batch(self, statements: List[tuple]) -> bool:
        """Execute multiple statements in a single atomic pipeline request."""
        requests_list = []
        for sql, params in statements:
            requests_list.append({
                "type": "execute",
                "stmt": {
                    "sql": sql,
                    "args": [self._format_arg(p) for p in params]
                }
            })
        requests_list.append({"type": "close"})

        payload = {"requests": requests_list}
        r = self.session.post(self.pipeline_url, json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        for res in data.get("results", []):
            if res.get("type") == "error":
                raise RuntimeError(f"Turso Batch Error: {res.get('error', {}).get('message')}")
        return True
