(() => {
  const SAMPLE_STORIES = {
    horor: {
      text: "Malam itu hujan turun sangat deras ketika aku terpaksa lembur sendirian di lantai empat kantor lama. Jam sudah menunjukkan pukul sebelas malam, dan semua lampu lorong sengaja dimatikan oleh satpam. Tiba-tiba, suara ketikan keyboard terdengar sangat cepat dari ruang rapat di ujung koridor. Padahal aku yakin seratus persen seluruh tim sudah pulang sejak pukul enam sore. Dengan langkah pelan aku mengintip lewat kaca buram ruang rapat tersebut. Di kursi paling pojok, ada seseorang menunduk menatap layar monitor yang mati total, lalu perlahan kepalanya menoleh ke arahku sambil tersenyum lebar. Sejak malam itu, aku tidak pernah berani mengambil lembur sendirian lagi, apalagi setelah satpam mengaku ruang rapat itu sudah dikunci rapat sejak tiga bulan lalu.",
      hook: "Part {part} | Lembur Horor Kantor Tua",
      tag: "KISAH NYATA",
    },
    fakta: {
      text: "Tahukah kamu bahwa gurita ternyata memiliki tiga jantung dan sembilan otak yang bekerja bersamaan? Dua jantung bertugas memompa darah menuju insang, sementara satu jantung utama mengalirkan darah ke seluruh tubuhnya. Uniknya lagi, saat gurita berenang cepat, jantung utamanya justru berhenti berdetak sementara sehingga mereka lebih suka merangkak di dasar laut agar tidak cepat kelelahan. Tidak hanya itu, delapan lengan gurita masing-masing memiliki gugus saraf mandiri yang bisa mengambil keputusan sendiri tanpa menunggu perintah dari otak pusat. Itulah sebabnya gurita dianggap sebagai salah satu makhluk laut paling cerdas dan misterius yang pernah diteliti ilmuwan.",
      hook: "Part {part} | Rahasia 3 Jantung Gurita",
      tag: "FAKTA UNIK",
    },
    curhat: {
      text: "Jujur, dulu aku sempat merasa tertinggal jauh saat melihat teman-teman seusiaku sudah mapan, punya kendaraan sendiri, dan sering liburan ke luar negeri. Setiap malam rasanya penuh perbandingan yang bikin dada sesak tanpa alasan jelas. Sampai suatu hari aku sadar bahwa setiap orang punya garis start, beban tanggungan, dan waktu mekarnya masing-masing. Pelan-pelan aku berhenti membandingkan hidupku dengan potongan terbaik orang lain di media sosial, lalu fokus memperbaiki satu hal kecil setiap hari. Ternyata ketenangan itu datang bukan saat kita memiliki segalanya, melainkan saat kita berani menghargai sejauh mana diri sendiri sudah bertahan.",
      hook: "Part {part} | Berhenti Bandingkan Hidupmu",
      tag: "SELF IMPROVEMENT",
    },
  };

  let selectedVideo = null;
  let libraryVideos = [];
  let affiliateVideos = [];
  let selectedAffiliate = null;
  let activeStream = null;
  let uploadedCustomCoverFilename = null;

  const $ = (id) => document.getElementById(id);

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let idx = 0;
    let val = bytes;
    while (val >= 1024 && idx < units.length - 1) {
      val /= 1024;
      idx++;
    }
    return `${val.toFixed(idx >= 2 ? 2 : 0)} ${units[idx]}`;
  }

  function formatSec(sec) {
    const s = Math.max(0, Math.round(sec || 0));
    const m = Math.floor(s / 60);
    const rem = s % 60;
    return m > 0 ? `${m}m ${String(rem).padStart(2, "0")}d` : `${rem}d`;
  }

  // Health Check
  async function loadHealth() {
    try {
      const res = await fetch("/api/health");
      const data = await res.json();
      const badges = [];
      badges.push(
        data.ffmpeg_available
          ? `<span class="px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30 font-medium">FFmpeg Ready</span>`
          : `<span class="px-2.5 py-1 rounded-full bg-red-500/15 text-red-400 border border-red-500/30 font-medium">FFmpeg Tidak Terdeteksi!</span>`
      );
      badges.push(
        `<span class="px-2.5 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-zinc-300">yt-dlp ${data.yt_dlp_available ? "OK" : "Missing"}</span>`
      );
      badges.push(
        `<span class="px-2.5 py-1 rounded-full bg-zinc-900 border border-zinc-800 text-zinc-300">edge-tts ${esc(data.edge_tts_version || "")}</span>`
      );
      $("healthBadges").innerHTML = badges.join("");
    } catch {
      $("healthBadges").innerHTML =
        `<span class="px-2.5 py-1 rounded-full bg-red-500/15 text-red-400 border border-red-500/30">Backend Offline</span>`;
    }
  }

  // Source Tabs
  function switchSourceTab(target) {
    document.querySelectorAll(".source-tab-btn").forEach((b) => {
      const active = b.dataset.sourceTab === target;
      b.classList.toggle("bg-zinc-800", active);
      b.classList.toggle("text-white", active);
      b.classList.toggle("text-zinc-400", !active);
    });
    $("tabUpload").classList.toggle("hidden", target !== "upload");
    $("tabYoutube").classList.toggle("hidden", target !== "youtube");
    $("tabLibrary").classList.toggle("hidden", target !== "library");
  }

  document.querySelectorAll(".source-tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => switchSourceTab(btn.dataset.sourceTab));
  });

  $("openLibraryTabBtn")?.addEventListener("click", () => {
    switchSourceTab("library");
    const libTabBtn = document.querySelector('.source-tab-btn[data-source-tab="library"]');
    if (libTabBtn) libTabBtn.scrollIntoView({ behavior: "smooth", block: "nearest" });
  });

  // Select Video function
  function selectVideo(meta) {
    if (!meta) return;
    selectedVideo = meta;

    const dropdown = $("videoSelectDropdown");
    if (dropdown && dropdown.value !== meta.filename) {
      dropdown.value = meta.filename;
    }

    const detailCard = $("selectedVideoDetailCard");
    if (detailCard) detailCard.classList.remove("hidden");

    $("selectedVideoTitle").textContent = meta.title || meta.filename;
    $("selectedVideoMeta").textContent = `${meta.width}×${meta.height} • ${formatSec(meta.duration)} • ${meta.fps} fps • ${
      meta.has_audio ? "Ada Audio" : "Tanpa Audio"
    } • ${formatBytes(meta.size_bytes)}`;

    renderLibraryList();
    updateLiveMockPreview();
  }

  // Populate Dropdown
  function populateVideoDropdown() {
    const dropdown = $("videoSelectDropdown");
    if (!dropdown) return;

    if (!libraryVideos.length) {
      dropdown.innerHTML = `<option value="">-- Belum ada video, silakan upload atau unduh dari YouTube --</option>`;
      return;
    }

    dropdown.innerHTML = libraryVideos
      .map((v) => {
        const title = v.title || v.filename;
        const info = `${formatSec(v.duration)} • ${v.width}x${v.height} • ${formatBytes(v.size_bytes)}`;
        return `<option value="${esc(v.filename)}">${esc(title)} (${esc(info)})</option>`;
      })
      .join("");

    if (selectedVideo) {
      dropdown.value = selectedVideo.filename;
    }
  }

  // Dropdown Change Listener
  $("videoSelectDropdown").addEventListener("change", (e) => {
    const fname = e.target.value;
    const found = libraryVideos.find((v) => v.filename === fname);
    if (found) {
      selectVideo(found);
    }
  });

  // Load Library from Backend
  async function loadLibrary() {
    try {
      const res = await fetch("/api/videos");
      libraryVideos = await res.json();

      const countStr = String(libraryVideos.length);
      $("libraryCount").textContent = countStr;
      const badgeEl = $("libraryVideosBadge");
      if (badgeEl) {
        badgeEl.textContent = `${countStr} Video Tersimpan`;
      }

      populateVideoDropdown();

      if (libraryVideos.length > 0) {
        if (!selectedVideo || !libraryVideos.some((v) => v.filename === selectedVideo.filename)) {
          selectVideo(libraryVideos[0]);
        } else {
          selectVideo(selectedVideo);
        }
      } else {
        selectedVideo = null;
        $("selectedVideoDetailCard")?.classList.add("hidden");
        renderLibraryList();
      }
    } catch {
      $("libraryList").innerHTML = `<div class="text-red-400">Gagal memuat library video.</div>`;
    }
  }

  // Render Library List items
  function renderLibraryList() {
    const container = $("libraryList");
    if (!libraryVideos.length) {
      container.innerHTML = `<div class="text-zinc-500 py-4 text-center">Belum ada video di library. Silakan upload atau unduh dari YouTube. Semua video yang diunduh akan otomatis tersimpan di sini.</div>`;
      return;
    }
    container.innerHTML = libraryVideos
      .map((v) => {
        const isSelected = selectedVideo && selectedVideo.filename === v.filename;
        return `
          <div class="flex items-center justify-between gap-2 p-3 rounded-xl border transition ${
            isSelected ? "border-tiktokCyan bg-tiktokCyan/10 shadow-sm shadow-tiktokCyan/10" : "border-zinc-800 bg-zinc-950/70 hover:border-zinc-700"
          }">
            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                ${isSelected ? '<span class="w-2 h-2 rounded-full bg-tiktokCyan animate-pulse"></span>' : ""}
                <div class="font-medium text-zinc-100 truncate text-xs sm:text-sm">${esc(v.title || v.filename)}</div>
              </div>
              <div class="text-[11px] text-zinc-400 mt-0.5">
                ${v.width}×${v.height} • ${formatSec(v.duration)} • ${v.fps} fps • ${formatBytes(v.size_bytes)} • <span class="text-zinc-500">${v.source_type === "youtube" ? "YouTube" : "Upload"}</span>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0">
              ${
                isSelected
                  ? `<span class="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">
                      ✓ Digunakan
                    </span>`
                  : `<button type="button" data-pick-video="${esc(v.filename)}"
                      class="px-2.5 py-1 rounded-lg text-[11px] font-medium bg-zinc-800 hover:bg-tiktokCyan hover:text-zinc-950 text-zinc-200 transition">
                      Pilih Video Ini
                    </button>`
              }
              <button type="button" data-del-video="${esc(v.filename)}" data-del-title="${esc(v.title || v.filename)}"
                class="px-2 py-1 rounded-lg text-[11px] bg-zinc-800 hover:bg-red-500/20 hover:text-red-400 text-zinc-400 transition"
                title="Hapus video ini dari library">
                Hapus
              </button>
            </div>
          </div>`;
      })
      .join("");

    container.querySelectorAll("[data-pick-video]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const found = libraryVideos.find((v) => v.filename === btn.dataset.pickVideo);
        if (found) selectVideo(found);
      });
    });

    container.querySelectorAll("[data-del-video]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const fname = btn.dataset.delVideo;
        const title = btn.dataset.delTitle || fname;
        if (!confirm(`Apakah Anda yakin ingin menghapus "${title}" dari Library? Video ini akan dihapus dari penyimpanan.`)) {
          return;
        }
        await fetch(`/api/videos/${encodeURIComponent(fname)}`, { method: "DELETE" });
        if (selectedVideo && selectedVideo.filename === fname) {
          selectedVideo = null;
        }
        await loadLibrary();
      });
    });
  }

  // Upload Video
  $("videoFileInput").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const statusEl = $("uploadStatus");
    statusEl.classList.remove("hidden");
    statusEl.textContent = `Mengunggah ${file.name} (${formatBytes(file.size)})...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/videos/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal mengunggah video.");
      statusEl.textContent = `✅ Berhasil ditambahkan ke Library: ${data.title || data.filename}`;
      await loadLibrary();
      selectVideo(data);
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
    } finally {
      e.target.value = "";
    }
  });

  // Preview Source Video in Player
  $("previewSourceBtn")?.addEventListener("click", () => {
    if (!selectedVideo) return;
    showVideoInPlayer({
      url: selectedVideo.url,
      label: `Sumber: ${selectedVideo.title || selectedVideo.filename}`,
      mp4Url: null,
      srtUrl: null,
      thumbUrl: null,
    });
  });

  // YouTube Download
  $("youtubeDownloadBtn").addEventListener("click", async () => {
    const url = $("youtubeUrlInput").value.trim();
    const maxHeight = parseInt($("youtubeMaxHeight").value, 10) || 1080;
    if (!url) {
      alert("Masukkan URL YouTube terlebih dahulu.");
      return;
    }

    const box = $("youtubeProgressBox");
    box.classList.remove("hidden");
    $("youtubeProgressText").textContent = "Menghubungkan ke YouTube...";
    $("youtubeProgressPct").textContent = "0%";
    $("youtubeProgressBar").style.width = "0%";
    $("youtubeDownloadBtn").disabled = true;

    try {
      const res = await fetch("/api/videos/youtube", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, max_height: maxHeight }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memulai unduhan YouTube.");

      watchJob(data.job_id, {
        onProgress: (job) => {
          $("youtubeProgressText").textContent = job.message;
          $("youtubeProgressPct").textContent = `${Math.round(job.progress)}%`;
          $("youtubeProgressBar").style.width = `${job.progress}%`;
        },
        onComplete: async (job) => {
          $("youtubeDownloadBtn").disabled = false;
          if (job.video_metadata) {
            await loadLibrary();
            selectVideo(job.video_metadata);
            $("youtubeProgressText").textContent = `✅ Berhasil diunduh & ditambahkan ke library!`;
          }
        },
        onError: (errMsg) => {
          $("youtubeDownloadBtn").disabled = false;
          $("youtubeProgressText").textContent = `Gagal: ${errMsg}`;
        },
      });
    } catch (err) {
      $("youtubeDownloadBtn").disabled = false;
      $("youtubeProgressText").textContent = `Error: ${err.message}`;
    }
  });

  // Clip Mode toggles
  function updateClipModeUI() {
    const mode = document.querySelector('input[name="clipMode"]:checked')?.value || "auto_random";
    $("manualTrimInputs").classList.toggle("hidden", mode !== "manual");
    $("autoPartInputs").classList.toggle("hidden", mode !== "auto_part");
  }
  document.querySelectorAll('input[name="clipMode"]').forEach((r) => {
    r.addEventListener("change", updateClipModeUI);
  });
  updateClipModeUI();

  $("partDurationInput").addEventListener("input", (e) => {
    $("partDurationVal").textContent = `${e.target.value} detik`;
  });

  // TTS Toggle & Story Stats
  $("includeTtsCheckbox").addEventListener("change", (e) => {
    $("ttsModuleBody").classList.toggle("opacity-40", !e.target.checked);
    $("ttsModuleBody").classList.toggle("pointer-events-none", !e.target.checked);
  });

  function getStoryText() {
    return ($("storyInput") || $("storyTextInput"))?.value || "";
  }

  function setStoryText(val) {
    const el = $("storyInput") || $("storyTextInput");
    if (el) el.value = val;
    updateStoryStats();
  }

  function updateStoryStats() {
    const text = getStoryText().trim();
    const words = text ? text.split(/\s+/).length : 0;
    const chars = text.length;
    const ratePct = parseInt($("ttsRateInput").value, 10) || 0;
    const mult = Math.max(0.5, 1 + ratePct / 100);
    const estSec = words > 0 ? Math.round(words / (2.45 * mult)) : 0;

    if ($("wordCountDisplay")) $("wordCountDisplay").textContent = String(words);
    if ($("charCountDisplay")) $("charCountDisplay").textContent = String(chars);
    if ($("estDurationDisplay")) $("estDurationDisplay").textContent = `${formatSec(estSec)}`;

    const maxWords = parseInt($("maxWordsInput").value, 10) || 120;
    const estParts = Math.max(1, Math.ceil(words / maxWords));
    if ($("targetPartsEstimate")) $("targetPartsEstimate").textContent = `${estParts} Part`;
  }

  ($("storyInput") || $("storyTextInput"))?.addEventListener("input", updateStoryStats);

  $("ttsRateInput").addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10);
    $("ttsRateVal").textContent = `${v >= 0 ? "+" : ""}${v}% (Rekomendasi TikTok)`;
    updateStoryStats();
  });

  $("maxWordsInput").addEventListener("input", (e) => {
    $("maxWordsVal").textContent = `${e.target.value} kata (~${Math.round(e.target.value / 2.45)}s)`;
    updateStoryStats();
  });

  $("wordsPerCueInput").addEventListener("input", (e) => {
    $("wordsPerCueVal").textContent = `${e.target.value} kata per tayangan`;
  });

  function updateBgAudioUI() {
    const enabled = $("bgAudioEnabledCheckbox").checked;
    const vol = $("bgVolumeInput").value;
    $("bgVolumeInput").disabled = !enabled;
    $("bgVolumeVal").textContent = enabled ? `ON • ${vol}%` : "OFF (Mute)";
    $("bgVolumeVal").className = enabled
      ? "font-mono text-emerald-400 font-semibold"
      : "font-mono text-zinc-500 font-semibold";
    $("bgAudioHint").textContent = enabled
      ? "Rekomendasi: 15%–25% (ASMR)"
      : "Suara video background dimatikan";
  }

  $("bgAudioEnabledCheckbox").addEventListener("change", updateBgAudioUI);
  $("bgVolumeInput").addEventListener("input", updateBgAudioUI);

  $("hookEnabledCheckbox").addEventListener("change", (e) => {
    $("hookOptions").classList.toggle("hidden", !e.target.checked);
  });

  $("hookDurationInput").addEventListener("input", (e) => {
    $("hookDurationVal").textContent = `${e.target.value} detik`;
  });

  $("autoSplitCheckbox").addEventListener("change", (e) => {
    $("splitOptions")?.classList.toggle("hidden", !e.target.checked);
    updateStoryStats();
  });

  // Preset Story Buttons
  document.querySelectorAll(".preset-btn, .sample-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.preset || btn.dataset.sample;
      if (SAMPLE_STORIES[key]) {
        const item = SAMPLE_STORIES[key];
        setStoryText(item.text);
        if ($("thumbTitleInput") && (!($("thumbTitleInput").value) || $("thumbTitleInput").value.includes("Kisah Nyata..."))) {
          $("thumbTitleInput").value = item.hook;
        }
        if ($("thumbSubtitleInput") && item.tag) {
          $("thumbSubtitleInput").value = item.tag;
        }
        updateLiveMockPreview();
      }
    });
  });

  // Preview Split Part
  $("previewSplitBtn")?.addEventListener("click", async () => {
    const storyText = getStoryText().trim();
    const box = $("splitPreviewBox") || $("splitPreviewResult");
    if (!box) return;

    if (!storyText) {
      box.classList.remove("hidden");
      box.innerHTML = `<div class="text-amber-400 text-xs py-2">Tulis naskah cerita terlebih dahulu.</div>`;
      return;
    }

    const rateVal = parseInt($("ttsRateInput").value, 10);
    const payload = {
      story_text: storyText,
      auto_split: $("autoSplitCheckbox").checked,
      max_words_per_part: parseInt($("maxWordsInput").value, 10),
      cta_template: $("ctaTemplateInput").value,
      final_cta: "",
      tts_rate: `${rateVal >= 0 ? "+" : ""}${rateVal}%`,
    };

    try {
      const res = await fetch("/api/story/split-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      box.classList.remove("hidden");

      const container = $("partsContainer") || box;
      if ($("splitSummaryText")) {
        $("splitSummaryText").textContent = `Total ${data.total_parts} part (${data.total_words} kata)`;
      }

      container.innerHTML = data.parts
        .map(
          (p) => `
          <div class="p-2.5 rounded-lg bg-zinc-900 border border-zinc-800 space-y-1">
            <div class="flex justify-between text-[11px] font-semibold text-tiktokPink">
              <span>Part ${p.part_number} / ${p.total_parts}</span>
              <span>${p.word_count} kata • ~${Math.round(p.estimated_duration)} detik</span>
            </div>
            <p class="text-[11px] text-zinc-300 leading-relaxed">${esc(p.text)}</p>
          </div>`
        )
        .join("");
    } catch (err) {
      box.classList.remove("hidden");
      box.innerHTML = `<div class="text-red-400 text-xs py-2">Gagal memproses split: ${esc(err.message)}</div>`;
    }
  });

  // ================= THUMBNAIL / SAMPUL STUDIO =================
  $("thumbEnabledCheckbox")?.addEventListener("change", (e) => {
    const box = $("thumbControlsBox");
    if (box) {
      box.classList.toggle("opacity-40", !e.target.checked);
      box.classList.toggle("pointer-events-none", !e.target.checked);
    }
  });

  document.querySelectorAll('input[name="thumbSourceRadio"]').forEach((r) => {
    r.addEventListener("change", () => {
      const isCustom = r.value === "custom_image";
      $("thumbCustomUploadBox")?.classList.toggle("hidden", !isCustom);
    });
  });

  // Custom Cover Image Upload
  $("thumbCustomFileInput")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const statusEl = $("thumbCustomUploadStatus");
    if (statusEl) statusEl.textContent = `Mengunggah gambar sampul (${formatBytes(file.size)})...`;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/thumbnail/upload-custom", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal mengunggah gambar sampul.");
      uploadedCustomCoverFilename = data.filename;
      if (statusEl) statusEl.textContent = `✅ Sampul kustom siap: ${data.filename}`;
      generateThumbnailPreview();
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    }
  });

  // Live Reactive Mock Preview
  function updateLiveMockPreview() {
    const titleVal = ($("thumbTitleInput")?.value.trim() || "Part 1 | Kisah Nyata...")
      .replace(/\{part\}/gi, "1")
      .replace(/\{total\}/gi, "3");
    const subVal = ($("thumbSubtitleInput")?.value.trim() || "KISAH NYATA")
      .replace(/\{part\}/gi, "1")
      .replace(/\{total\}/gi, "3");
    const style = $("thumbStyleSelect")?.value || "tiktok_yellow";

    const badgeEl = $("mockBadge");
    const title1El = $("mockTitle1");

    if (badgeEl) {
      badgeEl.textContent = subVal.toUpperCase();
      badgeEl.className = "inline-block px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wide ";
      if (style === "tiktok_yellow") {
        badgeEl.className += "bg-amber-400 text-zinc-950";
      } else if (style === "red_warning") {
        badgeEl.className += "bg-rose-600 text-white";
      } else if (style === "cyan_neon") {
        badgeEl.className += "bg-zinc-950 text-tiktokCyan border border-tiktokCyan";
      } else {
        badgeEl.className += "bg-zinc-800 text-white border border-zinc-600";
      }
    }

    if (title1El) {
      title1El.textContent = titleVal;
      title1El.className = "px-2.5 py-1 rounded-lg font-black text-xs tracking-tight shadow ";
      if (style === "tiktok_yellow") {
        title1El.className += "bg-amber-400 text-zinc-950";
      } else if (style === "red_warning") {
        title1El.className += "bg-rose-600 text-white";
      } else if (style === "cyan_neon") {
        title1El.className += "bg-zinc-900 text-tiktokCyan border border-tiktokCyan";
      } else {
        title1El.className += "bg-zinc-900/90 text-white border border-zinc-700";
      }
    }
  }

  $("thumbTitleInput")?.addEventListener("input", updateLiveMockPreview);
  $("thumbSubtitleInput")?.addEventListener("input", updateLiveMockPreview);
  $("thumbStyleSelect")?.addEventListener("change", updateLiveMockPreview);

  // Generate Thumbnail API Call
  async function generateThumbnailPreview() {
    const btn = $("generateThumbBtn");
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span>Membuat Sampul...</span>`;

    const title = ($("thumbTitleInput")?.value.trim() || "Part 1 | Kisah Nyata...")
      .replace(/\{part\}/gi, "1")
      .replace(/\{total\}/gi, "3");
    const subtitle = ($("thumbSubtitleInput")?.value.trim() || "KISAH NYATA")
      .replace(/\{part\}/gi, "1")
      .replace(/\{total\}/gi, "3");
    const style = $("thumbStyleSelect")?.value || "tiktok_yellow";
    const sourceType = document.querySelector('input[name="thumbSourceRadio"]:checked')?.value || "video_frame";
    const frameTime = parseFloat($("thumbFrameTimeInput")?.value) || 2.0;

    const payload = {
      video_filename: selectedVideo ? selectedVideo.filename : null,
      custom_image_filename: uploadedCustomCoverFilename,
      title: title,
      subtitle: subtitle,
      style: style,
      source_type: sourceType,
      frame_time: frameTime,
    };

    try {
      const res = await fetch("/api/thumbnail/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal membuat thumbnail.");

      const previewImg = $("thumbPreviewImg");
      const mockPreview = $("thumbMockPreview");
      if (previewImg) {
        previewImg.src = `${data.thumbnail_url}?t=${Date.now()}`;
        previewImg.classList.remove("hidden");
      }
      if (mockPreview) mockPreview.classList.add("hidden");

      const dlBtn = $("downloadThumbDirectBtn");
      if (dlBtn) {
        dlBtn.href = data.thumbnail_url;
        dlBtn.classList.remove("hidden");
      }
    } catch (err) {
      alert(`Gagal membuat preview thumbnail: ${err.message}`);
    } finally {
      btn.disabled = false;
      btn.innerHTML = origText;
    }
  }

  $("generateThumbBtn")?.addEventListener("click", generateThumbnailPreview);

  // ================= AFFILIATE VIDEO STUDIO =================
  function updateAffiliateUIState() {
    const enabled = $("affiliateEnabledCheckbox")?.checked || false;
    const box = $("affiliateControlsBox");
    if (box) {
      box.classList.toggle("opacity-45", !enabled);
      box.classList.toggle("pointer-events-none", !enabled);
    }
    const placement = document.querySelector('input[name="affiliatePlacement"]:checked')?.value || "end";
    $("affiliatePipStartBox")?.classList.toggle("hidden", placement !== "pip");
  }

  $("affiliateEnabledCheckbox")?.addEventListener("change", updateAffiliateUIState);
  document.querySelectorAll('input[name="affiliatePlacement"]').forEach((r) => {
    r.addEventListener("change", () => {
      updateAffiliateUIState();
      // Helpful default: if user picks PiP and volume was 100%, keep control obvious
      if (r.value === "pip" && $("affiliateVolumeInput")) {
        // leave user choice intact, just update hint/UI
      }
    });
  });

  $("affiliateVolumeInput")?.addEventListener("input", (e) => {
    const v = parseInt(e.target.value, 10) || 0;
    if ($("affiliateVolumeVal")) {
      $("affiliateVolumeVal").textContent = v === 0 ? "Mute (0%)" : `${v}%`;
    }
  });

  function selectAffiliateVideo(meta) {
    selectedAffiliate = meta || null;
    const dropdown = $("affiliateSelectDropdown");
    if (dropdown && meta && dropdown.value !== meta.filename) {
      dropdown.value = meta.filename;
    }
    const hasSel = Boolean(selectedAffiliate);
    if ($("previewAffiliateBtn")) $("previewAffiliateBtn").disabled = !hasSel;
    if ($("deleteAffiliateBtn")) $("deleteAffiliateBtn").disabled = !hasSel;
  }

  function populateAffiliateDropdown() {
    const dropdown = $("affiliateSelectDropdown");
    if (!dropdown) return;
    if (!affiliateVideos.length) {
      dropdown.innerHTML = `<option value="">-- Belum ada video affiliate, silakan upload --</option>`;
      selectAffiliateVideo(null);
      return;
    }
    dropdown.innerHTML = affiliateVideos
      .map((v) => {
        const title = v.title || v.filename;
        const info = `${formatSec(v.duration)} • ${v.width}×${v.height} • ${formatBytes(v.size_bytes)}`;
        return `<option value="${esc(v.filename)}">${esc(title)} (${esc(info)})</option>`;
      })
      .join("");

    if (selectedAffiliate && affiliateVideos.some((v) => v.filename === selectedAffiliate.filename)) {
      dropdown.value = selectedAffiliate.filename;
    } else {
      selectAffiliateVideo(affiliateVideos[0]);
    }
  }

  $("affiliateSelectDropdown")?.addEventListener("change", (e) => {
    const found = affiliateVideos.find((v) => v.filename === e.target.value);
    selectAffiliateVideo(found || null);
  });

  async function loadAffiliates() {
    try {
      const res = await fetch("/api/affiliates");
      affiliateVideos = await res.json();
      if ($("affiliateCountBadge")) {
        $("affiliateCountBadge").textContent = `${affiliateVideos.length} Video`;
      }
      populateAffiliateDropdown();
    } catch {
      if ($("affiliateSelectDropdown")) {
        $("affiliateSelectDropdown").innerHTML = `<option value="">Gagal memuat daftar video affiliate</option>`;
      }
    }
  }

  $("affiliateFileInput")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const statusEl = $("affiliateUploadStatus");
    if (statusEl) {
      statusEl.classList.remove("hidden");
      statusEl.textContent = `Mengunggah video affiliate ${file.name} (${formatBytes(file.size)})...`;
    }

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/affiliates/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal mengunggah video affiliate.");

      if ($("affiliateEnabledCheckbox") && !$("affiliateEnabledCheckbox").checked) {
        $("affiliateEnabledCheckbox").checked = true;
        updateAffiliateUIState();
      }

      if (statusEl) {
        statusEl.textContent = `✅ Video affiliate siap dipakai: ${data.title || data.filename}`;
      }
      await loadAffiliates();
      selectAffiliateVideo(data);
    } catch (err) {
      if (statusEl) statusEl.textContent = `Error: ${err.message}`;
    } finally {
      e.target.value = "";
    }
  });

  $("previewAffiliateBtn")?.addEventListener("click", () => {
    if (!selectedAffiliate) return;
    showVideoInPlayer({
      url: selectedAffiliate.url,
      label: `Affiliate: ${selectedAffiliate.title || selectedAffiliate.filename}`,
      mp4Url: null,
      srtUrl: null,
      thumbUrl: null,
    });
  });

  $("deleteAffiliateBtn")?.addEventListener("click", async () => {
    if (!selectedAffiliate) return;
    const label = selectedAffiliate.title || selectedAffiliate.filename;
    if (!confirm(`Hapus video affiliate "${label}"?`)) return;
    await fetch(`/api/affiliates/${encodeURIComponent(selectedAffiliate.filename)}`, { method: "DELETE" });
    selectedAffiliate = null;
    await loadAffiliates();
  });

  // Job Watcher (SSE with polling fallback)
  function watchJob(jobId, handlers) {
    if (activeStream) {
      activeStream.close();
      activeStream = null;
    }
    let settled = false;
    const sse = new EventSource(`/api/jobs/${encodeURIComponent(jobId)}/stream`);
    activeStream = sse;

    const handleJob = (job) => {
      handlers.onProgress?.(job);
      if (job.status === "completed" && !settled) {
        settled = true;
        sse.close();
        activeStream = null;
        handlers.onComplete?.(job);
      } else if (job.status === "failed" && !settled) {
        settled = true;
        sse.close();
        activeStream = null;
        handlers.onError?.(job.error || job.message);
      }
    };

    sse.onmessage = (ev) => {
      try {
        handleJob(JSON.parse(ev.data));
      } catch {}
    };

    sse.onerror = () => {
      sse.close();
      if (settled) return;
      const poll = setInterval(async () => {
        try {
          const r = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
          const job = await r.json();
          handleJob(job);
          if (job.status === "completed" || job.status === "failed") {
            clearInterval(poll);
          }
        } catch {
          clearInterval(poll);
        }
      }, 700);
    };
  }

  // Render Action
  $("renderBtn").addEventListener("click", async () => {
    if (!selectedVideo) {
      alert("Pilih atau upload video background terlebih dahulu dari menu di Modul 1!");
      return;
    }
    const includeTts = $("includeTtsCheckbox").checked;
    const storyText = getStoryText().trim();
    if (includeTts && !storyText) {
      alert("Masukkan naskah cerita terlebih dahulu, atau nonaktifkan toggle Narasi & Subtitle.");
      return;
    }

    const affEnabled = $("affiliateEnabledCheckbox")?.checked || false;
    if (affEnabled && !selectedAffiliate) {
      alert("Anda mengaktifkan Video Affiliate, silakan upload atau pilih video affiliate terlebih dahulu!");
      return;
    }

    const rateVal = parseInt($("ttsRateInput").value, 10);
    const clipMode = document.querySelector('input[name="clipMode"]:checked')?.value || "auto_random";
    const thumbEnabled = $("thumbEnabledCheckbox") ? $("thumbEnabledCheckbox").checked : true;
    const thumbSource = document.querySelector('input[name="thumbSourceRadio"]:checked')?.value || "video_frame";

    const payload = {
      video_filename: selectedVideo.filename,
      clip_mode: clipMode,
      start_time: $("startTimeInput").value.trim() || "00:00:00",
      end_time: $("endTimeInput").value.trim() || "00:01:00",
      part_duration: parseFloat($("partDurationInput").value) || 50,
      anti_copyright: $("antiCopyrightCheckbox").checked,

      include_tts: includeTts,
      story_text: storyText,
      auto_split: $("autoSplitCheckbox").checked,
      max_words_per_part: parseInt($("maxWordsInput").value, 10) || 120,
      cta_template: $("ctaTemplateInput").value,
      final_cta: "",
      voice: $("voiceSelect").value,
      tts_rate: `${rateVal >= 0 ? "+" : ""}${rateVal}%`,

      subtitle_style: $("subtitleStyleSelect").value,
      subtitle_font: $("subtitleFontSelect").value,
      subtitle_size: parseInt($("subtitleSizeSelect").value, 10) || 62,
      words_per_cue: parseInt($("wordsPerCueInput").value, 10) || 4,

      bg_audio_enabled: $("bgAudioEnabledCheckbox").checked,
      bg_volume: (parseInt($("bgVolumeInput").value, 10) || 0) / 100,
      hook_enabled: $("hookEnabledCheckbox").checked,
      hook_text: $("hookTextInput").value,
      hook_duration: parseFloat($("hookDurationInput").value) || 4,
      project_name: $("projectNameInput").value.trim() || "tiktok_story",

      // Thumbnail options
      generate_thumbnail: thumbEnabled,
      thumbnail_title: $("thumbTitleInput")?.value.trim() || "Part {part}",
      thumbnail_subtitle: $("thumbSubtitleInput")?.value.trim() || "KISAH NYATA",
      thumbnail_style: $("thumbStyleSelect")?.value || "tiktok_yellow",
      thumbnail_source: thumbSource,
      thumbnail_frame_time: parseFloat($("thumbFrameTimeInput")?.value) || 2.0,
      thumbnail_custom_filename: uploadedCustomCoverFilename,
      insert_cover_intro: $("insertCoverIntroCheckbox") ? $("insertCoverIntroCheckbox").checked : false,
      cover_intro_duration: 0.8,

      // Affiliate options
      affiliate_enabled: affEnabled,
      affiliate_filename: selectedAffiliate ? selectedAffiliate.filename : null,
      affiliate_placement: document.querySelector('input[name="affiliatePlacement"]:checked')?.value || "end",
      affiliate_fit_mode: $("affiliateFitModeSelect")?.value || "fit_blur",
      affiliate_apply_parts: $("affiliateApplyPartsSelect")?.value || "all",
      affiliate_start_time: $("affiliateStartTimeInput")?.value.trim() || "00:00:00",
      affiliate_end_time: $("affiliateEndTimeInput")?.value.trim() || "",
      affiliate_volume: (parseInt($("affiliateVolumeInput")?.value ?? "100", 10) || 0) / 100,
      affiliate_pip_start: parseFloat($("affiliatePipStartInput")?.value) || 3.0,
      affiliate_cta_text: $("affiliateCtaInput")?.value.trim() || "",
    };

    $("renderBtn").disabled = true;
    setJobUI("running", 1, "Mengirim permintaan render...", ["Memulai job rendering..."]);

    try {
      const res = await fetch("/api/render", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Gagal memulai rendering.");

      watchJob(data.job_id, {
        onProgress: (job) => {
          setJobUI(job.status, job.progress, job.message, job.logs);
        },
        onComplete: async (job) => {
          $("renderBtn").disabled = false;
          setJobUI("completed", 100, job.message, job.logs);
          await loadOutputs();
          if (job.outputs && job.outputs.length > 0) {
            const first = job.outputs[0];
            showVideoInPlayer({
              url: first.video_url,
              label: first.title,
              mp4Url: `/api/outputs/${encodeURIComponent(first.filename)}/download`,
              srtUrl: first.srt_filename ? `/api/outputs/${encodeURIComponent(first.srt_filename)}/download` : null,
              thumbUrl: first.thumbnail_url || null,
            });
          }
        },
        onError: (errMsg) => {
          $("renderBtn").disabled = false;
          setJobUI("failed", 0, `Gagal: ${errMsg}`, [`ERROR: ${errMsg}`]);
        },
      });
    } catch (err) {
      $("renderBtn").disabled = false;
      setJobUI("failed", 0, `Error: ${err.message}`, [`ERROR: ${err.message}`]);
    }
  });

  function setJobUI(status, progress, message, logs) {
    const badge = $("jobStatusBadge");
    badge.textContent =
      status === "running"
        ? "Rendering..."
        : status === "completed"
        ? "Selesai"
        : status === "failed"
        ? "Gagal"
        : "Siap";

    badge.className = "text-[11px] px-2.5 py-0.5 rounded-full font-medium ";
    if (status === "running") {
      badge.className += "bg-tiktokCyan/15 text-tiktokCyan border border-tiktokCyan/30 animate-pulse";
    } else if (status === "completed") {
      badge.className += "bg-emerald-500/15 text-emerald-400 border border-emerald-500/30";
    } else if (status === "failed") {
      badge.className += "bg-red-500/15 text-red-400 border border-red-500/30";
    } else {
      badge.className += "bg-zinc-800 text-zinc-400";
    }

    $("jobMessage").textContent = message || "";
    $("jobPct").textContent = `${Math.round(progress || 0)}%`;
    $("jobProgressBar").style.width = `${Math.max(0, Math.min(100, progress || 0))}%`;
    if (Array.isArray(logs) && logs.length > 0) {
      const logEl = $("jobLogs");
      logEl.textContent = logs.join("\n");
      logEl.scrollTop = logEl.scrollHeight;
    }
  }

  function showVideoInPlayer({ url, label, mp4Url, srtUrl, thumbUrl }) {
    const video = $("previewPlayer");
    $("playerPlaceholder").classList.add("hidden");
    video.classList.remove("hidden");
    video.src = url;
    video.load();
    video.play().catch(() => {});
    $("playerLabel").textContent = label || "Preview Video";

    const actions = $("playerActions");
    if (mp4Url) {
      actions.classList.remove("hidden");
      $("playerDownloadMp4").href = mp4Url;
      const srtBtn = $("playerDownloadSrt");
      if (srtUrl) {
        srtBtn.href = srtUrl;
        srtBtn.classList.remove("hidden");
      } else {
        srtBtn.classList.add("hidden");
      }

      const thumbBtn = $("playerDownloadThumb");
      if (thumbBtn) {
        if (thumbUrl) {
          thumbBtn.href = thumbUrl;
          thumbBtn.classList.remove("hidden");
        } else {
          thumbBtn.classList.add("hidden");
        }
      }
    } else {
      actions.classList.add("hidden");
    }
  }

  // Rendered Outputs List
  async function loadOutputs() {
    try {
      const res = await fetch("/api/outputs");
      const items = await res.json();
      $("outputsCount").textContent = String(items.length);
      const container = $("outputsList");
      if (!items.length) {
        container.innerHTML = `<div class="text-zinc-500 py-4 text-center">Belum ada video yang dirender.</div>`;
        return;
      }

      container.innerHTML = items
        .map(
          (item) => `
          <div class="p-3 rounded-xl bg-zinc-950 border border-zinc-800 flex items-center justify-between gap-3 hover:border-zinc-700 transition">
            <div class="flex items-center gap-3 min-w-0 flex-1">
              ${
                item.thumbnail_url
                  ? `<img src="${esc(item.thumbnail_url)}" class="w-11 h-16 object-cover rounded-lg border border-zinc-800 shrink-0 shadow" alt="Cover" />`
                  : `<div class="w-11 h-16 rounded-lg bg-zinc-900 border border-zinc-800 shrink-0 flex items-center justify-center text-zinc-600">
                      <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 20 20"><path d="M6.3 2.841A1.5 1.5 0 004 4.11v11.78a1.5 1.5 0 002.3 1.269l9.344-5.89a1.5 1.5 0 000-2.538L6.3 2.84z"/></svg>
                    </div>`
              }
              <div class="min-w-0 flex-1">
                <div class="font-medium text-white truncate text-xs sm:text-sm">${esc(item.title)}</div>
                <div class="text-[11px] text-zinc-400 mt-0.5">
                  ${formatSec(item.duration)} • ${formatBytes(item.size_bytes)}
                </div>
                <div class="text-[10px] text-zinc-500 font-mono truncate mt-0.5">${esc(item.filename)}</div>
              </div>
            </div>
            <div class="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
              <button type="button"
                data-play-output="${esc(item.filename)}"
                class="px-2.5 py-1.5 rounded-lg bg-tiktokCyan/15 text-tiktokCyan hover:bg-tiktokCyan/25 font-semibold transition text-xs">
                Putar
              </button>
              <a href="/api/outputs/${encodeURIComponent(item.filename)}/download" download
                class="px-2.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 font-medium transition text-xs">
                MP4
              </a>
              ${
                item.srt_filename
                  ? `<a href="/api/outputs/${encodeURIComponent(item.srt_filename)}/download" download
                      class="px-2 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition text-xs">
                      SRT
                    </a>`
                  : ""
              }
              ${
                item.thumbnail_url
                  ? `<a href="${esc(item.thumbnail_url)}" download="${esc(item.thumbnail_filename || 'cover.jpg')}"
                      class="px-2 py-1.5 rounded-lg bg-amber-500/15 text-amber-400 hover:bg-amber-500/25 border border-amber-500/30 transition text-xs font-medium"
                      title="Unduh Sampul / Cover TikTok">
                      Sampul
                    </a>`
                  : ""
              }
              <button type="button" data-del-output="${esc(item.filename)}"
                class="px-2 py-1.5 rounded-lg bg-zinc-900 hover:bg-red-500/20 hover:text-red-400 text-zinc-500 transition text-xs"
                title="Hapus video ini">
                ✕
              </button>
            </div>
          </div>`
        )
        .join("");

      container.querySelectorAll("[data-play-output]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const item = items.find((x) => x.filename === btn.dataset.playOutput);
          if (!item) return;
          showVideoInPlayer({
            url: item.video_url,
            label: item.title,
            mp4Url: `/api/outputs/${encodeURIComponent(item.filename)}/download`,
            srtUrl: item.srt_filename ? `/api/outputs/${encodeURIComponent(item.srt_filename)}/download` : null,
            thumbUrl: item.thumbnail_url || null,
          });
        });
      });

      container.querySelectorAll("[data-del-output]").forEach((btn) => {
        btn.addEventListener("click", async () => {
          if (!confirm(`Hapus hasil render "${btn.dataset.delOutput}"?`)) return;
          await fetch(`/api/outputs/${encodeURIComponent(btn.dataset.delOutput)}`, { method: "DELETE" });
          await loadOutputs();
        });
      });
    } catch {
      $("outputsList").innerHTML = `<div class="text-red-400 text-center py-3">Gagal memuat hasil render.</div>`;
    }
  }

  $("refreshOutputsBtn")?.addEventListener("click", loadOutputs);

  // Init
  loadHealth();
  loadLibrary();
  loadAffiliates();
  loadOutputs();
  updateAffiliateUIState();
  updateStoryStats();
  updateLiveMockPreview();
})();
