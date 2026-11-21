import sys

def verify():
    modules = [
        ("yt_dlp", "yt-dlp"),
        ("faster_whisper", "faster-whisper"),
        ("google.genai", "google-genai"),
        ("edge_tts", "edge-tts"),
        ("mediapipe", "mediapipe"),
        ("cv2", "opencv-python"),
        ("moviepy.editor", "moviepy==1.0.3")
    ]
    
    print(f"Testing imports on Python {sys.version}...\n")
    all_passed = True
    
    for mod_name, pkg_name in modules:
        try:
            __import__(mod_name)
            print(f"[OK] {pkg_name} ({mod_name}) imported successfully.")
        except Exception as e:
            print(f"[FAIL] {pkg_name} ({mod_name}) failed: {e}")
            all_passed = False
            
    if all_passed:
        print("\nAll dependencies verified successfully!")
        sys.exit(0)
    else:
        print("\nSome dependencies failed to import.")
        sys.exit(1)

if __name__ == "__main__":
    verify()
