import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional, Tuple

import edge_tts
import yt_dlp

from backend.config import BASE_DIR, UPLOADS_DIR
from backend.models import SystemHealthResponse, VideoMetadata


def sanitize_filename(name: str, fallback: str = "video") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_-")
    return (cleaned[:64] if cleaned else fallback)


def parse_timestamp(value: Optional[str | float | int]) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, float(value))
    raw = str(value).strip()
    if not raw:
        return 0.0
    if re.fullmatch(r"\d+(\.\d+)?", raw):
        return max(0.0, float(raw))
    parts = raw.split(":")
    if len(parts) == 2:
        mins, secs = parts
        return max(0.0, float(mins) * 60.0 + float(secs))
    if len(parts) == 3:
        hrs, mins, secs = parts
        return max(0.0, float(hrs) * 3600.0 + float(mins) * 60.0 + float(secs))
    raise ValueError(f"Format waktu tidak valid: '{raw}'. Gunakan detik (mis. 45) atau MM:SS / HH:MM:SS.")


def format_duration_hhmmss(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = seconds % 60.0
    if hrs > 0:
        return f"{hrs:02d}:{mins:02d}:{secs:05.2f}"
    return f"{mins:02d}:{secs:05.2f}"


def check_system_health() -> SystemHealthResponse:
    ffmpeg_path = shutil.which("ffmpeg")
    ffprobe_path = shutil.which("ffprobe")
    ffmpeg_version = None
    if ffmpeg_path:
        try:
            proc = subprocess.run(
                [ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if proc.returncode == 0 and proc.stdout:
                ffmpeg_version = proc.stdout.splitlines()[0].strip()
        except Exception:
            ffmpeg_version = None

    yt_dlp_available = True
    try:
        _ = yt_dlp.version.__version__
    except Exception:
        yt_dlp_available = shutil.which("yt-dlp") is not None

    edge_ver = getattr(edge_tts, "__version__", "unknown")
    ok = bool(ffmpeg_path and ffprobe_path and ffmpeg_version)
    return SystemHealthResponse(
        status="ok" if ok else "degraded",
        ffmpeg_available=bool(ffmpeg_path and ffmpeg_version),
        ffprobe_available=bool(ffprobe_path),
        yt_dlp_available=yt_dlp_available,
        ffmpeg_version=ffmpeg_version,
        edge_tts_version=edge_ver,
    )


def _parse_fps(rate_str: str) -> float:
    if not rate_str or rate_str == "0/0":
        return 30.0
    if "/" in rate_str:
        num_s, den_s = rate_str.split("/", 1)
        den = float(den_s)
        if den > 0:
            return round(float(num_s) / den, 2)
    try:
        return round(float(rate_str), 2)
    except ValueError:
        return 30.0


def probe_video(file_path: Path, source_type: str = "upload", title: Optional[str] = None, url_prefix: str = "/uploads") -> VideoMetadata:
    if not file_path.exists():
        raise FileNotFoundError(f"File video tidak ditemukan: {file_path}")

    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(file_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe gagal membaca video: {proc.stderr.strip()}")

    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not video_stream:
        raise ValueError("File tidak memiliki stream video yang valid.")

    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    duration = 0.0
    for candidate in (fmt.get("duration"), video_stream.get("duration")):
        if candidate is not None:
            try:
                duration = float(candidate)
                if duration > 0:
                    break
            except (TypeError, ValueError):
                pass

    width = int(video_stream.get("width") or 0)
    height = int(video_stream.get("height") or 0)
    fps = _parse_fps(video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate") or "30/1")
    size_bytes = file_path.stat().st_size

    return VideoMetadata(
        filename=file_path.name,
        source_type="youtube" if source_type == "youtube" else "upload",
        title=title or file_path.stem,
        duration=round(duration, 2),
        width=width,
        height=height,
        fps=fps,
        has_audio=audio_stream is not None,
        size_bytes=size_bytes,
        url=f"{url_prefix.rstrip('/')}/{file_path.name}",
    )


def find_youtube_cookies_file() -> Optional[Path]:
    cookie_candidates = [
        UPLOADS_DIR / "cookies.txt",
        BASE_DIR / "cookies.txt",
        Path("/app/uploads/cookies.txt"),
        Path("/app/cookies.txt"),
    ]
    env_cookie = os.environ.get("YTDLP_COOKIES_PATH")
    if env_cookie:
        cookie_candidates.insert(0, Path(env_cookie))

    for p in cookie_candidates:
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def check_cookies_status() -> Tuple[Optional[Path], bool]:
    path = find_youtube_cookies_file()
    if not path or not path.exists():
        return None, False
    try:
        txt = path.read_text(encoding="utf-8", errors="ignore")
        has_login = any(k in txt for k in ["LOGIN_INFO", "SAPISID", "SSID", "__Secure-3PSID", "SID"])
        return path, has_login
    except Exception:
        return path, False


def download_youtube_video(
    url: str,
    max_height: int = 1080,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Tuple[Path, str]:
    timestamp = int(time.time())
    out_template = str(UPLOADS_DIR / f"yt_{timestamp}_%(id)s.%(ext)s")

    def hook(d: dict) -> None:
        if not progress_cb:
            return
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100.0) if total > 0 else 0.0
            speed = d.get("_speed_str") or ""
            progress_cb(min(95.0, pct), f"Mengunduh dari YouTube... {pct:.1f}% {speed}".strip())
        elif status == "finished":
            progress_cb(96.0, "Menggabungkan video dan audio (yt-dlp)...")

    ydl_opts = {
        "format": (
            f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/bestvideo+bestaudio/best"
        ),
        "outtmpl": out_template,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "source_address": "0.0.0.0",
        "cachedir": False,
        "progress_hooks": [hook],
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        },
    }

    def _attempt_dl(opts_to_use: dict) -> Tuple[Path, str]:
        with yt_dlp.YoutubeDL(opts_to_use) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                raise RuntimeError("yt-dlp gagal mengambil informasi video.")
            video_title = info.get("title") or "YouTube Video"
            prepared = Path(ydl.prepare_filename(info))
            mp4_candidate = prepared.with_suffix(".mp4")
            if mp4_candidate.exists():
                return mp4_candidate, video_title
            elif prepared.exists():
                return prepared, video_title
            else:
                matches = sorted(UPLOADS_DIR.glob(f"yt_{timestamp}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
                if not matches:
                    raise FileNotFoundError("File hasil unduhan yt-dlp tidak ditemukan.")
                return matches[0], video_title

    # Strategy 1: visionos client WITHOUT cookies (bypasses bot-walls and format blocks on VPS)
    opts_visionos = dict(ydl_opts)
    opts_visionos["extractor_args"] = {"youtube": {"player_client": ["visionos"]}}

    try:
        final_path, video_title = _attempt_dl(opts_visionos)
    except Exception as err_visionos:
        # Strategy 2: If visionos failed (e.g. member/age-restricted), try cookies if available
        cookies_file, has_login = check_cookies_status()
        if cookies_file:
            if progress_cb:
                progress_cb(5.0, "Mencoba dengan autentikasi cookies...")
            opts_authed = dict(ydl_opts)
            opts_authed["cookiefile"] = str(cookies_file.resolve())
            try:
                final_path, video_title = _attempt_dl(opts_authed)
            except Exception:
                raise err_visionos
        else:
            raise err_visionos

    if progress_cb:
        progress_cb(100.0, "Unduhan selesai.")
    return final_path, video_title
