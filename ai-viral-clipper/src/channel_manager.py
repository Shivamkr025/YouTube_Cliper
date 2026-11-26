"""
Multi-Channel YouTube Manager
Supports connecting, storing, and switching between up to 5 YouTube channels simultaneously.
"""

import os
import json
import shutil
import logging
from typing import Dict, Any, List, Optional
from src.uploader import YouTubeUploader

logger = logging.getLogger(__name__)


class ChannelManager:
    MAX_CHANNELS = 5

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        self.channels_dir = os.path.join(self.base_dir, "channels")
        self.meta_file = os.path.join(self.channels_dir, "channels_meta.json")
        os.makedirs(self.channels_dir, exist_ok=True)
        self._migrate_legacy_token()

    def _load_meta(self) -> Dict[str, Any]:
        if os.path.exists(self.meta_file):
            try:
                with open(self.meta_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read channels_meta.json: {e}")
        return {"default_channel_id": None, "channels": []}

    def _save_meta(self, data: Dict[str, Any]):
        os.makedirs(self.channels_dir, exist_ok=True)
        with open(self.meta_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    def _migrate_legacy_token(self):
        """Migrates existing single token.json into ch_1 so user doesn't lose existing connection."""
        legacy_token = os.path.join(self.base_dir, "token.json")
        meta = self._load_meta()
        if os.path.exists(legacy_token) and len(meta.get("channels", [])) == 0:
            ch_id = "ch_1"
            ch_dir = os.path.join(self.channels_dir, ch_id)
            os.makedirs(ch_dir, exist_ok=True)
            new_token = os.path.join(ch_dir, "token.json")
            if not os.path.exists(new_token):
                shutil.copy2(legacy_token, new_token)

            info = {"yt_channel_id": "", "name": "Channel 1 (Primary)", "thumbnail": "", "subscriber_count": "-"}
            try:
                uploader = YouTubeUploader(
                    client_secrets_file=os.path.join(self.base_dir, "client_secret.json"),
                    token_file=new_token
                )
                uploader.authenticate()
                info = uploader.get_channel_info()
            except Exception as e:
                logger.warning(f"Legacy token channel info fetch notice: {e}")

            meta["channels"].append({
                "id": ch_id,
                "slot": 1,
                "name": info.get("name", "Channel 1"),
                "yt_channel_id": info.get("yt_channel_id", ""),
                "thumbnail": info.get("thumbnail", ""),
                "subscriber_count": info.get("subscriber_count", "-"),
                "token_file": new_token
            })
            meta["default_channel_id"] = ch_id
            self._save_meta(meta)
            logger.info("Migrated legacy token.json to multi-channel slot ch_1.")

    def list_channels(self) -> Dict[str, Any]:
        meta = self._load_meta()
        valid_channels = []
        for ch in meta.get("channels", []):
            if os.path.exists(ch.get("token_file", "")):
                valid_channels.append({
                    "id": ch["id"],
                    "slot": ch.get("slot", 1),
                    "name": ch.get("name", f"Channel {ch.get('slot', '')}"),
                    "yt_channel_id": ch.get("yt_channel_id", ""),
                    "thumbnail": ch.get("thumbnail", ""),
                    "subscriber_count": ch.get("subscriber_count", "-"),
                    "is_default": ch["id"] == meta.get("default_channel_id")
                })
        return {
            "channels": valid_channels,
            "default_channel_id": meta.get("default_channel_id"),
            "max_channels": self.MAX_CHANNELS
        }

    def get_next_available_slot(self) -> Optional[str]:
        meta = self._load_meta()
        existing_ids = {c["id"] for c in meta.get("channels", []) if os.path.exists(c.get("token_file", ""))}
        for i in range(1, self.MAX_CHANNELS + 1):
            cid = f"ch_{i}"
            if cid not in existing_ids:
                return cid
        return None

    def get_token_path(self, channel_id: Optional[str] = None) -> str:
        meta = self._load_meta()
        target_id = channel_id or meta.get("default_channel_id")
        if target_id:
            for ch in meta.get("channels", []):
                if ch["id"] == target_id and os.path.exists(ch.get("token_file", "")):
                    return ch["token_file"]
        # Fallback to first connected channel
        for ch in meta.get("channels", []):
            if os.path.exists(ch.get("token_file", "")):
                return ch["token_file"]
        return os.path.join(self.base_dir, "token.json")

    def register_channel(self, channel_id: str, creds_json: str, client_file: str) -> Dict[str, Any]:
        ch_dir = os.path.join(self.channels_dir, channel_id)
        os.makedirs(ch_dir, exist_ok=True)
        token_path = os.path.join(ch_dir, "token.json")
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(creds_json)

        # Fetch channel info
        info = {"yt_channel_id": "", "name": f"Channel {channel_id.replace('ch_', '')}", "thumbnail": "", "subscriber_count": "-"}
        try:
            uploader = YouTubeUploader(client_secrets_file=client_file, token_file=token_path)
            uploader.authenticate()
            info = uploader.get_channel_info()
        except Exception as e:
            logger.warning(f"Could not fetch channel info for {channel_id}: {e}")

        meta = self._load_meta()
        slot_num = int(channel_id.replace("ch_", "")) if channel_id.startswith("ch_") and channel_id[3:].isdigit() else len(meta["channels"]) + 1

        # Remove existing entry with same id if reconnecting
        meta["channels"] = [c for c in meta.get("channels", []) if c["id"] != channel_id]
        entry = {
            "id": channel_id,
            "slot": slot_num,
            "name": info.get("name", f"Channel {slot_num}"),
            "yt_channel_id": info.get("yt_channel_id", ""),
            "thumbnail": info.get("thumbnail", ""),
            "subscriber_count": info.get("subscriber_count", "-"),
            "token_file": token_path
        }
        meta["channels"].append(entry)
        meta["channels"].sort(key=lambda x: x.get("slot", 99))

        if not meta.get("default_channel_id"):
            meta["default_channel_id"] = channel_id

        # Also keep legacy token.json synced with ch_1/default
        if channel_id == meta.get("default_channel_id"):
            with open(os.path.join(self.base_dir, "token.json"), "w", encoding="utf-8") as f:
                f.write(creds_json)

        self._save_meta(meta)
        return entry

    def set_default_channel(self, channel_id: str) -> bool:
        meta = self._load_meta()
        found = any(c["id"] == channel_id for c in meta.get("channels", []))
        if not found:
            return False
        meta["default_channel_id"] = channel_id
        self._save_meta(meta)
        return True

    def remove_channel(self, channel_id: str) -> bool:
        meta = self._load_meta()
        before = len(meta.get("channels", []))
        meta["channels"] = [c for c in meta.get("channels", []) if c["id"] != channel_id]
        if len(meta["channels"]) == before:
            return False

        ch_dir = os.path.join(self.channels_dir, channel_id)
        if os.path.exists(ch_dir):
            shutil.rmtree(ch_dir, ignore_errors=True)

        if meta.get("default_channel_id") == channel_id:
            meta["default_channel_id"] = meta["channels"][0]["id"] if meta["channels"] else None

        self._save_meta(meta)
        return True
