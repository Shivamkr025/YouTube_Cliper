"""
Module 4: Facebook Page Reels Auto-Uploader
Uses Meta Graph API to upload vertical 9:16 video reels directly to a connected Facebook Page.
"""

import os
import requests
import logging
from typing import Dict, Any, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("FacebookUploader")

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

class FacebookReelsUploader:
    def __init__(self, page_id: Optional[str] = None, access_token: Optional[str] = None):
        self.page_id = page_id or os.getenv("FB_PAGE_ID", "").strip()
        self.access_token = access_token or os.getenv("FB_PAGE_ACCESS_TOKEN", "").strip()

    def is_configured(self) -> bool:
        return bool(self.page_id and self.access_token)

    def test_connection(self) -> Dict[str, Any]:
        """Tests Facebook Page token validity and returns page name."""
        if not self.is_configured():
            return {"connected": False, "error": "FB_PAGE_ID or FB_PAGE_ACCESS_TOKEN not set"}
        
        url = f"{GRAPH_API_BASE}/{self.page_id}"
        params = {"access_token": self.access_token, "fields": "name,id,picture"}
        try:
            res = requests.get(url, params=params, timeout=10)
            data = res.json()
            if "error" in data:
                return {"connected": False, "error": data["error"].get("message", "Invalid Token")}
            return {
                "connected": True,
                "page_name": data.get("name"),
                "page_id": data.get("id"),
                "picture": data.get("picture", {}).get("data", {}).get("url")
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}

    def upload_reel(
        self,
        video_path: str,
        title: str,
        description: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads a vertical 9:16 Short as a Facebook Reel in a 3-step session:
        1. Initialize Upload Session
        2. Upload Video Binary
        3. Finish & Publish Reel
        """
        if not self.is_configured():
            raise ValueError("Facebook Page ID or Access Token is missing.")

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found at: {video_path}")

        file_size = os.path.getsize(video_path)
        logger.info(f"Initializing Facebook Reel upload for: {title} ({file_size / (1024*1024):.2f} MB)...")

        # Step 1: Initialize Session
        init_url = f"{GRAPH_API_BASE}/{self.page_id}/video_reels"
        init_payload = {
            "upload_phase": "start",
            "access_token": self.access_token
        }
        res_init = requests.post(init_url, data=init_payload, timeout=15)
        init_data = res_init.json()
        if "error" in init_data:
            raise RuntimeError(f"FB Reel Init Failed: {init_data['error'].get('message')}")

        video_id = init_data.get("video_id")
        upload_url = init_data.get("upload_url")
        logger.info(f"Upload session initialized with Video ID: {video_id}")

        # Step 2: Transfer Video Bytes
        headers = {
            "Authorization": f"OAuth {self.access_token}",
            "offset": "0",
            "file_size": str(file_size)
        }
        with open(video_path, "rb") as video_file:
            res_upload = requests.post(upload_url, headers=headers, data=video_file, timeout=120)

        upload_data = res_upload.json()
        if not upload_data.get("success", False):
            raise RuntimeError(f"FB Video Chunk Upload Failed: {upload_data}")

        # Step 3: Publish Reel
        publish_payload = {
            "upload_phase": "finish",
            "access_token": self.access_token,
            "video_state": "PUBLISHED",
            "description": f"{title}\n\n{description or ''} #Reels #Shorts #Viral"
        }
        res_publish = requests.post(init_url, data=publish_payload, timeout=20)
        publish_data = res_publish.json()
        if not publish_data.get("success", False):
            raise RuntimeError(f"FB Reel Publish Failed: {publish_data}")

        reel_url = f"https://www.facebook.com/watch/?v={video_id}"
        logger.info(f"🎉 Facebook Reel published successfully! URL: {reel_url}")
        return {
            "success": True,
            "video_id": video_id,
            "url": reel_url,
            "title": title
        }

if __name__ == "__main__":
    uploader = FacebookReelsUploader()
    print("Facebook status:", uploader.test_connection())
