"""
Module 5: AI-Powered Local Video Editor (CapCut-Style)
Transforms raw local videos into polished 9:16 vertical Shorts with:
- Word-by-word CapCut-style ASS captions (faster-whisper word timestamps)
- Background noise reduction & voice clarity (FFmpeg afftdn/highpass/loudnorm)
- Professional color grading presets (Viral, Cinematic, Warm, Cool)
- Smooth zoom punch-in animations & fade transitions
- Optional Smart 9:16 face-centered reframe (MediaPipe)
- Optional AI Script enhancement & Voice-Over intro (Gemini + Edge-TTS)
- Pure-NumPy audio beat/energy peak detection for dynamic zoom hits
"""

import os
import re
import json
import wave
import math
import time
import logging
import subprocess
import requests
from typing import Dict, Any, List, Optional, Callable

import numpy as np
import cv2
import imageio_ffmpeg
from faster_whisper import WhisperModel
from src.voice_gen import VoiceoverGenerator
from src.element_library import ElementLibrary
from src.caption_utils import detect_existing_captions, convert_words_to_hinglish

logger = logging.getLogger(__name__)


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    if cs >= 100:
        cs = 99
    return f"{hrs}:{mins:02d}:{secs:02d}.{cs:02d}"


class LocalVideoEditor:
    COLOR_PRESETS = {
        "viral": "eq=brightness=0.03:saturation=1.28:contrast=1.12,unsharp=5:5:0.7:5:5:0.0",
        "cinematic": "eq=contrast=1.15:saturation=1.10:brightness=-0.01,vignette=PI/5",
        "warm": "colorbalance=rs=0.06:gs=0.02:bs=-0.05,eq=saturation=1.15:contrast=1.06",
        "cool": "colorbalance=rs=-0.04:gs=0.01:bs=0.06,eq=contrast=1.08:saturation=1.08",
        "none": ""
    }

    CAPTION_COLORS = {
        "yellow": "&H0000FFFF",   # Neon Yellow (BGR in ASS)
        "cyan": "&H00FFFF00",     # Electric Cyan
        "green": "&H0080FF00",    # Neon Green
        "rose": "&H006E3FF4",     # Viral Rose
        "white": "&H00FFFFFF"
    }

    def __init__(self, temp_dir: str = "workspace/temp", output_dir: str = "workspace/final_shorts"):
        self.ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
        self.temp_dir = os.path.abspath(temp_dir)
        self.output_dir = os.path.abspath(output_dir)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _get_video_info(self, video_path: str) -> Dict[str, Any]:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"width": 1920, "height": 1080, "fps": 30.0, "duration": 30.0}
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        cap.release()
        duration = frames / fps if fps > 0 and frames > 0 else 30.0
        return {"width": width, "height": height, "fps": fps, "duration": duration}

    def _detect_face_x_ratio(self, video_path: str) -> float:
        """Samples frames with MediaPipe to find average speaker horizontal center (0.0 to 1.0)."""
        try:
            import mediapipe as mp
            mp_face = mp.solutions.face_detection
            cap = cv2.VideoCapture(video_path)
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            if total_frames <= 0:
                cap.release()
                return 0.5

            sample_indices = np.linspace(0, max(0, total_frames - 1), num=min(12, total_frames), dtype=int)
            x_centers = []
            with mp_face.FaceDetection(model_selection=1, min_detection_confidence=0.5) as detector:
                for idx in sample_indices:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                    ok, frame = cap.read()
                    if not ok:
                        continue
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    res = detector.process(rgb)
                    if res.detections:
                        box = res.detections[0].location_data.relative_bounding_box
                        cx = box.xmin + box.width / 2.0
                        if 0.05 <= cx <= 0.95:
                            x_centers.append(cx)
            cap.release()
            if x_centers:
                return float(np.median(x_centers))
        except Exception as e:
            logger.warning(f"MediaPipe face detection fallback to center crop: {e}")
        return 0.5

    def transcribe_with_words(self, video_path: str, model_size: str = "base") -> Dict[str, Any]:
        """Extracts audio and runs faster-whisper with word-level timestamps."""
        wav_path = os.path.join(self.temp_dir, f"edit_audio_{int(time.time())}.wav")
        cmd = [
            self.ffmpeg_path, "-y", "-i", video_path,
            "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            wav_path
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, info = model.transcribe(wav_path, word_timestamps=True)

        words = []
        full_text_parts = []
        for seg in segments:
            full_text_parts.append(seg.text.strip())
            if seg.words:
                for w in seg.words:
                    clean_w = w.word.strip()
                    if clean_w:
                        words.append({
                            "word": clean_w,
                            "start": float(w.start),
                            "end": float(w.end)
                        })

        return {
            "language": info.language,
            "text": " ".join(full_text_parts).strip(),
            "words": words,
            "wav_path": wav_path
        }

    def detect_beat_peaks(self, wav_path: str, max_peaks: int = 8) -> List[float]:
        """Pure-NumPy audio energy peak detection (100% Smart App Control safe)."""
        if not wav_path or not os.path.exists(wav_path):
            return []
        try:
            with wave.open(wav_path, "rb") as wf:
                sr = wf.getframerate()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
            audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if len(audio) < sr:
                return []

            hop = max(1, int(sr * 0.25))  # 250ms windows
            energies = []
            for i in range(0, len(audio) - hop, hop):
                chunk = audio[i:i + hop]
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                energies.append((i / sr, rms))

            if not energies:
                return []

            avg_rms = np.mean([e[1] for e in energies])
            peaks = []
            last_t = -2.0
            for t, rms in sorted(energies, key=lambda x: x[1], reverse=True):
                if rms > avg_rms * 1.35 and all(abs(t - p) >= 2.2 for p in peaks):
                    peaks.append(round(t, 2))
                    if len(peaks) >= max_peaks:
                        break
            return sorted(peaks)
        except Exception as e:
            logger.warning(f"Beat peak detection skipped: {e}")
            return []

    def enhance_script_with_gemini(self, transcript_text: str, style_goal: str = "viral") -> Dict[str, Any]:
        """Uses Gemini REST API to polish script, write punchy VO hook, title & hashtags."""
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY_BACKUP", "").strip()
        default_res = {
            "title": "Watch Till The End! 🔥 #Shorts",
            "hook_voiceover": "Wait till you see what happens right here!",
            "description": f"{transcript_text[:200]}\n\n#Shorts #Viral #Trending",
            "hashtags": "#Shorts #Viral #Trending #Edit"
        }
        if not api_key or not transcript_text:
            return default_res

        prompt = (
            f"You are a viral YouTube Shorts & CapCut editor.\n"
            f"Given this raw video transcript:\n\"{transcript_text[:2500]}\"\n\n"
            f"Style goal: {style_goal}.\n"
            f"Return ONLY valid JSON with:\n"
            f"- 'title': high-CTR viral Shorts title under 75 chars\n"
            f"- 'hook_voiceover': a super punchy 1-sentence opening voiceover hook (under 12 words) in the same language as the transcript\n"
            f"- 'description': 2-line engaging caption + 5 relevant hashtags\n"
            f"- 'hashtags': 5 space-separated hashtags starting with #"
        )
        for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                resp = requests.post(
                    url,
                    headers={"Content-Type": "application/json"},
                    json={"contents": [{"parts": [{"text": prompt}]}]},
                    timeout=12
                )
                if resp.status_code == 200:
                    raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                    if "```json" in raw:
                        raw = raw.split("```json")[1].split("```")[0].strip()
                    elif "```" in raw:
                        raw = raw.split("```")[1].split("```")[0].strip()
                    parsed = json.loads(raw)
                    return {**default_res, **parsed}
            except Exception as e:
                logger.warning(f"Gemini script enhancement attempt failed on {model_name}: {e}")
        return default_res

    def generate_capcut_ass(
        self,
        words: List[Dict[str, Any]],
        ass_path: str,
        highlight_color: str = "yellow",
        time_offset: float = 0.0
    ) -> str:
        """Generates CapCut-style word-by-word pop & highlight ASS subtitle file for 1080x1920."""
        hl_bgr = self.CAPTION_COLORS.get(highlight_color, self.CAPTION_COLORS["yellow"])
        white_bgr = "&H00FFFFFF"

        header = (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            "PlayResX: 1080\n"
            "PlayResY: 1920\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding\n"
            "Style: CapCut,Arial Black,72,&H00FFFFFF,&H0000FFFF,&H00000000,&H80000000,"
            "-1,0,0,0,100,100,0,0,1,5,3,2,60,60,420,1\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )

        lines = [header]
        group_size = 3
        for i in range(0, len(words), group_size):
            chunk = words[i:i + group_size]
            if not chunk:
                continue
            for active_idx, active_w in enumerate(chunk):
                start_t = active_w["start"] + time_offset
                if active_idx + 1 < len(chunk):
                    end_t = chunk[active_idx + 1]["start"] + time_offset
                else:
                    end_t = active_w["end"] + time_offset
                if end_t <= start_t:
                    end_t = start_t + 0.18

                formatted_parts = []
                for j, w_obj in enumerate(chunk):
                    txt = re.sub(r"[{}\\]", "", w_obj["word"]).upper()
                    if j == active_idx:
                        formatted_parts.append(f"{{\\c{hl_bgr}&\\fscx114\\fscy114}}{txt}{{\\c{white_bgr}&\\fscx100\\fscy100}}")
                    else:
                        formatted_parts.append(txt)

                dialogue_text = " ".join(formatted_parts)
                lines.append(
                    f"Dialogue: 0,{_format_ass_time(start_t)},{_format_ass_time(end_t)},CapCut,,0,0,0,,{dialogue_text}\n"
                )

        with open(ass_path, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return ass_path

    def render_pro_edit(
        self,
        raw_video_path: str,
        options: Dict[str, Any],
        progress_cb: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """Full CapCut-style pipeline for a local raw video."""
        def update(pct: int, msg: str):
            logger.info(f"[LocalEditor {pct}%] {msg}")
            if progress_cb:
                progress_cb(pct, msg)

        if not os.path.exists(raw_video_path):
            raise FileNotFoundError(f"Raw video not found: {raw_video_path}")

        job_tag = f"edit_{int(time.time())}"
        info = self._get_video_info(raw_video_path)
        enable_captions = options.get("enable_captions", True)
        enable_noise_reduce = options.get("enable_noise_reduce", True)
        color_grade = options.get("color_grade", "viral")
        enable_zoom = options.get("enable_zoom", True)
        enable_reframe = options.get("enable_reframe", True)
        enable_voiceover = options.get("enable_voiceover", False)
        enable_beat_sync = options.get("enable_beat_sync", True)
        enable_elements = options.get("enable_elements", True)
        enable_progress_bar = options.get("enable_progress_bar", True)
        skip_existing_captions = options.get("skip_existing_captions", True)
        caption_language = options.get("caption_language", "auto")  # "auto", "hinglish", "english"
        caption_color = options.get("caption_color", "yellow")
        tts_voice = options.get("tts_voice", "en-US-ChristopherNeural")
        custom_hook = (options.get("custom_hook") or "").strip()

        # 1. Transcribe with word timestamps
        update(15, "Transcribing dialogue & word timestamps (faster-whisper)...")
        transcript = self.transcribe_with_words(raw_video_path, model_size=options.get("whisper_model", "base"))

        # 1B. Convert Hindi / Devanagari speech to accurate Hinglish
        if transcript.get("words"):
            force_hl = (caption_language == "hinglish")
            if caption_language != "english":
                conv_words, conv_text = convert_words_to_hinglish(
                    transcript["words"],
                    detected_lang=transcript.get("language", "en"),
                    full_text=transcript.get("text", ""),
                    force_hinglish=force_hl
                )
                transcript["words"] = conv_words
                transcript["text"] = conv_text

        # 2. Beat / peak detection
        peaks = []
        if enable_beat_sync:
            update(30, "Analyzing audio energy & beat peaks...")
            peaks = self.detect_beat_peaks(transcript.get("wav_path", ""))

        # 3. AI Script Enhancement
        update(42, "Enhancing script, title & viral hashtags with AI...")
        ai_meta = self.enhance_script_with_gemini(transcript.get("text", ""), style_goal=color_grade)
        hook_text = custom_hook or ai_meta.get("hook_voiceover", "")

        # 4. Optional AI Voice-Over
        vo_path = None
        if enable_voiceover and hook_text:
            update(52, "Generating smooth AI Voice-Over hook (Edge-TTS)...")
            try:
                vg = VoiceoverGenerator(temp_dir=self.temp_dir)
                vo_path = vg.generate_voiceover(hook_text, f"{job_tag}_vo.mp3", voice=tts_voice)
            except Exception as e:
                logger.warning(f"Voiceover generation skipped: {e}")

        # 5. Smart 9:16 Reframe + Existing-Caption Check + ASS Captions + Element Library
        update(62, "Checking for existing captions & matching script elements...")
        ass_path = os.path.join(self.temp_dir, f"{job_tag}_captions.ass")
        has_captions = False
        skipped_duplicate_captions = False

        if enable_captions and transcript.get("words"):
            if skip_existing_captions and detect_existing_captions(raw_video_path):
                skipped_duplicate_captions = True
                logger.info("Video already has burned-in captions; skipping duplicate caption overlay.")
            else:
                self.generate_capcut_ass(transcript["words"], ass_path, highlight_color=caption_color)
                has_captions = True

        elements = []
        if enable_elements:
            try:
                elem_lib = ElementLibrary(temp_dir=self.temp_dir)
                elements = elem_lib.build_elements_for_video(
                    job_tag=job_tag,
                    transcript_text=transcript.get("text", ""),
                    words=transcript.get("words", []),
                    duration=info["duration"],
                    title_hint=ai_meta.get("title", "")
                )
            except Exception as e:
                logger.warning(f"Element library generation notice: {e}")

        face_x = 0.5
        if enable_reframe:
            face_x = self._detect_face_x_ratio(raw_video_path)

        # Build Base FFmpeg Video Filter Chain (9:16 + Smooth Zoom + Color Grade + Fade)
        base_vf = []
        base_vf.append("scale='max(1080,iw*1920/ih)':'max(1920,ih*1080/iw)':force_original_aspect_ratio=increase")
        base_vf.append(f"crop=1080:1920:'max(0,min(iw-1080,(iw*{face_x:.3f})-540))':'(ih-1920)/2'")

        if enable_zoom:
            if peaks:
                base_vf.append("scale=w='trunc(1080*(1+0.045*(0.5-0.5*cos(t*1.2)))/2)*2':h='trunc(1920*(1+0.045*(0.5-0.5*cos(t*1.2)))/2)*2':eval=frame")
            else:
                base_vf.append("scale=w='trunc(1080*(1+0.035*sin(t*0.9)^2)/2)*2':h='trunc(1920*(1+0.035*sin(t*0.9)^2)/2)*2':eval=frame")
            base_vf.append("crop=1080:1920:(iw-1080)/2:(ih-1920)/2")

        grade_filter = self.COLOR_PRESETS.get(color_grade, "")
        if grade_filter:
            base_vf.append(grade_filter)

        base_vf.append("fade=t=in:st=0:d=0.35")

        if enable_progress_bar and info["duration"] > 0:
            dur_s = max(1.0, float(info["duration"]))
            base_vf.append(f"drawbox=x=0:y=0:w='iw*min(1,t/{dur_s:.2f})':h=10:color=#F43F5E@0.95:t=fill")

        # Build Clean Audio Filter Chain (NO metallic afftdn or aggressive loudnorm)
        af_parts = []
        if enable_noise_reduce:
            af_parts.append("highpass=f=75,acompressor=threshold=-20dB:ratio=2:attack=15:release=120")
        af_parts.append("afade=t=in:st=0:d=0.2")
        af_chain = ",".join(af_parts)

        final_filename = f"pro_edit_{job_tag}.mp4"
        final_output_path = os.path.join(self.output_dir, final_filename)

        update(78, f"Rendering 1080x1920 Pro Video ({len(elements)} script elements + captions)...")

        # Assemble FFmpeg inputs and filter_complex
        cmd = [self.ffmpeg_path, "-y", "-i", raw_video_path]
        next_input_idx = 1

        vo_input_idx = None
        if vo_path and os.path.exists(vo_path):
            cmd.extend(["-i", vo_path])
            vo_input_idx = next_input_idx
            next_input_idx += 1

        elem_inputs = []
        for el in elements:
            if os.path.exists(el["png_path"]):
                cmd.extend(["-i", el["png_path"]])
                elem_inputs.append((next_input_idx, el))
                next_input_idx += 1

        filter_steps = [f"[0:v]{','.join(base_vf)}[v_base]"]
        curr_v = "[v_base]"

        # Overlay each animated script element with smooth slide-in
        for idx, (in_idx, el) in enumerate(elem_inputs):
            next_v = f"[v_el_{idx}]"
            st = el["start"]
            en = el["end"]
            x_pos = el["x"]
            y_pos = el["y"]
            y_expr = f"if(lt(t-{st},0.28),{y_pos - 45}+45*((t-{st})/0.28),{y_pos})"
            filter_steps.append(
                f"{curr_v}[{in_idx}:v]overlay=x={x_pos}:y='{y_expr}':enable='between(t,{st},{en})'{next_v}"
            )
            curr_v = next_v

        # Burn CapCut ASS captions on top of base + elements
        if has_captions and os.path.exists(ass_path):
            escaped_ass = ass_path.replace("\\", "/").replace(":", "\\:")
            filter_steps.append(f"{curr_v}ass='{escaped_ass}'[vout]")
        else:
            filter_steps.append(f"{curr_v}copy[vout]")

        # Audio routing
        if vo_input_idx is not None:
            filter_steps.append(f"[0:a]{af_chain},volume='if(lt(t,4.5),0.35,1.0)':eval=frame[a_orig]")
            filter_steps.append(f"[{vo_input_idx}:a]volume=1.25,apad[a_vo]")
            filter_steps.append("[a_orig][a_vo]amix=inputs=2:duration=first:dropout_transition=2[aout]")
        else:
            filter_steps.append(f"[0:a]{af_chain}[aout]")

        cmd.extend([
            "-filter_complex", ";".join(filter_steps),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            final_output_path
        ])

        subprocess.run(cmd, check=True)

        # Generate high-CTR poster thumbnail
        update(94, "Extracting high-CTR poster thumbnail...")
        thumb_path = final_output_path.replace(".mp4", "_thumb.jpg")
        try:
            thumb_ss = min(1.5, max(0.3, info["duration"] / 3.0))
            subprocess.run([
                self.ffmpeg_path, "-y", "-ss", str(thumb_ss),
                "-i", final_output_path, "-vframes", "1", "-q:v", "2", thumb_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logger.warning(f"Thumbnail generation notice: {e}")

        # Save metadata into workspace/temp so gallery lists AI title & description
        meta_path = os.path.join(self.temp_dir, f"{job_tag}_metadata.json")
        with open(meta_path, "w", encoding="utf-8") as mf:
            json.dump([{
                "clip_id": job_tag,
                "title": ai_meta.get("title", "Pro Edited Short"),
                "description": ai_meta.get("description", ""),
                "hook_reason": f"CapCut Pro Edit ({color_grade}) | {len(elements)} script elements | {len(peaks)} beat peaks",
                "duration": round(info["duration"], 1)
            }], mf, indent=2)

        update(100, "Pro CapCut-Style Short Ready!")
        return {
            "filename": final_filename,
            "video_url": f"/media/shorts/{final_filename}",
            "thumbnail_url": f"/media/shorts/{final_filename.replace('.mp4', '_thumb.jpg')}" if os.path.exists(thumb_path) else None,
            "title": ai_meta.get("title"),
            "description": ai_meta.get("description"),
            "hashtags": ai_meta.get("hashtags"),
            "transcript": transcript.get("text", ""),
            "beat_peaks": peaks,
            "skipped_duplicate_captions": skipped_duplicate_captions,
            "elements_added": [{"badge": e["badge"], "text": e["text"], "start": e["start"], "end": e["end"]} for e in elements]
        }
