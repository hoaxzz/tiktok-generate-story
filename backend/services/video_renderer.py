import random
import subprocess
import threading
from collections import deque
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from backend.config import (
    ANTI_COPYRIGHT_BRIGHTNESS,
    ANTI_COPYRIGHT_CONTRAST,
    ANTI_COPYRIGHT_SATURATION,
    ANTI_COPYRIGHT_SPEED,
    TARGET_FPS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)
from backend.models import VideoMetadata


def _prepare_manual_loop_clip(
    source_video: Path,
    start_sec: float,
    end_sec: float,
    out_clip: Path,
    has_audio: bool,
) -> Path:
    span = max(0.5, end_sec - start_sec)
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "warning",
        "-ss",
        f"{start_sec:.3f}",
        "-t",
        f"{span:.3f}",
        "-i",
        str(source_video.resolve()),
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
    ]
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")
    cmd.append(str(out_clip.resolve()))

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        raise RuntimeError(f"Gagal memotong segmen manual: {proc.stderr[-800:]}")
    return out_clip


def compute_clip_segments(
    video_meta: VideoMetadata,
    clip_mode: str,
    target_durations: List[float],
    start_sec: float = 0.0,
    end_sec: float = 60.0,
    part_duration: float = 50.0,
    anti_copyright: bool = False,
) -> List[Tuple[float, float, bool]]:
    """
    Returns list of (seek_start, raw_needed_dur, needs_loop) per output part.
    """
    speed = ANTI_COPYRIGHT_SPEED if anti_copyright else 1.0
    vid_dur = max(0.5, video_meta.duration)
    segments: List[Tuple[float, float, bool]] = []

    if clip_mode == "manual":
        if start_sec >= vid_dur:
            raise ValueError(
                f"Start Time ({start_sec:.1f}s) melebihi durasi video ({vid_dur:.1f}s)."
            )
        clamped_end = min(end_sec, vid_dur)
        if clamped_end <= start_sec:
            raise ValueError("End Time harus lebih besar dari Start Time.")
        manual_span = clamped_end - start_sec
        for target_dur in target_durations:
            raw_needed = target_dur * speed
            needs_loop = manual_span < (raw_needed - 0.1)
            segments.append((start_sec, raw_needed, needs_loop))
        return segments

    if clip_mode == "auto_random":
        used_starts: List[float] = []
        for target_dur in target_durations:
            raw_needed = target_dur * speed
            if vid_dur <= raw_needed + 0.2:
                segments.append((0.0, raw_needed, vid_dur < raw_needed))
                continue
            margin = 2.0 if vid_dur > raw_needed + 6.0 else 0.0
            max_start = max(margin, vid_dur - raw_needed - margin)
            best_start = random.uniform(margin, max_start)
            for _ in range(8):
                cand = random.uniform(margin, max_start)
                if all(abs(cand - prev) >= min(raw_needed * 0.6, 15.0) for prev in used_starts):
                    best_start = cand
                    break
            used_starts.append(best_start)
            segments.append((round(best_start, 2), raw_needed, False))
        return segments

    # auto_part: sequential slices
    cursor = 0.0
    for target_dur in target_durations:
        raw_needed = target_dur * speed
        if vid_dur <= raw_needed + 0.1:
            segments.append((0.0, raw_needed, vid_dur < raw_needed))
            continue
        if cursor + raw_needed > vid_dur:
            cursor = 0.0
        segments.append((round(cursor, 2), raw_needed, False))
        step = max(raw_needed, part_duration * speed) if len(target_durations) > 1 else raw_needed
        cursor += step
        if cursor >= vid_dur - 1.0:
            cursor = 0.0
    return segments


def render_vertical_video(
    source_video: Path,
    video_meta: VideoMetadata,
    output_path: Path,
    temp_dir: Path,
    target_duration: float,
    seek_start: float,
    needs_loop: bool,
    clip_mode: str,
    manual_start: float,
    manual_end: float,
    anti_copyright: bool,
    tts_audio_path: Optional[Path],
    ass_path: Optional[Path],
    bg_volume: float,
    progress_cb: Optional[Callable[[float, str], None]] = None,
    cover_thumb_path: Optional[Path] = None,
    cover_intro_duration: float = 0.8,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    speed = ANTI_COPYRIGHT_SPEED if anti_copyright else 1.0
    raw_needed = max(0.5, target_duration * speed)

    input_video = source_video.resolve()
    use_stream_loop = needs_loop
    effective_seek = seek_start

    if clip_mode == "manual" and needs_loop:
        slice_path = temp_dir / f"manual_slice_{output_path.stem}.mp4"
        input_video = _prepare_manual_loop_clip(
            source_video=source_video,
            start_sec=manual_start,
            end_sec=min(manual_end, video_meta.duration),
            out_clip=slice_path,
            has_audio=video_meta.has_audio,
        ).resolve()
        use_stream_loop = True
        effective_seek = 0.0

    cmd: List[str] = ["ffmpeg", "-y", "-loglevel", "warning", "-progress", "pipe:1", "-nostats"]

    if use_stream_loop:
        cmd.extend(["-stream_loop", "-1", "-i", str(input_video)])
    else:
        cmd.extend(["-ss", f"{effective_seek:.3f}", "-t", f"{raw_needed:.3f}", "-i", str(input_video)])

    input_idx = 1
    has_tts = tts_audio_path is not None and tts_audio_path.exists()
    tts_idx: Optional[int] = None
    if has_tts:
        cmd.extend(["-i", str(tts_audio_path.resolve())])
        tts_idx = input_idx
        input_idx += 1

    has_cover = (
        cover_thumb_path is not None
        and cover_thumb_path.exists()
        and cover_intro_duration > 0.05
    )
    cover_idx: Optional[int] = None
    if has_cover:
        cmd.extend(["-loop", "1", "-t", f"{cover_intro_duration:.3f}", "-i", str(cover_thumb_path.resolve())])
        cover_idx = input_idx
        input_idx += 1

    v_filters = [
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase",
        f"crop={TARGET_WIDTH}:{TARGET_HEIGHT}",
        "setsar=1",
        f"fps={TARGET_FPS}",
    ]
    if anti_copyright:
        v_filters.append("hflip")
        v_filters.append(f"setpts=PTS/{ANTI_COPYRIGHT_SPEED}")
        v_filters.append(
            f"eq=saturation={ANTI_COPYRIGHT_SATURATION}:contrast={ANTI_COPYRIGHT_CONTRAST}:brightness={ANTI_COPYRIGHT_BRIGHTNESS}"
        )
    if ass_path is not None and ass_path.exists():
        v_filters.append(f"ass={ass_path.name}")

    if has_cover and cover_idx is not None:
        v_chain = "[0:v]" + ",".join(v_filters) + "[vbase]"
        cov_chain = f"[{cover_idx}:v]scale={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,fps={TARGET_FPS}[cov]"
        ov_chain = f"[vbase][cov]overlay=0:0:enable='between(t,0,{cover_intro_duration:.3f})',format=yuv420p[vout]"
        filter_parts = [v_chain, cov_chain, ov_chain]
    else:
        v_filters.append("format=yuv420p")
        v_chain = "[0:v]" + ",".join(v_filters) + "[vout]"
        filter_parts = [v_chain]

    map_audio = True
    use_bg_audio = video_meta.has_audio and bg_volume > 0.005

    if has_tts and use_bg_audio and tts_idx is not None:
        bg_a_filters = []
        if anti_copyright:
            bg_a_filters.append(f"atempo={ANTI_COPYRIGHT_SPEED}")
        bg_a_filters.append(f"volume={bg_volume:.3f}")
        bg_a_filters.append("aresample=44100")
        bg_a_filters.append(f"apad=whole_dur={target_duration:.3f}")
        bg_chain = "[0:a]" + ",".join(bg_a_filters) + "[bga]"

        tts_chain = f"[{tts_idx}:a]volume=1.0,aresample=44100,apad=whole_dur={target_duration:.3f}[ttsa]"
        mix_chain = (
            f"[bga][ttsa]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0,"
            f"atrim=0:{target_duration:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        filter_parts.extend([bg_chain, tts_chain, mix_chain])
    elif has_tts and tts_idx is not None:
        tts_chain = (
            f"[{tts_idx}:a]volume=1.0,aresample=44100,apad=whole_dur={target_duration:.3f},"
            f"atrim=0:{target_duration:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        filter_parts.append(tts_chain)
    elif use_bg_audio:
        bg_a_filters = []
        if anti_copyright:
            bg_a_filters.append(f"atempo={ANTI_COPYRIGHT_SPEED}")
        bg_a_filters.append(f"volume={bg_volume:.3f}")
        bg_a_filters.append("aresample=44100")
        bg_a_filters.append(f"atrim=0:{target_duration:.3f}")
        bg_a_filters.append("asetpts=PTS-STARTPTS")
        filter_parts.append("[0:a]" + ",".join(bg_a_filters) + "[aout]")
    else:
        map_audio = False

    cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[vout]"])
    if map_audio:
        cmd.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"])
    else:
        cmd.append("-an")

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            "-t",
            f"{target_duration:.3f}",
            str(output_path.resolve()),
        ]
    )

    run_cwd = str(ass_path.parent.resolve()) if (ass_path is not None and ass_path.exists()) else str(temp_dir.resolve())

    process = subprocess.Popen(
        cmd,
        cwd=run_cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines: deque[str] = deque(maxlen=60)

    def _drain_stderr() -> None:
        if not process.stderr:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    if process.stdout:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    elapsed = us / 1_000_000.0
                    pct = min(99.0, max(0.0, (elapsed / max(0.5, target_duration)) * 100.0))
                    if progress_cb:
                        progress_cb(pct, f"Rendering FFmpeg... {elapsed:.1f}s / {target_duration:.1f}s")
                except ValueError:
                    pass
            elif line == "progress=end":
                if progress_cb:
                    progress_cb(100.0, "Finalisasi MP4...")

    return_code = process.wait()
    stderr_thread.join(timeout=5)

    if return_code != 0 or not output_path.exists():
        tail = "\n".join(list(stderr_lines)[-20:])
        raise RuntimeError(f"FFmpeg error (exit {return_code}):\n{tail}")

    return output_path


def merge_affiliate_video(
    main_video: Path,
    main_meta: VideoMetadata,
    affiliate_video: Path,
    affiliate_meta: VideoMetadata,
    output_path: Path,
    temp_dir: Path,
    placement: str = "end",
    fit_mode: str = "fit_blur",
    aff_start_sec: float = 0.0,
    aff_end_sec: Optional[float] = None,
    aff_volume: float = 1.0,
    pip_start: float = 3.0,
    cta_badge_path: Optional[Path] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> Path:
    """
    Merges an affiliate product video into the rendered 9:16 video.
    Supports placement: 'end', 'start', 'middle', 'pip'.
    Supports fit_mode: 'fit_blur' (keeps whole frame with blurred background), 'crop' (9:16 fill).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_dir.mkdir(parents=True, exist_ok=True)

    main_dur = max(0.5, main_meta.duration)
    aff_total = max(0.5, affiliate_meta.duration)

    eff_start = max(0.0, min(aff_start_sec, max(0.0, aff_total - 0.5)))
    if aff_end_sec is not None and aff_end_sec > eff_start + 0.3:
        eff_end = min(aff_end_sec, aff_total)
    else:
        eff_end = aff_total
    aff_dur = max(0.5, eff_end - eff_start)

    effective_placement = placement
    if effective_placement == "middle" and main_dur < 2.0:
        effective_placement = "end"

    total_out_dur = main_dur if effective_placement == "pip" else (main_dur + aff_dur)

    cmd: List[str] = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "warning",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        str(main_video.resolve()),
        "-ss",
        f"{eff_start:.3f}",
        "-t",
        f"{aff_dur:.3f}",
        "-i",
        str(affiliate_video.resolve()),
    ]

    has_cta = cta_badge_path is not None and cta_badge_path.exists()
    if has_cta:
        cmd.extend(["-i", str(cta_badge_path.resolve())])

    main_has_audio = main_meta.has_audio
    aff_has_audio = affiliate_meta.has_audio and aff_volume > 0.005
    any_audio = main_has_audio or aff_has_audio

    filter_parts: List[str] = []

    if effective_placement == "pip":
        eff_pip_start = max(0.0, min(pip_start, max(0.0, main_dur - 0.5)))
        pip_end = min(main_dur, eff_pip_start + aff_dur)
        pip_clip_dur = max(0.3, pip_end - eff_pip_start)

        filter_parts.append(
            f"[1:v]trim=start=0:end={pip_clip_dur:.3f},"
            f"scale=360:-2,fps={TARGET_FPS},setsar=1,"
            f"pad=w=iw+8:h=ih+8:x=4:y=4:color=#25F4EE,"
            f"setpts=PTS-STARTPTS+{eff_pip_start:.3f}/TB[pip]"
        )
        if has_cta:
            filter_parts.append(
                f"[0:v]setsar=1,fps={TARGET_FPS}[mbase];"
                f"[mbase][pip]overlay=W-w-36:240:eof_action=pass:enable='between(t,{eff_pip_start:.3f},{pip_end:.3f})'[mpip];"
                f"[mpip][2:v]overlay=0:0:enable='between(t,{eff_pip_start:.3f},{pip_end:.3f})',setsar=1,format=yuv420p[vout]"
            )
        else:
            filter_parts.append(
                f"[0:v]setsar=1,fps={TARGET_FPS}[mbase];"
                f"[mbase][pip]overlay=W-w-36:240:eof_action=pass:enable='between(t,{eff_pip_start:.3f},{pip_end:.3f})',setsar=1,format=yuv420p[vout]"
            )

        if main_has_audio and aff_has_audio:
            delay_ms = int(round(eff_pip_start * 1000))
            filter_parts.append(
                f"[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[ma];"
                f"[1:a]atrim=start=0:end={pip_clip_dur:.3f},aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={aff_volume:.3f},adelay={delay_ms}|{delay_ms}[pa];"
                f"[ma][pa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
        elif aff_has_audio:
            delay_ms = int(round(eff_pip_start * 1000))
            filter_parts.append(
                f"anullsrc=r=44100:cl=stereo:d={main_dur:.3f}[sil];"
                f"[1:a]atrim=start=0:end={pip_clip_dur:.3f},aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                f"volume={aff_volume:.3f},adelay={delay_ms}|{delay_ms}[pa];"
                f"[sil][pa]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[aout]"
            )
        elif main_has_audio:
            filter_parts.append(
                "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"
            )
    else:
        # Sequential concat modes: start, middle, end
        if fit_mode == "fit_blur":
            filter_parts.append(
                f"[1:v]fps={TARGET_FPS},split=2[abg][afg];"
                f"[abg]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,boxblur=20:5[abg2];"
                f"[afg]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=decrease,setsar=1[afg2];"
                f"[abg2][afg2]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p[va_pre]"
            )
        else:
            filter_parts.append(
                f"[1:v]scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,"
                f"crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1,fps={TARGET_FPS},format=yuv420p[va_pre]"
            )

        if has_cta:
            filter_parts.append(
                "[va_pre][2:v]overlay=0:0,setsar=1,format=yuv420p,setpts=PTS-STARTPTS[va]"
            )
        else:
            filter_parts.append("[va_pre]setpts=PTS-STARTPTS[va]")

        if any_audio:
            if aff_has_audio:
                filter_parts.append(
                    f"[1:a]volume={aff_volume:.3f},aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"asetpts=PTS-STARTPTS[aa]"
                )
            else:
                filter_parts.append(
                    f"anullsrc=r=44100:cl=stereo:d={aff_dur:.3f},"
                    f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[aa]"
                )

        if effective_placement == "middle":
            mid = round(main_dur / 2.0, 3)
            rem = max(0.3, main_dur - mid)
            filter_parts.append(
                f"[0:v]setsar=1,fps={TARGET_FPS},format=yuv420p,split=2[mv1][mv2];"
                f"[mv1]trim=start=0:end={mid:.3f},setpts=PTS-STARTPTS[v1];"
                f"[mv2]trim=start={mid:.3f},setpts=PTS-STARTPTS[v2]"
            )
            if any_audio:
                if main_has_audio:
                    filter_parts.append(
                        f"[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,asplit=2[ma1][ma2];"
                        f"[ma1]atrim=start=0:end={mid:.3f},asetpts=PTS-STARTPTS[a1];"
                        f"[ma2]atrim=start={mid:.3f},asetpts=PTS-STARTPTS[a2]"
                    )
                else:
                    filter_parts.append(
                        f"anullsrc=r=44100:cl=stereo:d={mid:.3f},"
                        f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a1];"
                        f"anullsrc=r=44100:cl=stereo:d={rem:.3f},"
                        f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[a2]"
                    )
                filter_parts.append("[v1][a1][va][aa][v2][a2]concat=n=3:v=1:a=1[vout][aout]")
            else:
                filter_parts.append("[v1][va][v2]concat=n=3:v=1:a=0[vout]")
        else:
            # start or end
            filter_parts.append(
                f"[0:v]setsar=1,fps={TARGET_FPS},format=yuv420p,setpts=PTS-STARTPTS[vm]"
            )
            if any_audio:
                if main_has_audio:
                    filter_parts.append(
                        "[0:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                        "asetpts=PTS-STARTPTS[am]"
                    )
                else:
                    filter_parts.append(
                        f"anullsrc=r=44100:cl=stereo:d={main_dur:.3f},"
                        f"aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS[am]"
                    )
                if effective_placement == "start":
                    filter_parts.append("[va][aa][vm][am]concat=n=2:v=1:a=1[vout][aout]")
                else:
                    filter_parts.append("[vm][am][va][aa]concat=n=2:v=1:a=1[vout][aout]")
            else:
                if effective_placement == "start":
                    filter_parts.append("[va][vm]concat=n=2:v=1:a=0[vout]")
                else:
                    filter_parts.append("[vm][va]concat=n=2:v=1:a=0[vout]")

    cmd.extend(["-filter_complex", ";".join(filter_parts), "-map", "[vout]"])
    if any_audio:
        cmd.extend(["-map", "[aout]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"])
    else:
        cmd.append("-an")

    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-movflags",
            "+faststart",
            str(output_path.resolve()),
        ]
    )

    process = subprocess.Popen(
        cmd,
        cwd=str(temp_dir.resolve()),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    stderr_lines: deque[str] = deque(maxlen=60)

    def _drain_stderr() -> None:
        if not process.stderr:
            return
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    if process.stdout:
        for raw_line in process.stdout:
            line = raw_line.strip()
            if line.startswith("out_time_us="):
                try:
                    us = int(line.split("=", 1)[1])
                    elapsed = us / 1_000_000.0
                    pct = min(99.0, max(0.0, (elapsed / max(0.5, total_out_dur)) * 100.0))
                    if progress_cb:
                        progress_cb(pct, f"Menggabungkan Video Affiliate... {elapsed:.1f}s / {total_out_dur:.1f}s")
                except ValueError:
                    pass
            elif line == "progress=end":
                if progress_cb:
                    progress_cb(100.0, "Finalisasi video + affiliate...")

    return_code = process.wait()
    stderr_thread.join(timeout=5)

    if return_code != 0 or not output_path.exists():
        tail = "\n".join(list(stderr_lines)[-20:])
        raise RuntimeError(f"FFmpeg affiliate merge error (exit {return_code}):\n{tail}")

    return output_path
