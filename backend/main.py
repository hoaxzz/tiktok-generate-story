import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional

import aiofiles
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.config import (
    APP_PASSWORD,
    EXPECTED_AUTH_TOKEN,
    AFFILIATES_DIR,
    ALLOWED_IMAGE_EXTENSIONS,
    ALLOWED_VIDEO_EXTENSIONS,
    COVERS_DIR,
    FRONTEND_DIR,
    OUTPUTS_DIR,
    SUBTITLE_FONTS,
    SUBTITLE_STYLES,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    THUMBNAIL_STYLES,
    UPLOADS_DIR,
    VOICES,
)
from backend.models import (
    AuthStatusResponse,
    LoginRequest,
    LoginResponse,
    JobStatusResponse,
    RenderRequest,
    RenderedOutputItem,
    StorySplitPreviewRequest,
    StorySplitPreviewResponse,
    SystemHealthResponse,
    ThumbnailGenerateRequest,
    ThumbnailResponse,
    VideoMetadata,
    YoutubeDownloadRequest,
)
from backend.services.job_manager import job_manager, list_rendered_outputs
from backend.services.media_utils import check_system_health, check_cookies_status, find_youtube_cookies_file, probe_video, sanitize_filename
from backend.services.story_splitter import split_story_into_parts
from backend.services.thumbnail_generator import generate_thumbnail_image


@asynccontextmanager
async def lifespan(_app: FastAPI):
    health = check_system_health()
    if not health.ffmpeg_available:
        print("[WARNING] FFmpeg tidak terdeteksi di PATH! Pastikan FFmpeg sudah terinstal.")
    else:
        print(f"[OK] {health.ffmpeg_version}")
    yield


app = FastAPI(
    title="TikTok Story & Satisfying Clipper Studio",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def app_auth_middleware(request: Request, call_next):
    if not APP_PASSWORD:
        return await call_next(request)

    path = request.url.path
    # Public routes that can be loaded without auth
    if (
        path == "/"
        or path.startswith("/static/")
        or path == "/favicon.ico"
        or path.startswith("/api/auth/")
        or path == "/api/health"
    ):
        return await call_next(request)

    token = (
        request.headers.get("X-App-Auth")
        or request.cookies.get("app_auth_token")
        or request.query_params.get("auth")
    )
    if token != EXPECTED_AUTH_TOKEN:
        return JSONResponse(
            status_code=401,
            content={"detail": "Akses ditolak. Silakan masukkan kata sandi studio terlebih dahulu."},
        )

    return await call_next(request)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/api/auth/status", response_model=AuthStatusResponse)
async def api_auth_status(request: Request):
    if not APP_PASSWORD:
        return AuthStatusResponse(auth_required=False, logged_in=True)
    token = (
        request.headers.get("X-App-Auth")
        or request.cookies.get("app_auth_token")
        or request.query_params.get("auth")
    )
    logged_in = bool(token and token == EXPECTED_AUTH_TOKEN)
    return AuthStatusResponse(auth_required=True, logged_in=logged_in)


@app.post("/api/auth/login", response_model=LoginResponse)
async def api_auth_login(req: LoginRequest, response: Response):
    if not APP_PASSWORD:
        return LoginResponse(success=True, token="no_auth", message="Login berhasil (tanpa proteksi sandi).")

    if req.password.strip() == APP_PASSWORD:
        token = EXPECTED_AUTH_TOKEN
        response.set_cookie(
            key="app_auth_token",
            value=token,
            max_age=30 * 24 * 3600,
            httponly=False,
            samesite="lax",
            path="/",
        )
        return LoginResponse(success=True, token=token, message="Kata sandi benar. Selamat datang!")

    raise HTTPException(status_code=401, detail="Kata sandi salah. Silakan periksa kembali.")


@app.post("/api/auth/logout")
async def api_auth_logout(response: Response):
    response.delete_cookie(key="app_auth_token", path="/")
    return {"success": True, "message": "Berhasil mengunci studio."}


@app.get("/api/health", response_model=SystemHealthResponse)
async def api_health():
    return check_system_health()


@app.get("/api/config")
async def api_config():
    cookie_path, has_login = check_cookies_status()
    return {
        "voices": [{"id": k, "label": v} for k, v in VOICES.items()],
        "subtitle_styles": [{"id": k, "label": v} for k, v in SUBTITLE_STYLES.items()],
        "subtitle_fonts": SUBTITLE_FONTS,
        "thumbnail_styles": [{"id": k, "label": v} for k, v in THUMBNAIL_STYLES.items()],
        "cookies_installed": cookie_path is not None,
        "cookies_has_login": has_login,
    }

@app.post("/api/cookies/upload")
async def api_upload_cookies(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="File tidak valid.")
    content = await file.read()
    if len(content) < 10:
        raise HTTPException(status_code=400, detail="File kosong atau tidak valid.")
    target_path = UPLOADS_DIR / "cookies.txt"
    async with aiofiles.open(target_path, "wb") as out:
        await out.write(content)

    text_content = content.decode("utf-8", errors="ignore")
    has_youtube = ".youtube.com" in text_content
    has_login = any(k in text_content for k in ["LOGIN_INFO", "SAPISID", "SSID", "__Secure-3PSID", "SID"])

    return {
        "status": "ok",
        "size_bytes": len(content),
        "has_youtube": has_youtube,
        "has_login": has_login,
        "message": (
            "File cookies.txt tersimpan dan akun login terverifikasi!"
            if has_login
            else "File tersimpan, namun TIDAK terdeteksi akun login YouTube (hanya guest). Pastikan login ke akun YouTube di browser sebelum export cookies!"
        ),
    }


@app.delete("/api/cookies")
async def api_delete_cookies():
    cookie_p, _ = check_cookies_status()
    if cookie_p and cookie_p.exists():
        cookie_p.unlink(missing_ok=True)
    return {"status": "ok", "message": "File cookies.txt berhasil dihapus."}


@app.get("/api/videos", response_model=List[VideoMetadata])
async def api_list_videos():
    files = sorted(
        [
            p
            for p in UPLOADS_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items: List[VideoMetadata] = []
    for f in files:
        try:
            src_type = "youtube" if f.name.startswith("yt_") else "upload"
            items.append(await asyncio.to_thread(probe_video, f, src_type))
        except Exception:
            continue
    return items


@app.post("/api/videos/upload", response_model=VideoMetadata)
async def api_upload_video(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nama file tidak valid.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format '{ext}' tidak didukung. Gunakan: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    safe_stem = sanitize_filename(Path(file.filename).stem, "bg_video")
    target_name = f"{safe_stem}_{int(time.time())}{ext}"
    target_path = UPLOADS_DIR / target_name

    try:
        async with aiofiles.open(target_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                await out.write(chunk)
        meta = await asyncio.to_thread(probe_video, target_path, "upload", Path(file.filename).stem)
        return meta
    except Exception as exc:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Gagal memproses video: {exc}") from exc


@app.post("/api/videos/youtube")
async def api_download_youtube(req: YoutubeDownloadRequest):
    if not ("youtube.com" in req.url or "youtu.be" in req.url):
        raise HTTPException(status_code=400, detail="Masukkan URL YouTube yang valid (youtube.com atau youtu.be).")
    job_id = await job_manager.start_youtube_job(req)
    return {"job_id": job_id}


@app.delete("/api/videos/{filename}")
async def api_delete_video(filename: str):
    target = (UPLOADS_DIR / Path(filename).name).resolve()
    if not target.exists() or target.parent != UPLOADS_DIR.resolve():
        raise HTTPException(status_code=404, detail="File video tidak ditemukan.")
    target.unlink()
    return {"deleted": filename}


@app.get("/api/affiliates", response_model=List[VideoMetadata])
async def api_list_affiliates():
    files = sorted(
        [
            p
            for p in AFFILIATES_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in ALLOWED_VIDEO_EXTENSIONS
        ],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items: List[VideoMetadata] = []
    for f in files:
        try:
            items.append(await asyncio.to_thread(probe_video, f, "upload", None, "/uploads/affiliates"))
        except Exception:
            continue
    return items


@app.post("/api/affiliates/upload", response_model=VideoMetadata)
async def api_upload_affiliate(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nama file tidak valid.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format '{ext}' tidak didukung. Gunakan: {', '.join(sorted(ALLOWED_VIDEO_EXTENSIONS))}",
        )

    safe_stem = sanitize_filename(Path(file.filename).stem, "affiliate_vid")
    target_name = f"{safe_stem}_{int(time.time())}{ext}"
    target_path = AFFILIATES_DIR / target_name

    try:
        async with aiofiles.open(target_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                await out.write(chunk)
        meta = await asyncio.to_thread(
            probe_video,
            target_path,
            "upload",
            Path(file.filename).stem,
            "/uploads/affiliates",
        )
        return meta
    except Exception as exc:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Gagal memproses video affiliate: {exc}") from exc


@app.delete("/api/affiliates/{filename}")
async def api_delete_affiliate(filename: str):
    target = (AFFILIATES_DIR / Path(filename).name).resolve()
    if not target.exists() or target.parent != AFFILIATES_DIR.resolve():
        raise HTTPException(status_code=404, detail="File video affiliate tidak ditemukan.")
    target.unlink()
    return {"deleted": filename}


@app.post("/api/thumbnail/upload-custom")
async def api_upload_custom_cover(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Nama file gambar tidak valid.")
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Format '{ext}' tidak didukung. Gunakan: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}",
        )

    safe_stem = sanitize_filename(Path(file.filename).stem, "custom_cover")
    target_name = f"{safe_stem}_{int(time.time())}{ext}"
    target_path = COVERS_DIR / target_name

    try:
        async with aiofiles.open(target_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                await out.write(chunk)
        return {"filename": target_name, "url": f"/uploads/covers/{target_name}"}
    except Exception as exc:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Gagal mengunggah gambar: {exc}") from exc


@app.post("/api/thumbnail/generate", response_model=ThumbnailResponse)
async def api_generate_thumbnail(req: ThumbnailGenerateRequest):
    safe_title = sanitize_filename(req.title[:20] if req.title else "thumb", "cover")
    stamp = int(time.time())
    out_name = f"preview_thumb_{safe_title}_{stamp}.jpg"
    out_path = OUTPUTS_DIR / out_name

    vid_path: Optional[Path] = None
    if req.source_type == "video_frame" and req.video_filename:
        v_cand = (UPLOADS_DIR / Path(req.video_filename).name).resolve()
        if v_cand.exists() and v_cand.parent == UPLOADS_DIR.resolve():
            vid_path = v_cand

    cust_path: Optional[Path] = None
    if req.source_type == "custom_image" and req.custom_image_filename:
        c_cand = (COVERS_DIR / Path(req.custom_image_filename).name).resolve()
        if not c_cand.exists():
            c_cand = (UPLOADS_DIR / Path(req.custom_image_filename).name).resolve()
        if c_cand.exists():
            cust_path = c_cand

    try:
        await asyncio.to_thread(
            generate_thumbnail_image,
            output_path=out_path,
            title=req.title,
            subtitle=req.subtitle,
            style=req.style,
            video_path=vid_path,
            custom_image_path=cust_path,
            frame_time=req.frame_time,
        )
        return ThumbnailResponse(
            thumbnail_url=f"/outputs/{out_name}",
            filename=out_name,
            width=TARGET_WIDTH,
            height=TARGET_HEIGHT,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Gagal membuat thumbnail: {exc}") from exc


@app.post("/api/story/split-preview", response_model=StorySplitPreviewResponse)
async def api_story_split_preview(req: StorySplitPreviewRequest):
    parts = split_story_into_parts(
        story_text=req.story_text,
        auto_split=req.auto_split,
        max_words_per_part=req.max_words_per_part,
        cta_template=req.cta_template,
        final_cta=req.final_cta,
        tts_rate=req.tts_rate,
    )
    total_words = sum(p.word_count for p in parts)
    return StorySplitPreviewResponse(parts=parts, total_parts=len(parts), total_words=total_words)


@app.post("/api/render")
async def api_start_render(req: RenderRequest):
    health = check_system_health()
    if not health.ffmpeg_available:
        raise HTTPException(
            status_code=503,
            detail="FFmpeg tidak terdeteksi di sistem. Instal FFmpeg dan pastikan ada di PATH.",
        )
    source = (UPLOADS_DIR / Path(req.video_filename).name).resolve()
    if not source.exists():
        raise HTTPException(status_code=404, detail="Video background tidak ditemukan. Silakan upload atau unduh dulu.")

    job_id = await job_manager.start_render_job(req)
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}", response_model=JobStatusResponse)
async def api_get_job(job_id: str):
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")
    return job


@app.get("/api/jobs/{job_id}/stream")
async def api_stream_job(job_id: str):
    if not job_manager.get_job(job_id):
        raise HTTPException(status_code=404, detail="Job tidak ditemukan.")

    async def event_generator():
        last_payload = ""
        while True:
            job = job_manager.get_job(job_id)
            if not job:
                break
            payload = job.model_dump_json()
            if payload != last_payload:
                yield f"data: {payload}\n\n"
                last_payload = payload
            if job.status in ("completed", "failed"):
                break
            await asyncio.sleep(0.35)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/outputs", response_model=List[RenderedOutputItem])
async def api_list_outputs():
    return await asyncio.to_thread(list_rendered_outputs)


@app.get("/api/outputs/{filename}/download")
async def api_download_output(filename: str):
    target = (OUTPUTS_DIR / Path(filename).name).resolve()
    if not target.exists() or target.parent != OUTPUTS_DIR.resolve():
        raise HTTPException(status_code=404, detail="File hasil render tidak ditemukan.")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type="application/octet-stream",
    )


@app.delete("/api/outputs/{filename}")
async def api_delete_output(filename: str):
    target = (OUTPUTS_DIR / Path(filename).name).resolve()
    if not target.exists() or target.parent != OUTPUTS_DIR.resolve():
        raise HTTPException(status_code=404, detail="File hasil render tidak ditemukan.")
    target.unlink(missing_ok=True)
    target.with_suffix(".srt").unlink(missing_ok=True)
    target.with_suffix(".meta.json").unlink(missing_ok=True)
    (target.parent / f"{target.stem}_thumb.jpg").unlink(missing_ok=True)
    return {"deleted": filename}
