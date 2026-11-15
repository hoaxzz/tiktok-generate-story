import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from backend.config import TARGET_HEIGHT, TARGET_WIDTH


def _get_font(font_names: List[str], size: int) -> ImageFont.FreeTypeFont:
    candidate_dirs = [
        Path("C:/Windows/Fonts"),
        Path("/usr/share/fonts/truetype"),
        Path("/usr/share/fonts"),
        Path("/usr/local/share/fonts"),
    ]
    for name in font_names:
        for cdir in candidate_dirs:
            p = cdir / name
            if p.exists():
                try:
                    return ImageFont.truetype(str(p), size)
                except Exception:
                    pass
        # Try direct name resolution via fontconfig / PIL
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass

    # Linux & universal fallbacks
    fallbacks = [
        "DejaVuSans-Bold.ttf",
        "LiberationSans-Bold.ttf",
        "FreeSansBold.ttf",
        "arialbd.ttf",
        "arial.ttf",
        "Arial.ttf",
    ]
    for fb in fallbacks:
        for cdir in candidate_dirs:
            if (cdir / fb).exists():
                try:
                    return ImageFont.truetype(str(cdir / fb), size)
                except Exception:
                    pass
        try:
            return ImageFont.truetype(fb, size)
        except Exception:
            pass

    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    words = text.split()
    if not words:
        return []
    lines: List[str] = []
    current_line: List[str] = []

    for word in words:
        test_line = " ".join(current_line + [word])
        bbox = draw.textbbox((0, 0), test_line, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width or not current_line:
            current_line.append(word)
        else:
            lines.append(" ".join(current_line))
            current_line = [word]

    if current_line:
        lines.append(" ".join(current_line))
    return lines


def _extract_video_frame(video_path: Path, frame_time: float, temp_out: Path) -> bool:
    if not video_path.exists():
        return False
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-ss",
        f"{max(0.0, frame_time):.3f}",
        "-i",
        str(video_path.resolve()),
        "-vframes",
        "1",
        "-vf",
        f"scale={TARGET_WIDTH}:{TARGET_HEIGHT}:force_original_aspect_ratio=increase,crop={TARGET_WIDTH}:{TARGET_HEIGHT},setsar=1",
        "-q:v",
        "2",
        str(temp_out.resolve()),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return proc.returncode == 0 and temp_out.exists()


def generate_thumbnail_image(
    output_path: Path,
    title: str,
    subtitle: str = "",
    style: str = "tiktok_yellow",
    video_path: Optional[Path] = None,
    custom_image_path: Optional[Path] = None,
    frame_time: float = 2.0,
) -> Path:
    """
    Generates a 1080x1920 vertical thumbnail optimized for TikTok and YouTube Shorts covers.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_img: Optional[Image.Image] = None

    # Step 1: Base background image
    if custom_image_path and custom_image_path.exists():
        try:
            raw_img = Image.open(custom_image_path).convert("RGB")
            # Scale & crop to 1080x1920
            w, h = raw_img.size
            scale = max(TARGET_WIDTH / w, TARGET_HEIGHT / h)
            nw, nh = int(w * scale), int(h * scale)
            resized = raw_img.resize((nw, nh), Image.Resampling.LANCZOS)
            x_left = (nw - TARGET_WIDTH) // 2
            y_top = (nh - TARGET_HEIGHT) // 2
            base_img = resized.crop((x_left, y_top, x_left + TARGET_WIDTH, y_top + TARGET_HEIGHT))
        except Exception:
            base_img = None

    if base_img is None and video_path and video_path.exists():
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_p = Path(tmp.name)
        try:
            if _extract_video_frame(video_path, frame_time, tmp_p):
                base_img = Image.open(tmp_p).convert("RGB")
        except Exception:
            base_img = None
        finally:
            tmp_p.unlink(missing_ok=True)

    if base_img is None:
        # Fallback aesthetic dark gradient
        base_img = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (16, 16, 24))
        draw_fb = ImageDraw.Draw(base_img)
        for y in range(TARGET_HEIGHT):
            ratio = y / TARGET_HEIGHT
            r = int(14 + 18 * ratio)
            g = int(14 + 20 * ratio)
            b = int(24 + 36 * ratio)
            draw_fb.line([(0, y), (TARGET_WIDTH, y)], fill=(r, g, b))

    # Step 2: Overlay contrast vignette to ensure text readability
    overlay = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0, 0))
    d_ov = ImageDraw.Draw(overlay)

    # Darken middle section where text sits
    text_center_y = int(TARGET_HEIGHT * 0.44)
    for y in range(TARGET_HEIGHT):
        dist = abs(y - text_center_y) / (TARGET_HEIGHT * 0.42)
        if dist < 1.0:
            alpha = int(120 * (1.0 - dist * 0.5))
            d_ov.line([(0, y), (TARGET_WIDTH, y)], fill=(0, 0, 0, min(140, alpha)))

    # Composite base image + dark overlay
    base_img = Image.alpha_composite(base_img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(base_img, "RGBA")

    # Step 3: Typography & Colors based on style
    # Fonts
    font_title = _get_font(["impact.ttf", "arialbd.ttf"], 76)
    font_badge = _get_font(["arialbd.ttf", "segoeuib.ttf"], 36)
    font_sub = _get_font(["arialbd.ttf", "segoeuib.ttf"], 34)

    # Style definitions
    # Available: tiktok_yellow, red_warning, cyan_neon, clean_white
    style = style if style in ("tiktok_yellow", "red_warning", "cyan_neon", "clean_white") else "tiktok_yellow"

    clean_title = title.strip() or "TIKTOK STORY"
    clean_sub = subtitle.strip()

    # Wrap title
    max_line_width = TARGET_WIDTH - 140
    lines = _wrap_text(clean_title, font_title, max_line_width, draw)
    if not lines:
        lines = [clean_title]
    if len(lines) > 4:
        # If too many lines, slightly smaller font
        font_title = _get_font(["impact.ttf", "arialbd.ttf"], 64)
        lines = _wrap_text(clean_title, font_title, max_line_width, draw)

    # Measure total height of title block
    line_metrics: List[Tuple[str, int, int]] = []
    total_title_h = 0
    line_gap = 18

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font_title)
        lw = bbox[2] - bbox[0]
        lh = bbox[3] - bbox[1]
        line_metrics.append((line, lw, lh))
        total_title_h += lh + line_gap
    total_title_h -= line_gap

    # Placement coordinates (upper-middle of 9:16 screen, safe from TikTok UI)
    badge_h = 60 if clean_sub else 0
    start_y = int(TARGET_HEIGHT * 0.36) - (total_title_h // 2)
    if clean_sub:
        start_y += 30

    # Draw Badge / Pill (Tagline on top of title)
    if clean_sub:
        b_bbox = draw.textbbox((0, 0), clean_sub.upper(), font=font_badge)
        b_w = b_bbox[2] - b_bbox[0]
        b_h = b_bbox[3] - b_bbox[1]
        badge_y = start_y - b_h - 40
        badge_x = (TARGET_WIDTH - b_w) // 2

        pad_x = 26
        pad_y = 12
        b_box = [badge_x - pad_x, badge_y - pad_y, badge_x + b_w + pad_x, badge_y + b_h + pad_y]

        if style == "tiktok_yellow":
            draw.rounded_rectangle(b_box, radius=20, fill=(255, 230, 0, 255))
            draw.text((badge_x, badge_y), clean_sub.upper(), font=font_badge, fill=(0, 0, 0, 255))
        elif style == "red_warning":
            draw.rounded_rectangle(b_box, radius=20, fill=(235, 28, 56, 255))
            draw.text((badge_x, badge_y), clean_sub.upper(), font=font_badge, fill=(255, 255, 255, 255))
        elif style == "cyan_neon":
            draw.rounded_rectangle(b_box, radius=20, fill=(10, 10, 15, 230), outline=(0, 242, 254, 255), width=3)
            draw.text((badge_x, badge_y), clean_sub.upper(), font=font_badge, fill=(0, 242, 254, 255))
        else:  # clean_white
            draw.rounded_rectangle(b_box, radius=20, fill=(24, 24, 30, 220), outline=(255, 255, 255, 180), width=2)
            draw.text((badge_x, badge_y), clean_sub.upper(), font=font_badge, fill=(255, 255, 255, 255))

    # Draw Title Lines
    curr_y = start_y
    for line, lw, lh in line_metrics:
        lx = (TARGET_WIDTH - lw) // 2
        pad_x = 24
        pad_y = 12
        line_box = [lx - pad_x, curr_y - pad_y, lx + lw + pad_x, curr_y + lh + pad_y]

        if style == "tiktok_yellow":
            # Yellow banner with black bold text
            draw.rounded_rectangle(line_box, radius=16, fill=(255, 230, 0, 255))
            draw.text((lx, curr_y), line, font=font_title, fill=(0, 0, 0, 255))
        elif style == "red_warning":
            # Red banner with white bold text + dark shadow
            draw.rounded_rectangle(
                [line_box[0] + 6, line_box[1] + 6, line_box[2] + 6, line_box[3] + 6],
                radius=16,
                fill=(0, 0, 0, 180),
            )
            draw.rounded_rectangle(line_box, radius=16, fill=(225, 29, 72, 255))
            draw.text((lx, curr_y), line, font=font_title, fill=(255, 255, 255, 255))
        elif style == "cyan_neon":
            # Dark backing with neon cyan glow/border + cyan text
            draw.rounded_rectangle(line_box, radius=16, fill=(9, 9, 14, 240), outline=(0, 242, 254, 255), width=3)
            draw.text((lx, curr_y), line, font=font_title, fill=(0, 242, 254, 255))
        else:  # clean_white
            # White text with thick dark outline & strong drop shadow
            draw.rounded_rectangle(line_box, radius=16, fill=(15, 15, 20, 210))
            draw.text(
                (lx, curr_y),
                line,
                font=font_title,
                fill=(255, 255, 255, 255),
                stroke_width=4,
                stroke_fill=(0, 0, 0, 255),
            )

        curr_y += lh + line_gap

    # Footer Indicator: e.g. "TIKTOK VIRAL • 9:16"
    footer_text = "SWIPE UNTUK LANJUTAN  ▶"
    f_bbox = draw.textbbox((0, 0), footer_text, font=font_sub)
    fw = f_bbox[2] - f_bbox[0]
    fh = f_bbox[3] - f_bbox[1]
    fy = curr_y + 36
    fx = (TARGET_WIDTH - fw) // 2
    f_box = [fx - 22, fy - 10, fx + fw + 22, fy + fh + 12]
    draw.rounded_rectangle(f_box, radius=16, fill=(0, 0, 0, 160))
    draw.text((fx, fy), footer_text, font=font_sub, fill=(220, 220, 230, 255))

    # Save finalized thumbnail as high-res JPG
    base_img.convert("RGB").save(str(output_path.resolve()), "JPEG", quality=95, optimize=True)
    return output_path


def generate_cta_badge_png(output_path: Path, cta_text: str, y_center: int = 1420) -> Optional[Path]:
    """
    Generates a transparent 1080x1920 PNG containing a vibrant TikTok-safe affiliate CTA pill badge.
    """
    clean = (cta_text or "").strip()
    if not clean:
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas = Image.new("RGBA", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")

    font = _get_font(["arialbd.ttf", "segoeuib.ttf", "impact.ttf"], 42)
    lines = _wrap_text(clean, font, TARGET_WIDTH - 180, draw)
    if not lines:
        return None
    if len(lines) > 2:
        font = _get_font(["arialbd.ttf", "segoeuib.ttf"], 34)
        lines = _wrap_text(clean, font, TARGET_WIDTH - 160, draw)[:2]

    line_metrics: List[Tuple[str, int, int]] = []
    max_w = 0
    total_h = 0
    gap = 10
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=font)
        lw = bb[2] - bb[0]
        lh = bb[3] - bb[1]
        line_metrics.append((ln, lw, lh))
        max_w = max(max_w, lw)
        total_h += lh + gap
    total_h -= gap

    pad_x = 38
    pad_y = 20
    box_w = max_w + pad_x * 2
    box_h = total_h + pad_y * 2
    x0 = (TARGET_WIDTH - box_w) // 2
    y0 = y_center - box_h // 2

    # Drop shadow
    draw.rounded_rectangle(
        [x0 + 6, y0 + 8, x0 + box_w + 6, y0 + box_h + 8],
        radius=28,
        fill=(0, 0, 0, 175),
    )
    # Bright TikTok Yellow-Orange pill with bold dark text + subtle cyan border
    draw.rounded_rectangle(
        [x0, y0, x0 + box_w, y0 + box_h],
        radius=28,
        fill=(255, 222, 0, 245),
        outline=(255, 255, 255, 230),
        width=3,
    )

    curr_y = y0 + pad_y
    for ln, lw, lh in line_metrics:
        lx = (TARGET_WIDTH - lw) // 2
        draw.text((lx, curr_y), ln, font=font, fill=(15, 15, 20, 255))
        curr_y += lh + gap

    canvas.save(str(output_path.resolve()), "PNG")
    return output_path
