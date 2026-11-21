"""
Module 2A: AI Voiceover Generator
Uses edge-tts to generate natural, high-retention AI voiceovers with customizable voices and pacing.
"""

import os
import asyncio
import logging
from typing import Optional, Dict, Any
import edge_tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class VoiceoverGenerator:
    DEFAULT_VOICES = {
        "en_male_deep": "en-US-ChristopherNeural",
        "en_male_energetic": "en-US-GuyNeural",
        "en_female": "en-US-JennyNeural",
        "hi_male": "hi-IN-MadhurNeural",
        "hi_female": "hi-IN-SwaraNeural"
    }

    def __init__(self, temp_dir: str = "workspace/temp"):
        self.temp_dir = os.path.abspath(temp_dir)
        os.makedirs(self.temp_dir, exist_ok=True)

    async def _generate_audio_async(self, text: str, output_path: str, voice: str, rate: str, pitch: str):
        communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch)
        await communicate.save(output_path)

    def generate_voiceover(
        self,
        text: str,
        output_filename: str,
        voice: Optional[str] = None,
        rate: str = "+5%",
        pitch: str = "+0Hz"
    ) -> str:
        """
        Generates MP3 voiceover for the given text.
        Args:
            text: Script to speak.
            output_filename: Name of the output audio file (e.g. 'intro_clip_1.mp3').
            voice: Voice name or preset key.
            rate: Speed adjustment (e.g. '+5%' for energetic shorts pace).
            pitch: Pitch adjustment.
        Returns:
            Absolute path to the generated voiceover file.
        """
        if not text or not text.strip():
            logger.warning("Empty text passed for voiceover generation.")
            return ""

        selected_voice = self.DEFAULT_VOICES.get(voice, voice or self.DEFAULT_VOICES["en_male_deep"])
        output_path = os.path.join(self.temp_dir, output_filename)

        logger.info(f"Generating AI voiceover using voice '{selected_voice}' for: '{text[:50]}...'")
        
        try:
            asyncio.run(self._generate_audio_async(text, output_path, selected_voice, rate, pitch))
            logger.info(f"Voiceover successfully generated at: {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Failed to generate voiceover with edge-tts: {e}")
            raise e

if __name__ == "__main__":
    vg = VoiceoverGenerator()
    test_file = vg.generate_voiceover("Wait till you see what happens next in this insane challenge!", "test_intro.mp3")
    print("Voiceover created at:", test_file)
