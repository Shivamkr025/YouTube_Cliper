"""
Module 3: YouTube Data API v3 Auto-Uploader
Handles authentication via OAuth 2.0 and uploads / schedules Shorts with SEO metadata.
"""

import os
import sys
import logging
from typing import Dict, Any, List, Optional
import google.auth
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

class YouTubeUploader:
    def __init__(self, client_secrets_file: str = "client_secret.json", token_file: str = "token.json"):
        self.client_secrets_file = os.path.abspath(client_secrets_file)
        if not os.path.exists(self.client_secrets_file):
            alt_path = os.path.join(os.path.dirname(os.path.dirname(self.client_secrets_file)), "client_secret.json")
            if os.path.exists(alt_path):
                self.client_secrets_file = alt_path

        self.token_file = os.path.abspath(token_file)
        if not os.path.exists(self.token_file):
            alt_token = os.path.join(os.path.dirname(os.path.dirname(self.token_file)), "token.json")
            if os.path.exists(alt_token):
                self.token_file = alt_token
        self.service = None

    def authenticate(self):
        """Authenticates with YouTube API via OAuth 2.0."""
        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
            
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing expired YouTube OAuth token...")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.client_secrets_file):
                    raise FileNotFoundError(
                        f"Missing '{self.client_secrets_file}'. "
                        "Download OAuth Client Secret JSON from Google Cloud Console to enable auto-upload."
                    )
                logger.info("Initiating browser OAuth 2.0 flow for YouTube channel authorization...")
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
                creds = flow.run_local_server(port=0)

            with open(self.token_file, "w") as token:
                token.write(creds.to_json())

        self.service = build("youtube", "v3", credentials=creds)
        logger.info("Successfully authenticated with YouTube Data API v3.")

    def upload_short(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: Optional[List[str]] = None,
        category_id: str = "24",  # Entertainment
        privacy_status: str = "private",  # 'private', 'unlisted', or 'public'
        publish_at: Optional[str] = None,  # ISO 8601 string for scheduling (e.g. 2026-11-21T18:00:00Z)
        thumbnail_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Uploads a vertical Short to the authorized YouTube channel.
        """
        if not self.service:
            self.authenticate()

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Video file not found: {video_path}")

        # Ensure #Shorts is present in title or description
        if "#Shorts" not in title and "#shorts" not in title:
            title = f"{title[:80]} #Shorts"

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags or ["#Shorts", "#Viral", "#AI"],
                "categoryId": category_id
            },
            "status": {
                "privacyStatus": "private" if publish_at else privacy_status,
                "selfDeclaredMadeForKids": False
            }
        }

        if publish_at:
            body["status"]["publishAt"] = publish_at
            body["status"]["privacyStatus"] = "private"  # Scheduled videos must be private initially

        logger.info(f"Uploading '{title}' ({privacy_status})...")
        media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
        request = self.service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info(f"Upload progress: {int(status.progress() * 100)}%")

        video_id = response.get("id")
        video_url = f"https://www.youtube.com/shorts/{video_id}"

        # Auto-set custom high-CTR thumbnail if provided and exists
        if thumbnail_path and os.path.exists(thumbnail_path):
            try:
                logger.info(f"Setting custom high-CTR thumbnail for video {video_id}...")
                thumb_media = MediaFileUpload(thumbnail_path, mimetype="image/jpeg")
                self.service.thumbnails().set(
                    videoId=video_id,
                    media_body=thumb_media
                ).execute()
                logger.info("✅ Custom high-CTR thumbnail attached successfully to YouTube Short!")
            except Exception as e:
                logger.warning(f"Thumbnail attachment notice: {e} (Note: Setting custom thumbnails requires verified YouTube phone number on your channel).")

        logger.info(f"🎉 Short successfully uploaded! Link: {video_url}")
        return {
            "video_id": video_id,
            "url": video_url,
            "title": title,
            "status": privacy_status
        }

if __name__ == "__main__":
    uploader = YouTubeUploader()
    print("YouTubeUploader loaded.")
