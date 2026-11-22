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
    def _find_cookie_file() -> Optional[str]:
        """Looks for cookies.txt in root or workspace directory."""
        candidates = [
            "cookies.txt",
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cookies.txt"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "cookies.txt")
        ]
        return next((os.path.abspath(f) for f in candidates if os.path.exists(f)), None)

    @classmethod
    def _get_base_ydl_opts(cls) -> Dict[str, Any]:
        """Base options for yt-dlp to bypass bot detection, 403 blocks, and login walls."""
        opts = {
            "noplaylist": True,
            "extract_flat": False,
            "geo_bypass": True,
            "socket_timeout": 30,
            "retries": 3,
            "extractor_args": {
                "youtube": {
                    "player_client": ["mweb", "android", "web"],
                    "player_skip": ["webpage", "configs"],
                }
            },
            "http_headers": {
                "User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
                "Accept-Language": "en-US,en;q=0.9",
            }
        }

        cookie_file = cls._find_cookie_file()
        if cookie_file:
            logger.info(f"Using cookies file: {cookie_file}")
            opts["cookiefile"] = cookie_file
        elif sys.platform == "win32":
            # Fallback to local Chrome browser cookies if on Windows and cookies.txt absent
            try:
                opts["cookiesfrombrowser"] = ("chrome",)
            except Exception:
                pass

        return opts

    def get_video_info(self, url: str) -> Dict[str, Any]:
        """Extracts metadata without downloading using multi-strategy fallback."""
        clean_url = self.clean_youtube_url(url)
        last_err = None

        strategies = [
            {"name": "Default with cookies", "use_browser_cookies": True, "clients": ["mweb", "android", "web"]},
            {"name": "No-cookie Mobile Fallback", "use_browser_cookies": False, "clients": ["mweb", "android"]},
            {"name": "Android Client Only", "use_browser_cookies": False, "clients": ["android"]},
            {"name": "iOS Client Fallback", "use_browser_cookies": False, "clients": ["ios"]},
            {"name": "TV Embedded Fallback", "use_browser_cookies": False, "clients": ["tv_embedded"]},
            {"name": "Standard Web Client", "use_browser_cookies": False, "clients": ["web"]},
        ]

        for strat in strategies:
            ydl_opts = self._get_base_ydl_opts()
            if not strat["use_browser_cookies"]:
                ydl_opts.pop("cookiesfrombrowser", None)
            ydl_opts["extractor_args"] = {
                "youtube": {
                    "player_client": strat["clients"],
                    "player_skip": ["webpage", "configs"],
                }
            }
            ydl_opts.update({
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
            })

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(clean_url, download=False)
                    if info:
                        return {
                            "id": info.get("id"),
                            "title": info.get("title"),
                            "duration": info.get("duration"),
                            "uploader": info.get("uploader"),
                            "thumbnail": info.get("thumbnail"),
                            "description": info.get("description"),
                        }
            except Exception as e:
                last_err = e
                logger.warning(f"Metadata extraction strategy '{strat['name']}' encountered: {e}")
                err_str = str(e).lower()
                if "unavailable" in err_str or "does not exist" in err_str:
                    break

        err_str = str(last_err).lower() if last_err else ""
        if "unavailable" in err_str or "failed to extract any player response" in err_str:
            raise ValueError(f"Invalid YouTube URL: Video '{clean_url}' exist nahi karti ya YouTube ne block ki hai. Kripya valid YouTube link use karein ya settings mein cookies.txt upload karein.")
        raise last_err if last_err else RuntimeError("Failed to extract video info")

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

        # Check if already downloaded and verify it is high definition (>= 720p)
        existing_videos = [
            os.path.join(self.raw_videos_dir, f)
            for f in os.listdir(self.raw_videos_dir)
            if video_id in f and not f.endswith(".part") and os.path.getsize(os.path.join(self.raw_videos_dir, f)) > 1000000
        ]
        
        is_hd = False
        if existing_videos:
            try:
                import cv2
                cap = cv2.VideoCapture(existing_videos[0])
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                cap.release()
                if min(w, h) >= 720:
                    is_hd = True
                else:
                    logger.warning(f"Cached video '{existing_videos[0]}' is low resolution ({w}x{h} < 720p). Overwriting with fresh Full HD 1080p stream...")
            except Exception:
                is_hd = True
        
        if existing_videos and is_hd and os.path.exists(audio_output_path):
            logger.info(f"Existing Full HD video and audio found for {video_id}! Skipping download.")
            return {
                "video_id": video_id,
                "title": info["title"],
                "video_path": existing_videos[0],
                "audio_path": audio_output_path,
                "duration": info["duration"]
            }

        # 1. Download Video (Crisp 1080p Full HD / Best Quality)
        if not existing_videos or not is_hd:
            download_strategies = [
                {"name": "Default with cookies", "use_browser_cookies": True, "clients": ["mweb", "android", "web"]},
                {"name": "No-cookie Mobile Fallback", "use_browser_cookies": False, "clients": ["mweb", "android"]},
                {"name": "Android Client Only", "use_browser_cookies": False, "clients": ["android"]},
                {"name": "iOS Client Fallback", "use_browser_cookies": False, "clients": ["ios"]},
                {"name": "TV Embedded Fallback", "use_browser_cookies": False, "clients": ["tv_embedded"]},
            ]
            download_success = False
            last_dl_err = None

            for strat in download_strategies:
                ydl_opts_video = self._get_base_ydl_opts()
                if not strat["use_browser_cookies"]:
                    ydl_opts_video.pop("cookiesfrombrowser", None)
                ydl_opts_video["extractor_args"] = {
                    "youtube": {
                        "player_client": strat["clients"],
                        "player_skip": ["webpage", "configs"],
                    }
                }
                ydl_opts_video.update({
                    "format": "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best",
                    "outtmpl": video_output_template,
                    "merge_output_format": "mp4",
                    "ffmpeg_location": ffmpeg_dir,
                    "quiet": False,
                    "no_warnings": True,
                })

                logger.info(f"Downloading Full HD stream with strategy '{strat['name']}'...")
                try:
                    with yt_dlp.YoutubeDL(ydl_opts_video) as ydl:
                        ydl.download([url])
                    download_success = True
                    break
                except Exception as e:
                    last_dl_err = e
                    logger.warning(f"Download strategy '{strat['name']}' failed: {e}")

            if not download_success:
                err_str = str(last_dl_err).lower() if last_dl_err else ""
                if "unavailable" in err_str or "failed to extract any player response" in err_str:
                    raise ValueError(f"Invalid YouTube URL: Video '{url}' download nahi ho paayi. Kripya valid YouTube link check karein ya settings mein cookies.txt upload karein.")
                raise last_dl_err if last_dl_err else RuntimeError("Download failed across all strategies")

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
