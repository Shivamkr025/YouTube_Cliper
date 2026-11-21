"""
AI Viral Shorts & Clips Generator - Master Pipeline
Orchestrates downloading, transcription, Gemini viral clip extraction,
AI voiceover generation, 9:16 face-crop video editing, and YouTube auto-upload.
"""

import os
import sys
import argparse
import logging
from typing import Optional

from src.downloader import YouTubeDownloader
from src.analyzer import AudioTranscriber, ViralMomentsAnalyzer
from src.voice_gen import VoiceoverGenerator
from src.video_editor import VideoEditor
from src.uploader import YouTubeUploader
from src.api import app  # Expose FastAPI app for uvicorn (e.g. uvicorn main:app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Pipeline")

def run_pipeline(
    youtube_url: str,
    max_clips: int = 5,
    whisper_model: str = "base",
    voice: Optional[str] = None,
    enable_voiceover: bool = True,
    auto_upload: bool = False,
    privacy_status: str = "private"
):
    print("=" * 65)
    print("🎬 AI VIRAL SHORTS & CLIPS GENERATOR PIPELINE")
    print("=" * 65)
    print(f"Target Video URL: {youtube_url}")
    print(f"Max Viral Clips : {max_clips}")
    print(f"Whisper Model   : {whisper_model}")
    print(f"Voiceover Intro : {'Enabled' if enable_voiceover else 'Disabled'}")
    print(f"Auto-Upload     : {'Enabled (' + privacy_status + ')' if auto_upload else 'Disabled'}")
    print("-" * 65)

    # -------------------------------------------------------------
    # Step 1: Download Video & Audio
    # -------------------------------------------------------------
    logger.info(">>> [STEP 1/5] Downloading YouTube Video & Audio...")
    downloader = YouTubeDownloader()
    dl_data = downloader.download(youtube_url)
    video_id = dl_data["video_id"]
    video_path = dl_data["video_path"]
    audio_path = dl_data["audio_path"]
    logger.info(f"Video '{dl_data['title']}' ready for processing.")

    # -------------------------------------------------------------
    # Step 2: Transcribe Audio with Word Timestamps
    # -------------------------------------------------------------
    logger.info(">>> [STEP 2/5] Transcribing Audio with faster-whisper...")
    transcriber = AudioTranscriber(model_size=whisper_model)
    transcript_data = transcriber.transcribe(audio_path, video_id)
    total_words = len(transcript_data.get("words", []))
    logger.info(f"Transcription complete: {total_words} words recognized.")

    # -------------------------------------------------------------
    # Step 3: Analyze Viral Moments with Google Gemini API
    # -------------------------------------------------------------
    logger.info(">>> [STEP 3/5] Extracting High-Retention Viral Moments with Gemini...")
    analyzer = ViralMomentsAnalyzer()
    viral_clips = analyzer.analyze_viral_moments(transcript_data, max_clips=max_clips)
    
    if not viral_clips:
        logger.error("No viral moments detected or failed to parse Gemini response.")
        return

    logger.info(f"Identified {len(viral_clips)} viral moments.")

    # -------------------------------------------------------------
    # Step 4: Voiceover Generation & 9:16 Video Editing
    # -------------------------------------------------------------
    logger.info(">>> [STEP 4/5] Editing Clips, Burning Subtitles & Generating Voiceovers...")
    voice_gen = VoiceoverGenerator() if enable_voiceover else None
    editor = VideoEditor()

    rendered_shorts = []

    for idx, clip in enumerate(viral_clips, 1):
        clip_id = clip.get("clip_id", idx)
        title = clip.get("title", f"Viral Moment #{clip_id}")
        start_t = clip.get("start_time", 0.0)
        end_t = clip.get("end_time", start_t + 30.0)
        vo_script = clip.get("voiceover_intro", "")

        print(f"\n[Clip {idx}/{len(viral_clips)}] '{title}' ({start_t}s -> {end_t}s)")
        print(f"Hook: {clip.get('hook_reason', 'N/A')}")

        vo_path = None
        if enable_voiceover and vo_script:
            try:
                vo_filename = f"vo_clip_{clip_id}.mp3"
                vo_path = voice_gen.generate_voiceover(vo_script, vo_filename, voice=voice)
            except Exception as e:
                logger.warning(f"Skipping voiceover for clip {clip_id} due to: {e}")

        # Render 9:16 vertical short
        try:
            rendered_path = editor.render_short(
                video_path=video_path,
                clip_data=clip,
                words_data=transcript_data.get("words", []),
                voiceover_path=vo_path,
                output_filename=f"short_{video_id}_clip_{clip_id}.mp4"
            )
            rendered_shorts.append({
                "clip_data": clip,
                "video_path": rendered_path
            })
        except Exception as e:
            logger.error(f"Failed to render clip {clip_id}: {e}")

    # -------------------------------------------------------------
    # Step 5: Optional YouTube Auto-Upload
    # -------------------------------------------------------------
    if auto_upload and rendered_shorts:
        logger.info(">>> [STEP 5/5] Auto-Uploading Final Shorts to YouTube...")
        try:
            uploader = YouTubeUploader()
            uploader.authenticate()
            for item in rendered_shorts:
                c = item["clip_data"]
                uploader.upload_short(
                    video_path=item["video_path"],
                    title=c.get("title", "Viral Short #Shorts"),
                    description=c.get("description", "#Shorts #Viral"),
                    tags=c.get("tags", ["#Shorts", "#Viral"]),
                    privacy_status=privacy_status
                )
        except Exception as e:
            logger.error(f"YouTube Upload Error: {e}")
            logger.info("Videos are safely saved locally in workspace/final_shorts/ for manual upload.")

    print("\n" + "=" * 65)
    print(f"🎉 PIPELINE COMPLETED! {len(rendered_shorts)} SHORTS CREATED.")
    print("📁 Output Location: workspace/final_shorts/")
    print("=" * 65)

def start_server(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    print("\n" + "=" * 60)
    print(f"🚀 ViralClip AI Web Server starting at: http://localhost:{port}")
    print("=" * 60 + "\n")
    uvicorn.run("src.api:app", host=host, port=port, reload=True)

def main():
    parser = argparse.ArgumentParser(description="AI Viral Shorts & Clips Generator")
    parser.add_argument("command", nargs="?", default="", help="Optional command: 'server' to start web server")
    parser.add_argument("--server", action="store_true", help="Start the FastAPI Web Server & UI")
    parser.add_argument("--port", type=int, default=8000, help="Port for web server (default: 8000)")
    parser.add_argument("--url", type=str, help="YouTube video URL to clip")
    parser.add_argument("--max-clips", type=int, default=10, help="Max clips to generate (default: 10)")
    parser.add_argument("--model", type=str, default="base", help="Whisper model size (tiny, base, small, medium)")
    parser.add_argument("--voice", type=str, default=None, help="TTS Voice (e.g. en_male_deep, hi_male)")
    parser.add_argument("--no-vo", action="store_true", help="Disable AI intro voiceover generation")
    parser.add_argument("--upload", action="store_true", help="Auto-upload final clips to YouTube")
    parser.add_argument("--privacy", type=str, default="private", choices=["private", "unlisted", "public"])

    args = parser.parse_args()

    # 1. Start Server command: python main.py server OR python main.py --server
    if args.server or args.command.lower() in ["server", "start"]:
        start_server(port=args.port)
        return

    url = args.url
    if not url:
        print("\n" + "=" * 60)
        print("  🎬 VIRALCLIP AI - SHORTS & REELS GENERATOR")
        print("=" * 60)
        print("  [1] Start Web Dashboard Server (Recommended)")
        print("  [2] Enter YouTube URL to run CLI directly")
        print("-" * 60)
        choice = input("Select an option (Press Enter for Web Server, or paste URL): ").strip()

        if choice in ["", "1", "server", "start"]:
            start_server(port=args.port)
            return
        elif choice.startswith("http://") or choice.startswith("https://") or "youtube" in choice or "youtu.be" in choice:
            url = choice
        else:
            url = input("Enter YouTube Video URL: ").strip()
            if not url:
                print("No URL provided. Exiting.")
                sys.exit(1)

    run_pipeline(
        youtube_url=url,
        max_clips=args.max_clips,
        whisper_model=args.model,
        voice=args.voice,
        enable_voiceover=not args.no_vo,
        auto_upload=args.upload,
        privacy_status=args.privacy
    )

if __name__ == "__main__":
    main()
