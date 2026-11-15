from typing import List, Literal, Optional
from pydantic import BaseModel, Field, field_validator


class SystemHealthResponse(BaseModel):
    status: str
    ffmpeg_available: bool
    ffprobe_available: bool
    yt_dlp_available: bool
    ffmpeg_version: Optional[str] = None
    edge_tts_version: Optional[str] = None


class VideoMetadata(BaseModel):
    filename: str
    source_type: Literal["upload", "youtube"]
    title: str
    duration: float
    width: int
    height: int
    fps: float
    has_audio: bool
    size_bytes: int
    url: str


class YoutubeDownloadRequest(BaseModel):
    url: str = Field(..., min_length=8)
    max_height: int = Field(default=1080, ge=360, le=2160)


class StorySplitPreviewRequest(BaseModel):
    story_text: str = ""
    auto_split: bool = True
    max_words_per_part: int = Field(default=120, ge=30, le=350)
    cta_template: str = "Cek profil dan follow untuk lanjut ke Part {next_part}!"
    final_cta: str = ""
    tts_rate: str = "+10%"


class StoryPart(BaseModel):
    part_number: int
    total_parts: int
    text: str
    word_count: int
    estimated_duration: float


class StorySplitPreviewResponse(BaseModel):
    parts: List[StoryPart]
    total_parts: int
    total_words: int


class RenderRequest(BaseModel):
    video_filename: str = Field(..., min_length=1)
    clip_mode: Literal["manual", "auto_random", "auto_part"] = "auto_random"
    start_time: Optional[str] = "00:00:00"
    end_time: Optional[str] = "00:01:00"
    part_duration: float = Field(default=50.0, ge=10.0, le=180.0)
    anti_copyright: bool = False

    include_tts: bool = True
    story_text: str = ""
    auto_split: bool = True
    max_words_per_part: int = Field(default=120, ge=30, le=350)
    cta_template: str = "Cek profil dan follow untuk lanjut ke Part {next_part}!"
    final_cta: str = ""
    voice: Literal["id-ID-ArdiNeural", "id-ID-GadisNeural"] = "id-ID-GadisNeural"
    tts_rate: str = "+10%"

    subtitle_style: Literal["yellow_bold", "white_bold", "karaoke_highlight"] = "karaoke_highlight"
    subtitle_font: Literal["Arial", "Impact", "Segoe UI"] = "Arial"
    subtitle_size: int = Field(default=62, ge=40, le=90)
    words_per_cue: int = Field(default=4, ge=1, le=8)

    bg_audio_enabled: bool = True
    bg_volume: float = Field(default=0.20, ge=0.0, le=1.0)
    hook_enabled: bool = True
    hook_text: str = "Part {part} | Kisah Nyata..."
    hook_duration: float = Field(default=4.0, ge=1.0, le=10.0)
    project_name: str = Field(default="tiktok_story", min_length=1, max_length=80)

    # Thumbnail / Cover options
    generate_thumbnail: bool = True
    thumbnail_title: str = "Part {part} | Kisah Nyata..."
    thumbnail_subtitle: str = "Tonton Sampai Habis"
    thumbnail_style: Literal["tiktok_yellow", "red_warning", "cyan_neon", "clean_white"] = "tiktok_yellow"
    thumbnail_source: Literal["video_frame", "custom_image"] = "video_frame"
    thumbnail_frame_time: float = Field(default=2.0, ge=0.0)
    thumbnail_custom_filename: Optional[str] = None
    insert_cover_intro: bool = False
    cover_intro_duration: float = Field(default=0.8, ge=0.3, le=3.0)

    # Affiliate Video options
    affiliate_enabled: bool = False
    affiliate_filename: Optional[str] = None
    affiliate_placement: Literal["end", "start", "middle", "pip"] = "end"
    affiliate_fit_mode: Literal["fit_blur", "crop"] = "fit_blur"
    affiliate_apply_parts: Literal["all", "last", "first"] = "all"
    affiliate_start_time: Optional[str] = "00:00:00"
    affiliate_end_time: Optional[str] = ""
    affiliate_volume: float = Field(default=1.0, ge=0.0, le=1.5)
    affiliate_pip_start: float = Field(default=3.0, ge=0.0)
    affiliate_cta_text: str = ""

    @field_validator("tts_rate")
    @classmethod
    def validate_tts_rate(cls, v: str) -> str:
        v = v.strip()
        if not v.endswith("%"):
            raise ValueError("tts_rate harus diakhiri '%', contoh '+10%' atau '-5%'")
        if not (v.startswith("+") or v.startswith("-")):
            v = f"+{v}"
        num = int(v[:-1])
        if num < -50 or num > 100:
            raise ValueError("tts_rate harus antara -50% dan +100%")
        return f"{num:+d}%"


class RenderedOutputItem(BaseModel):
    filename: str
    title: str
    part_number: int
    total_parts: int
    duration: float
    size_bytes: int
    created_at: str
    video_url: str
    srt_filename: Optional[str] = None
    srt_url: Optional[str] = None
    thumbnail_filename: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ThumbnailGenerateRequest(BaseModel):
    video_filename: Optional[str] = None
    custom_image_filename: Optional[str] = None
    title: str = "Part 1 | Kisah Nyata..."
    subtitle: str = "Tonton Sampai Habis"
    style: Literal["tiktok_yellow", "red_warning", "cyan_neon", "clean_white"] = "tiktok_yellow"
    source_type: Literal["video_frame", "custom_image"] = "video_frame"
    frame_time: float = Field(default=2.0, ge=0.0)


class ThumbnailResponse(BaseModel):
    thumbnail_url: str
    filename: str
    width: int
    height: int


class JobStatusResponse(BaseModel):
    job_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: float = Field(default=0.0, ge=0.0, le=100.0)
    stage: str
    message: str
    logs: List[str] = Field(default_factory=list)
    outputs: List[RenderedOutputItem] = Field(default_factory=list)
    video_metadata: Optional[VideoMetadata] = None
    error: Optional[str] = None


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    token: Optional[str] = None
    message: str


class AuthStatusResponse(BaseModel):
    auth_required: bool
    logged_in: bool
