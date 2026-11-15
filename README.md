# TikTok Story & Satisfying Clipper Studio

Aplikasi web lokal berbasis **FastAPI + FFmpeg + yt-dlp + edge-tts** untuk memotong video *satisfying* berdurasi panjang menjadi video vertikal **9:16 (1080×1920)** sekaligus menggabungkannya dengan narasi cerita Bahasa Indonesia (*Text-to-Speech*), subtitle otomatis bergaya TikTok (`.ass`/`.srt`), teks Hook awal, dan mixing audio ASMR.

## Struktur Folder

```text
.
├── backend/
│   ├── main.py                  # FastAPI server & REST/SSE endpoints
│   ├── config.py                # Konfigurasi direktori, suara, resolusi & filter
│   ├── models.py                # Skema Pydantic request/response
│   └── services/
│       ├── media_utils.py       # Deteksi FFmpeg, ffprobe metadata, downloader yt-dlp
│       ├── story_splitter.py    # Pemecah cerita panjang otomatis + CTA antar part
│       ├── tts_subtitle.py      # Sintesis suara edge-tts & generator subtitle .SRT/.ASS
│       ├── video_renderer.py    # Pipeline FFmpeg (9:16 crop, anti-copyright, burn ASS, audio mix)
│       └── job_manager.py       # Pengelola antrean job & streaming progress real-time
├── frontend/
│   ├── index.html               # UI Studio Dark Mode (Tailwind CSS)
│   └── app.js                   # Logika antarmuka, preview player, & SSE progress
├── uploads/                     # Video sumber (upload lokal & unduhan YouTube)
├── outputs/                     # Video hasil render (.mp4), subtitle (.srt), & metadata
├── temp/                        # File sementara per job (otomatis dibersihkan)
├── requirements.txt
└── run.py                       # Script praktis menjalankan server
```

## Prasyarat: Memastikan FFmpeg Terdeteksi di Sistem

Aplikasi ini membutuhkan `ffmpeg` dan `ffprobe` yang dapat dipanggil dari terminal (`PATH`).

1. Cek apakah FFmpeg sudah terpasang:
   ```powershell
   ffmpeg -version
   ffprobe -version
   ```
2. Jika belum terpasang di Windows:
   - Menggunakan **winget**:
     ```powershell
     winget install Gyan.FFmpeg
     ```
   - Atau unduh build dari `gyan.dev/ffmpeg/builds/`, ekstrak ke `C:\ffmpeg`, lalu tambahkan `C:\ffmpeg\bin` ke **Environment Variables → Path** dan buka ulang terminal.

## Cara Menjalankan Server

1. Buat & aktifkan virtual environment (opsional tapi disarankan):
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Instal dependensi Python:
   ```powershell
   pip install -r requirements.txt
   ```
3. Jalankan server FastAPI:
   ```powershell
   python run.py
   ```
   Atau langsung via Uvicorn:
   ```powershell
   uvicorn backend.main:app --host 127.0.0.1 --port 8000 --reload
   ```
4. Buka browser dan akses:
   ```
   http://127.0.0.1:8000
   ```

Di pojok kanan atas UI, indikator **FFmpeg Ready**, **yt-dlp OK**, dan **edge-tts** akan otomatis memverifikasi bahwa seluruh komponen siap digunakan.
