"""
Starlette/ASGI Backend Server for ViralClip AI Dashboard
100% pure Python implementation with zero dependency on Rust/pydantic_core.
Runs reliably across Windows (Smart App Control compliant), Linux Docker (Render), and macOS.
"""

import os
import sys
import json
import logging
import threading
import requests
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv, set_key

from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse, HTMLResponse
from starlette.staticfiles import StaticFiles
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route, Mount

from src.downloader import YouTubeDownloader
from src.analyzer import AudioTranscriber, ViralMomentsAnalyzer
from src.voice_gen import VoiceoverGenerator
from src.video_editor import VideoEditor
from src.uploader import YouTubeUploader
from src.fb_uploader import FacebookReelsUploader

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("APIServer")

# Directory setup
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT_DIR = os.path.dirname(BASE_DIR)
FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")
if not os.path.exists(FRONTEND_DIR):
    FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

FINAL_SHORTS_DIR = os.path.join(BASE_DIR, "workspace", "final_shorts")
TEMP_DIR = os.path.join(BASE_DIR, "workspace", "temp")
os.makedirs(FINAL_SHORTS_DIR, exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

# In-memory Pipeline State
pipeline_state = {
    "status": "idle",  # "idle", "processing", "completed", "error"
    "progress": 0,
    "message": "Ready to clip videos",
    "current_url": None,
    "error": None
}

def background_video_worker(req: Dict[str, Any]):
    global pipeline_state
    pipeline_state["status"] = "processing"
    pipeline_state["current_url"] = req.get("url")
    pipeline_state["progress"] = 10
    pipeline_state["message"] = "Downloading YouTube video & extracting audio..."

    try:
        # Step 1: Downloader
        downloader = YouTubeDownloader()
        dl_data = downloader.download(req["url"])
        video_id = dl_data["video_id"]
        video_path = dl_data["video_path"]
        audio_path = dl_data["audio_path"]

        pipeline_state["progress"] = 30
        pipeline_state["message"] = "Transcribing audio with faster-whisper..."

        # Step 2: Transcriber
        whisper_model = req.get("whisper_model", "base")
        transcriber = AudioTranscriber(model_size=whisper_model)
        transcript_data = transcriber.transcribe(audio_path, video_id)

        pipeline_state["progress"] = 55
        pipeline_state["message"] = "Analyzing viral hooks with Google Gemini AI..."

        # Step 3: Viral Moments
        max_clips = int(req.get("max_clips", 10))
        analyzer = ViralMomentsAnalyzer()
        viral_clips = analyzer.analyze_viral_moments(transcript_data, max_clips=max_clips)

        if not viral_clips:
            raise RuntimeError("Gemini failed to identify viral moments.")

        # Step 4: Render Shorts
        pipeline_state["progress"] = 70
        pipeline_state["message"] = f"Editing & face-cropping {len(viral_clips)} vertical Shorts..."

        enable_vo = req.get("enable_voiceover", True)
        speed_factor = float(req.get("speed_factor", 1.0))
        subtitle_color = str(req.get("subtitle_color", "yellow"))
        bgm_volume = float(req.get("bgm_volume", 0.12))

        voice_gen = VoiceoverGenerator() if enable_vo else None
        editor = VideoEditor()

        for idx, clip in enumerate(viral_clips, 1):
            clip_id = clip.get("clip_id", idx)
            vo_script = clip.get("voiceover_intro", "")
            vo_path = None

            if enable_vo and vo_script:
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
                speed_factor=speed_factor,
                color_theme=subtitle_color,
                bgm_volume=bgm_volume
            )
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


# Route Handlers
async def serve_index(request):
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({
        "status": "online",
        "service": "ViralClip AI Backend Engine",
        "version": "1.0.0",
        "health": "/api/health"
    })

async def get_status(request):
    return JSONResponse(pipeline_state)

async def health_check(request):
    import shutil
    import yt_dlp.version
    ffmpeg_avail = bool(shutil.which("ffmpeg") or os.path.exists(os.path.join(os.path.dirname(sys.executable), "ffmpeg.exe")))
    return JSONResponse({
        "status": "healthy",
        "yt_dlp_version": yt_dlp.version.__version__,
        "ffmpeg": ffmpeg_avail,
        "cookies_file": os.path.exists("cookies.txt") or os.path.exists(os.path.join(BASE_DIR, "cookies.txt")),
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "facebook_configured": bool(os.getenv("FB_PAGE_ID") and os.getenv("FB_PAGE_ACCESS_TOKEN")),
        "youtube_configured": os.path.exists(os.path.join(BASE_DIR, "token.json")),
    })

async def start_generation(request):
    global pipeline_state
    if pipeline_state["status"] == "processing":
        return JSONResponse({"detail": "A video is already being processed!"}, status_code=400)

    try:
        req_data = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid JSON body"}, status_code=400)

    threading.Thread(target=background_video_worker, args=(req_data,), daemon=True).start()
    return JSONResponse({"message": "Pipeline triggered in background"})

async def list_clips(request):
    if not os.path.exists(FINAL_SHORTS_DIR):
        return JSONResponse([])

    files = [
        f for f in os.listdir(FINAL_SHORTS_DIR)
        if f.endswith(".mp4") and not f.startswith("test_") and os.path.getsize(os.path.join(FINAL_SHORTS_DIR, f)) > 50000
    ]
    files.sort(key=lambda x: os.path.getmtime(os.path.join(FINAL_SHORTS_DIR, x)), reverse=True)

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

    return JSONResponse(results)

async def get_settings(request):
    load_dotenv(override=True)
    return JSONResponse({
        "gemini_key": os.getenv("GEMINI_API_KEY", "")[:10] + "..." if os.getenv("GEMINI_API_KEY") else "",
        "gemini_key_backup": os.getenv("GEMINI_API_KEY_BACKUP", "")[:10] + "..." if os.getenv("GEMINI_API_KEY_BACKUP") else "",
        "tts_voice": "en-US-ChristopherNeural",
        "fb_page_id": os.getenv("FB_PAGE_ID", ""),
        "fb_access_token": os.getenv("FB_PAGE_ACCESS_TOKEN", "")[:10] + "..." if os.getenv("FB_PAGE_ACCESS_TOKEN") else ""
    })

async def save_settings(request):
    req_data = await request.json()
    env_file = os.path.join(BASE_DIR, ".env")
    gemini_key = req_data.get("gemini_key")
    gemini_key_backup = req_data.get("gemini_key_backup")
    fb_page_id = req_data.get("fb_page_id")
    fb_access_token = req_data.get("fb_access_token")

    if gemini_key and not gemini_key.endswith("..."):
        set_key(env_file, "GEMINI_API_KEY", gemini_key)
        os.environ["GEMINI_API_KEY"] = gemini_key
    if gemini_key_backup and not gemini_key_backup.endswith("..."):
        set_key(env_file, "GEMINI_API_KEY_BACKUP", gemini_key_backup)
        os.environ["GEMINI_API_KEY_BACKUP"] = gemini_key_backup
    if fb_page_id:
        set_key(env_file, "FB_PAGE_ID", fb_page_id)
        os.environ["FB_PAGE_ID"] = fb_page_id
    if fb_access_token and not fb_access_token.endswith("..."):
        set_key(env_file, "FB_PAGE_ACCESS_TOKEN", fb_access_token)
        os.environ["FB_PAGE_ACCESS_TOKEN"] = fb_access_token
    return JSONResponse({"message": "All settings saved successfully"})

async def test_gemini_key(request):
    req_data = await request.json()
    api_key = req_data.get("api_key", "").strip()
    if not api_key:
        return JSONResponse({"valid": False, "message": "API key cannot be empty"})

    candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    last_err = None
    for model_name in candidate_models:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
            resp = requests.post(
                url,
                headers={"Content-Type": "application/json"},
                json={"contents": [{"parts": [{"text": "Hi"}]}]},
                timeout=10
            )
            if resp.status_code == 200:
                return JSONResponse({"valid": True, "message": f"Key is active and working with {model_name}!"})
            else:
                last_err = f"HTTP {resp.status_code}: {resp.text[:150]}"
        except Exception as e:
            last_err = str(e)
            continue
    return JSONResponse({"valid": False, "message": str(last_err)})

async def facebook_status(request):
    uploader = FacebookReelsUploader()
    return JSONResponse(uploader.test_connection())

async def upload_to_facebook(request):
    req_data = await request.json()
    filename = req_data.get("filename", "")
    title = req_data.get("title")
    description = req_data.get("description")
    video_path = os.path.join(FINAL_SHORTS_DIR, filename)

    if not os.path.exists(video_path):
        return JSONResponse({"detail": "Video file not found"}, status_code=404)

    try:
        uploader = FacebookReelsUploader()
        res = uploader.upload_reel(
            video_path=video_path,
            title=title or f"Viral Short #{filename[:15]}",
            description=description
        )
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"detail": str(e)}, status_code=500)

async def upload_client_secret(request):
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"detail": "No file uploaded"}, status_code=400)
    target_path = os.path.join(BASE_DIR, "client_secret.json")
    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)
    return JSONResponse({"success": True, "message": "client_secret.json uploaded successfully!"})

async def youtube_status(request):
    token_file = os.path.join(BASE_DIR, "token.json")
    client_file = os.path.join(BASE_DIR, "client_secret.json")
    return JSONResponse({
        "connected": os.path.exists(token_file),
        "has_client_secret": os.path.exists(client_file),
        "channel_title": "Authorized Channel" if os.path.exists(token_file) else None
    })

async def youtube_auth_flow(request):
    client_file = os.path.join(BASE_DIR, "client_secret.json")
    if not os.path.exists(client_file):
        alt_path = os.path.join(BASE_DIR, "ai-viral-clipper", "client_secret.json")
        if os.path.exists(alt_path):
            client_file = alt_path
        else:
            return HTMLResponse(
                "<body style='background:#0b0f17;color:#fff;font-family:sans-serif;padding:30px;'>"
                "<h2 style='color:#f43f5e;'>client_secret.json missing!</h2>"
                "<p>Please download your OAuth client_secret.json from Google Cloud Console and place it into the ai-viral-clipper folder.</p>"
                "</body>"
            )

    token_file = os.path.join(BASE_DIR, "token.json")

    try:
        import wsgiref.simple_server
        from google_auth_oauthlib.flow import (
            InstalledAppFlow,
            _RedirectWSGIApp,
            _ExclusiveWSGIServer,
            _WSGIRequestHandler
        )

        SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
        flow = InstalledAppFlow.from_client_secrets_file(client_file, SCOPES)
        success_message = """
        <html>
          <head><title>YouTube Connected</title></head>
          <body style="background:#0b0f17;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:90vh;margin:0;text-align:center;">
            <div style="background:#131b2e;padding:40px;border-radius:24px;border:1px solid #1e293b;max-width:400px;box-shadow:0 20px 40px rgba(0,0,0,0.5);">
              <h2 style="color:#10b981;margin-bottom:10px;">YouTube Channel Connected! 🎉</h2>
              <p style="color:#94a3b8;font-size:14px;">Authorization successful. This window will close automatically.</p>
            </div>
            <script>
              if (window.opener) {
                try { window.opener.checkYouTubeStatus(); } catch(e){}
              }
              setTimeout(() => { window.close(); }, 2500);
            </script>
          </body>
        </html>
        """
        wsgi_app = _RedirectWSGIApp(success_message)
        local_server = wsgiref.simple_server.make_server(
            "localhost",
            0,
            wsgi_app,
            server_class=_ExclusiveWSGIServer,
            handler_class=_WSGIRequestHandler,
        )
        flow.redirect_uri = f"http://localhost:{local_server.server_port}/"
        auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

        def listen_in_background():
            try:
                local_server.timeout = 180
                local_server.handle_request()
                authorization_response = wsgi_app.last_request_uri.replace("http", "https")
                flow.fetch_token(authorization_response=authorization_response)
                with open(token_file, "w") as f:
                    f.write(flow.credentials.to_json())
                # Mirror in ai-viral-clipper folder as well if exists
                alt_token = os.path.join(BASE_DIR, "ai-viral-clipper", "token.json")
                if os.path.exists(os.path.dirname(alt_token)):
                    with open(alt_token, "w") as f:
                        f.write(flow.credentials.to_json())
                logger.info("Successfully saved YouTube OAuth credentials to token.json")
            except Exception as ex:
                logger.error(f"YouTube OAuth background listener error: {ex}")
            finally:
                try:
                    local_server.server_close()
                except Exception:
                    pass

        threading.Thread(target=listen_in_background, daemon=True).start()

        # Instantly navigate the popup window directly to Google's sign-in URL
        return HTMLResponse(
            f"""<!DOCTYPE html>
            <html>
              <head>
                <meta http-equiv="refresh" content="0; url='{auth_url}'" />
                <title>Redirecting to Google...</title>
                <script>window.location.href = "{auth_url}";</script>
              </head>
              <body style="background:#0b0f17;color:#fff;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:90vh;text-align:center;">
                <div>
                  <h3 style="color:#38bdf8;">Connecting to Google Account...</h3>
                  <p style="color:#94a3b8;">Redirecting you to Google sign-in. If it doesn't open automatically, <a href="{auth_url}" style="color:#f43f5e;font-weight:bold;">click here</a>.</p>
                </div>
              </body>
            </html>"""
        )
    except Exception as e:
        logger.error(f"Failed to start YouTube OAuth flow: {e}", exc_info=True)
        return HTMLResponse(
            f"<body style='background:#0b0f17;color:#fff;font-family:sans-serif;padding:30px;'>"
            f"<h2 style='color:#f43f5e;'>Authentication Failed</h2><p>{e}</p></body>"
        )

async def upload_to_youtube(request):
    req_data = await request.json()
    filename = req_data.get("filename", "")
    privacy = req_data.get("privacy", "public")
    title = req_data.get("title") or f"Viral Short #{filename[:15]} #Shorts"
    description = req_data.get("description") or "Auto-generated viral short! #Shorts #Viral"
    publish_at = req_data.get("publish_at")
    category_id = req_data.get("category_id", "24")
    tags = req_data.get("tags")
    video_path = os.path.join(FINAL_SHORTS_DIR, filename)

    if not os.path.exists(video_path):
        return JSONResponse({"detail": "Video file not found"}, status_code=404)

    # Format publish_at if provided (ensure ISO 8601 UTC with 'Z')
    if publish_at:
        try:
            # Handle formats like 2026-11-24T18:00 or 2026-11-24T18:00:00
            import datetime
            if "Z" not in publish_at and "+" not in publish_at:
                dt = datetime.datetime.fromisoformat(publish_at)
                # Convert to UTC ISO string
                publish_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception as e:
            logger.warning(f"Publish_at format notice: {e}")

    try:
        uploader = YouTubeUploader()
        uploader.authenticate()
        res = uploader.upload_short(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy_status=privacy,
            publish_at=publish_at
        )
        return JSONResponse(res)
    except Exception as e:
        logger.error(f"YouTube upload error: {e}", exc_info=True)
        return JSONResponse({"detail": str(e)}, status_code=500)

async def batch_schedule_youtube(request):
    req_data = await request.json()
    items = req_data.get("items", [])
    if not items:
        return JSONResponse({"detail": "No items provided"}, status_code=400)

    uploader = YouTubeUploader()
    try:
        uploader.authenticate()
    except Exception as e:
        return JSONResponse({"detail": f"YouTube Authentication Failed: {e}"}, status_code=401)

    results = []
    errors = []
    for item in items:
        filename = item.get("filename")
        video_path = os.path.join(FINAL_SHORTS_DIR, filename)
        if not os.path.exists(video_path):
            errors.append(f"{filename}: File not found")
            continue

        title = item.get("title") or f"Viral Short #{filename[:15]} #Shorts"
        description = item.get("description") or "Auto-generated viral short! #Shorts #Viral"
        publish_at = item.get("publish_at")
        privacy = item.get("privacy", "private" if publish_at else "public")

        if publish_at:
            try:
                import datetime
                if "Z" not in publish_at and "+" not in publish_at:
                    dt = datetime.datetime.fromisoformat(publish_at)
                    publish_at = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception:
                pass

        try:
            res = uploader.upload_short(
                video_path=video_path,
                title=title,
                description=description,
                privacy_status=privacy,
                publish_at=publish_at
            )
            results.append(res)
        except Exception as e:
            errors.append(f"{filename}: {str(e)}")

    return JSONResponse({
        "success": True,
        "scheduled_count": len(results),
        "results": results,
        "errors": errors
    })


# Routes Assembly
routes = [
    Route("/", endpoint=serve_index, methods=["GET"]),
    Route("/api/status", endpoint=get_status, methods=["GET"]),
    Route("/api/health", endpoint=health_check, methods=["GET"]),
    Route("/api/generate", endpoint=start_generation, methods=["POST"]),
    Route("/api/clips", endpoint=list_clips, methods=["GET"]),
    Route("/api/settings", endpoint=get_settings, methods=["GET"]),
    Route("/api/settings", endpoint=save_settings, methods=["POST"]),
    Route("/api/gemini/test", endpoint=test_gemini_key, methods=["POST"]),
    Route("/api/facebook/status", endpoint=facebook_status, methods=["GET"]),
    Route("/api/facebook/upload", endpoint=upload_to_facebook, methods=["POST"]),
    Route("/api/youtube/status", endpoint=youtube_status, methods=["GET"]),
    Route("/api/youtube/auth", endpoint=youtube_auth_flow, methods=["GET"]),
    Route("/api/youtube/upload", endpoint=upload_to_youtube, methods=["POST"]),
    Route("/api/youtube/schedule-batch", endpoint=batch_schedule_youtube, methods=["POST"]),
    Route("/api/youtube/upload-secret", endpoint=upload_client_secret, methods=["POST"]),
    Mount("/media/shorts", app=StaticFiles(directory=FINAL_SHORTS_DIR), name="media_shorts"),
]

if os.path.exists(FRONTEND_DIR):
    routes.append(Mount("/static", app=StaticFiles(directory=FRONTEND_DIR), name="static"))
    css_dir = os.path.join(FRONTEND_DIR, "css")
    js_dir = os.path.join(FRONTEND_DIR, "js")
    if os.path.exists(css_dir):
        routes.append(Mount("/css", app=StaticFiles(directory=css_dir), name="css"))
    if os.path.exists(js_dir):
        routes.append(Mount("/js", app=StaticFiles(directory=js_dir), name="js"))

middleware = [
    Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
]

app = Starlette(routes=routes, middleware=middleware)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print("\n" + "=" * 60)
    print(f"🚀 ViralClip AI Web Server starting on port: {port}")
    print("=" * 60 + "\n")
    uvicorn.run("src.api:app", host="0.0.0.0", port=port, reload=False)
