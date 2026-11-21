"""
Module 1A: YouTube Video & Audio Downloader
Downloads YouTube videos at high quality and extracts 16kHz mono audio for transcription.
"""

import os
import re
import sys
import logging
from typing import Dict, Any, Optional
import yt_dlp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class YouTubeDownloader:
    def __init__(self, raw_videos_dir: str = "workspace/raw_videos", temp_dir: str = "workspace/temp"):
        self.raw_videos_dir = os.path.abspath(raw_videos_dir)
        self.temp_dir = os.path.abspath(temp_dir)
        os.makedirs(self.raw_videos_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        self.ffmpeg_path = self._find_ffmpeg()
        if os.path.exists(self.ffmpeg_path):
            ff_dir = os.path.dirname(self.ffmpeg_path)
            if ff_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")
        logger.info(f"YouTubeDownloader using FFmpeg at: {self.ffmpeg_path}")

    @staticmethod
    def _find_ffmpeg() -> str:
        import shutil
        sys_ffmpeg = shutil.which("ffmpeg")
        if sys_ffmpeg:
            return sys_ffmpeg
        venv_ffmpeg = os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")
        if os.path.exists(venv_ffmpeg):
            return venv_ffmpeg
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
        return "ffmpeg"

    @staticmethod
    def sanitize_filename(name: str) -> str:
        """Sanitizes strings to be safe for filenames."""
        return re.sub(r'[\\/*?:"<>|]', "", name).replace(" ", "_")[:60]

    @staticmethod
    def clean_youtube_url(url: str) -> str:
        """
        Strips playlist parameters (&list=RD..., &index=..., &start_radio=1) to prevent
        yt-dlp from attempting to download entire playlists or failing with 403 on youtube:tab.
        """
        match = re.search(r'(?:v=|\/|vi=)([0-9A-Za-z_-]{11})', url)
        if match:
            return f"https://www.youtube.com/watch?v={match.group(1)}"
        return url

    @staticmethod
    def _get_base_ydl_opts() -> Dict[str, Any]:
        """Base options for yt-dlp to bypass datacenter/cloud 403 Forbidden blocks and playlist traps."""
        return {
            "noplaylist": True,
            "extract_flat": False,
            "geo_bypass": True,
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "ios", "web_creator", "mweb"]
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Extracts metadata without downloading."""
        clean_url = self.clean_youtube_url(url)
        ydl_opts = self._get_base_ydl_opts()
        ydl_opts.update({
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        })
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(clean_url, download=False)
            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "duration": info.get("duration"),
                "uploader": info.get("uploader"),
                "thumbnail": info.get("thumbnail"),
                "description": info.get("description"),
            }

    def download(self, url: str) -> Dict[str, str]:
        """
        Downloads the video in 1080p/best format and extracts 16kHz mono audio.
        Returns paths to both the video and the extracted audio.
        """
        url = self.clean_youtube_url(url)
        logger.info(f"Extracting video information from: {url}")
        info = self.get_video_info(url)
        video_id = info["id"]
        safe_title = self.sanitize_filename(info["title"] or video_id)
        
        video_output_template = os.path.join(self.raw_videos_dir, f"{safe_title}_{video_id}.%(ext)s")
        audio_output_path = os.path.join(self.temp_dir, f"{video_id}_audio.wav")
        actual_video_path = os.path.join(self.raw_videos_dir, f"{safe_title}_{video_id}.mp4")

        # ffmpeg_location for yt-dlp must be a DIRECTORY, not a file path
        ffmpeg_dir = os.path.dirname(self.ffmpeg_path) if os.path.isfile(self.ffmpeg_path) else self.ffmpeg_path

        # Check if already downloaded
        existing_videos = [
            os.path.join(self.raw_videos_dir, f)
            for f in os.listdir(self.raw_videos_dir)
            if video_id in f and not f.endswith(".part") and os.path.getsize(os.path.join(self.raw_videos_dir, f)) > 1000000
        ]
        
        if existing_videos and os.path.exists(audio_output_path):
            logger.info(f"Existing video and audio found for {video_id}! Skipping download.")
            return {
                "video_id": video_id,
                "title": info["title"],
                "video_path": existing_videos[0],
                "audio_path": audio_output_path,
                "duration": info["duration"]
            }

        # 1. Download Video (fast & high quality up to 1080p)
        if not existing_videos:
            ydl_opts_video = self._get_base_ydl_opts()
            ydl_opts_video.update({
                "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/bestvideo[height<=1080]+bestaudio/best",
                "outtmpl": video_output_template,
                "merge_output_format": "mp4",
                "ffmpeg_location": ffmpeg_dir,
                "quiet": False,
                "no_warnings": True,
            })

            logger.info("Downloading video stream...")
            with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                ydl.download([url])

        if not os.path.exists(actual_video_path):
            candidates = [os.path.join(self.raw_videos_dir, f) for f in os.listdir(self.raw_videos_dir) if video_id in f and not f.endswith(".part")]
            if candidates:
                actual_video_path = candidates[0]

        # 2. Extract 16kHz mono audio from downloaded video locally using FFmpeg (instant & saves downloading twice!)
        if not os.path.exists(audio_output_path):
            logger.info("Extracting 16kHz mono audio directly from video using FFmpeg...")
            extract_cmd = [
                self.ffmpeg_path, "-y",
                "-i", actual_video_path,
                "-vn", "-ar", "16000", "-ac", "1",
                audio_output_path
            ]
            import subprocess
            subprocess.run(extract_cmd, check=True, capture_output=True)

        logger.info(f"Video saved at: {actual_video_path}")
        logger.info(f"Audio saved at: {audio_output_path}")

        return {
            "video_id": video_id,
            "title": info["title"],
            "video_path": actual_video_path,
            "audio_path": audio_output_path,
            "duration": info["duration"]
        }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        test_url = sys.argv[1]
    else:
        test_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    downloader = YouTubeDownloader()
    result = downloader.download(test_url)
    print("Download result:", result)
