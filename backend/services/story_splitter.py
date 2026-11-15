import re
from typing import List

from backend.models import StoryPart


def _rate_to_multiplier(tts_rate: str) -> float:
    raw = tts_rate.strip().rstrip("%")
    try:
        pct = float(raw)
    except ValueError:
        pct = 0.0
    return max(0.5, min(2.0, 1.0 + pct / 100.0))


def estimate_tts_duration(text: str, tts_rate: str = "+10%") -> float:
    words = len(re.findall(r"\S+", text))
    if words == 0:
        return 0.0
    # Indonesian edge-tts baseline ~2.45 words/sec at +0%
    words_per_sec = 2.45 * _rate_to_multiplier(tts_rate)
    return round(max(1.5, words / words_per_sec), 1)


def _split_into_sentences(text: str) -> List[str]:
    normalized = re.sub(r"\r\n|\r", "\n", text.strip())
    paragraphs = [p.strip() for p in normalized.split("\n") if p.strip()]
    sentences: List[str] = []
    for para in paragraphs:
        chunks = re.split(r"(?<=[.!?…])\s+", para)
        for chunk in chunks:
            c = chunk.strip()
            if c:
                sentences.append(c)
    return sentences


def _split_long_sentence(sentence: str, max_words: int) -> List[str]:
    words = sentence.split()
    if len(words) <= max_words:
        return [sentence]
    result: List[str] = []
    for i in range(0, len(words), max_words):
        result.append(" ".join(words[i : i + max_words]))
    return result


def split_story_into_parts(
    story_text: str,
    auto_split: bool = True,
    max_words_per_part: int = 120,
    cta_template: str = "Cek profil dan follow untuk lanjut ke Part {next_part}!",
    final_cta: str = "",
    tts_rate: str = "+10%",
) -> List[StoryPart]:
    cleaned = story_text.strip()
    if not cleaned:
        return []

    if not auto_split:
        words = len(re.findall(r"\S+", cleaned))
        return [
            StoryPart(
                part_number=1,
                total_parts=1,
                text=cleaned,
                word_count=words,
                estimated_duration=estimate_tts_duration(cleaned, tts_rate),
            )
        ]

    raw_sentences = _split_into_sentences(cleaned)
    sentences: List[str] = []
    for s in raw_sentences:
        sentences.extend(_split_long_sentence(s, max_words_per_part))

    buckets: List[List[str]] = []
    current_bucket: List[str] = []
    current_words = 0

    for sentence in sentences:
        s_words = len(sentence.split())
        if current_bucket and (current_words + s_words > max_words_per_part):
            buckets.append(current_bucket)
            current_bucket = [sentence]
            current_words = s_words
        else:
            current_bucket.append(sentence)
            current_words += s_words

    if current_bucket:
        buckets.append(current_bucket)

    total_parts = len(buckets)
    parts: List[StoryPart] = []

    for idx, bucket in enumerate(buckets, start=1):
        part_body = " ".join(bucket).strip()
        if total_parts > 1 and idx < total_parts and cta_template.strip():
            cta = cta_template.strip().format(
                next_part=idx + 1,
                current_part=idx,
                total_parts=total_parts,
            )
            if not part_body.endswith((".", "!", "?", "…")):
                part_body += "."
            part_body = f"{part_body} {cta}"
        elif idx == total_parts and final_cta.strip():
            cta = final_cta.strip().format(
                current_part=idx,
                total_parts=total_parts,
                next_part=1,
            )
            if not part_body.endswith((".", "!", "?", "…")):
                part_body += "."
            part_body = f"{part_body} {cta}"

        word_count = len(re.findall(r"\S+", part_body))
        parts.append(
            StoryPart(
                part_number=idx,
                total_parts=total_parts,
                text=part_body,
                word_count=word_count,
                estimated_duration=estimate_tts_duration(part_body, tts_rate),
            )
        )

    return parts
