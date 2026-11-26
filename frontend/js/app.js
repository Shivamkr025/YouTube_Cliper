// ViralClip AI - Master Frontend Controller & API Bridge
const RENDER_BACKEND_URL = "https://youtube-cliper.onrender.com";

// Smart Auto-Detect:
// 1. If user set a custom URL in Settings, use it.
// 2. If opened from localhost/127.0.0.1, connect to local backend (http://127.0.0.1:8000).
// 3. If deployed on Vercel or any cloud domain, connect to Render cloud backend.
let API_BASE = localStorage.getItem("VIRALCLIP_API_URL");
if (!API_BASE) {
  if (window.location.port === "8000") {
    API_BASE = "";
  } else if (window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1" || window.location.protocol === "file:") {
    API_BASE = "http://127.0.0.1:8000";
  } else {
    API_BASE = RENDER_BACKEND_URL;
  }
}
let currentPollingInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  lucide.createIcons();
  loadRenderedClips();
  checkYouTubeStatus();
  checkFacebookStatus();
  loadSettings();
});

// =========================================================
// 1. Pipeline Trigger & Real-Time Progress Polling
// =========================================================
async function startGeneration() {
  let url = document.getElementById("youtube-url").value.trim();
  if (!url) {
    alert("Please enter a valid YouTube video URL!");
    return;
  }

  // Auto clean URL: strip playlist/mix parameters (&list=RD..., &index=...)
  const vidMatch = url.match(/(?:v=|\/|vi=)([0-9A-Za-z_-]{11})/);
  if (vidMatch && vidMatch[1]) {
    url = `https://www.youtube.com/watch?v=${vidMatch[1]}`;
    document.getElementById("youtube-url").value = url;
  }

  const clipsCount = parseInt(document.getElementById("clips-count").value, 10);
  const speedFactor = parseFloat(document.getElementById("speed-select").value);
  const subtitleTheme = document.getElementById("subtitle-theme").value;
  const enableVo = document.getElementById("enable-vo").checked;
  const bgmVol = parseInt(document.getElementById("bgm-vol").value, 10) / 100.0;

  const btn = document.getElementById("btn-generate");
  btn.disabled = true;
  btn.classList.add("opacity-50", "cursor-not-allowed");

  const progressBox = document.getElementById("progress-container");
  progressBox.classList.remove("hidden");
  updateProgress(5, "Sending job to AI Video Engine...");

  try {
    const res = await fetch(API_BASE + "/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url,
        max_clips: clipsCount,
        enable_voiceover: enableVo,
        speed_factor: speedFactor,
        subtitle_color: subtitleTheme,
        bgm_volume: bgmVol
      })
    });

    const data = await res.json();
    if (!res.ok) {
      alert("Error: " + (data.detail || "Failed to start pipeline"));
      resetGenerateButton();
      return;
    }

    // Start live polling
    pollStatus();
  } catch (err) {
    alert("Network error: " + err);
    resetGenerateButton();
  }
}

function pollStatus() {
  if (currentPollingInterval) clearInterval(currentPollingInterval);

  currentPollingInterval = setInterval(async () => {
    try {
      const res = await fetch(API_BASE + "/api/status");
      const data = await res.json();

      if (data.status === "processing") {
        updateProgress(data.progress || 20, data.message || "Processing video...");
      } else if (data.status === "completed") {
        clearInterval(currentPollingInterval);
        updateProgress(100, "🎉 All Shorts & Reels Rendered!");
        setTimeout(() => {
          resetGenerateButton();
          loadRenderedClips();
        }, 1500);
      } else if (data.status === "error") {
        clearInterval(currentPollingInterval);
        let rawMsg = data.message || "Unknown error";
        let userMsg = rawMsg;

        if (rawMsg.includes("Failed to extract any player response") || rawMsg.includes("Sign in") || rawMsg.includes("Please sign in")) {
          userMsg = "⚠️ YouTube Bot Detection Block:\n\nYouTube ne is video ko server par block kiya hai.\n\n👉 Solutions:\n1. Kripya doosri video ka link try karein.\n2. Ya agar Render/VPS pe run kar rahe hain toh Settings (⚙️) se cookies.txt file upload karein.";
        } else if (rawMsg.includes("exist nahi karti") || rawMsg.includes("typo")) {
          userMsg = "❌ Invalid YouTube URL:\n\nYeh video exist nahi karti ya link mein typo hai. Kripya YouTube tab se exact link copy karein.";
        } else if (rawMsg.includes("GEMINI_API_KEY") || rawMsg.includes("No GEMINI_API_KEY found")) {
          userMsg = "🔑 Gemini API Key Missing:\n\nSettings (⚙️) mein jaakar apni active Google Gemini API Key save karein.";
        }

        alert("ViralClip AI Alert:\n\n" + userMsg);
        resetGenerateButton();
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 2000);
}

function updateProgress(percent, message) {
  document.getElementById("progress-bar").style.width = percent + "%";
  document.getElementById("progress-percentage").innerText = percent + "%";
  document.getElementById("step-desc").innerText = message;
}

function resetGenerateButton() {
  const btn = document.getElementById("btn-generate");
  btn.disabled = false;
  btn.classList.remove("opacity-50", "cursor-not-allowed");
}

// =========================================================
// 2. Rendered Shorts Gallery & Selection Controller
// =========================================================
let cachedRenderedClips = [];
let selectedClipFilenames = new Set();

async function loadRenderedClips() {
  const container = document.getElementById("clips-grid");
  try {
    const res = await fetch(API_BASE + "/api/clips");
    const clips = await res.json();
    cachedRenderedClips = clips || [];

    if (!clips || clips.length === 0) {
      selectedClipFilenames.clear();
      updateSelectedClipsUI();
      container.innerHTML = `
        <div class="col-span-full py-16 text-center text-slate-500 glass-card rounded-3xl border border-dashed border-slate-800">
          <i data-lucide="film" class="w-10 h-10 mx-auto text-slate-600 mb-2"></i>
          <p class="text-sm">No shorts rendered yet. Paste a link above and click Generate!</p>
        </div>
      `;
      lucide.createIcons();
      return;
    }

    container.innerHTML = clips.map((clip, idx) => {
      const fullVideoUrl = clip.video_url.startsWith('http') ? clip.video_url : API_BASE + clip.video_url;
      const fullThumbUrl = clip.thumbnail_url ? (clip.thumbnail_url.startsWith('http') ? clip.thumbnail_url : API_BASE + clip.thumbnail_url) : null;
      const isChecked = selectedClipFilenames.has(clip.filename) ? "checked" : "";
      const isSelected = selectedClipFilenames.has(clip.filename);

      return `
      <div class="glass-card rounded-3xl overflow-hidden border ${isSelected ? 'border-rose-500 shadow-rose-950/40 ring-1 ring-rose-500/50' : 'border-slate-800/80 hover:border-slate-700'} transition flex flex-col justify-between group shadow-xl relative" id="card-${clip.filename.replace(/[^a-zA-Z0-9]/g, '_')}">
        
        <!-- Selection Checkbox (Tick for sequenced batch upload) -->
        <label class="absolute top-3 left-3 z-20 flex items-center space-x-1.5 px-2.5 py-1 rounded-xl bg-black/85 backdrop-blur-md border border-slate-700 shadow-lg cursor-pointer hover:border-rose-500 transition" onclick="event.stopPropagation()">
          <input type="checkbox" class="clip-selector-cb w-4 h-4 accent-rose-500 rounded cursor-pointer" data-filename="${clip.filename}" ${isChecked} onchange="onClipCheckboxChange('${clip.filename}', this.checked)">
          <span class="text-[11px] font-bold text-white select-none">Clip #${clip.clip_id || idx + 1}</span>
        </label>

        <!-- 9:16 Video / High-CTR Thumbnail Poster Preview -->
        <div class="relative aspect-[9/16] bg-black/60 overflow-hidden cursor-pointer" onclick="openVideoModal('${fullVideoUrl}')">
          ${fullThumbUrl ? 
            `<img src="${fullThumbUrl}" alt="High-CTR Poster" class="w-full h-full object-cover group-hover:scale-105 transition duration-300">` : 
            `<video src="${fullVideoUrl}#t=0.5" preload="metadata" class="w-full h-full object-cover group-hover:scale-105 transition duration-300"></video>`
          }
          <div class="absolute inset-0 bg-black/30 flex items-center justify-center opacity-0 group-hover:opacity-100 transition">
            <div class="w-12 h-12 rounded-full bg-rose-600/90 flex items-center justify-center shadow-lg">
              <i data-lucide="play" class="w-5 h-5 text-white ml-0.5"></i>
            </div>
          </div>
          <div class="absolute top-3 right-3 flex items-center space-x-1">
            ${fullThumbUrl ? `<span class="px-2 py-0.5 rounded-lg bg-black/80 backdrop-blur-md text-[10px] font-bold text-amber-400 border border-amber-500/30">Auto-Thumb</span>` : ''}
            <span class="px-2 py-0.5 rounded-lg bg-black/80 backdrop-blur-md text-[10px] font-bold text-emerald-400 border border-white/10">
              ${clip.duration ? clip.duration + 's' : '9:16'}
            </span>
          </div>
        </div>

        <!-- Info & Multi-Channel Actions -->
        <div class="p-4 space-y-3 flex-1 flex flex-col justify-between">
          <div>
            <h4 class="text-xs sm:text-sm font-bold text-white line-clamp-2 leading-snug">${clip.title || clip.filename}</h4>
            <p class="text-[11px] text-slate-400 line-clamp-2 mt-1">${clip.hook_reason || clip.description || 'Auto-generated Short'}</p>
          </div>

          <div class="pt-2 border-t border-slate-800/80 space-y-1.5">
            <div class="grid grid-cols-2 gap-1.5">
              <a href="${fullVideoUrl}" download class="py-2 px-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-[11px] font-semibold text-slate-200 flex items-center justify-center space-x-1 transition">
                <i data-lucide="download" class="w-3.5 h-3.5"></i>
                <span>Download</span>
              </a>
              <button onclick="openYouTubeScheduleModal('${clip.filename}', '${escapeHtml(clip.title || '')}', '${escapeHtml(clip.description || '')}')" class="py-2 px-2.5 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 text-[11px] font-semibold flex items-center justify-center space-x-1 transition">
                <i data-lucide="youtube" class="w-3.5 h-3.5 text-rose-500"></i>
                <span>Schedule / YT</span>
              </button>
            </div>
            <button onclick="uploadToFacebook('${clip.filename}', '${escapeHtml(clip.title || '')}', '${escapeHtml(clip.description || '')}')" class="w-full py-2 px-2.5 rounded-xl bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 text-[11px] font-semibold flex items-center justify-center space-x-1 transition">
              <i data-lucide="facebook" class="w-3.5 h-3.5 text-blue-400"></i>
              <span>Post as Facebook Reel</span>
            </button>
          </div>
        </div>
      </div>
    `;
    }).join("");

    updateSelectedClipsUI();
    lucide.createIcons();
  } catch (e) {
    console.error("Failed to load clips:", e);
  }
}

function onClipCheckboxChange(filename, isChecked) {
  if (isChecked) {
    selectedClipFilenames.add(filename);
  } else {
    selectedClipFilenames.delete(filename);
  }
  const safeId = "card-" + filename.replace(/[^a-zA-Z0-9]/g, '_');
  const card = document.getElementById(safeId);
  if (card) {
    if (isChecked) {
      card.classList.add("border-rose-500", "shadow-rose-950/40", "ring-1", "ring-rose-500/50");
      card.classList.remove("border-slate-800/80");
    } else {
      card.classList.remove("border-rose-500", "shadow-rose-950/40", "ring-1", "ring-rose-500/50");
      card.classList.add("border-slate-800/80");
    }
  }
  updateSelectedClipsUI();
}

function toggleSelectAllClips(selectAll) {
  if (selectAll) {
    cachedRenderedClips.forEach(c => selectedClipFilenames.add(c.filename));
  } else {
    selectedClipFilenames.clear();
  }
  document.querySelectorAll(".clip-selector-cb").forEach(cb => {
    cb.checked = selectAll;
  });
  cachedRenderedClips.forEach(c => {
    const safeId = "card-" + c.filename.replace(/[^a-zA-Z0-9]/g, '_');
    const card = document.getElementById(safeId);
    if (card) {
      if (selectAll) {
        card.classList.add("border-rose-500", "shadow-rose-950/40", "ring-1", "ring-rose-500/50");
        card.classList.remove("border-slate-800/80");
      } else {
        card.classList.remove("border-rose-500", "shadow-rose-950/40", "ring-1", "ring-rose-500/50");
        card.classList.add("border-slate-800/80");
      }
    }
  });
  updateSelectedClipsUI();
}

function updateSelectedClipsUI() {
  const count = selectedClipFilenames.size;
  const badge = document.getElementById("selected-clips-badge");
  const btn = document.getElementById("btn-schedule-selected");
  const btnText = document.getElementById("btn-schedule-selected-text");
  const selectAllCb = document.getElementById("select-all-clips-cb");

  if (badge) {
    badge.innerText = `${count} selected`;
    if (count > 0) {
      badge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30";
    } else {
      badge.className = "px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-slate-800 text-slate-400 border border-slate-700";
    }
  }

  if (btn && btnText) {
    if (count > 0) {
      btn.disabled = false;
      btn.classList.remove("opacity-50", "cursor-not-allowed");
      btnText.innerText = `⚡ Schedule Selected (${count})`;
    } else {
      btn.disabled = true;
      btn.classList.add("opacity-50", "cursor-not-allowed");
      btnText.innerText = `⚡ Schedule Selected (0)`;
    }
  }

  if (selectAllCb && cachedRenderedClips.length > 0) {
    selectAllCb.checked = (count === cachedRenderedClips.length);
  }
}

function openAutoPilotWithSelected() {
  if (selectedClipFilenames.size === 0) {
    alert("Kripya pehle un clips ko tick (checkbox select) karein jinhe aap schedule karna chahte hain!");
    return;
  }
  toggleYouTubeControllerModal();
}

function escapeHtml(text) {
  return text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// =========================================================
// 3. YouTube Multi-Channel & Facebook Integration
// =========================================================
let ytHasSecret = false;
let connectedYouTubeChannels = [];

async function checkYouTubeStatus() {
  try {
    const res = await fetch(API_BASE + "/api/youtube/status");
    const data = await res.json();
    ytHasSecret = data.has_client_secret;
    connectedYouTubeChannels = data.channels || [];

    const tag = document.getElementById("yt-status-tag");
    const listContainer = document.getElementById("yt-channels-list");
    const dot = document.getElementById("dot-yt");
    const text = document.getElementById("text-yt");

    if (data.connected && connectedYouTubeChannels.length > 0) {
      if (tag) {
        tag.innerText = `${connectedYouTubeChannels.length} Linked ✅`;
        tag.className = "px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
      }
      if (dot) dot.className = "w-2 h-2 rounded-full bg-emerald-400";
      if (text) text.innerText = `YouTube (${connectedYouTubeChannels.length} Ch)`;

      if (listContainer) {
        listContainer.innerHTML = connectedYouTubeChannels.map(ch => `
          <div class="p-2.5 rounded-2xl bg-slate-900/80 border ${ch.is_default ? 'border-emerald-500/40' : 'border-slate-800'} flex items-center justify-between gap-2">
            <div class="flex items-center space-x-2.5 min-w-0">
              ${ch.thumbnail
                ? `<img src="${ch.thumbnail}" class="w-7 h-7 rounded-full object-cover border border-slate-700 shrink-0">`
                : `<div class="w-7 h-7 rounded-full bg-rose-500/20 text-rose-400 flex items-center justify-center text-xs font-bold shrink-0">${ch.slot || 'YT'}</div>`
              }
              <div class="min-w-0">
                <p class="text-xs font-bold text-white truncate">${ch.name}</p>
                <p class="text-[10px] text-slate-400">${ch.subscriber_count !== '-' ? ch.subscriber_count + ' subs • ' : ''}${ch.is_default ? '<span class="text-emerald-400 font-semibold">Default</span>' : 'Slot ' + ch.slot}</p>
              </div>
            </div>
            <div class="flex items-center space-x-1 shrink-0">
              ${!ch.is_default ? `<button onclick="setDefaultYouTubeChannel('${ch.id}')" title="Set Default" class="px-2 py-1 rounded-lg bg-slate-800 hover:bg-emerald-600/30 text-[10px] text-slate-300 hover:text-emerald-300 transition">Default</button>` : ''}
              <button onclick="removeYouTubeChannel('${ch.id}')" title="Disconnect" class="p-1 rounded-lg bg-slate-800 hover:bg-rose-600/30 text-slate-400 hover:text-rose-400 transition">
                <i data-lucide="trash-2" class="w-3 h-3"></i>
              </button>
            </div>
          </div>
        `).join("");
      }
    } else {
      if (tag) {
        tag.innerText = "Not Linked";
        tag.className = "px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/10 text-amber-400 border border-amber-500/20";
      }
      if (listContainer) {
        listContainer.innerHTML = `<p class="text-xs text-slate-400 p-2 rounded-xl bg-slate-900/60 border border-slate-800 text-center">No YouTube channel connected yet. Click <b>Add Channel</b> below.</p>`;
      }
      if (dot) dot.className = "w-2 h-2 rounded-full bg-slate-500";
      if (text) text.innerText = "YouTube";
    }

    populateChannelDropdowns();
    lucide.createIcons();
  } catch (e) {
    console.error("YT check error:", e);
  }
}

function populateChannelDropdowns() {
  const selectors = ["yt-target-channel-select", "single-clip-channel-select"];
  selectors.forEach(selId => {
    const sel = document.getElementById(selId);
    if (!sel) return;
    if (connectedYouTubeChannels.length === 0) {
      sel.innerHTML = `<option value="">No Channel Connected</option>`;
      return;
    }
    sel.innerHTML = connectedYouTubeChannels.map(ch =>
      `<option value="${ch.id}" ${ch.is_default ? 'selected' : ''}>${ch.name} (${ch.is_default ? 'Default' : 'Slot ' + ch.slot})</option>`
    ).join("");
  });
}

async function setDefaultYouTubeChannel(channelId) {
  try {
    const res = await fetch(API_BASE + "/api/youtube/channels/default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel_id: channelId })
    });
    if (res.ok) await checkYouTubeStatus();
  } catch (e) {
    console.error(e);
  }
}

async function removeYouTubeChannel(channelId) {
  if (!confirm("Kya aap is YouTube channel ko disconnect karna chahte hain?")) return;
  try {
    const res = await fetch(API_BASE + "/api/youtube/channels/remove", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ channel_id: channelId })
    });
    if (res.ok) await checkYouTubeStatus();
  } catch (e) {
    console.error(e);
  }
}

function toggleYouTubeModal() {
  const modal = document.getElementById("yt-modal");
  modal.classList.toggle("hidden");
  modal.classList.toggle("flex");
}

function connectYouTube() {
  if (!ytHasSecret) {
    toggleYouTubeModal();
  } else {
    launchGoogleAuth();
  }
}

function launchGoogleAuth(slot = "") {
  const query = slot ? `?slot=${encodeURIComponent(slot)}` : "";
  window.open(API_BASE + "/api/youtube/auth" + query, "_blank", "width=600,height=700");
}

async function uploadClientSecretFile() {
  const fileInput = document.getElementById("yt-secret-file");
  if (!fileInput.files || fileInput.files.length === 0) {
    alert("Pehle Google Cloud se downloaded client_secret.json file select karein!");
    return;
  }
  const file = fileInput.files[0];
  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch(API_BASE + "/api/youtube/upload-secret", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (res.ok) {
      alert("✅ client_secret.json successfully upload ho gaya!\nAb Step 3 mein 'Authorize with Google' par click karein.");
      ytHasSecret = true;
    } else {
      alert("Upload failed: " + (data.detail || "Error"));
    }
  } catch (e) {
    alert("Error uploading file: " + e);
  }
}

let currentDailyTarget = 2;

function setDailyTarget(num) {
  currentDailyTarget = num;
  document.querySelectorAll(".yt-target-btn").forEach(btn => {
    if (parseInt(btn.getAttribute("data-target"), 10) === num) {
      btn.className = "yt-target-btn py-2 rounded-xl bg-rose-600/30 border border-rose-500 text-rose-300 font-bold text-center";
    } else {
      btn.className = "yt-target-btn py-2 rounded-xl bg-slate-800 border border-slate-700 font-bold text-center hover:border-rose-500 transition text-slate-300";
    }
  });
}

function toggleYouTubeControllerModal() {
  const modal = document.getElementById("yt-controller-modal");
  const isOpening = modal.classList.contains("hidden");
  modal.classList.toggle("hidden");
  modal.classList.toggle("flex");

  if (isOpening) {
    // Default start datetime to tomorrow 10:00 AM
    const startInput = document.getElementById("yt-start-datetime");
    if (!startInput.value) {
      const tomorrow = new Date();
      tomorrow.setDate(tomorrow.getDate() + 1);
      tomorrow.setHours(10, 0, 0, 0);
      const localIso = new Date(tomorrow.getTime() - (tomorrow.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
      startInput.value = localIso;
    }

    // Update target scope info
    const scopeInfo = document.getElementById("autopilot-target-info");
    const btnText = document.getElementById("btn-auto-schedule-text");
    const btnHint = document.getElementById("btn-auto-schedule-hint");
    const count = selectedClipFilenames.size;

    if (count > 0) {
      if (scopeInfo) scopeInfo.innerText = `${count} Selected Clips (Category Sequence)`;
      if (btnText) btnText.innerText = `⚡ Auto-Schedule ${count} Selected Clips`;
      if (btnHint) btnHint.innerText = `Sirf aapki ticked/selected (${count}) clips ko time slots ke hisaab se YouTube calendar mein sequence me schedule karega.`;
    } else {
      const total = cachedRenderedClips.length;
      if (scopeInfo) scopeInfo.innerText = `All ${total} Clips (Full Gallery)`;
      if (btnText) btnText.innerText = `⚡ Auto-Schedule All ${total} Clips`;
      if (btnHint) btnHint.innerText = `Gallery ke saare clips ko automatically sequence me calendar par schedule karega.`;
    }
  }
}

// 2X Views Channel & Niche Preset Optimizer
async function applyNichePreset(nicheKey) {
  try {
    const res = await fetch(API_BASE + "/api/youtube/optimize-niche", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ niche: nicheKey })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      if (data.category_id) {
        document.getElementById("yt-default-category").value = data.category_id;
      }
      if (data.hashtags) {
        document.getElementById("yt-default-tags").value = data.hashtags;
      }
      if (data.timing_strategy) {
        document.getElementById("yt-timing-strategy").value = data.timing_strategy;
      }
      if (data.daily_target) {
        setDailyTarget(data.daily_target);
      }
      const tipBox = document.getElementById("niche-strategy-tip");
      const titleEl = document.getElementById("niche-applied-title");
      const textEl = document.getElementById("niche-strategy-text");
      if (tipBox && textEl) {
        tipBox.classList.remove("hidden");
        titleEl.innerText = `2X Views Preset Applied: ${data.niche_name || nicheKey}`;
        textEl.innerText = data.strategy_tip || "Settings optimized for maximum algorithmic views!";
      }
    }
  } catch (e) {
    console.error("Niche preset error:", e);
  }
}

async function analyzeCustomNiche() {
  const customTopic = document.getElementById("custom-niche-input").value.trim();
  if (!customTopic) {
    alert("Pehle apna custom channel topic likhein (e.g. Cricket, Horror Stories, Crypto, Finance)!");
    return;
  }
  const btn = document.getElementById("btn-custom-niche");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i><span>Analyzing...</span>`;
  lucide.createIcons();

  try {
    const res = await fetch(API_BASE + "/api/youtube/optimize-niche", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ custom_topic: customTopic })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      if (data.category_id) {
        document.getElementById("yt-default-category").value = data.category_id;
      }
      if (data.hashtags) {
        document.getElementById("yt-default-tags").value = data.hashtags;
      }
      if (data.timing_strategy) {
        document.getElementById("yt-timing-strategy").value = data.timing_strategy;
      }
      if (data.daily_target) {
        setDailyTarget(data.daily_target);
      }
      const tipBox = document.getElementById("niche-strategy-tip");
      const titleEl = document.getElementById("niche-applied-title");
      const textEl = document.getElementById("niche-strategy-text");
      if (tipBox && textEl) {
        tipBox.classList.remove("hidden");
        titleEl.innerText = `AI 2X Optimized: ${data.niche_name || customTopic}`;
        textEl.innerText = data.strategy_tip || "Custom algorithmic strategy successfully generated and applied!";
      }
    } else {
      alert("Analysis failed: " + (data.detail || "Error"));
    }
  } catch (e) {
    alert("Network error: " + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="sparkles" class="w-3.5 h-3.5"></i><span>AI 2X Analyze</span>`;
    lucide.createIcons();
  }
}

// Single Clip Schedule Modal
function openYouTubeScheduleModal(filename, title, description) {
  document.getElementById("single-clip-filename").value = filename;
  document.getElementById("single-clip-title").value = title || filename.replace(".mp4", "");
  document.getElementById("single-clip-desc").value = description || "#Shorts #Viral";
  
  // Default to tomorrow 6 PM
  const dtInput = document.getElementById("single-clip-datetime");
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(18, 0, 0, 0);
  const localIso = new Date(tomorrow.getTime() - (tomorrow.getTimezoneOffset() * 60000)).toISOString().slice(0, 16);
  dtInput.value = localIso;

  const modal = document.getElementById("clip-schedule-modal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
}

function closeClipScheduleModal() {
  const modal = document.getElementById("clip-schedule-modal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
}

function toggleSingleScheduleTime(mode) {
  const container = document.getElementById("single-clip-time-container");
  if (mode === "schedule") {
    container.classList.remove("hidden");
  } else {
    container.classList.add("hidden");
  }
}

async function submitSingleClipSchedule() {
  const filename = document.getElementById("single-clip-filename").value;
  const title = document.getElementById("single-clip-title").value.trim();
  const desc = document.getElementById("single-clip-desc").value.trim();
  const mode = document.getElementById("single-clip-mode").value;
  const category = document.getElementById("single-clip-category").value;
  const tags = document.getElementById("single-clip-tags").value.split(",").map(t => t.trim()).filter(Boolean);
  const dtVal = document.getElementById("single-clip-datetime").value;

  let publishAt = null;
  let privacy = mode;
  if (mode === "schedule") {
    if (!dtVal) {
      alert("Kripya schedule publish date aur time select karein!");
      return;
    }
    publishAt = new Date(dtVal).toISOString();
    privacy = "private"; // YouTube API requirement for scheduled videos
  }

  const btn = document.getElementById("btn-submit-single-schedule");
  btn.disabled = true;
  btn.innerText = "Scheduling on YouTube...";

  const channelId = document.getElementById("single-clip-channel-select")?.value || null;
  try {
    const res = await fetch(API_BASE + "/api/youtube/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        filename: filename,
        title: title,
        description: desc,
        category_id: category,
        tags: tags,
        privacy: privacy,
        publish_at: publishAt,
        channel_id: channelId
      })
    });
    const data = await res.json();
    if (res.ok) {
      if (publishAt) {
        alert(`🎉 Short Successfully Scheduled on YouTube!\n\n📅 Publish Time: ${new Date(publishAt).toLocaleString()}\n🔗 Link: ${data.url}`);
      } else {
        alert(`🎉 Short Successfully Published on YouTube!\n\n🔗 Link: ${data.url}`);
      }
      closeClipScheduleModal();
    } else {
      alert("Upload/Schedule Error: " + (data.detail || "Failed"));
    }
  } catch (e) {
    alert("Network error: " + e);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="send" class="w-3.5 h-3.5"></i><span>Schedule & Upload</span>`;
    lucide.createIcons();
  }
}

// Auto-Pilot: Schedule ALL rendered clips across chosen daily slots
async function autoScheduleAllRenderedClips() {
  if (!cachedRenderedClips || cachedRenderedClips.length === 0) {
    alert("Gallery mein koi clips nahi hain! Pehle clips generate karein.");
    return;
  }

  // Check if specific clips were ticked/selected
  let targetClips = cachedRenderedClips;
  let isFiltered = false;
  if (selectedClipFilenames.size > 0) {
    targetClips = cachedRenderedClips.filter(c => selectedClipFilenames.has(c.filename));
    isFiltered = true;
  }

  if (targetClips.length === 0) {
    alert("Schedule karne ke liye koi clip nahi mili! Kripya clips select karein.");
    return;
  }

  const startVal = document.getElementById("yt-start-datetime").value;
  if (!startVal) {
    alert("Kripya starting date aur time select karein!");
    return;
  }

  const strategy = document.getElementById("yt-timing-strategy").value;
  const privacy = document.getElementById("yt-default-privacy").value;
  const category = document.getElementById("yt-default-category").value;
  const tagsStr = document.getElementById("yt-default-tags").value.trim();
  const tags = tagsStr.replace(/#/g, "").split(/\s+/).filter(Boolean);

  const confirmMsg = isFiltered 
    ? `Auto-Pilot will schedule ${targetClips.length} SELECTED Shorts in sequence at ${currentDailyTarget} clips per day.\nDo you want to proceed?`
    : `Auto-Pilot will schedule ALL ${targetClips.length} Shorts at ${currentDailyTarget} clips per day.\nDo you want to proceed?`;
  if (!confirm(confirmMsg)) return;

  const btn = document.getElementById("btn-auto-schedule-all");
  btn.disabled = true;
  btn.innerText = `⏳ Scheduling ${targetClips.length} clips on YouTube calendar...`;

  // Calculate schedule timestamps for each clip sequentially
  let currentDt = new Date(startVal);
  const peakHours = [10, 14, 18, 21];
  const eveningHours = [17, 19, 21];

  const batchItems = targetClips.map((clip, idx) => {
    let slotDt = new Date(currentDt);
    if (strategy === "peak") {
      const dayOffset = Math.floor(idx / currentDailyTarget);
      const slotHour = peakHours[idx % Math.min(peakHours.length, currentDailyTarget)];
      slotDt.setDate(currentDt.getDate() + dayOffset);
      slotDt.setHours(slotHour, 0, 0, 0);
    } else if (strategy === "evening") {
      const dayOffset = Math.floor(idx / currentDailyTarget);
      const slotHour = eveningHours[idx % Math.min(eveningHours.length, currentDailyTarget)];
      slotDt.setDate(currentDt.getDate() + dayOffset);
      slotDt.setHours(slotHour, 0, 0, 0);
    } else if (strategy === "spaced4") {
      slotDt.setHours(currentDt.getHours() + (idx * 4));
    } else if (strategy === "spaced6") {
      slotDt.setHours(currentDt.getHours() + (idx * 6));
    }

    // Clip-specific title and targeted hashtags
    let cleanTitle = (clip.title || clip.filename.replace(".mp4", "")).trim();
    if (!cleanTitle.toLowerCase().includes("#shorts")) {
      cleanTitle = `${cleanTitle.slice(0, 85)} #Shorts`;
    }

    let clipDesc = clip.description || clip.hook_reason || "Auto-generated Viral Short";
    let fullDescription = `${clipDesc}\n\n${tagsStr}\n\n#YouTubeShorts #Viral`;

    return {
      filename: clip.filename,
      title: cleanTitle,
      description: fullDescription,
      category_id: category,
      tags: tags,
      privacy: privacy === "scheduled" ? "private" : privacy,
      publish_at: privacy === "scheduled" ? slotDt.toISOString() : null
    };
  });

  const channelId = document.getElementById("yt-target-channel-select")?.value || null;
  try {
    const res = await fetch(API_BASE + "/api/youtube/schedule-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: batchItems, channel_id: channelId })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      alert(`🎉 Auto-Pilot Success!\n\n✅ ${data.scheduled_count} Shorts scheduled on your YouTube channel calendar!\nStarting: ${new Date(startVal).toLocaleString()}\n${data.errors && data.errors.length ? 'Errors:\n' + data.errors.join('\n') : ''}`);
      toggleYouTubeControllerModal();
    } else {
      alert("Auto-Schedule notice: " + (data.detail || JSON.stringify(data.errors)));
    }
  } catch (err) {
    alert("Network error: " + err);
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="zap" class="w-4 h-4"></i><span id="btn-auto-schedule-text">⚡ Auto-Schedule Sequence Now</span>`;
    lucide.createIcons();
  }
}

async function uploadToYouTube(filename) {
  if (!confirm(`Upload ${filename} to YouTube Shorts as Private?`)) return;
  try {
    const res = await fetch(API_BASE + "/api/youtube/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: filename, privacy: "private" })
    });
    const data = await res.json();
    if (res.ok) {
      alert("🎉 Short uploaded to YouTube!\nLink: " + data.url);
    } else {
      alert("YouTube upload error: " + (data.detail || "Failed"));
    }
  } catch (err) {
    alert("Upload failed: " + err);
  }
}

// Facebook Page Status & Upload
async function checkFacebookStatus() {
  try {
    const res = await fetch(API_BASE + "/api/facebook/status");
    const data = await res.json();
    const tag = document.getElementById("fb-status-tag");
    const name = document.getElementById("fb-page-name");
    const dot = document.getElementById("dot-fb");
    const text = document.getElementById("text-fb");

    if (data.connected) {
      tag.innerText = "Linked ✅";
      tag.className = "px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20";
      name.innerText = data.page_name || "Facebook Page Active";
      dot.className = "w-2 h-2 rounded-full bg-blue-400";
      text.innerText = "FB: " + (data.page_name || "Connected");
    } else {
      tag.innerText = "Not Linked";
      name.innerText = "No Page Connected";
    }
  } catch (e) {
    console.error("FB status check error:", e);
  }
}

function toggleFacebookModal() {
  const modal = document.getElementById("fb-modal");
  modal.classList.toggle("hidden");
  modal.classList.toggle("flex");
}

async function testFacebookConnection() {
  const pageId = document.getElementById("fb-page-id").value.trim();
  const token = document.getElementById("fb-access-token").value.trim();
  const resultP = document.getElementById("fb-test-result");

  if (!pageId || !token) {
    alert("Please enter both Page ID and Page Access Token!");
    return;
  }

  resultP.classList.remove("hidden");
  resultP.className = "text-xs text-center text-amber-400";
  resultP.innerText = "Validating with Meta Graph API...";

  try {
    // Temporarily save to test
    await fetch(API_BASE + "/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ fb_page_id: pageId, fb_access_token: token })
    });
    const res = await fetch(API_BASE + "/api/facebook/status");
    const data = await res.json();
    if (data.connected) {
      resultP.className = "text-xs text-center text-emerald-400 font-bold";
      resultP.innerText = `✅ Connected to Page: "${data.page_name}"`;
    } else {
      resultP.className = "text-xs text-center text-rose-400";
      resultP.innerText = `❌ Error: ${data.error || "Invalid Credentials"}`;
    }
  } catch (err) {
    resultP.className = "text-xs text-center text-rose-400";
    resultP.innerText = "Network Error: " + err;
  }
}

async function saveFacebookSettings() {
  const pageId = document.getElementById("fb-page-id").value.trim();
  const token = document.getElementById("fb-access-token").value.trim();

  await fetch(API_BASE + "/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fb_page_id: pageId, fb_access_token: token })
  });

  alert("Facebook connection saved!");
  toggleFacebookModal();
  checkFacebookStatus();
}

async function uploadToFacebook(filename, title, description) {
  if (!confirm(`Post ${filename} as a Facebook Page Reel?`)) return;
  try {
    const res = await fetch(API_BASE + "/api/facebook/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename: filename, title: title, description: description })
    });
    const data = await res.json();
    if (res.ok && data.success) {
      alert("🎉 Facebook Reel Published Successfully!\nWatch: " + data.url);
    } else {
      alert("Facebook upload error: " + (data.detail || data.error || "Failed to publish Reel"));
    }
  } catch (err) {
    alert("Facebook publish failed: " + err);
  }
}

// =========================================================
// 4. Gemini API Key Tester & Settings Manager
// =========================================================
function toggleSettingsModal() {
  const modal = document.getElementById("settings-modal");
  modal.classList.toggle("hidden");
  modal.classList.toggle("flex");
}

async function testKey(type) {
  const inputId = type === 'primary' ? 'settings-gemini-key' : 'settings-gemini-key-backup';
  const key = document.getElementById(inputId).value.trim();
  if (!key) {
    alert("Please enter an API key to test!");
    return;
  }

  try {
    const res = await fetch(API_BASE + "/api/gemini/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: key })
    });
    const data = await res.json();
    if (data.valid) {
      alert("✅ SUCCESS! Gemini Key is active & working!");
    } else {
      alert("❌ FAILED: " + data.message);
    }
  } catch (e) {
    alert("Test failed: " + e);
  }
}

async function loadSettings() {
  const urlInput = document.getElementById("settings-backend-url");
  if (urlInput) {
    urlInput.value = localStorage.getItem("VIRALCLIP_API_URL") || RENDER_BACKEND_URL;
  }
  try {
    const res = await fetch(API_BASE + "/api/settings");
    const data = await res.json();
    if (data.gemini_key) document.getElementById("settings-gemini-key").value = data.gemini_key;
    if (data.gemini_key_backup) document.getElementById("settings-gemini-key-backup").value = data.gemini_key_backup;
    if (data.fb_page_id) document.getElementById("fb-page-id").value = data.fb_page_id;
    if (data.fb_access_token) document.getElementById("fb-access-token").value = data.fb_access_token;
  } catch (e) {
    console.error("Settings load error:", e);
  }
}

async function saveAllSettings() {
  const customUrl = document.getElementById("settings-backend-url")?.value.trim();
  if (customUrl) {
    // Strip trailing slash if present
    const cleanUrl = customUrl.replace(/\/+$/, "");
    localStorage.setItem("VIRALCLIP_API_URL", cleanUrl);
    API_BASE = cleanUrl;
  }

  const primaryKey = document.getElementById("settings-gemini-key").value.trim();
  const backupKey = document.getElementById("settings-gemini-key-backup").value.trim();
  const voice = document.getElementById("settings-tts-voice").value;

  try {
    const res = await fetch(API_BASE + "/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        gemini_key: primaryKey,
        gemini_key_backup: backupKey,
        tts_voice: voice
      })
    });
    if (res.ok) {
      alert("All API keys & settings saved successfully!");
      toggleSettingsModal();
    }
  } catch (e) {
    alert("Error saving: " + e);
  }
}

// =========================================================
// 5. Video Player Modal
// =========================================================
function openVideoModal(videoSrc) {
  const modal = document.getElementById("video-modal");
  const player = document.getElementById("modal-video-player");
  player.src = videoSrc;
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  player.play();
}

function closeVideoModal() {
  const modal = document.getElementById("video-modal");
  const player = document.getElementById("modal-video-player");
  player.pause();
  player.src = "";
  modal.classList.remove("flex");
  modal.classList.add("hidden");
}

// =========================================================
// 6. AI CapCut Local Video Editor Controller
// =========================================================
function switchStudioTab(tab) {
  const clipperTab = document.getElementById("studio-tab-clipper");
  const editorTab = document.getElementById("studio-tab-editor");
  const btnClipper = document.getElementById("tab-btn-clipper");
  const btnEditor = document.getElementById("tab-btn-editor");

  if (tab === "editor") {
    clipperTab?.classList.add("hidden");
    editorTab?.classList.remove("hidden");
    if (btnEditor) btnEditor.className = "px-4 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-violet-600 to-fuchsia-600 text-white shadow-md transition flex items-center space-x-2";
    if (btnClipper) btnClipper.className = "px-4 py-2 rounded-xl text-xs font-bold text-zinc-400 hover:text-white transition flex items-center space-x-2";
  } else {
    editorTab?.classList.add("hidden");
    clipperTab?.classList.remove("hidden");
    if (btnClipper) btnClipper.className = "px-4 py-2 rounded-xl text-xs font-bold bg-gradient-to-r from-rose-600 to-rose-500 text-white shadow-md transition flex items-center space-x-2";
    if (btnEditor) btnEditor.className = "px-4 py-2 rounded-xl text-xs font-bold text-zinc-400 hover:text-white transition flex items-center space-x-2";
  }
}

function onRawEditorFileSelected(input) {
  const label = document.getElementById("raw-editor-filename");
  if (input.files && input.files.length > 0) {
    const file = input.files[0];
    const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
    label.innerText = `Selected: ${file.name} (${sizeMb} MB)`;
  }
}

let editorPollInterval = null;

async function startLocalVideoEdit() {
  const fileInput = document.getElementById("raw-editor-file");
  if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
    alert("Kripya pehle apne PC se koi raw video (.mp4 / .mov) select karein!");
    return;
  }

  const options = {
    enable_captions: document.getElementById("ed-captions")?.checked ?? true,
    enable_noise_reduce: document.getElementById("ed-noise")?.checked ?? true,
    enable_zoom: document.getElementById("ed-zoom")?.checked ?? true,
    enable_reframe: document.getElementById("ed-reframe")?.checked ?? true,
    enable_beat_sync: document.getElementById("ed-beats")?.checked ?? true,
    enable_elements: document.getElementById("ed-elements")?.checked ?? true,
    enable_progress_bar: document.getElementById("ed-progress-bar")?.checked ?? true,
    enable_voiceover: document.getElementById("ed-vo")?.checked ?? false,
    color_grade: document.getElementById("ed-color-grade")?.value || "viral",
    caption_color: document.getElementById("ed-caption-color")?.value || "yellow",
    custom_hook: document.getElementById("ed-custom-hook")?.value || "",
    tts_voice: document.getElementById("settings-tts-voice")?.value || "en-US-ChristopherNeural"
  };

  const formData = new FormData();
  formData.append("file", fileInput.files[0]);
  formData.append("options", JSON.stringify(options));

  const btn = document.getElementById("btn-render-local-edit");
  const progBox = document.getElementById("editor-progress-container");
  btn.disabled = true;
  btn.classList.add("opacity-50", "cursor-not-allowed");
  progBox.classList.remove("hidden");
  document.getElementById("editor-step-desc").innerText = "Uploading raw video to AI CapCut engine...";
  document.getElementById("editor-progress-pct").innerText = "5%";
  document.getElementById("editor-progress-bar").style.width = "5%";

  try {
    const res = await fetch(API_BASE + "/api/editor/render", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Upload failed");
    }

    if (editorPollInterval) clearInterval(editorPollInterval);
    editorPollInterval = setInterval(pollEditorStatus, 1800);
  } catch (e) {
    alert("Local Editor Error: " + e.message);
    btn.disabled = false;
    btn.classList.remove("opacity-50", "cursor-not-allowed");
  }
}

async function pollEditorStatus() {
  try {
    const res = await fetch(API_BASE + "/api/editor/status");
    const state = await res.json();
    document.getElementById("editor-step-desc").innerText = state.message || "Editing...";
    document.getElementById("editor-progress-pct").innerText = `${state.progress || 0}%`;
    document.getElementById("editor-progress-bar").style.width = `${state.progress || 0}%`;

    if (state.status === "completed") {
      clearInterval(editorPollInterval);
      const btn = document.getElementById("btn-render-local-edit");
      btn.disabled = false;
      btn.classList.remove("opacity-50", "cursor-not-allowed");
      await loadRenderedClips();
      const elCount = (state.result?.elements_added || []).length;
      alert(`🎉 Pro CapCut-Style Video Ready!\n\nTitle: ${state.result?.title || 'Edited Short'}\nScript Elements Added: ${elCount}\nNeeche Gallery mein check karein aur kisi bhi connected YouTube channel par upload/schedule karein!`);
    } else if (state.status === "error") {
      clearInterval(editorPollInterval);
      const btn = document.getElementById("btn-render-local-edit");
      btn.disabled = false;
      btn.classList.remove("opacity-50", "cursor-not-allowed");
      alert("Edit Error: " + (state.error || state.message));
    }
  } catch (e) {
    console.error("Editor poll error:", e);
  }
}
