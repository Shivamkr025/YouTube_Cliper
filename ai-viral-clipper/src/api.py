"""
FastAPI Backend Server for ViralClip AI Dashboard
Serves the responsive Web UI and orchestrates background video processing tasks.
"""

import os
import sys
import json
import logging
import threading
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv, set_key

from src.downloader import YouTubeDownloader
from src.analyzer import AudioTranscriber, ViralMomentsAnalyzer
from src.voice_gen import VoiceoverGenerator
from src.video_editor import VideoEditor
from src.uploader import YouTubeUploader
from src.fb_uploader import FacebookReelsUploader

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("APIServer")

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ViralClip AI API")

# Enable CORS so VS Code Live Server (port 5500) or any external frontend can connect
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Static Directories
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
if os.path.exists(os.path.join(BASE_DIR, "frontend")):
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
elif os.path.exists(os.path.join(ROOT_DIR, "frontend")):
    FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
else:
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
FINAL_SHORTS_DIR = os.path.join(BASE_DIR, "workspace", "final_shorts")
TEMP_DIR = os.path.join(BASE_DIR, "workspace", "temp")
os.makedirs(FINAL_SHORTS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
app.mount("/media/shorts", StaticFiles(directory=FINAL_SHORTS_DIR), name="media_shorts")

# In-memory Pipeline State
pipeline_state = {
    "status": "idle",  # "idle", "processing", "completed", "error"
    "progress": 0,
    "message": "Ready to clip videos",
    "current_url": None,
    "error": None
}

class GenerateRequest(BaseModel):
    url: str
    max_clips: int = 10
    enable_voiceover: bool = True
    whisper_model: str = "base"
    speed_factor: float = 1.0  # 1.0, 1.15, 1.25
    subtitle_color: str = "yellow"  # "yellow", "cyan", "emerald", "pink"
    bgm_volume: float = 0.12

class SettingsRequest(BaseModel):
    gemini_key: Optional[str] = None
    gemini_key_backup: Optional[str] = None
    tts_voice: Optional[str] = None
    fb_page_id: Optional[str] = None
    fb_access_token: Optional[str] = None

class GeminiTestRequest(BaseModel):
    api_key: str

class FacebookUploadRequest(BaseModel):
    filename: str
    title: Optional[str] = None
    description: Optional[str] = None

class UploadRequest(BaseModel):
    filename: str
    privacy: str = "private"

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

@app.get("/api/status")
def get_status():
    return pipeline_state

def background_video_worker(req: GenerateRequest):
    global pipeline_state
    pipeline_state["status"] = "processing"
    pipeline_state["current_url"] = req.url
    pipeline_state["progress"] = 10
    pipeline_state["message"] = "Downloading YouTube video & extracting audio..."

    try:
        # Step 1: Downloader
        downloader = YouTubeDownloader()
        dl_data = downloader.download(req.url)
        video_id = dl_data["video_id"]
        video_path = dl_data["video_path"]
        audio_path = dl_data["audio_path"]

        pipeline_state["progress"] = 30
        pipeline_state["message"] = f"Transcribing audio with faster-whisper..."

        # Step 2: Transcriber
        transcriber = AudioTranscriber(model_size=req.whisper_model)
        transcript_data = transcriber.transcribe(audio_path, video_id)

        pipeline_state["progress"] = 55
        pipeline_state["message"] = "Analyzing viral hooks with Google Gemini AI..."

        # Step 3: Viral Moments
        analyzer = ViralMomentsAnalyzer()
        viral_clips = analyzer.analyze_viral_moments(transcript_data, max_clips=req.max_clips)

        if not viral_clips:
            raise RuntimeError("Gemini failed to identify viral moments.")

        # Step 4: Render Shorts
        pipeline_state["progress"] = 70
        pipeline_state["message"] = f"Editing & face-cropping {len(viral_clips)} vertical Shorts..."

        voice_gen = VoiceoverGenerator() if req.enable_voiceover else None
        editor = VideoEditor()

        for idx, clip in enumerate(viral_clips, 1):
            clip_id = clip.get("clip_id", idx)
            vo_script = clip.get("voiceover_intro", "")
            vo_path = None

            if req.enable_voiceover and vo_script:
                try:
                    vo_path = voice_gen.generate_voiceover(vo_script, f"vo_{video_id}_{clip_id}.mp3")
                except Exception as e:
                    logger.warning(f"Voiceover skip: {e}")

            editor.render_short(
                video_path=video_path,
                clip_data=clip,
                words_data=transcript_data.get("words", []),
                voiceover_path=vo_path,
                output_filename=f"short_{video_id}_clip_{clip_id}.mp4",
                speed_factor=req.speed_factor,
                color_theme=req.subtitle_color,
                bgm_volume=req.bgm_volume
            )
            # Update progress incrementally
            progress_step = int(70 + (25 * (idx / len(viral_clips))))
            pipeline_state["progress"] = min(98, progress_step)
            pipeline_state["message"] = f"Rendered clip {idx}/{len(viral_clips)}: {clip.get('title', '')[:30]}..."

        pipeline_state["progress"] = 100
        pipeline_state["status"] = "completed"
        pipeline_state["message"] = f"Completed! Generated {len(viral_clips)} Shorts."

    except Exception as e:
        logger.error(f"Worker Error: {e}", exc_info=True)
        pipeline_state["status"] = "error"
        pipeline_state["message"] = str(e)

@app.post("/api/generate")
def start_generation(req: GenerateRequest, background_tasks: BackgroundTasks):
    global pipeline_state
    if pipeline_state["status"] == "processing":
        raise HTTPException(status_code=400, detail="A video is already being processed!")

    background_tasks.add_task(background_video_worker, req)
    return {"message": "Pipeline triggered in background"}

@app.get("/api/clips")
def list_clips():
    """Lists all rendered MP4 files in workspace/final_shorts/ with their metadata."""
    if not os.path.exists(FINAL_SHORTS_DIR):
        return []

    files = [f for f in os.listdir(FINAL_SHORTS_DIR) if f.endswith(".mp4")]
    # Sort newest first
    files.sort(key=lambda x: os.path.getmtime(os.path.join(FINAL_SHORTS_DIR, x)), reverse=True)

    # Check for metadata in temp/
    all_metadata = {}
    for temp_f in os.listdir(TEMP_DIR):
        if temp_f.endswith("_viral_clips.json"):
            try:
                with open(os.path.join(TEMP_DIR, temp_f), "r", encoding="utf-8") as f:
                    clips_list = json.load(f)
                    for c in clips_list:
                        all_metadata[c.get("clip_id")] = c
            except Exception:
                pass

    results = []
    for f in files:
        # Extract clip_id from name short_<vid>_clip_<id>.mp4
        clip_id = None
        if "_clip_" in f:
            try:
                clip_id = int(f.split("_clip_")[1].replace(".mp4", ""))
            except ValueError:
                pass

        meta = all_metadata.get(clip_id, {})
        results.append({
            "filename": f,
            "video_url": f"/media/shorts/{f}",
            "clip_id": clip_id,
            "title": meta.get("title", f.replace(".mp4", "")),
            "description": meta.get("description", ""),
            "hook_reason": meta.get("hook_reason", ""),
            "duration": int(meta.get("end_time", 30) - meta.get("start_time", 0)) if meta else 45
        })

    return results

@app.get("/api/settings")
def get_settings():
    load_dotenv(override=True)
    return {
        "gemini_key": os.getenv("GEMINI_API_KEY", "")[:10] + "..." if os.getenv("GEMINI_API_KEY") else "",
        "gemini_key_backup": os.getenv("GEMINI_API_KEY_BACKUP", "")[:10] + "..." if os.getenv("GEMINI_API_KEY_BACKUP") else "",
        "tts_voice": "en-US-ChristopherNeural",
        "fb_page_id": os.getenv("FB_PAGE_ID", ""),
        "fb_access_token": os.getenv("FB_PAGE_ACCESS_TOKEN", "")[:10] + "..." if os.getenv("FB_PAGE_ACCESS_TOKEN") else ""
    }

@app.post("/api/settings")
def save_settings(req: SettingsRequest):
    env_file = os.path.join(BASE_DIR, ".env")
    if req.gemini_key and not req.gemini_key.endswith("..."):
        set_key(env_file, "GEMINI_API_KEY", req.gemini_key)
        os.environ["GEMINI_API_KEY"] = req.gemini_key
    if req.gemini_key_backup and not req.gemini_key_backup.endswith("..."):
        set_key(env_file, "GEMINI_API_KEY_BACKUP", req.gemini_key_backup)
        os.environ["GEMINI_API_KEY_BACKUP"] = req.gemini_key_backup
    if req.fb_page_id:
        set_key(env_file, "FB_PAGE_ID", req.fb_page_id)
        os.environ["FB_PAGE_ID"] = req.fb_page_id
    if req.fb_access_token and not req.fb_access_token.endswith("..."):
        set_key(env_file, "FB_PAGE_ACCESS_TOKEN", req.fb_access_token)
        os.environ["FB_PAGE_ACCESS_TOKEN"] = req.fb_access_token
    return {"message": "All settings saved successfully"}

@app.post("/api/gemini/test")
def test_gemini_key(req: GeminiTestRequest):
    from google import genai
    try:
        c = genai.Client(api_key=req.api_key)
        resp = c.models.generate_content(model="gemini-3.5-flash", contents="Hi")
        return {"valid": True, "message": "Key is active and working!"}
    except Exception as e:
        return {"valid": False, "message": str(e)}

@app.get("/api/facebook/status")
def facebook_status():
    uploader = FacebookReelsUploader()
    return uploader.test_connection()

@app.post("/api/facebook/upload")
def upload_to_facebook(req: FacebookUploadRequest):
    video_path = os.path.join(FINAL_SHORTS_DIR, req.filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    try:
        uploader = FacebookReelsUploader()
        res = uploader.upload_reel(
            video_path=video_path,
            title=req.title or f"Viral Short #{req.filename[:15]}",
            description=req.description
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/youtube/upload-secret")
async def upload_client_secret(file: UploadFile = File(...)):
    target_path = os.path.join(BASE_DIR, "client_secret.json")
    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)
    return {"success": True, "message": "client_secret.json uploaded successfully!"}

@app.get("/api/youtube/status")
def youtube_status():
    token_file = os.path.join(BASE_DIR, "token.json")
    client_file = os.path.join(BASE_DIR, "client_secret.json")
    return {
        "connected": os.path.exists(token_file),
        "has_client_secret": os.path.exists(client_file),
        "channel_title": "Authorized Channel" if os.path.exists(token_file) else None
    }

@app.get("/api/youtube/auth")
def youtube_auth_flow():
    client_file = os.path.join(BASE_DIR, "client_secret.json")
    if not os.path.exists(client_file):
        return HTMLResponse(
            "<body style='background:#0b0f17;color:#fff;font-family:sans-serif;padding:30px;'>"
            "<h2 style='color:#f43f5e;'>client_secret.json missing!</h2>"
            "<p>Please download your OAuth client_secret.json from Google Cloud Console and place it into the ai-viral-clipper folder.</p>"
            "</body>"
        )
    try:
        uploader = YouTubeUploader()
        uploader.authenticate()
        return HTMLResponse(
            "<body style='background:#0b0f17;color:#fff;font-family:sans-serif;padding:30px;text-align:center;'>"
            "<h2 style='color:#10b981;'>YouTube Channel Connected Successfully! 🎉</h2>"
            "<p>You can close this window now.</p>"
            "<script>setTimeout(function(){ window.close(); }, 2000);</script>"
            "</body>"
        )
    except Exception as e:
        return HTMLResponse(
            f"<body style='background:#0b0f17;color:#fff;font-family:sans-serif;padding:30px;'>"
            f"<h2 style='color:#f43f5e;'>Authentication Failed</h2><p>{e}</p></body>"
        )

@app.post("/api/youtube/upload")
def upload_to_youtube(req: UploadRequest):
    video_path = os.path.join(FINAL_SHORTS_DIR, req.filename)
    if not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Video file not found")

    try:
        uploader = YouTubeUploader()
        uploader.authenticate()
        res = uploader.upload_short(
            video_path=video_path,
            title=f"Viral Short #{req.filename[:15]} #Shorts",
            description="Auto-generated viral short! #Shorts #Viral",
            privacy_status=req.privacy
        )
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 60)
    print(f"🚀 ViralClip AI Web Server starting on port: {port}")
    print("=" * 60 + "\n")
    uvicorn.run("src.api:app", host="0.0.0.0", port=port, reload=False)
