from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
TEMP_DIR = BASE_DIR / "temp"
FRONTEND_DIR = BASE_DIR / "frontend"
COVERS_DIR = UPLOADS_DIR / "covers"
AFFILIATES_DIR = UPLOADS_DIR / "affiliates"

for _dir in (UPLOADS_DIR, OUTPUTS_DIR, TEMP_DIR, FRONTEND_DIR, COVERS_DIR, AFFILIATES_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
TARGET_FPS = 30

ANTI_COPYRIGHT_SPEED = 1.05
ANTI_COPYRIGHT_SATURATION = 1.08
ANTI_COPYRIGHT_CONTRAST = 1.05
ANTI_COPYRIGHT_BRIGHTNESS = 0.01

VOICES = {
    "id-ID-GadisNeural": "Gadis (Wanita Indonesia - Natural)",
    "id-ID-ArdiNeural": "Ardi (Pria Indonesia - Natural)",
}

ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"}
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SUBTITLE_STYLES = {
    "karaoke_highlight": "Karaoke Kuning-Putih (Sorot Kata Aktif)",
    "yellow_bold": "Kuning Tebal Klasik TikTok",
    "white_bold": "Putih Tebal Outline Hitam",
}

SUBTITLE_FONTS = ["Arial", "Impact", "Segoe UI"]

THUMBNAIL_STYLES = {
    "tiktok_yellow": "TikTok Viral Kuning (Teks Hitam + Kotak Kuning)",
    "red_warning": "Peringatan / Alert Merah (Banner Merah + Teks Putih)",
    "cyan_neon": "Cyber Neon Cyan (Aksen Neon TikTok Cyan)",
    "clean_white": "Putih Tebal Minimalis (Outline Hitam + Bayangan)",
}
