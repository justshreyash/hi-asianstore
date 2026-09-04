"""
Byse API Provider
Documentation: https://byse.sx/api-docs
"""

import time
import requests
from typing import Optional, Dict, Any

BYSE_API_KEY = "48397uaa9vk8w0su5yrjw"
BASE_URL = "https://api.byse.sx"


class ByseProvider:
    def __init__(self, api_key: str = BYSE_API_KEY):
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def get_account_info(self) -> Dict[str, Any]:
        """Fetch Byse account details."""
        url = f"{BASE_URL}/account/info"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        return r.json()

    def list_folders(self) -> list[Dict[str, Any]]:
        """List all folders."""
        url = f"{BASE_URL}/folder/list"
        r = self.session.get(url, params={"key": self.api_key}, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("result", {}).get("folders", [])

    def create_folder(self, name: str, parent_id: int = 0) -> str:
        """Create a new folder and return its fld_id."""
        url = f"{BASE_URL}/folder/create"
        r = self.session.get(url, params={"key": self.api_key, "name": name, "parent_id": parent_id}, timeout=15)
        r.raise_for_status()
        data = r.json()
        res = data.get("result", {})
        fld_id = res.get("fld_id")
        if not fld_id:
            raise ValueError(f"Byse: Failed to create folder '{name}'. Response: {data}")
        return str(fld_id)

    def get_or_create_folder(self, folder_name: str = "hindi-asian") -> str:
        """Find folder by name or create it if not found."""
        folders = self.list_folders()
        for f in folders:
            if f.get("name", "").lower() == folder_name.lower():
                return str(f.get("fld_id"))
        return self.create_folder(folder_name)

    def upload_url(self, video_url: str, folder_id: Optional[str] = None, max_retries: int = 3) -> Dict[str, Any]:
        """
        Submit a direct video URL for remote upload.
        Performs exponential backoff on 429/503.
        """
        if not video_url:
            raise ValueError("Byse: video_url cannot be empty")

        url = f"{BASE_URL}/remote/add"
        last_err = None

        for attempt in range(1, max_retries + 1):
            try:
                r = self.session.get(url, params={"key": self.api_key, "url": video_url}, timeout=25)

                if r.status_code == 429 or r.status_code == 503:
                    wait_sec = attempt * 3
                    time.sleep(wait_sec)
                    continue

                r.raise_for_status()
                data = r.json()

                res_info = data.get("result", {})
                filecode = res_info.get("filecode")

                if not filecode:
                    raise ValueError(f"Byse: Remote upload failed. Response: {data}")

                # Assign to folder if specified
                if folder_id:
                    try:
                        self.set_folder(filecode, folder_id)
                    except Exception:
                        pass

                return {
                    "provider": "byse",
                    "filecode": filecode,
                    "embed_url": f"https://byse.sx/e/{filecode}",
                    "download_url": f"https://byse.sx/d/{filecode}",
                    "raw_response": data
                }
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(2 * attempt)

        raise last_err or RuntimeError(f"Byse upload failed after {max_retries} attempts.")

    def set_folder(self, filecode: str, folder_id: str) -> bool:
        """Assign/move a file into a folder."""
        # Try /file/set_folder first, fallback to /file/clone if needed
        for endpoint in ["/file/set_folder", "/file/clone"]:
            try:
                url = f"{BASE_URL}{endpoint}"
                r = self.session.get(url, params={"key": self.api_key, "file_code": filecode, "fld_id": folder_id}, timeout=15)
                if r.status_code == 200 and r.json().get("status") == 200:
                    return True
            except Exception:
                continue
        return False
