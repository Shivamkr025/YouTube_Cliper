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
        alert("Pipeline error: " + data.message);
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
// 2. Rendered Shorts Gallery
// =========================================================
async function loadRenderedClips() {
  const container = document.getElementById("clips-grid");
  try {
    const res = await fetch(API_BASE + "/api/clips");
    const clips = await res.json();

    if (!clips || clips.length === 0) {
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
      return `
      <div class="glass-card rounded-3xl overflow-hidden border border-slate-800/80 hover:border-slate-700 transition flex flex-col justify-between group shadow-xl">
        <!-- 9:16 Video Preview -->
        <div class="relative aspect-[9/16] bg-black/60 overflow-hidden cursor-pointer" onclick="openVideoModal('${fullVideoUrl}')">
          <video src="${fullVideoUrl}#t=0.5" preload="metadata" class="w-full h-full object-cover group-hover:scale-105 transition duration-300"></video>
          <div class="absolute inset-0 bg-black/30 flex items-center justify-center opacity-0 group-hover:opacity-100 transition">
            <div class="w-12 h-12 rounded-full bg-rose-600/90 flex items-center justify-center shadow-lg">
              <i data-lucide="play" class="w-5 h-5 text-white ml-0.5"></i>
            </div>
          </div>
          <span class="absolute top-3 left-3 px-2 py-0.5 rounded-lg bg-black/70 backdrop-blur-md text-[10px] font-bold text-rose-400 border border-white/10">
            Clip #${clip.clip_id || idx + 1}
          </span>
          <span class="absolute top-3 right-3 px-2 py-0.5 rounded-lg bg-black/70 backdrop-blur-md text-[10px] font-bold text-emerald-400 border border-white/10">
            ${clip.duration ? clip.duration + 's' : '9:16'}
          </span>
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
              <button onclick="uploadToYouTube('${clip.filename}')" class="py-2 px-2.5 rounded-xl bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border border-rose-500/30 text-[11px] font-semibold flex items-center justify-center space-x-1 transition">
                <i data-lucide="youtube" class="w-3.5 h-3.5 text-rose-500"></i>
                <span>YT Short</span>
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

    lucide.createIcons();
  } catch (e) {
    console.error("Failed to load clips:", e);
  }
}

function escapeHtml(text) {
  return text.replace(/'/g, "\\'").replace(/"/g, '&quot;');
}

// =========================================================
// 3. YouTube & Facebook Integration
// =========================================================
let ytHasSecret = false;

async function checkYouTubeStatus() {
  try {
    const res = await fetch(API_BASE + "/api/youtube/status");
    const data = await res.json();
    ytHasSecret = data.has_client_secret;
    const tag = document.getElementById("yt-status-tag");
    const name = document.getElementById("yt-channel-name");
    const btn = document.getElementById("btn-yt-connect");
    const dot = document.getElementById("dot-yt");
    const text = document.getElementById("text-yt");

    if (data.connected) {
      tag.innerText = "Linked ✅";
      tag.className = "px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20";
      name.innerText = data.channel_title || "Channel Connected";
      btn.innerText = "Reconnect YouTube";
      dot.className = "w-2 h-2 rounded-full bg-emerald-400";
      text.innerText = "YouTube Connected";
    } else {
      tag.innerText = "Not Linked";
      name.innerText = "No Channel Connected";
    }
  } catch (e) {
    console.error("YT check error:", e);
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

function launchGoogleAuth() {
  window.open(API_BASE + "/api/youtube/auth", "_blank", "width=600,height=700");
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
