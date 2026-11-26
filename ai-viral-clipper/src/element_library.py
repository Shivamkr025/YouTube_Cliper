"""
Module 5B: Script-Aware Visual Element Library (CapCut-Style Overlays)
Analyzes video transcript with Gemini AI to select & render timed graphic elements:
- Top Hook Banner (0.4s - 3.5s)
- Script-Matched Keyword / Stat / Tip Callout Cards at exact spoken timestamps
- Animated Like & Subscribe CTA Card near the end
- Custom user elements from workspace/elements/ (if present)
"""

import os
import json
import logging
import requests
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)


def _load_font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """Loads a crisp sans-serif font across Windows and Linux Docker."""
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


class ElementLibrary:
    ACCENT_COLORS = {
        "amber": (245, 158, 11, 255),
        "cyan": (6, 182, 212, 255),
        "rose": (244, 63, 94, 255),
        "emerald": (16, 185, 129, 255),
        "violet": (139, 92, 246, 255),
    }

    def __init__(self, temp_dir: str = "workspace/temp", elements_dir: str = "workspace/elements"):
        self.temp_dir = os.path.abspath(temp_dir)
        self.elements_dir = os.path.abspath(elements_dir)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.elements_dir, exist_ok=True)

    def plan_elements_from_script(
        self,
        transcript_text: str,
        words: List[Dict[str, Any]],
        duration: float,
        title_hint: str = ""
    ) -> List[Dict[str, Any]]:
        """
        Uses Gemini AI to match visual elements to exact moments in the script.
        Falls back to smart keyword extraction if Gemini is unavailable.
        """
        duration = max(4.0, float(duration))
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GEMINI_API_KEY_BACKUP", "").strip()

        # Build compact timestamped script for Gemini
        timed_lines = []
        if words:
            step = max(1, len(words) // 10)
            for idx in range(0, len(words), step):
                chunk = " ".join(w["word"] for w in words[idx:idx + step])
                t = round(words[idx]["start"], 1)
                timed_lines.append(f"[{t}s] {chunk}")
        timed_script = "\n".join(timed_lines) or transcript_text[:1500]

        if api_key and transcript_text.strip():
            prompt = (
                f"You are a CapCut motion graphics director editing a {duration:.1f}s vertical Short.\n"
                f"Timestamped script:\n{timed_script}\n\n"
                f"Design 3 to 5 crisp visual overlay elements that match the spoken words at exact timestamps.\n"
                f"Return ONLY a JSON array of objects, each with:\n"
                f"- 'kind': 'hook_banner' (at start 0.4s-3.5s), 'callout' (middle key points), or 'cta' (near end)\n"
                f"- 'badge': short 1-2 word uppercase label (e.g. 'HOOK', 'KEY POINT', 'PRO TIP', 'WARNING', 'FACT', 'SUBSCRIBE')\n"
                f"- 'text': short punchy 2-5 word text matching what is being said (e.g. '3X FASTER RESULTS', 'STOP MAKING THIS MISTAKE')\n"
                f"- 'color': one of 'amber', 'cyan', 'rose', 'emerald', 'violet'\n"
                f"- 'start': start time in seconds (float, >= 0.3, < {duration - 1.5:.1f})\n"
                f"- 'end': end time in seconds (float, start + 2.5 to 3.5, <= {duration - 0.3:.1f})\n"
                f"Keep text concise, uppercase, and strictly relevant to the script."
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
                        items = json.loads(raw)
                        if isinstance(items, list) and len(items) > 0:
                            cleaned = []
                            for it in items[:6]:
                                st = max(0.2, float(it.get("start", 0.5)))
                                en = min(duration - 0.2, float(it.get("end", st + 2.8)))
                                if en > st + 0.6:
                                    cleaned.append({
                                        "kind": it.get("kind", "callout"),
                                        "badge": str(it.get("badge", "KEY POINT"))[:16].upper(),
                                        "text": str(it.get("text", "WATCH THIS"))[:38].upper(),
                                        "color": it.get("color", "amber") if it.get("color") in self.ACCENT_COLORS else "amber",
                                        "start": round(st, 2),
                                        "end": round(en, 2)
                                    })
                            if cleaned:
                                return cleaned
                except Exception as e:
                    logger.warning(f"Gemini element planning failed on {model_name}: {e}")

        # Smart deterministic fallback matched to transcript words
        elements = []
        hook_label = (title_hint or "WATCH TILL THE END").replace("#Shorts", "").strip()[:32].upper()
        elements.append({
            "kind": "hook_banner",
            "badge": "FEATURED",
            "text": hook_label or "KEY INSIGHT",
            "color": "rose",
            "start": 0.4,
            "end": min(3.4, duration - 0.5)
        })

        if duration > 7.0 and words:
            mid_idx = len(words) // 2
            mid_t = max(3.6, min(duration - 4.0, float(words[mid_idx]["start"])))
            snippet = " ".join(w["word"] for w in words[mid_idx:mid_idx + 4]).strip().upper()[:32]
            elements.append({
                "kind": "callout",
                "badge": "KEY POINT",
                "text": snippet or "IMPORTANT MOMENT",
                "color": "cyan",
                "start": round(mid_t, 2),
                "end": round(min(duration - 1.5, mid_t + 3.0), 2)
            })

        if duration > 5.0:
            elements.append({
                "kind": "cta",
                "badge": "FOLLOW",
                "text": "LIKE & SUBSCRIBE FOR MORE",
                "color": "emerald",
                "start": round(max(3.5, duration - 3.2), 2),
                "end": round(duration - 0.3, 2)
            })

        return elements

    def render_element_card_png(self, elem: Dict[str, Any], out_path: str) -> str:
        """
        Renders a sleek glassmorphic CapCut-style overlay card as a transparent PNG (920x130).
        """
        width, height = 920, 128
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        accent = self.ACCENT_COLORS.get(elem.get("color", "amber"), self.ACCENT_COLORS["amber"])
        badge_text = elem.get("badge", "TIP").upper()
        body_text = elem.get("text", "").upper()

        # Glassmorphic dark rounded rectangle with glowing border
        draw.rounded_rectangle(
            [(4, 4), (width - 5, height - 5)],
            radius=28,
            fill=(15, 23, 42, 230),
            outline=accent,
            width=4
        )

        font_badge = _load_font(26, bold=True)
        font_body = _load_font(34, bold=True)

        # Measure badge pill
        b_bbox = draw.textbbox((0, 0), badge_text, font=font_badge)
        b_w = (b_bbox[2] - b_bbox[0]) + 36
        b_h = 54
        b_x = 26
        b_y = (height - b_h) // 2

        draw.rounded_rectangle(
            [(b_x, b_y), (b_x + b_w, b_y + b_h)],
            radius=16,
            fill=accent
        )
        # Dark text inside bright badge pill
        b_txt_w = b_bbox[2] - b_bbox[0]
        b_txt_h = b_bbox[3] - b_bbox[1]
        draw.text(
            (b_x + (b_w - b_txt_w) // 2, b_y + (b_h - b_txt_h) // 2 - 4),
            badge_text,
            font=font_badge,
            fill=(10, 15, 25, 255)
        )

        # Main callout text on the right of badge
        text_x = b_x + b_w + 24
        max_text_w = width - text_x - 24
        # Shrink font if text is slightly wide
        body_size = 34
        while body_size > 22:
            font_body = _load_font(body_size, bold=True)
            t_bbox = draw.textbbox((0, 0), body_text, font=font_body)
            if (t_bbox[2] - t_bbox[0]) <= max_text_w:
                break
            body_size -= 2

        t_bbox = draw.textbbox((0, 0), body_text, font=font_body)
        t_h = t_bbox[3] - t_bbox[1]
        draw.text(
            (text_x, (height - t_h) // 2 - 5),
            body_text,
            font=font_body,
            fill=(255, 255, 255, 255)
        )

        img.save(out_path, "PNG")
        return out_path

    def build_elements_for_video(
        self,
        job_tag: str,
        transcript_text: str,
        words: List[Dict[str, Any]],
        duration: float,
        title_hint: str = ""
    ) -> List[Dict[str, Any]]:
        """Plans script-matched elements and renders their PNG assets."""
        planned = self.plan_elements_from_script(transcript_text, words, duration, title_hint=title_hint)
        rendered = []
        for idx, elem in enumerate(planned):
            png_path = os.path.join(self.temp_dir, f"{job_tag}_elem_{idx}.png")
            self.render_element_card_png(elem, png_path)
            # Position: hook_banner & callouts near top (y=150), cta slightly lower-upper (y=290)
            y_pos = 150 if elem.get("kind") in ("hook_banner", "callout") else 290
            rendered.append({
                **elem,
                "png_path": png_path,
                "x": 80,  # (1080 - 920) / 2 = 80
                "y": y_pos
            })
        return rendered
