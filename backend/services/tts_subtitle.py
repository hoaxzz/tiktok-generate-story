import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List

import edge_tts

from backend.config import TARGET_HEIGHT, TARGET_WIDTH


@dataclass
class WordTiming:
    text: str
    start: float
    end: float


@dataclass
class CaptionCue:
    words: List[WordTiming]
    start: float
    end: float

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class TTSResult:
    audio_path: Path
    srt_path: Path
    ass_path: Path
    duration: float
    word_count: int


def _escape_ass_text(text: str) -> str:
    return (
        text.replace("\\", r"\\")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("\n", r"\N")
    )


def _format_ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_cs = int(round(seconds * 100))
    cs = total_cs % 100
    total_s = total_cs // 100
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _format_srt_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def probe_audio_duration(audio_path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if proc.returncode == 0 and proc.stdout.strip():
        try:
            return float(proc.stdout.strip())
        except ValueError:
            pass
    return 0.0


def _split_sentence_boundary_to_words(text: str, start: float, end: float) -> List[WordTiming]:
    tokens = [t for t in text.strip().split() if t]
    if not tokens:
        return []
    total_chars = sum(max(1, len(t)) for t in tokens)
    total_dur = max(0.08, end - start)
    cursor = start
    out: List[WordTiming] = []
    for i, tok in enumerate(tokens):
        weight = max(1, len(tok)) / total_chars
        dur = total_dur * weight
        w_end = end if i == len(tokens) - 1 else min(end, cursor + dur)
        out.append(WordTiming(text=tok, start=cursor, end=max(cursor + 0.03, w_end)))
        cursor = w_end
    return out


def _group_words_into_cues(words: List[WordTiming], words_per_cue: int = 4) -> List[CaptionCue]:
    if not words:
        return []
    cues: List[CaptionCue] = []
    bucket: List[WordTiming] = []
    max_cue_chars = max(18, min(32, words_per_cue * 7))

    for idx, word in enumerate(words):
        bucket.append(word)
        char_len = sum(len(w.text) for w in bucket) + max(0, len(bucket) - 1)
        next_gap = (words[idx + 1].start - word.end) if idx + 1 < len(words) else 0.0
        ends_sentence = word.text.endswith((".", "!", "?", "…"))
        ends_clause = word.text.endswith((",", ";", ":")) and len(bucket) >= 2

        should_flush = (
            len(bucket) >= words_per_cue
            or char_len >= max_cue_chars
            or ends_sentence
            or ends_clause
            or next_gap > 0.35
            or idx == len(words) - 1
        )
        if should_flush:
            cues.append(
                CaptionCue(
                    words=list(bucket),
                    start=bucket[0].start,
                    end=max(bucket[-1].end, bucket[0].start + 0.15),
                )
            )
            bucket.clear()

    # Prevent any timestamp overlap between sequential cues
    for i in range(len(cues) - 1):
        if cues[i].end > cues[i + 1].start:
            cues[i].end = max(cues[i].start + 0.05, cues[i + 1].start)
        for j in range(len(cues[i].words) - 1):
            if cues[i].words[j].end > cues[i].words[j + 1].start:
                cues[i].words[j].end = max(cues[i].words[j].start + 0.03, cues[i].words[j + 1].start)
        if cues[i].words:
            cues[i].words[-1].end = min(cues[i].words[-1].end, cues[i].end)

    return cues


def _wrap_hook_text(text: str, max_chars_per_line: int = 22) -> str:
    words = text.strip().split()
    if not words:
        return ""
    lines: List[str] = []
    curr: List[str] = []
    for w in words:
        tentative = " ".join(curr + [w])
        if curr and len(tentative) > max_chars_per_line:
            lines.append(" ".join(curr))
            curr = [w]
        else:
            curr.append(w)
    if curr:
        lines.append(" ".join(curr))
    return r"\N".join(_escape_ass_text(line) for line in lines)


def _split_cue_into_lines(words: List[WordTiming], max_chars_per_line: int = 18) -> List[List[int]]:
    """
    Splits word indices in a cue into balanced visual lines so text never overflows horizontally.
    """
    if not words:
        return []
    total_len = sum(len(w.text) for w in words) + max(0, len(words) - 1)
    if total_len <= max_chars_per_line or len(words) == 1:
        return [list(range(len(words)))]

    # Balance across 2 lines when possible
    if len(words) >= 2 and total_len <= max_chars_per_line * 2:
        best_split = 1
        best_diff = 10**9
        for split_idx in range(1, len(words)):
            left_len = sum(len(words[k].text) for k in range(split_idx)) + (split_idx - 1)
            right_len = sum(len(words[k].text) for k in range(split_idx, len(words))) + (len(words) - split_idx - 1)
            if left_len <= max_chars_per_line and right_len <= max_chars_per_line:
                diff = abs(left_len - right_len)
                if diff < best_diff:
                    best_diff = diff
                    best_split = split_idx
        left_len = sum(len(words[k].text) for k in range(best_split)) + (best_split - 1)
        right_len = sum(len(words[k].text) for k in range(best_split, len(words))) + (len(words) - best_split - 1)
        if left_len <= max_chars_per_line and right_len <= max_chars_per_line:
            return [list(range(0, best_split)), list(range(best_split, len(words)))]

    # Greedy multi-line fallback
    lines: List[List[int]] = []
    curr: List[int] = []
    curr_len = 0
    for idx, w in enumerate(words):
        added = len(w.text) + (1 if curr else 0)
        if curr and (curr_len + added > max_chars_per_line):
            lines.append(curr)
            curr = [idx]
            curr_len = len(w.text)
        else:
            curr.append(idx)
            curr_len += added
    if curr:
        lines.append(curr)
    return lines


def build_ass_content(
    cues: List[CaptionCue],
    subtitle_style: str = "karaoke_highlight",
    subtitle_font: str = "Arial",
    subtitle_size: int = 62,
    hook_enabled: bool = False,
    hook_text: str = "",
    hook_duration: float = 4.0,
) -> str:
    font_name = subtitle_font if subtitle_font in ("Arial", "Impact", "Segoe UI") else "Arial"
    font_size = max(40, min(90, int(subtitle_size)))
    outline_px = max(4, round(font_size / 12))
    # Safe max characters per line for 1080px width minus MarginL(95)+MarginR(95) = 890px
    max_chars_per_line = max(13, min(26, int(1120 / font_size)))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {TARGET_WIDTH}
PlayResY: {TARGET_HEIGHT}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: MainYellow,{font_name},{font_size},&H0000E6FF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,0.5,0,1,{outline_px},2,5,95,95,0,1
Style: MainWhite,{font_name},{font_size},&H00FFFFFF,&H0000E6FF,&H00000000,&H90000000,-1,0,0,0,100,100,0.5,0,1,{outline_px},2,5,95,95,0,1
Style: HookBox,{font_name},46,&H00FFFFFF,&H0000E6FF,&H2810101A,&H00000000,-1,0,0,0,100,100,0.5,0,3,14,0,8,95,95,200,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events: List[str] = []

    if hook_enabled and hook_text.strip():
        hook_end = _format_ass_time(max(1.0, hook_duration))
        wrapped = _wrap_hook_text(hook_text.strip(), max_chars_per_line=22)
        events.append(f"Dialogue: 2,0:00:00.00,{hook_end},HookBox,,0,0,0,,{wrapped}")

    for cue in cues:
        if not cue.words:
            continue
        line_groups = _split_cue_into_lines(cue.words, max_chars_per_line=max_chars_per_line)

        if subtitle_style == "karaoke_highlight":
            for active_idx, active_word in enumerate(cue.words):
                seg_start = cue.start if active_idx == 0 else active_word.start
                seg_end = (
                    cue.words[active_idx + 1].start
                    if active_idx + 1 < len(cue.words)
                    else cue.end
                )
                seg_end = max(seg_start + 0.04, seg_end)

                rendered_lines: List[str] = []
                for idx_group in line_groups:
                    line_tokens: List[str] = []
                    for j in idx_group:
                        safe_w = _escape_ass_text(cue.words[j].text)
                        if j == active_idx:
                            line_tokens.append(
                                r"{\c&H0000E6FF&\fscx106\fscy106}"
                                + safe_w
                                + r"{\c&H00FFFFFF&\fscx100\fscy100}"
                            )
                        else:
                            line_tokens.append(safe_w)
                    rendered_lines.append(" ".join(line_tokens))

                line_text = r"\N".join(rendered_lines)
                events.append(
                    f"Dialogue: 1,{_format_ass_time(seg_start)},{_format_ass_time(seg_end)},MainWhite,,0,0,0,,{line_text}"
                )
        else:
            style_name = "MainWhite" if subtitle_style == "white_bold" else "MainYellow"
            rendered_lines = [
                " ".join(_escape_ass_text(cue.words[j].text) for j in idx_group)
                for idx_group in line_groups
            ]
            line_text = r"\N".join(rendered_lines)
            events.append(
                f"Dialogue: 1,{_format_ass_time(cue.start)},{_format_ass_time(cue.end)},{style_name},,0,0,0,,{line_text}"
            )

    return header + "\n".join(events) + "\n"


def build_srt_content(cues: List[CaptionCue]) -> str:
    blocks: List[str] = []
    for idx, cue in enumerate(cues, start=1):
        blocks.append(
            f"{idx}\n{_format_srt_time(cue.start)} --> {_format_srt_time(cue.end)}\n{cue.text}\n"
        )
    return "\n".join(blocks)


async def generate_tts_and_subtitles(
    text: str,
    voice: str,
    tts_rate: str,
    output_dir: Path,
    basename: str,
    subtitle_style: str = "karaoke_highlight",
    subtitle_font: str = "Arial",
    subtitle_size: int = 62,
    words_per_cue: int = 4,
    hook_enabled: bool = False,
    hook_text: str = "",
    hook_duration: float = 4.0,
) -> TTSResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{basename}.mp3"
    srt_path = output_dir / f"{basename}.srt"
    ass_path = output_dir / f"{basename}.ass"

    cleaned_text = re.sub(r"\s+", " ", text.strip())
    if not cleaned_text:
        raise ValueError("Naskah cerita tidak boleh kosong saat mode TTS aktif.")

    try:
        communicate = edge_tts.Communicate(
            text=cleaned_text,
            voice=voice,
            rate=tts_rate,
            boundary="WordBoundary",
        )
    except TypeError:
        communicate = edge_tts.Communicate(
            text=cleaned_text,
            voice=voice,
            rate=tts_rate,
        )

    submaker = edge_tts.SubMaker()
    word_timings: List[WordTiming] = []
    sentence_timings: List[dict] = []

    with open(audio_path, "wb") as audio_file:
        async for chunk in communicate.stream():
            chunk_type = chunk.get("type")
            if chunk_type == "audio":
                audio_file.write(chunk["data"])
            elif chunk_type == "WordBoundary":
                if hasattr(submaker, "feed"):
                    submaker.feed(chunk)
                elif hasattr(submaker, "create_sub"):
                    submaker.create_sub((chunk["offset"], chunk["duration"]), chunk["text"])
                start_s = chunk["offset"] / 10_000_000.0
                dur_s = max(0.05, chunk["duration"] / 10_000_000.0)
                chunk_text = chunk["text"].strip()
                if " " in chunk_text:
                    word_timings.extend(
                        _split_sentence_boundary_to_words(chunk_text, start_s, start_s + dur_s)
                    )
                elif chunk_text:
                    word_timings.append(
                        WordTiming(
                            text=chunk_text,
                            start=start_s,
                            end=start_s + dur_s,
                        )
                    )
            elif chunk_type == "SentenceBoundary":
                sentence_timings.append(chunk)

    if not word_timings and sentence_timings:
        for sb in sentence_timings:
            if hasattr(submaker, "feed"):
                submaker.feed(sb)
            start_s = sb["offset"] / 10_000_000.0
            dur_s = max(0.2, sb["duration"] / 10_000_000.0)
            word_timings.extend(_split_sentence_boundary_to_words(sb["text"], start_s, start_s + dur_s))

    audio_duration = probe_audio_duration(audio_path)
    if audio_duration <= 0 and word_timings:
        audio_duration = word_timings[-1].end + 0.3

    if not word_timings and audio_duration > 0:
        word_timings = _split_sentence_boundary_to_words(cleaned_text, 0.1, max(0.5, audio_duration - 0.1))

    cues = _group_words_into_cues(word_timings, words_per_cue=words_per_cue)

    if cues:
        srt_text = build_srt_content(cues)
    elif hasattr(submaker, "get_srt"):
        srt_text = submaker.get_srt()
    else:
        srt_text = submaker.generate_subs()

    srt_path.write_text(srt_text, encoding="utf-8")

    ass_text = build_ass_content(
        cues=cues,
        subtitle_style=subtitle_style,
        subtitle_font=subtitle_font,
        subtitle_size=subtitle_size,
        hook_enabled=hook_enabled,
        hook_text=hook_text,
        hook_duration=hook_duration,
    )
    ass_path.write_text(ass_text, encoding="utf-8")

    return TTSResult(
        audio_path=audio_path,
        srt_path=srt_path,
        ass_path=ass_path,
        duration=round(audio_duration, 3),
        word_count=len(word_timings),
    )


def generate_hook_only_ass(
    ass_path: Path,
    hook_text: str,
    hook_duration: float = 4.0,
    subtitle_font: str = "Arial",
) -> Path:
    ass_text = build_ass_content(
        cues=[],
        subtitle_style="yellow_bold",
        subtitle_font=subtitle_font,
        hook_enabled=True,
        hook_text=hook_text,
        hook_duration=hook_duration,
    )
    ass_path.write_text(ass_text, encoding="utf-8")
    return ass_path
