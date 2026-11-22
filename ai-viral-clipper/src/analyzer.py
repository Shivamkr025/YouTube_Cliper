"""
Module 1B: Transcript & Viral Clip Analyzer
Uses faster-whisper for word-level timestamps and Google Gemini API for viral moment detection.
"""

import os
import json
import logging
from typing import Dict, List, Any, Optional
from dotenv import load_dotenv

# Compatibility patch for PyAV 14+ / 19+ with faster-whisper
import av
_orig_av_open = av.open
def _safe_av_open(*args, **kwargs):
    kwargs.pop("metadata_errors", None)
    return _orig_av_open(*args, **kwargs)
av.open = _safe_av_open

from faster_whisper import WhisperModel
import requests

try:
    from google import genai
    from google.genai import types
    HAS_GENAI_SDK = True
except Exception:
    HAS_GENAI_SDK = False

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class AudioTranscriber:
    def __init__(self, model_size: str = "base", temp_dir: str = "workspace/temp"):
        self.temp_dir = os.path.abspath(temp_dir)
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Auto-detect device
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"
            
        compute_type = "float16" if device == "cuda" else "int8"
        logger.info(f"Loading faster-whisper model '{model_size}' on device: {device} ({compute_type})...")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: str, video_id: str) -> Dict[str, Any]:
        """
        Transcribes the audio file and extracts word-level timestamps.
        Saves structured transcript to temp directory.
        """
        transcript_file = os.path.join(self.temp_dir, f"{video_id}_transcript.json")
        if os.path.exists(transcript_file):
            logger.info(f"Existing transcript found at: {transcript_file}")
            with open(transcript_file, "r", encoding="utf-8") as f:
                return json.load(f)

        logger.info(f"Starting audio transcription for: {audio_path}")
        
        has_onnx = False
        try:
            import onnxruntime
            has_onnx = True
        except Exception:
            has_onnx = False

        transcribe_kwargs = {
            "beam_size": 2,
            "word_timestamps": True,
            "vad_filter": has_onnx,
        }
        if has_onnx:
            transcribe_kwargs["vad_parameters"] = dict(min_silence_duration_ms=500)

        segments, info = self.model.transcribe(audio_path, **transcribe_kwargs)
        logger.info(f"Detected language: '{info.language}' (probability {info.language_probability:.2f})")
        logger.info(f"Audio total duration: {info.duration:.1f} seconds. Decoding speech segments...")

        words_data = []
        full_text = []
        last_logged = 0.0

        for segment in segments:
            full_text.append(segment.text.strip())
            if segment.end - last_logged >= 60.0 or last_logged == 0.0:
                logger.info(f"Transcription progress: {int(segment.end)}s / {int(info.duration)}s ({int(segment.end / max(1, info.duration) * 100)}%)")
                last_logged = segment.end

            if segment.words:
                for word in segment.words:
                    words_data.append({
                        "word": word.word.strip(),
                        "start": round(word.start, 2),
                        "end": round(word.end, 2),
                        "probability": round(word.probability, 2)
                    })

        transcript_result = {
            "video_id": video_id,
            "language": info.language,
            "duration": round(info.duration, 2),
            "full_text": " ".join(full_text),
            "words": words_data
        }

        with open(transcript_file, "w", encoding="utf-8") as f:
            json.dump(transcript_result, f, indent=2, ensure_ascii=False)

        logger.info(f"Word-level transcript saved ({len(words_data)} words) to: {transcript_file}")
        return transcript_result


class ViralMomentsAnalyzer:
    def __init__(self, temp_dir: str = "workspace/temp"):
        self.temp_dir = os.path.abspath(temp_dir)
        load_dotenv(override=True)
        self.api_keys = []
        for env_var in ["GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"]:
            val = os.getenv(env_var, "").strip()
            if val:
                for k in val.split(","):
                    if k.strip() and k.strip() not in self.api_keys:
                        self.api_keys.append(k.strip())
        
        if not self.api_keys:
            raise ValueError("No GEMINI_API_KEY found in environment or .env file.")
        
        logger.info(f"ViralMomentsAnalyzer loaded with {len(self.api_keys)} Gemini API key(s) for auto-failover.")

    def analyze_viral_moments(self, transcript_data: Dict[str, Any], max_clips: int = 10) -> List[Dict[str, Any]]:
        """
        Analyzes the transcript with Gemini to identify high-retention viral moments (30-60s),
        hooks, titles, original voiceover scripts, and tags.
        """
        video_id = transcript_data.get("video_id", "clip")
        output_file = os.path.join(self.temp_dir, f"{video_id}_viral_clips.json")

        if os.path.exists(output_file):
            try:
                with open(output_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                    if isinstance(cached, list) and len(cached) >= max_clips:
                        logger.info(f"Existing viral clips ({len(cached)} clips) found. Using top {max_clips} clips.")
                        return cached[:max_clips]
                    else:
                        logger.info(f"Cached clips ({len(cached) if isinstance(cached, list) else 0}) < requested ({max_clips}). Extracting {max_clips} fresh viral clips...")
            except Exception:
                pass

        full_text = transcript_data.get("full_text", "")
        duration = transcript_data.get("duration", 0)
        words = transcript_data.get("words", [])

        # Create compact time-stamped text for LLM context across the entire video
        compact_transcript = []
        for i in range(0, len(words), 30):
            chunk = words[i:i+30]
            if chunk:
                compact_transcript.append(f"[{chunk[0]['start']}s - {chunk[-1]['end']}s]: " + " ".join(w["word"] for w in chunk))
        transcript_sample = "\n".join(compact_transcript)

        prompt = f"""
You are a world-class YouTube Shorts & TikTok viral content strategist.
Analyze the following timestamped video transcript (Total Duration: {duration} seconds / {int(duration // 60)} minutes).
Identify exactly {max_clips} distinct, high-retention viral moments distributed across the entire video (beginning, middle challenges, major plot twists, and climax).

Each clip should ideally be between 25 and 60 seconds long with a strong emotional hook, shocking reveal, intense challenge, high financial stakes, or high-value insight.

For each of the {max_clips} clips, provide:
1. `clip_id`: Integer index (1, 2, ..., {max_clips})
2. `start_time`: Precise start time in seconds (float or int).
3. `end_time`: Precise end time in seconds (float or int, max 60s from start).
4. `viral_score`: Score from 80 to 100 based on hook potential.
5. `hook_reason`: Why this moment will stop people from scrolling in the first 3 seconds.
6. `title`: Catchy, click-worthy YouTube Short title (with emojis, under 60 chars).
7. `description`: High-converting description with CTA and relevant hashtags.
8. `tags`: List of 5-8 SEO tags (e.g. ["#Shorts", "#Viral", ...]).
9. `voiceover_intro`: A punchy 3-5 second introductory hook script to be spoken before or during the clip start (for monetization originality).

Video Transcript:
{transcript_sample}

Respond ONLY with a valid JSON array of {max_clips} objects adhering to the structure above. Do not include markdown code block quotes like ```json, just return the raw JSON array.
"""

        candidate_models = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
        raw_text = ""

        for key_idx, api_key in enumerate(self.api_keys):
            client = genai.Client(api_key=api_key) if HAS_GENAI_SDK else None
            logger.info(f"Using Gemini API Key #{key_idx + 1} ({api_key[:6]}...{api_key[-4:]})")
            
            for model_id in candidate_models:
                for attempt in range(2):
                    try:
                        logger.info(f"Querying Gemini model '{model_id}' (attempt {attempt+1})...")
                        if HAS_GENAI_SDK and client:
                            response = client.models.generate_content(
                                model=model_id,
                                contents=prompt
                            )
                            if response and response.text:
                                raw_text = response.text.strip()
                                break
                        else:
                            # Direct REST API fallback (Zero dependency on pydantic)
                            api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={api_key}"
                            resp = requests.post(
                                api_url,
                                headers={"Content-Type": "application/json"},
                                json={"contents": [{"parts": [{"text": prompt}]}]},
                                timeout=60
                            )
                            if resp.status_code == 200:
                                res_json = resp.json()
                                candidates = res_json.get("candidates", [])
                                if candidates and "content" in candidates[0]:
                                    parts = candidates[0]["content"].get("parts", [])
                                    if parts and "text" in parts[0]:
                                        raw_text = parts[0]["text"].strip()
                                        break
                            else:
                                logger.warning(f"Gemini REST error {resp.status_code}: {resp.text[:150]}")
                    except Exception as e:
                        logger.warning(f"Key #{key_idx+1} | Model '{model_id}' attempt {attempt+1} encountered: {e}")
                        import time
                        time.sleep(2)
                if raw_text:
                    logger.info(f"Successfully received response from '{model_id}' using Key #{key_idx + 1}.")
                    break
            if raw_text:
                break
            else:
                logger.warning(f"Key #{key_idx+1} exhausted. Checking next backup key...")

        # Clean JSON fences if present
        if "```json" in raw_text:
            raw_text = raw_text.split("```json", 1)[1].split("```", 1)[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```", 1)[1].split("```", 1)[0].strip()

        try:
            clips = json.loads(raw_text)
        except json.JSONDecodeError as err:
            logger.error(f"Failed to parse Gemini response as JSON: {err}\nResponse was:\n{raw_text}")
            clips = []

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(clips, f, indent=2, ensure_ascii=False)

        logger.info(f"Successfully extracted {len(clips)} viral clips. Saved to: {output_file}")
        return clips


if __name__ == "__main__":
    import sys
    print("Testing AudioTranscriber and ViralMomentsAnalyzer...")
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        v_id = "test_video"
        transcriber = AudioTranscriber(model_size="base")
        t_data = transcriber.transcribe(audio_file, v_id)
        analyzer = ViralMomentsAnalyzer()
        viral_clips = analyzer.analyze_viral_moments(t_data, max_clips=5)
        print(f"Extracted {len(viral_clips)} viral moments.")
