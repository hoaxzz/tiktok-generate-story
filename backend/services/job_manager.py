import asyncio
import json
import shutil
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from backend.config import AFFILIATES_DIR, ANTI_COPYRIGHT_SPEED, OUTPUTS_DIR, TEMP_DIR, UPLOADS_DIR
from backend.models import (
    JobStatusResponse,
    RenderRequest,
    RenderedOutputItem,
    StoryPart,
    YoutubeDownloadRequest,
)
from backend.services.media_utils import (
    download_youtube_video,
    parse_timestamp,
    probe_video,
    sanitize_filename,
)
from backend.services.story_splitter import split_story_into_parts
from backend.services.thumbnail_generator import generate_cta_badge_png, generate_thumbnail_image
from backend.services.tts_subtitle import generate_hook_only_ass, generate_tts_and_subtitles
from backend.services.video_renderer import compute_clip_segments, merge_affiliate_video, render_vertical_video


class JobManager:
    def __init__(self) -> None:
        self._jobs: Dict[str, JobStatusResponse] = {}
        self._lock = threading.Lock()

    def create_job(self, stage: str, message: str) -> str:
        job_id = uuid.uuid4().hex[:12]
        with self._lock:
            self._jobs[job_id] = JobStatusResponse(
                job_id=job_id,
                status="queued",
                progress=0.0,
                stage=stage,
                message=message,
                logs=[f"[{self._now_time()}] {message}"],
            )
        return job_id

    def get_job(self, job_id: str) -> Optional[JobStatusResponse]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def _now_time(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _update(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        progress: Optional[float] = None,
        stage: Optional[str] = None,
        message: Optional[str] = None,
        log: Optional[str] = None,
        outputs: Optional[List[RenderedOutputItem]] = None,
        video_metadata=None,
        error: Optional[str] = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            if status is not None:
                job.status = status
            if progress is not None:
                job.progress = round(max(0.0, min(100.0, progress)), 1)
            if stage is not None:
                job.stage = stage
            if message is not None:
                job.message = message
            if log is not None:
                job.logs.append(f"[{self._now_time()}] {log}")
                if len(job.logs) > 80:
                    job.logs = job.logs[-80:]
            if outputs is not None:
                job.outputs = outputs
            if video_metadata is not None:
                job.video_metadata = video_metadata
            if error is not None:
                job.error = error

    async def start_youtube_job(self, req: YoutubeDownloadRequest) -> str:
        job_id = self.create_job("youtube_download", "Menyiapkan unduhan YouTube...")
        asyncio.create_task(self._run_youtube_job(job_id, req))
        return job_id

    async def _run_youtube_job(self, job_id: str, req: YoutubeDownloadRequest) -> None:
        self._update(
            job_id,
            status="running",
            progress=2.0,
            stage="youtube_download",
            message="Menghubungi YouTube via yt-dlp...",
            log=f"Memulai unduhan YouTube: {req.url}",
        )
        try:
            def on_dl_progress(pct: float, msg: str) -> None:
                self._update(job_id, progress=pct, message=msg)

            file_path, title = await asyncio.to_thread(
                download_youtube_video,
                req.url,
                req.max_height,
                on_dl_progress,
            )
            self._update(
                job_id,
                progress=98.0,
                stage="probing",
                message="Membaca metadata video...",
                log=f"Unduhan selesai: {file_path.name}. Memeriksa spesifikasi...",
            )
            meta = await asyncio.to_thread(probe_video, file_path, "youtube", title)
            self._update(
                job_id,
                status="completed",
                progress=100.0,
                stage="done",
                message=f"Video berhasil diunduh ({meta.width}x{meta.height}, {meta.fps}fps, {meta.duration:.0f}s)",
                log=f"Video siap digunakan: {meta.title}",
                video_metadata=meta,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="error",
                message=f"Gagal mengunduh: {exc}",
                log=f"ERROR: {exc}",
                error=str(exc),
            )

    async def start_render_job(self, req: RenderRequest) -> str:
        job_id = self.create_job("init", "Memulai antrean render...")
        asyncio.create_task(self._run_render_job(job_id, req))
        return job_id

    async def _run_render_job(self, job_id: str, req: RenderRequest) -> None:
        job_temp_dir = TEMP_DIR / f"job_{job_id}"
        job_temp_dir.mkdir(parents=True, exist_ok=True)

        self._update(
            job_id,
            status="running",
            progress=3.0,
            stage="probing",
            message="Membaca video background...",
            log="Memeriksa file video background...",
        )

        try:
            source_video = (UPLOADS_DIR / Path(req.video_filename).name).resolve()
            if not source_video.exists():
                raise FileNotFoundError(f"Video background tidak ditemukan: {req.video_filename}")

            video_meta = await asyncio.to_thread(probe_video, source_video)
            self._update(
                job_id,
                log=f"Video sumber: {video_meta.filename} ({video_meta.width}x{video_meta.height}, durasi {video_meta.duration:.1f}s)",
            )

            manual_start = parse_timestamp(req.start_time or "0")
            manual_end = parse_timestamp(req.end_time or "60")

            # Optional Affiliate Video preparation
            aff_video_path: Optional[Path] = None
            aff_meta = None
            aff_start_sec = 0.0
            aff_end_sec: Optional[float] = None
            cta_badge_path: Optional[Path] = None
            if req.affiliate_enabled:
                if not req.affiliate_filename:
                    raise ValueError("Video affiliate diaktifkan, tetapi belum ada file video affiliate yang dipilih.")
                aff_cand = (AFFILIATES_DIR / Path(req.affiliate_filename).name).resolve()
                if not aff_cand.exists():
                    aff_cand = (UPLOADS_DIR / Path(req.affiliate_filename).name).resolve()
                if not aff_cand.exists():
                    raise FileNotFoundError(f"Video affiliate tidak ditemukan: {req.affiliate_filename}")
                aff_video_path = aff_cand
                aff_meta = await asyncio.to_thread(probe_video, aff_video_path, "upload", None, "/uploads/affiliates")
                aff_start_sec = parse_timestamp(req.affiliate_start_time or "0")
                if req.affiliate_end_time and req.affiliate_end_time.strip():
                    aff_end_sec = parse_timestamp(req.affiliate_end_time.strip())
                if req.affiliate_cta_text and req.affiliate_cta_text.strip():
                    cta_badge_path = await asyncio.to_thread(
                        generate_cta_badge_png,
                        job_temp_dir / "affiliate_cta.png",
                        req.affiliate_cta_text.strip(),
                    )
                self._update(
                    job_id,
                    log=f"Video affiliate aktif: {aff_meta.filename} ({aff_meta.duration:.1f}s, posisi={req.affiliate_placement}, mode={req.affiliate_fit_mode})",
                )

            # Determine story parts
            if req.include_tts:
                if not req.story_text.strip():
                    raise ValueError("Naskah cerita kosong. Isi naskah atau matikan opsi TTS.")
                parts = split_story_into_parts(
                    story_text=req.story_text,
                    auto_split=req.auto_split,
                    max_words_per_part=req.max_words_per_part,
                    cta_template=req.cta_template,
                    final_cta=req.final_cta,
                    tts_rate=req.tts_rate,
                )
                if not parts:
                    raise ValueError("Naskah cerita gagal diproses.")
            else:
                # Clipper-only mode (no TTS)
                if req.clip_mode == "manual":
                    span = max(1.0, min(manual_end, video_meta.duration) - manual_start)
                    num_parts = 1
                elif req.clip_mode == "auto_part":
                    raw_part = req.part_duration * (ANTI_COPYRIGHT_SPEED if req.anti_copyright else 1.0)
                    num_parts = max(1, int(video_meta.duration // max(5.0, raw_part)))
                    if num_parts == 0:
                        num_parts = 1
                else:
                    num_parts = 1
                parts = [
                    StoryPart(
                        part_number=i,
                        total_parts=num_parts,
                        text="",
                        word_count=0,
                        estimated_duration=req.part_duration,
                    )
                    for i in range(1, num_parts + 1)
                ]

            total_parts = len(parts)
            self._update(
                job_id,
                progress=5.0,
                stage="prepare",
                message=f"Menyiapkan {total_parts} part video...",
                log=f"Total part: {total_parts} | Mode klip: {req.clip_mode} | Anti-Copyright: {'ON' if req.anti_copyright else 'OFF'}",
            )

            # Step 1: Generate TTS + subtitles per part (if include_tts)
            tts_results = []
            target_durations: List[float] = []
            part_slice = 95.0 / max(1, total_parts)

            for idx, part in enumerate(parts):
                base_pct = 5.0 + idx * part_slice
                if req.include_tts:
                    self._update(
                        job_id,
                        progress=base_pct + part_slice * 0.05,
                        stage="tts",
                        message=f"Membuat suara TTS & subtitle Part {part.part_number}/{total_parts}...",
                        log=f"Sintesis TTS ({req.voice}, {req.tts_rate}) untuk Part {part.part_number}...",
                    )
                    hook_formatted = (
                        req.hook_text.format(part=part.part_number, total=total_parts)
                        if req.hook_enabled and req.hook_text.strip()
                        else ""
                    )
                    tts_res = await generate_tts_and_subtitles(
                        text=part.text,
                        voice=req.voice,
                        tts_rate=req.tts_rate,
                        output_dir=job_temp_dir,
                        basename=f"part_{part.part_number:02d}",
                        subtitle_style=req.subtitle_style,
                        subtitle_font=req.subtitle_font,
                        subtitle_size=req.subtitle_size,
                        words_per_cue=req.words_per_cue,
                        hook_enabled=req.hook_enabled,
                        hook_text=hook_formatted,
                        hook_duration=req.hook_duration,
                    )
                    tts_results.append(tts_res)
                    target_durations.append(round(tts_res.duration + 0.45, 3))
                    self._update(
                        job_id,
                        progress=base_pct + part_slice * 0.25,
                        log=f"TTS Part {part.part_number} selesai ({tts_res.duration:.2f}s, {tts_res.word_count} kata).",
                    )
                else:
                    tts_results.append(None)
                    if req.clip_mode == "manual":
                        span = max(1.0, min(manual_end, video_meta.duration) - manual_start)
                        speed = ANTI_COPYRIGHT_SPEED if req.anti_copyright else 1.0
                        target_durations.append(round(span / speed, 3))
                    else:
                        target_durations.append(round(min(req.part_duration, video_meta.duration) if video_meta.duration > 1 else req.part_duration, 3))

            # Step 2: Compute clip segments for all parts
            clip_segments = compute_clip_segments(
                video_meta=video_meta,
                clip_mode=req.clip_mode,
                target_durations=target_durations,
                start_sec=manual_start,
                end_sec=manual_end,
                part_duration=req.part_duration,
                anti_copyright=req.anti_copyright,
            )

            # Step 3: Render each part with FFmpeg
            rendered_items: List[RenderedOutputItem] = []
            safe_project = sanitize_filename(req.project_name, "tiktok_story")
            stamp = int(time.time())

            for idx, part in enumerate(parts):
                base_pct = 5.0 + idx * part_slice
                render_start_pct = base_pct + (part_slice * 0.25 if req.include_tts else 0.0)
                render_span_pct = part_slice * (0.75 if req.include_tts else 1.0)

                seek_start, _raw_needed, needs_loop = clip_segments[idx]
                target_dur = target_durations[idx]
                tts_res = tts_results[idx]

                ass_path: Optional[Path] = None
                srt_out_name: Optional[str] = None
                out_stem = f"{safe_project}_{stamp}_part{part.part_number:02d}"
                out_mp4 = OUTPUTS_DIR / f"{out_stem}.mp4"

                if tts_res is not None:
                    ass_path = tts_res.ass_path
                    srt_out_name = f"{out_stem}.srt"
                    shutil.copy2(tts_res.srt_path, OUTPUTS_DIR / srt_out_name)
                elif req.hook_enabled and req.hook_text.strip():
                    hook_formatted = req.hook_text.format(part=part.part_number, total=total_parts)
                    ass_path = generate_hook_only_ass(
                        ass_path=job_temp_dir / f"hook_part_{part.part_number:02d}.ass",
                        hook_text=hook_formatted,
                        hook_duration=req.hook_duration,
                        subtitle_font=req.subtitle_font,
                    )

                # Thumbnail generation per part
                thumb_out_name: Optional[str] = None
                thumb_path: Optional[Path] = None
                if req.generate_thumbnail:
                    thumb_title = (req.thumbnail_title or f"Part {part.part_number}").format(
                        part=part.part_number, total=total_parts
                    )
                    thumb_subtitle = (req.thumbnail_subtitle or "").format(
                        part=part.part_number, total=total_parts
                    )
                    thumb_out_name = f"{out_stem}_thumb.jpg"
                    thumb_path = OUTPUTS_DIR / thumb_out_name

                    custom_img: Optional[Path] = None
                    if req.thumbnail_source == "custom_image" and req.thumbnail_custom_filename:
                        c_cand = UPLOADS_DIR / "covers" / req.thumbnail_custom_filename
                        if not c_cand.exists():
                            c_cand = UPLOADS_DIR / req.thumbnail_custom_filename
                        if c_cand.exists():
                            custom_img = c_cand

                    f_time = (seek_start + 1.5) if req.thumbnail_source == "video_frame" else req.thumbnail_frame_time
                    try:
                        await asyncio.to_thread(
                            generate_thumbnail_image,
                            output_path=thumb_path,
                            title=thumb_title,
                            subtitle=thumb_subtitle,
                            style=req.thumbnail_style,
                            video_path=source_video,
                            custom_image_path=custom_img,
                            frame_time=f_time,
                        )
                        self._update(job_id, log=f"Thumbnail Part {part.part_number} berhasil dibuat ({thumb_out_name}).")
                    except Exception as t_err:
                        self._update(job_id, log=f"Peringatan: Gagal membuat thumbnail Part {part.part_number}: {t_err}")
                        thumb_path = None
                        thumb_out_name = None

                self._update(
                    job_id,
                    progress=render_start_pct,
                    stage="rendering",
                    message=f"Merender video 9:16 Part {part.part_number}/{total_parts}...",
                    log=f"FFmpeg Part {part.part_number}: start={seek_start:.2f}s, dur={target_dur:.2f}s, loop={needs_loop}",
                )

                apply_aff_this_part = (
                    req.affiliate_enabled
                    and aff_video_path is not None
                    and aff_meta is not None
                    and (
                        req.affiliate_apply_parts == "all"
                        or (req.affiliate_apply_parts == "last" and part.part_number == total_parts)
                        or (req.affiliate_apply_parts == "first" and part.part_number == 1)
                    )
                )

                main_render_target = (job_temp_dir / f"main_{out_stem}.mp4") if apply_aff_this_part else out_mp4
                main_weight = 0.72 if apply_aff_this_part else 1.0

                def on_ffmpeg_progress(ff_pct: float, ff_msg: str) -> None:
                    overall = render_start_pct + (ff_pct / 100.0) * (render_span_pct * main_weight)
                    self._update(
                        job_id,
                        progress=overall,
                        message=f"Part {part.part_number}/{total_parts}: {ff_msg}",
                    )

                await asyncio.to_thread(
                    render_vertical_video,
                    source_video=source_video,
                    video_meta=video_meta,
                    output_path=main_render_target,
                    temp_dir=job_temp_dir,
                    target_duration=target_dur,
                    seek_start=seek_start,
                    needs_loop=needs_loop,
                    clip_mode=req.clip_mode,
                    manual_start=manual_start,
                    manual_end=manual_end,
                    anti_copyright=req.anti_copyright,
                    tts_audio_path=tts_res.audio_path if tts_res else None,
                    ass_path=ass_path,
                    bg_volume=(req.bg_volume if req.bg_audio_enabled else 0.0),
                    progress_cb=on_ffmpeg_progress,
                    cover_thumb_path=(thumb_path if (req.insert_cover_intro and thumb_path and thumb_path.exists()) else None),
                    cover_intro_duration=req.cover_intro_duration,
                )

                if apply_aff_this_part and aff_video_path is not None and aff_meta is not None:
                    main_part_meta = await asyncio.to_thread(probe_video, main_render_target)
                    self._update(
                        job_id,
                        progress=render_start_pct + render_span_pct * main_weight,
                        stage="affiliate_merge",
                        message=f"Part {part.part_number}/{total_parts}: Menyisipkan video affiliate ({req.affiliate_placement})...",
                        log=f"Menyisipkan video affiliate '{aff_meta.filename}' ke Part {part.part_number} (posisi={req.affiliate_placement}).",
                    )

                    def on_aff_progress(af_pct: float, af_msg: str) -> None:
                        overall = render_start_pct + render_span_pct * main_weight + (af_pct / 100.0) * (render_span_pct * (1.0 - main_weight))
                        self._update(
                            job_id,
                            progress=overall,
                            message=f"Part {part.part_number}/{total_parts}: {af_msg}",
                        )

                    await asyncio.to_thread(
                        merge_affiliate_video,
                        main_video=main_render_target,
                        main_meta=main_part_meta,
                        affiliate_video=aff_video_path,
                        affiliate_meta=aff_meta,
                        output_path=out_mp4,
                        temp_dir=job_temp_dir,
                        placement=req.affiliate_placement,
                        fit_mode=req.affiliate_fit_mode,
                        aff_start_sec=aff_start_sec,
                        aff_end_sec=aff_end_sec,
                        aff_volume=req.affiliate_volume,
                        pip_start=req.affiliate_pip_start,
                        cta_badge_path=cta_badge_path,
                        progress_cb=on_aff_progress,
                    )

                final_meta = await asyncio.to_thread(probe_video, out_mp4)
                created_iso = datetime.now(timezone.utc).isoformat()
                item = RenderedOutputItem(
                    filename=out_mp4.name,
                    title=f"{req.project_name} - Part {part.part_number}/{total_parts}" if total_parts > 1 else req.project_name,
                    part_number=part.part_number,
                    total_parts=total_parts,
                    duration=final_meta.duration,
                    size_bytes=final_meta.size_bytes,
                    created_at=created_iso,
                    video_url=f"/outputs/{out_mp4.name}",
                    srt_filename=srt_out_name,
                    srt_url=f"/outputs/{srt_out_name}" if srt_out_name else None,
                    thumbnail_filename=thumb_out_name if (thumb_path and thumb_path.exists()) else None,
                    thumbnail_url=f"/outputs/{thumb_out_name}" if (thumb_path and thumb_path.exists()) else None,
                )
                (OUTPUTS_DIR / f"{out_stem}.meta.json").write_text(
                    item.model_dump_json(indent=2), encoding="utf-8"
                )
                rendered_items.append(item)
                self._update(
                    job_id,
                    progress=base_pct + part_slice,
                    log=f"Selesai render: {out_mp4.name} ({final_meta.duration:.1f}s, {final_meta.size_bytes / (1024*1024):.2f} MB)",
                )

            self._update(
                job_id,
                status="completed",
                progress=100.0,
                stage="done",
                message=f"Berhasil merender {len(rendered_items)} video TikTok 9:16!",
                log="Semua proses rendering selesai.",
                outputs=rendered_items,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="failed",
                stage="error",
                message=f"Render gagal: {exc}",
                log=f"ERROR: {exc}",
                error=str(exc),
            )
        finally:
            shutil.rmtree(job_temp_dir, ignore_errors=True)


def list_rendered_outputs() -> List[RenderedOutputItem]:
    items: List[RenderedOutputItem] = []
    mp4_files = sorted(OUTPUTS_DIR.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    for mp4 in mp4_files:
        meta_file = mp4.with_suffix(".meta.json")
        thumb_candidate = mp4.parent / f"{mp4.stem}_thumb.jpg"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                item = RenderedOutputItem(**data)
                if not item.thumbnail_filename and thumb_candidate.exists():
                    item.thumbnail_filename = thumb_candidate.name
                    item.thumbnail_url = f"/outputs/{thumb_candidate.name}"
                items.append(item)
                continue
            except Exception:
                pass
        stat = mp4.stat()
        srt_candidate = mp4.with_suffix(".srt")
        duration = 0.0
        try:
            duration = probe_video(mp4).duration
        except Exception:
            pass
        items.append(
            RenderedOutputItem(
                filename=mp4.name,
                title=mp4.stem,
                part_number=1,
                total_parts=1,
                duration=duration,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                video_url=f"/outputs/{mp4.name}",
                srt_filename=srt_candidate.name if srt_candidate.exists() else None,
                srt_url=f"/outputs/{srt_candidate.name}" if srt_candidate.exists() else None,
                thumbnail_filename=thumb_candidate.name if thumb_candidate.exists() else None,
                thumbnail_url=f"/outputs/{thumb_candidate.name}" if thumb_candidate.exists() else None,
            )
        )
    return items

job_manager = JobManager()
