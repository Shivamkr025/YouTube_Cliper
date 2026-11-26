"""
Caption Utilities:
1. Burned-in Caption Detector (OpenCV): Detects if a video/clip already has hardcoded subtitles
   so the AI agent avoids adding duplicate overlapping captions.
2. Hinglish AI Converter (Gemini + Phonetic Fallback): Converts Hindi/Devanagari or misheard
   Hindi-audio Whisper transcripts into crisp, natural Hinglish (Romanized Hindi) while
   preserving exact word-level timestamps.
"""

import os
import re
import json
import logging
import requests
from typing import List, Dict, Any, Optional, Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Basic Devanagari-to-Hinglish phonetic map as offline fallback
_DEV_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "अं": "an", "अः": "ah", "ऋ": "ri"
}
_DEV_MATRAS = {
    "ा": "a", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ं": "n", "ँ": "n", "ः": "h", "्": ""
}
_DEV_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "ng",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "ny",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh",
    "ष": "sh", "स": "s", "ह": "h", "क़": "q", "ख़": "kh",
    "ग़": "g", "ज़": "z", "ड़": "d", "ढ़": "dh", "फ़": "f"
}


def has_devanagari(text: str) -> bool:
    return bool(re.search(r"[\u0900-\u097F]", text or ""))


def _phonetic_devanagari_to_hinglish(text: str) -> str:
    """Offline fallback transliterator if Gemini API is unavailable."""
    out = []
    chars = list(text)
    i = 0
    while i < len(chars):
        ch = chars[i]
        if ch in _DEV_VOWELS:
            out.append(_DEV_VOWELS[ch])
        elif ch in _DEV_CONS:
            out.append(_DEV_CONS[ch])
            nxt = chars[i + 1] if i + 1 < len(chars) else ""
            if nxt not in _DEV_MATRAS and nxt != "्" and nxt not in (" ", "", ",", ".", "!", "?"):
                out.append("a")
        elif ch in _DEV_MATRAS:
            out.append(_DEV_MATRAS[ch])
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def detect_existing_captions(
    video_path: str,
    start_time: float = 0.0,
    end_time: Optional[float] = None,
    sample_count: int = 8
) -> bool:
    """
    Detects whether a video clip already has burned-in subtitles/captions.
    Samples frames in the lower-middle caption band (55%-88% height) and checks
    for dynamic, high-contrast horizontal text-line structures across frames.
    """
    if not video_path or not os.path.exists(video_path):
        return False

    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return False

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps > 0 and total_frames > 0 else 10.0

        t0 = max(0.2, float(start_time))
        t1 = min(duration - 0.2, float(end_time)) if end_time else max(t0 + 0.5, duration - 0.2)
        if t1 <= t0:
            cap.release()
            return False

        sample_times = np.linspace(t0, t1, num=sample_count)
        text_band_masks = []
        frames_with_text_lines = 0

        for t in sample_times:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            h, w = frame.shape[:2]
            # Subtitle zone: y from 55% to 88%, x from 12% to 88%
            roi = frame[int(h * 0.55):int(h * 0.88), int(w * 0.12):int(w * 0.88)]
            if roi.size == 0:
                continue

            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

            # High-contrast bright white OR bright yellow/cyan caption pixels
            bright_white = (gray > 215) & (hsv[:, :, 1] < 60)
            bright_color = (hsv[:, :, 2] > 200) & (hsv[:, :, 1] > 120)
            mask = (bright_white | bright_color).astype(np.uint8) * 255

            # Require sharp edges nearby (captions have crisp outlines/edges, unlike smooth sky/walls)
            edges = cv2.Canny(gray, 120, 240)
            edges_dilated = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
            crisp_text = cv2.bitwise_and(mask, edges_dilated)

            # Connect characters horizontally into word/line blobs
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(8, int(roi.shape[1] * 0.025)), 3))
            connected = cv2.dilate(crisp_text, kernel, iterations=1)

            contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            roi_h, roi_w = roi.shape[:2]
            valid_lines = 0
            for cnt in contours:
                x, y, cw, ch = cv2.boundingRect(cnt)
                # Text line heuristic: reasonable height (3%..26% of ROI), wide enough
                if (roi_h * 0.03) <= ch <= (roi_h * 0.28) and cw >= (ch * 1.8) and cw <= (roi_w * 0.95):
                    valid_lines += 1

            if valid_lines >= 1:
                frames_with_text_lines += 1
                text_band_masks.append(cv2.resize(crisp_text, (160, 64)))

        cap.release()

        if frames_with_text_lines < 3 or len(text_band_masks) < 3:
            return False

        # Verify captions actually change over time (so static watermarks/logos don't trigger)
        diffs = []
        for i in range(1, len(text_band_masks)):
            diff_ratio = float(np.mean(cv2.absdiff(text_band_masks[i], text_band_masks[i - 1]) > 0))
            diffs.append(diff_ratio)

        avg_change = float(np.mean(diffs)) if diffs else 0.0
        has_caps = frames_with_text_lines >= 3 and avg_change > 0.0015
        logger.info(
            f"Existing-caption check: text_frames={frames_with_text_lines}/{sample_count}, "
            f"avg_change={avg_change:.4f} -> detected={has_caps}"
        )
        return has_caps
    except Exception as e:
        logger.warning(f"Existing caption detection skipped: {e}")
        return False


def convert_words_to_hinglish(
    words: List[Dict[str, Any]],
    detected_lang: str = "en",
    full_text: str = "",
    force_hinglish: bool = False
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Converts Hindi/Devanagari or misheard Hindi transcripts into natural Hinglish
    (Romanized Hindi using English letters only) while preserving word timestamps.
    """
    if not words:
        return words, full_text

    hindi_langs = {"hi", "ur", "pa", "mr", "bn", "gu", "ne"}
    needs_hinglish = force_hinglish or (detected_lang in hindi_langs) or has_devanagari(full_text)
    if not needs_hinglish:
        return words, full_text

    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY_BACKUP", "").strip()
    converted_words = [dict(w) for w in words]

    if api_key:
        # Process in chunks of up to 100 words so JSON stays exact
        chunk_size = 100
        for start_i in range(0, len(converted_words), chunk_size):
            batch = converted_words[start_i:start_i + chunk_size]
            raw_list = [w["word"] for w in batch]
            prompt = (
                f"The audio in this video is spoken in Hindi/Hinglish (Whisper detected '{detected_lang}').\n"
                f"Here is the list of {len(raw_list)} word tokens:\n{json.dumps(raw_list, ensure_ascii=False)}\n\n"
                f"Task: Convert EVERY token into clean, natural HINGLISH (Romanized Hindi written in English letters ONLY, "
                f"NO Devanagari/Hindi script, NO Urdu script). Fix obvious speech-to-text misspellings using context.\n"
                f"CRITICAL RULE: Return ONLY a valid JSON array of EXACTLY {len(raw_list)} strings (1-to-1 aligned with the input list)."
            )
            success = False
            for model_name in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
                    resp = requests.post(
                        url,
                        headers={"Content-Type": "application/json"},
                        json={"contents": [{"parts": [{"text": prompt}]}]},
                        timeout=15
                    )
                    if resp.status_code == 200:
                        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
                        if "```json" in raw:
                            raw = raw.split("```json")[1].split("```")[0].strip()
                        elif "```" in raw:
                            raw = raw.split("```")[1].split("```")[0].strip()
                        parsed = json.loads(raw)
                        if isinstance(parsed, list) and len(parsed) == len(batch):
                            for j, new_w in enumerate(parsed):
                                clean_tok = str(new_w).strip()
                                if clean_tok:
                                    converted_words[start_i + j]["word"] = clean_tok
                            success = True
                            break
                except Exception as e:
                    logger.warning(f"Gemini Hinglish conversion attempt failed on {model_name}: {e}")
                    continue

            if not success:
                for j in range(len(batch)):
                    if has_devanagari(converted_words[start_i + j]["word"]):
                        converted_words[start_i + j]["word"] = _phonetic_devanagari_to_hinglish(
                            converted_words[start_i + j]["word"]
                        )
    else:
        for w in converted_words:
            if has_devanagari(w["word"]):
                w["word"] = _phonetic_devanagari_to_hinglish(w["word"])

    new_full_text = " ".join(w["word"] for w in converted_words).strip()
    return converted_words, new_full_text
