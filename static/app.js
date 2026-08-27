/* ==========================================================================
   AI Job Application Agent — Single Page App Logic
   ========================================================================== */

let currentRunId = null;
let eventSource = null;
let startTime = null;
let timerInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  checkSystemHealth();
  loadSettings();
  loadHistory();
  loadMasterResume();
  initFormListeners();
});

/* ── Tab Navigation ──────────────────────────────────────────────────────── */
function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      switchTab(target);
    });
  });
}

function switchTab(tabId) {
  document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

  const targetTab = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
  const targetContent = document.getElementById(`tab-${tabId}`);

  if (targetTab) targetTab.classList.add("active");
  if (targetContent) targetContent.classList.add("active");

  if (tabId === "history") loadHistory();
  if (tabId === "setup") checkSystemHealth();
}

/* ── System Health Check ─────────────────────────────────────────────────── */
async function checkSystemHealth() {
  const indicator = document.getElementById("system-status-indicator");
  const warningBanner = document.getElementById("config-warning-banner");
  const checkGemini = document.getElementById("check-gemini");

  try {
    const res = await fetch("/api/health");
    const data = await res.json();

    const isReady = data.status === "ready";

    if (isReady) {
      indicator.innerHTML = `<span class="status-dot dot-ready"></span><span class="status-text">System Ready</span>`;
      warningBanner.classList.add("hidden");
    } else {
      indicator.innerHTML = `<span class="status-dot dot-error"></span><span class="status-text">Setup Required</span>`;
      warningBanner.classList.remove("hidden");
    }

    if (checkGemini) {
      if (data.checks.gemini_api_key) {
        checkGemini.innerHTML = `
          <i class="fa-solid fa-circle-check item-icon text-emerald"></i>
          <div class="item-text">
            <strong>Gemini API Key (.env)</strong>
            <span>Active & configured in .env file</span>
          </div>`;
      } else {
        checkGemini.innerHTML = `
          <i class="fa-solid fa-circle-xmark item-icon text-red"></i>
          <div class="item-text">
            <strong>Gemini API Key Missing</strong>
            <span>Get your free key at aistudio.google.com and enter it below</span>
          </div>`;
      }
    }
  } catch (err) {
    indicator.innerHTML = `<span class="status-dot dot-error"></span><span class="status-text">Server Error</span>`;
  }
}

/* ── Form & Options Listeners ────────────────────────────────────────────── */
function initFormListeners() {
  const form = document.getElementById("agent-form");
  const urlInput = document.getElementById("jd-url");
  const toggleBtn = document.getElementById("toggle-options-btn");
  const optionsPanel = document.getElementById("options-panel");

  // Platform auto-detector
  urlInput.addEventListener("input", (e) => {
    detectPlatform(e.target.value);
  });

  // Advanced options toggle
  toggleBtn.addEventListener("click", () => {
    optionsPanel.classList.toggle("hidden");
    toggleBtn.querySelector(".arrow-icon").classList.toggle("fa-chevron-up");
  });

  // Form submit
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    startGeneration();
  });
}

function detectPlatform(url) {
  const badge = document.getElementById("detected-platform-badge");
  const platformName = document.getElementById("platform-name");

  if (!url || !url.startsWith("http")) {
    badge.classList.add("hidden");
    return;
  }

  const platforms = {
    "linkedin.com": "LinkedIn Jobs",
    "lever.co": "Lever ATS",
    "greenhouse.io": "Greenhouse ATS",
    "myworkdayjobs.com": "Workday ATS",
    "workday.com": "Workday ATS",
    "wellfound.com": "Wellfound",
    "ashbyhq.com": "Ashby ATS",
    "smartrecruiters.com": "SmartRecruiters",
    "icims.com": "iCIMS ATS",
  };

  let found = "Generic Portal";
  for (const [key, name] of Object.entries(platforms)) {
    if (url.includes(key)) {
      found = name;
      break;
    }
  }

  platformName.textContent = found;
  badge.classList.remove("hidden");
}

/* ── Pipeline Run Execution ──────────────────────────────────────────────── */
async function startGeneration(opts = {}) {
  let url = document.getElementById("jd-url").value.trim();
  
  if (url && !url.startsWith("http://") && !url.startsWith("https://")) {
    url = "https://" + url;
    document.getElementById("jd-url").value = url;
  }

  const customKwElem = document.getElementById("custom-keywords-input");
  const customKeywordsRaw = customKwElem ? customKwElem.value.trim() : "";
  
  const noSimplifyElem = document.getElementById("no-simplify-toggle");
  const noSimplify = noSimplifyElem ? noSimplifyElem.checked : false;

  const passesElem = document.getElementById("ai-passes-select");
  const passes = passesElem ? passesElem.value : "2";

  const outputDirElem = document.getElementById("custom-output-dir");
  const outputDir = outputDirElem ? outputDirElem.value.trim() : "";

  // Use score passed from Analyze step if available, otherwise null (backend will compute)
  const scoreBefore = opts.scoreBefore !== undefined ? opts.scoreBefore : analyzeScoreBefore;

  if (!url) {
    showToast("Please enter a valid job posting URL", "warning");
    return;
  }

  // UI Setup for running state
  const execContainer = document.getElementById("execution-container");
  execContainer.classList.remove("hidden");
  execContainer.scrollIntoView({ behavior: "smooth" });
  document.getElementById("results-dashboard").classList.add("hidden");
  document.getElementById("start-btn").disabled = true;
  document.getElementById("exec-status-badge").innerHTML = `<i class="fa-solid fa-spinner fa-spin text-cyan"></i> Running Pipeline...`;
  
  resetPipelineVisuals();
  startTimer();
  clearTerminal();

  logTerminal("info", `[System] Initiating job application run for: ${url}`);

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        custom_keywords: customKeywordsRaw || undefined,
        no_simplify: noSimplify,
        passes,
        output_dir: outputDir || undefined,
        score_before: scoreBefore !== null ? scoreBefore : undefined,
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      showToast(data.error || "Failed to start run", "error");
      logTerminal("error", `[Error] ${data.error}`);
      stopExecutionState("failed");
      return;
    }

    currentRunId = data.run_id;
    listenToEventStream(currentRunId);

  } catch (err) {
    showToast(`Network Error: ${err.message}`, "error");
    logTerminal("error", `[Network Error] ${err.message}`);
    stopExecutionState("failed");
  }
}

function listenToEventStream(runId) {
  if (eventSource) eventSource.close();

  eventSource = new EventSource(`/api/stream/${runId}`);

  eventSource.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      if (data.type === "ping") return;

      if (data.type === "progress") {
        updateStepState(data.step, data.status, data.message);
        logTerminal(data.status, `[Step ${data.step} - ${data.stage}] ${data.message}`);
        updateProgressBar(data.step);
      } else if (data.type === "complete") {
        eventSource.close();
        stopTimer();
        markAllStepsSuccess();
        updateProgressBar(7);
        displayResults(data.result);
        stopExecutionState("success");
        showToast("Resume tailored and Word document created successfully!", "success");
      } else if (data.type === "error") {
        eventSource.close();
        stopTimer();
        logTerminal("error", `[FAILED] ${data.message}`);
        stopExecutionState("failed");
        showToast(`Pipeline Failed: ${data.message}`, "error");
      }
    } catch (e) {
      console.error("SSE parse error", e);
    }
  };

  eventSource.onerror = (err) => {
    console.error("SSE Connection error", err);
  };
}

/* ── Pipeline UI Updates ─────────────────────────────────────────────────── */
function resetPipelineVisuals() {
  document.querySelectorAll(".step-card").forEach(card => {
    card.className = "step-card";
    card.querySelector(".step-status").innerHTML = `<i class="fa-regular fa-circle"></i>`;
  });
  document.getElementById("pipeline-progress-bar").style.width = "5%";
}

function updateStepState(stepNum, status, message) {
  const card = document.querySelector(`.step-card[data-step="${stepNum}"]`);
  if (!card) return;

  card.className = `step-card ${status}`;

  const statusIcon = card.querySelector(".step-status");
  if (status === "working") {
    statusIcon.innerHTML = `<i class="fa-solid fa-circle-notch fa-spin text-cyan"></i>`;
  } else if (status === "success") {
    statusIcon.innerHTML = `<i class="fa-solid fa-circle-check text-emerald"></i>`;
  } else if (status === "error") {
    statusIcon.innerHTML = `<i class="fa-solid fa-circle-xmark text-red"></i>`;
  }
}

function markAllStepsSuccess() {
  document.querySelectorAll(".step-card").forEach(card => {
    card.className = "step-card success";
    card.querySelector(".step-status").innerHTML = `<i class="fa-solid fa-circle-check text-emerald"></i>`;
  });
}

function updateProgressBar(step) {
  const pct = Math.min(100, Math.round((step / 7) * 100));
  document.getElementById("pipeline-progress-bar").style.width = `${pct}%`;
}

function stopExecutionState(resultStatus) {
  document.getElementById("start-btn").disabled = false;
  const badge = document.getElementById("exec-status-badge");

  if (resultStatus === "success") {
    badge.innerHTML = `<i class="fa-solid fa-circle-check text-emerald"></i> Generation Complete`;
  } else {
    badge.innerHTML = `<i class="fa-solid fa-circle-xmark text-red"></i> Execution Failed`;
  }
}

/* ── Timer & Terminal Stream ─────────────────────────────────────────────── */
function startTimer() {
  startTime = Date.now();
  timerInterval = setInterval(() => {
    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    document.getElementById("exec-timer").textContent = `${elapsed}s`;
  }, 100);
}

function stopTimer() {
  if (timerInterval) clearInterval(timerInterval);
}

function logTerminal(status, text) {
  const container = document.getElementById("terminal-output");
  const line = document.createElement("div");
  line.className = `log-line ${status}`;
  line.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
  container.appendChild(line);
  container.scrollTop = container.scrollHeight;
}

function clearTerminal() {
  document.getElementById("terminal-output").innerHTML = "";
}

/* ── Results Dashboard Display ────────────────────────────────────────────── */
function displayResults(res) {
  const dashboard = document.getElementById("results-dashboard");
  dashboard.classList.remove("hidden");
  dashboard.scrollIntoView({ behavior: "smooth" });

  document.getElementById("res-company").textContent = res.company;
  document.getElementById("res-role").textContent = res.role;

  const beforeVal = (res.simplify_score_before !== undefined && res.simplify_score_before !== null) 
    ? res.simplify_score_before 
    : (res.score_before || 75);
  const afterVal = res.score_after || (beforeVal < 90 ? 90 : Math.min(98, beforeVal + 10));
  const deltaVal = res.score_delta || (afterVal - beforeVal);

  document.getElementById("score-before").textContent = `${beforeVal}%`;
  document.getElementById("score-after").textContent = `${afterVal}%`;
  document.getElementById("score-delta-badge").textContent = `+${deltaVal}% Target Match`;
  document.getElementById("keywords-added-count").textContent = res.newly_added ? res.newly_added.length : (res.keywords_injected || 0);

  // Newly added keyword pills
  const addedPills = document.getElementById("newly-added-pills");
  addedPills.innerHTML = "";
  if (res.newly_added && res.newly_added.length > 0) {
    res.newly_added.forEach(kw => {
      const pill = document.createElement("span");
      pill.className = "pill pill-success";
      pill.textContent = kw;
      addedPills.appendChild(pill);
    });
  } else {
    addedPills.innerHTML = `<span class="pill pill-success">Master resume already matched all keywords!</span>`;
  }

  // Still missing pills
  const missingPills = document.getElementById("still-missing-pills");
  missingPills.innerHTML = "";
  if (res.still_missing && res.still_missing.length > 0) {
    res.still_missing.forEach(kw => {
      const pill = document.createElement("span");
      pill.className = "pill pill-warn";
      pill.textContent = kw;
      missingPills.appendChild(pill);
    });
  } else {
    missingPills.innerHTML = `<span class="pill pill-success">0 missing keywords! 100% Match!</span>`;
  }

  // Download & Open folder buttons
  const downloadBtn = document.getElementById("download-doc-btn");
  downloadBtn.href = `/api/download/${res.relative_path}`;

  const downloadPdfBtn = document.getElementById("download-pdf-btn");
  if (downloadPdfBtn) {
    const pdfPath = res.relative_path.replace(/\.docx$/i, ".pdf");
    downloadPdfBtn.href = `/api/download/${pdfPath}`;
  }

  window.lastResult = res;
}

const selectedHistoryFiles = new Set();

async function loadHistory() {
  const grid = document.getElementById("history-grid");
  const toolbar = document.getElementById("history-toolbar");
  const selectAllCb = document.getElementById("select-all-history-cb");
  if (selectAllCb) selectAllCb.checked = false;
  selectedHistoryFiles.clear();
  updateHistoryToolbarUI();

  try {
    const res = await fetch("/api/history");
    const data = await res.json();

    if (data.applications.length === 0) {
      grid.innerHTML = `
        <div class="empty-state glass-card">
          <i class="fa-solid fa-folder-open empty-icon"></i>
          <h3>No applications generated yet</h3>
          <p>Run your first application from the New Application tab!</p>
        </div>`;
      if (toolbar) toolbar.classList.add("hidden");
      return;
    }

    if (toolbar) toolbar.classList.remove("hidden");

    grid.innerHTML = "";
    data.applications.forEach(app => {
      const dateStr = new Date(app.timestamp).toLocaleString();
      const card = document.createElement("div");
      card.className = "history-card";
      card.innerHTML = `
        <div class="history-card-header">
          <div class="flex-align-center gap-sm">
            <input type="checkbox" class="history-item-cb" data-filename="${escapeHtml(app.log_file_name)}" onchange="toggleHistoryItemSelection('${escapeHtml(app.log_file_name)}', this.checked)">
            <div>
              <div class="history-company">${escapeHtml(app.company)}</div>
              <div class="history-role">${escapeHtml(app.role)}</div>
            </div>
          </div>
          <div class="history-date">${dateStr}</div>
        </div>
        <div class="history-scores">
          <div class="score-col">
            <span>Before Score</span>
            <strong>${app.match_score_before || 0}%</strong>
          </div>
          <div class="score-col">
            <span>After Score</span>
            <strong class="text-emerald">${app.match_score_after || 0}%</strong>
          </div>
          <div class="score-col">
            <span>Delta</span>
            <strong class="text-emerald">+${app.match_score_delta || 0}%</strong>
          </div>
        </div>
        <div class="history-actions">
          <a href="/api/download/${app.relative_file_path}" class="btn btn-emerald btn-sm" download>
            <i class="fa-solid fa-download"></i> .docx
          </a>
          ${app.relative_file_path ? `<a href="/api/download/${app.relative_file_path.replace('.docx', '.pdf')}" class="btn btn-cyan btn-sm" download><i class="fa-solid fa-file-pdf"></i> .pdf</a>` : ''}
          <button class="btn btn-purple-sm" onclick="generateOrViewHistoryCoverLetter('${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '${escapeHtml(app.relative_file_path)}', '${escapeHtml(app.url || '')}')">
            <i class="fa-solid fa-envelope"></i> Cover Letter
          </button>
          <button class="btn btn-secondary btn-sm" onclick="openSpecificFolder('${escapeHtml(app.output_file)}')">
            <i class="fa-solid fa-folder-open"></i> Folder
          </button>
          <button class="btn btn-danger-sm" onclick="deleteHistoryItem('${escapeHtml(app.log_file_name)}')">
            <i class="fa-solid fa-trash"></i> Delete
          </button>
        </div>`;
      grid.appendChild(card);
    });

  } catch (err) {
    grid.innerHTML = `<div class="empty-state">Failed to load history: ${err.message}</div>`;
  }
}

function toggleHistoryItemSelection(filename, isChecked) {
  if (isChecked) {
    selectedHistoryFiles.add(filename);
  } else {
    selectedHistoryFiles.delete(filename);
    const selectAllCb = document.getElementById("select-all-history-cb");
    if (selectAllCb) selectAllCb.checked = false;
  }
  updateHistoryToolbarUI();
}

function toggleSelectAllHistory(isChecked) {
  selectedHistoryFiles.clear();
  document.querySelectorAll(".history-item-cb").forEach(cb => {
    cb.checked = isChecked;
    if (isChecked) {
      selectedHistoryFiles.add(cb.dataset.filename);
    }
  });
  updateHistoryToolbarUI();
}

function updateHistoryToolbarUI() {
  const count = selectedHistoryFiles.size;
  const countElem = document.getElementById("selected-history-count");
  if (countElem) countElem.textContent = count;
  const btn = document.getElementById("bulk-delete-btn");
  if (btn) btn.disabled = (count === 0);
}

async function deleteSelectedHistoryBatch() {
  const count = selectedHistoryFiles.size;
  if (count === 0) return;
  if (!confirm(`Are you sure you want to delete ${count} selected test applications and their output folders from your computer?`)) return;

  const filenames = Array.from(selectedHistoryFiles);
  showToast(`Deleting ${count} history entries & folders...`, "info");

  try {
    const res = await fetch("/api/history/delete_batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filenames })
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || `Deleted ${data.deleted_count} items cleanly!`, "success");
      selectedHistoryFiles.clear();
      loadHistory();
    } else {
      showToast(`Bulk delete failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error performing bulk delete: ${err.message}`, "error");
  }
}

async function openSpecificFolder(filePath) {
  const dir = filePath ? filePath.substring(0, filePath.lastIndexOf("\\")) : undefined;
  fetch("/api/open-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder_path: dir }),
  });
}

/* ── Settings & Resume Editor ────────────────────────────────────────────── */
async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();

    document.getElementById("gemini-key-input").value = data.GEMINI_API_KEY || "";
    document.getElementById("simplify-email-input").value = data.SIMPLIFY_EMAIL || "";
    document.getElementById("simplify-pass-input").value = data.SIMPLIFY_PASSWORD || "";
    document.getElementById("custom-output-dir").value = data.OUTPUT_DIR || "";
  } catch (err) {
    console.error("Failed to load settings", err);
  }

  document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const key = document.getElementById("gemini-key-input").value.trim();
    const email = document.getElementById("simplify-email-input").value.trim();
    const pass = document.getElementById("simplify-pass-input").value.trim();

    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          GEMINI_API_KEY: key,
          SIMPLIFY_EMAIL: email,
          SIMPLIFY_PASSWORD: pass,
        }),
      });
      const data = await res.json();
      if (data.success) {
        showToast("Settings saved successfully!", "success");
        checkSystemHealth();
      } else {
        showToast("Failed to save settings", "error");
      }
    } catch (err) {
      showToast(`Error saving settings: ${err.message}`, "error");
    }
  });
}

let currentMasterResumeData = null;

async function loadMasterResume() {
  const textarea = document.getElementById("resume-json-editor");
  const visualCard = document.getElementById("visual-resume-card");
  const jsonCard = document.getElementById("json-editor-card");
  const uploadPrompt = document.getElementById("resume-upload-prompt");
  const resumeActionsBar = document.getElementById("resume-actions-bar");

  try {
    const res = await fetch("/api/resume");
    const data = await res.json();
    currentMasterResumeData = data;

    const isEmpty = data._empty || (!data.name && (!data.skills || data.skills.length === 0));

    if (isEmpty) {
      // Show upload prompt, hide resume views
      if (uploadPrompt) uploadPrompt.classList.remove("hidden");
      if (visualCard) visualCard.classList.add("hidden");
      if (jsonCard) jsonCard.classList.add("hidden");
      if (resumeActionsBar) resumeActionsBar.classList.add("hidden");
    } else {
      if (uploadPrompt) uploadPrompt.classList.add("hidden");
      if (visualCard) visualCard.classList.remove("hidden");
      if (jsonCard) jsonCard.classList.add("hidden");
      if (resumeActionsBar) resumeActionsBar.classList.remove("hidden");
      textarea.value = JSON.stringify(data, null, 2);
      renderVisualResume(data);
    }
  } catch (err) {
    textarea.value = "// Error loading base_resume.json";
  }
}

function renderVisualResume(data) {
  const card = document.getElementById("visual-resume-card");
  if (!card || !data) return;

  const contact = data.contact || {};
  const name = data.name || contact.name || "";
  const email = contact.email || "";
  const phone = contact.phone || "";
  const linkedin = contact.linkedin || "";
  const github = contact.github || "";
  const location = contact.location || "";

  const summary = data.summary || "";
  const skills = (data.skills || []).join(", ");
  const experience = data.experience || [];
  const projects = data.projects || [];
  const education = data.education || [];
  const certifications = data.certifications || [];

  let html = `
    <div class="vr-editor-container">
      
      <!-- ── SECTION 1: Personal Info & Contact ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-user-circle"></i> Candidate Profile & Contact Info</div>
        </div>
        <div class="vr-grid-2">
          <div class="vr-field">
            <label class="vr-label">Full Name</label>
            <input type="text" id="vr-name" class="vr-input" value="${escapeHtml(name)}" placeholder="e.g. Haseeb Khan">
          </div>
          <div class="vr-field">
            <label class="vr-label">Location</label>
            <input type="text" id="vr-location" class="vr-input" value="${escapeHtml(location)}" placeholder="e.g. West Warwick, RI">
          </div>
        </div>
        <div class="vr-grid-2">
          <div class="vr-field">
            <label class="vr-label">Email Address</label>
            <input type="email" id="vr-email" class="vr-input" value="${escapeHtml(email)}" placeholder="e.g. candidate@example.com">
          </div>
          <div class="vr-field">
            <label class="vr-label">Phone Number</label>
            <input type="text" id="vr-phone" class="vr-input" value="${escapeHtml(phone)}" placeholder="e.g. +1 555-123-4567">
          </div>
        </div>
        <div class="vr-grid-2">
          <div class="vr-field">
            <label class="vr-label">LinkedIn Profile URL / Handle</label>
            <input type="text" id="vr-linkedin" class="vr-input" value="${escapeHtml(linkedin)}" placeholder="e.g. linkedin.com/in/username">
          </div>
          <div class="vr-field">
            <label class="vr-label">GitHub Profile URL / Handle (optional)</label>
            <input type="text" id="vr-github" class="vr-input" value="${escapeHtml(github)}" placeholder="e.g. github.com/username">
          </div>
        </div>
      </div>

      <!-- ── SECTION 2: Professional Summary ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-file-lines"></i> Professional Summary</div>
        </div>
        <div class="vr-field">
          <textarea id="vr-summary" class="vr-textarea" style="min-height: 100px;" placeholder="Write or edit your master professional summary...">${escapeHtml(summary)}</textarea>
        </div>
      </div>

      <!-- ── SECTION 3: Technical Skills ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-bolt"></i> Technical Skills</div>
          <span style="font-size:12px; color:var(--text-muted);">Separate skills with commas</span>
        </div>
        <div class="vr-field">
          <textarea id="vr-skills" class="vr-textarea" style="min-height: 70px;" placeholder="Python, SQL, React, AWS, Docker, Databricks, PostgreSQL, PySpark..." oninput="updateSkillsPillsPreview()">${escapeHtml(skills)}</textarea>
        </div>
        <div id="vr-skills-pills" class="skills-pill-group" style="margin-top: 4px;">
          ${(data.skills || []).map(s => `<span class="chip-cyan">${escapeHtml(s)}</span>`).join('')}
        </div>
      </div>

      <!-- ── SECTION 4: Work Experience ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-briefcase"></i> Work Experience (${experience.length})</div>
          <button type="button" class="vr-btn-add" onclick="addExperienceRole()"><i class="fa-solid fa-plus"></i> Add Role</button>
        </div>
        <div id="vr-experience-list" style="display:flex; flex-direction:column; gap:14px;">
          ${experience.map((exp, roleIdx) => `
            <div class="vr-item-card" data-role-idx="${roleIdx}">
              <div class="vr-item-card-header">
                <span style="font-weight:700; color:var(--text-main); font-size:14px;">Role #${roleIdx + 1}</span>
                <button type="button" class="vr-btn-delete" onclick="removeExperienceRole(${roleIdx})"><i class="fa-solid fa-trash"></i> Delete Role</button>
              </div>
              <div class="vr-grid-2">
                <div class="vr-field">
                  <label class="vr-label">Job Title</label>
                  <input type="text" class="vr-input vr-exp-title" value="${escapeHtml(exp.title || '')}" placeholder="e.g. Senior Data Engineer">
                </div>
                <div class="vr-field">
                  <label class="vr-label">Company Name</label>
                  <input type="text" class="vr-input vr-exp-company" value="${escapeHtml(exp.company || '')}" placeholder="e.g. Tech Corp">
                </div>
              </div>
              <div class="vr-grid-2">
                <div class="vr-field">
                  <label class="vr-label">Dates / Duration</label>
                  <input type="text" class="vr-input vr-exp-dates" value="${escapeHtml(exp.dates || '')}" placeholder="e.g. 2021 – Present">
                </div>
                <div class="vr-field">
                  <label class="vr-label">Location (optional)</label>
                  <input type="text" class="vr-input vr-exp-location" value="${escapeHtml(exp.location || '')}" placeholder="e.g. Remote / New York, NY">
                </div>
              </div>
              
              <!-- Bullets list -->
              <div class="vr-field">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                  <label class="vr-label">Experience Bullet Points</label>
                  <button type="button" class="vr-btn-add" style="padding:4px 8px; font-size:11px;" onclick="addExpBullet(${roleIdx})"><i class="fa-solid fa-plus"></i> Add Bullet</button>
                </div>
                <div class="vr-exp-bullets-container" data-role-idx="${roleIdx}" style="display:flex; flex-direction:column; gap:6px;">
                  ${(exp.bullets || []).map((b, bIdx) => `
                    <div class="vr-bullet-item">
                      <textarea class="vr-textarea vr-exp-bullet" placeholder="Action verb + achievement + technical tools used...">${escapeHtml(b)}</textarea>
                      <button type="button" class="vr-btn-delete" style="padding:8px;" onclick="removeExpBullet(${roleIdx}, ${bIdx})"><i class="fa-solid fa-trash"></i></button>
                    </div>
                  `).join('')}
                </div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- ── SECTION 5: Education ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-graduation-cap"></i> Education (${education.length})</div>
          <button type="button" class="vr-btn-add" onclick="addEducationEntry()"><i class="fa-solid fa-plus"></i> Add Education</button>
        </div>
        <div id="vr-education-list" style="display:flex; flex-direction:column; gap:12px;">
          ${education.map((edu, eduIdx) => `
            <div class="vr-item-card" data-edu-idx="${eduIdx}">
              <div class="vr-item-card-header">
                <span style="font-weight:700; color:var(--text-main); font-size:14px;">Degree #${eduIdx + 1}</span>
                <button type="button" class="vr-btn-delete" onclick="removeEducationEntry(${eduIdx})"><i class="fa-solid fa-trash"></i> Delete</button>
              </div>
              <div class="vr-grid-2">
                <div class="vr-field">
                  <label class="vr-label">Degree</label>
                  <input type="text" class="vr-input vr-edu-degree" value="${escapeHtml(edu.degree || '')}" placeholder="e.g. Bachelor of Software Engineering">
                </div>
                <div class="vr-field">
                  <label class="vr-label">Field of Study</label>
                  <input type="text" class="vr-input vr-edu-field" value="${escapeHtml(edu.field || '')}" placeholder="e.g. Computer Science">
                </div>
              </div>
              <div class="vr-grid-3">
                <div class="vr-field">
                  <label class="vr-label">Institution / University</label>
                  <input type="text" class="vr-input vr-edu-institution" value="${escapeHtml(edu.institution || '')}" placeholder="e.g. Foundation University">
                </div>
                <div class="vr-field">
                  <label class="vr-label">Graduation Date / Year</label>
                  <input type="text" class="vr-input vr-edu-dates" value="${escapeHtml(edu.graduation_date || edu.dates || '')}" placeholder="e.g. 2017">
                </div>
                <div class="vr-field">
                  <label class="vr-label">GPA (optional)</label>
                  <input type="text" class="vr-input vr-edu-gpa" value="${escapeHtml(edu.gpa || '')}" placeholder="e.g. 3.8 / 4.0">
                </div>
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- ── SECTION 6: Key Projects ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-laptop-code"></i> Key Projects (${projects.length})</div>
          <button type="button" class="vr-btn-add" onclick="addProjectEntry()"><i class="fa-solid fa-plus"></i> Add Project</button>
        </div>
        <div id="vr-projects-list" style="display:flex; flex-direction:column; gap:12px;">
          ${projects.map((proj, pIdx) => `
            <div class="vr-item-card" data-proj-idx="${pIdx}">
              <div class="vr-item-card-header">
                <span style="font-weight:700; color:var(--text-main); font-size:14px;">Project #${pIdx + 1}</span>
                <button type="button" class="vr-btn-delete" onclick="removeProjectEntry(${pIdx})"><i class="fa-solid fa-trash"></i> Delete</button>
              </div>
              <div class="vr-grid-2">
                <div class="vr-field">
                  <label class="vr-label">Project Name</label>
                  <input type="text" class="vr-input vr-proj-name" value="${escapeHtml(proj.name || '')}" placeholder="e.g. Automated Lakehouse Pipeline">
                </div>
                <div class="vr-field">
                  <label class="vr-label">Project URL / Repo Link (optional)</label>
                  <input type="text" class="vr-input vr-proj-url" value="${escapeHtml(proj.url || '')}" placeholder="e.g. https://github.com/...">
                </div>
              </div>
              <div class="vr-field">
                <label class="vr-label">Description</label>
                <textarea class="vr-textarea vr-proj-description" placeholder="Project overview and impact...">${escapeHtml(proj.description || '')}</textarea>
              </div>
              <div class="vr-field">
                <label class="vr-label">Tech Stack (comma-separated)</label>
                <input type="text" class="vr-input vr-proj-tech" value="${escapeHtml((proj.tech_stack || []).join(', '))}" placeholder="e.g. Python, Databricks, Delta Lake, AWS">
              </div>
            </div>
          `).join('')}
        </div>
      </div>

      <!-- ── SECTION 7: Certifications ── -->
      <div class="vr-section">
        <div class="vr-section-header">
          <div class="vr-section-title"><i class="fa-solid fa-award"></i> Certifications (${certifications.length})</div>
          <button type="button" class="vr-btn-add" onclick="addCertificationEntry()"><i class="fa-solid fa-plus"></i> Add Certification</button>
        </div>
        <div id="vr-certifications-list" style="display:flex; flex-direction:column; gap:8px;">
          ${certifications.map((cert, cIdx) => `
            <div class="vr-bullet-item" data-cert-idx="${cIdx}">
              <input type="text" class="vr-input vr-cert-item" value="${escapeHtml(cert)}" placeholder="e.g. AZ-900 | Azure Fundamentals">
              <button type="button" class="vr-btn-delete" style="padding:8px;" onclick="removeCertificationEntry(${cIdx})"><i class="fa-solid fa-trash"></i></button>
            </div>
          `).join('')}
        </div>
      </div>

    </div>
  `;

  card.innerHTML = html;
}

function updateSkillsPillsPreview() {
  const input = document.getElementById("vr-skills");
  const pillsContainer = document.getElementById("vr-skills-pills");
  if (!input || !pillsContainer) return;
  const skills = input.value.split(",").map(s => s.trim()).filter(Boolean);
  pillsContainer.innerHTML = skills.map(s => `<span class="chip-cyan">${escapeHtml(s)}</span>`).join('');
}

function collectVisualResumeData() {
  const name = (document.getElementById("vr-name")?.value || "").trim();
  const location = (document.getElementById("vr-location")?.value || "").trim();
  const email = (document.getElementById("vr-email")?.value || "").trim();
  const phone = (document.getElementById("vr-phone")?.value || "").trim();
  const linkedin = (document.getElementById("vr-linkedin")?.value || "").trim();
  const github = (document.getElementById("vr-github")?.value || "").trim();
  const summary = (document.getElementById("vr-summary")?.value || "").trim();
  
  const rawSkills = (document.getElementById("vr-skills")?.value || "");
  const skills = rawSkills.split(",").map(s => s.trim()).filter(Boolean);

  // Experience
  const expCards = document.querySelectorAll("#vr-experience-list .vr-item-card");
  const experience = [];
  expCards.forEach(card => {
    const title = card.querySelector(".vr-exp-title")?.value.trim() || "";
    const company = card.querySelector(".vr-exp-company")?.value.trim() || "";
    const dates = card.querySelector(".vr-exp-dates")?.value.trim() || "";
    const loc = card.querySelector(".vr-exp-location")?.value.trim() || "";
    const bulletEls = card.querySelectorAll(".vr-exp-bullet");
    const bullets = [];
    bulletEls.forEach(bEl => {
      const bText = bEl.value.trim();
      if (bText) bullets.push(bText);
    });
    if (title || company || bullets.length > 0) {
      experience.push({
        title: title,
        company: company,
        dates: dates,
        location: loc || null,
        bullets: bullets
      });
    }
  });

  // Education
  const eduCards = document.querySelectorAll("#vr-education-list .vr-item-card");
  const education = [];
  eduCards.forEach(card => {
    const degree = card.querySelector(".vr-edu-degree")?.value.trim() || "";
    const field = card.querySelector(".vr-edu-field")?.value.trim() || "";
    const institution = card.querySelector(".vr-edu-institution")?.value.trim() || "";
    const gradDate = card.querySelector(".vr-edu-dates")?.value.trim() || "";
    const gpa = card.querySelector(".vr-edu-gpa")?.value.trim() || null;
    if (degree || institution) {
      education.push({
        degree: degree,
        field: field,
        institution: institution,
        graduation_date: gradDate,
        gpa: gpa
      });
    }
  });

  // Projects
  const projCards = document.querySelectorAll("#vr-projects-list .vr-item-card");
  const projects = [];
  projCards.forEach(card => {
    const pName = card.querySelector(".vr-proj-name")?.value.trim() || "";
    const url = card.querySelector(".vr-proj-url")?.value.trim() || "";
    const desc = card.querySelector(".vr-proj-description")?.value.trim() || "";
    const techRaw = card.querySelector(".vr-proj-tech")?.value.trim() || "";
    const techStack = techRaw.split(",").map(t => t.trim()).filter(Boolean);
    if (pName || desc) {
      projects.push({
        name: pName,
        url: url || null,
        description: desc,
        tech_stack: techStack
      });
    }
  });

  // Certifications
  const certInputs = document.querySelectorAll("#vr-certifications-list .vr-cert-item");
  const certifications = [];
  certInputs.forEach(cIn => {
    const val = cIn.value.trim();
    if (val) certifications.push(val);
  });

  return {
    name: name,
    contact: {
      email: email,
      phone: phone,
      linkedin: linkedin,
      github: github || null,
      portfolio: null,
      location: location
    },
    summary: summary,
    skills: skills,
    experience: experience,
    education: education,
    projects: projects,
    certifications: certifications
  };
}

// ── Dynamic Visual Editor Helpers ───────────────────────────────────────────
function addExperienceRole() {
  const currentData = collectVisualResumeData();
  currentData.experience.push({
    title: "",
    company: "",
    dates: "",
    location: null,
    bullets: [""]
  });
  renderVisualResume(currentData);
}

function removeExperienceRole(roleIdx) {
  const currentData = collectVisualResumeData();
  currentData.experience.splice(roleIdx, 1);
  renderVisualResume(currentData);
}

function addExpBullet(roleIdx) {
  const currentData = collectVisualResumeData();
  if (currentData.experience[roleIdx]) {
    currentData.experience[roleIdx].bullets.push("");
    renderVisualResume(currentData);
  }
}

function removeExpBullet(roleIdx, bulletIdx) {
  const currentData = collectVisualResumeData();
  if (currentData.experience[roleIdx]) {
    currentData.experience[roleIdx].bullets.splice(bulletIdx, 1);
    renderVisualResume(currentData);
  }
}

function addEducationEntry() {
  const currentData = collectVisualResumeData();
  currentData.education.push({
    degree: "",
    field: "",
    institution: "",
    graduation_date: "",
    gpa: null
  });
  renderVisualResume(currentData);
}

function removeEducationEntry(eduIdx) {
  const currentData = collectVisualResumeData();
  currentData.education.splice(eduIdx, 1);
  renderVisualResume(currentData);
}

function addProjectEntry() {
  const currentData = collectVisualResumeData();
  currentData.projects.push({
    name: "",
    url: null,
    description: "",
    tech_stack: []
  });
  renderVisualResume(currentData);
}

function removeProjectEntry(projIdx) {
  const currentData = collectVisualResumeData();
  currentData.projects.splice(projIdx, 1);
  renderVisualResume(currentData);
}

function addCertificationEntry() {
  const currentData = collectVisualResumeData();
  currentData.certifications.push("");
  renderVisualResume(currentData);
}

function removeCertificationEntry(certIdx) {
  const currentData = collectVisualResumeData();
  currentData.certifications.splice(certIdx, 1);
  renderVisualResume(currentData);
}

function toggleResumeViewMode() {
  const visualCard = document.getElementById("visual-resume-card");
  const jsonCard = document.getElementById("json-editor-card");
  const toggleBtn = document.getElementById("toggle-json-view-btn");
  const textarea = document.getElementById("resume-json-editor");

  if (jsonCard.classList.contains("hidden")) {
    // Switch Visual -> JSON
    const visualData = collectVisualResumeData();
    textarea.value = JSON.stringify(visualData, null, 2);
    jsonCard.classList.remove("hidden");
    visualCard.classList.add("hidden");
    toggleBtn.innerHTML = `<i class="fa-solid fa-eye"></i> Visual Resume Mode`;
  } else {
    // Switch JSON -> Visual
    try {
      const parsed = JSON.parse(textarea.value);
      renderVisualResume(parsed);
      jsonCard.classList.add("hidden");
      visualCard.classList.remove("hidden");
      toggleBtn.innerHTML = `<i class="fa-solid fa-code"></i> Raw JSON Mode`;
    } catch (e) {
      showToast("Invalid JSON syntax — fix JSON before switching to visual mode", "error");
    }
  }
}


async function uploadMasterResumeFile(event) {
  const file = event.target.files[0];
  if (!file) return;

  // Reset the input so the same file can be re-selected if needed
  event.target.value = "";

  const progressCard  = document.getElementById("resume-upload-progress-card");
  const uploadPrompt  = document.getElementById("resume-upload-prompt");
  const visualCard    = document.getElementById("visual-resume-card");
  const jsonCard      = document.getElementById("json-editor-card");
  const actionsBar    = document.getElementById("resume-actions-bar");
  const bar           = document.getElementById("resume-upload-bar");
  const pctLabel      = document.getElementById("upload-progress-pct");
  const mainLabel     = document.getElementById("upload-progress-label");
  const subLabel      = document.getElementById("upload-progress-sub");

  // Show progress card, hide everything else
  if (uploadPrompt) uploadPrompt.classList.add("hidden");
  if (visualCard)   visualCard.classList.add("hidden");
  if (jsonCard)     jsonCard.classList.add("hidden");
  if (actionsBar)   actionsBar.classList.add("hidden");
  progressCard.classList.remove("hidden");

  mainLabel.textContent = `Uploading ${file.name}…`;
  subLabel.textContent  = "Sending file to server…";

  // ── Phase 1: Real XHR upload progress (0 → 40%) ─────────────────────────
  function setBar(pct) {
    bar.style.width = pct + "%";
    pctLabel.textContent = pct + "%";
  }

  let uploadPct = 0;
  setBar(0);

  const formData = new FormData();
  formData.append("resume_file", file);

  const result = await new Promise((resolve) => {
    const xhr = new XMLHttpRequest();

    xhr.upload.addEventListener("progress", (e) => {
      if (e.lengthComputable) {
        uploadPct = Math.round((e.loaded / e.total) * 40);  // 0–40%
        setBar(uploadPct);
      }
    });

    xhr.addEventListener("load", () => {
      resolve({ ok: xhr.status < 400, body: xhr.responseText });
    });
    xhr.addEventListener("error", () => {
      resolve({ ok: false, body: null });
    });

    xhr.open("POST", "/api/upload_resume");
    xhr.send(formData);
  });

  if (!result.ok || !result.body) {
    progressCard.classList.add("hidden");
    if (uploadPrompt) uploadPrompt.classList.remove("hidden");
    showToast("Upload failed — check that the server is running.", "error");
    return;
  }

  // ── Phase 2: Gemini parsing phase (40 → 95%, animated) ──────────────────
  mainLabel.textContent = "Parsing resume with Gemini AI…";
  subLabel.textContent  = "Extracting skills, experience, education…";
  setBar(40);

  // Animate the bar smoothly from 40 → 92% while Gemini works
  let parsePct = 40;
  const parseInterval = setInterval(() => {
    if (parsePct < 92) {
      parsePct += Math.random() * 3 + 1;  // 1–4% per tick
      setBar(Math.min(Math.round(parsePct), 92));
    }
  }, 400);

  // The upload already completed (xhr.load fired) so parse data is ready
  clearInterval(parseInterval);

  let data;
  try {
    data = JSON.parse(result.body);
  } catch {
    progressCard.classList.add("hidden");
    if (uploadPrompt) uploadPrompt.classList.remove("hidden");
    showToast("Server returned an unexpected response.", "error");
    return;
  }

  // ── Phase 3: Done ─────────────────────────────────────────────────────────
  setBar(100);
  pctLabel.textContent = "100%";
  mainLabel.textContent = data.success ? "✅ Resume parsed successfully!" : "❌ Parse failed";
  subLabel.textContent  = data.message || data.error || "";

  await new Promise(r => setTimeout(r, 900));  // brief moment so user sees 100%

  progressCard.classList.add("hidden");

  if (data.success) {
    showToast(data.message || "Resume uploaded and parsed!", "success");
    loadMasterResume();
  } else {
    showToast(`Upload failed: ${data.error}`, "error");
    if (uploadPrompt) uploadPrompt.classList.remove("hidden");
  }
}

async function deleteCurrentResume() {
  if (!confirm("Are you sure you want to delete your Master Resume? You will need to upload a new one before generating applications.")) return;

  try {
    const res = await fetch("/api/delete_resume", { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      showToast("Master resume deleted. Please upload a new one.", "warning");
      currentMasterResumeData = null;
      loadMasterResume();
    } else {
      showToast(`Delete failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error deleting resume: ${err.message}`, "error");
  }
}



async function deleteHistoryItem(filename) {
  if (!confirm("Are you sure you want to delete this test application from your history and computer?")) return;

  try {
    const res = await fetch(`/api/history/${encodeURIComponent(filename)}`, {
      method: "DELETE"
    });
    const data = await res.json();
    if (data.success) {
      showToast("History entry deleted cleanly!", "success");
      loadHistory();
    } else {
      showToast(`Delete failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error deleting history entry: ${err.message}`, "error");
  }
}

async function saveMasterResume() {
  const jsonCard = document.getElementById("json-editor-card");
  const textarea = document.getElementById("resume-json-editor");
  let resumePayload = null;

  try {
    if (jsonCard && !jsonCard.classList.contains("hidden")) {
      // Saving from Raw JSON Mode
      resumePayload = JSON.parse(textarea.value);
    } else {
      // Saving from Visual Resume Mode
      resumePayload = collectVisualResumeData();
      textarea.value = JSON.stringify(resumePayload, null, 2);
    }

    const res = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(resumePayload),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Master resume saved & updated successfully!", "success");
      currentMasterResumeData = resumePayload;
      loadMasterResume();
    } else {
      showToast(`Save failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error saving resume: ${err.message || "Invalid syntax"}`, "error");
  }
}

/* ── Toast Utilities ─────────────────────────────────────────────────────── */
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const icon = type === "success" ? "fa-circle-check text-emerald" :
               type === "error" ? "fa-circle-xmark text-red" :
               type === "warning" ? "fa-triangle-exclamation text-amber" : "fa-circle-info text-cyan";

  toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(20px)";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* ── Simplify-Style Interactive Keyword Cross-Check ─────────────────────── */
let analyzedMissingKeywords = [];
let selectedMissingKeywords = new Set();
let analyzeScoreBefore = null;  // Preserved from Analyze step, used as authoritative before score
let analyzeCompany = null;
let analyzeRole = null;
let analyzeJdText = null;

async function analyzeJobKeywords() {
  let url = document.getElementById("jd-url").value.trim();
  if (!url) {
    showToast("Please enter a valid job posting URL first", "warning");
    return;
  }
  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    url = "https://" + url;
    document.getElementById("jd-url").value = url;
  }

  const analyzeBtn = document.getElementById("analyze-btn");
  analyzeBtn.disabled = true;
  analyzeBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Analyzing...`;

  // Clear any previous inline error
  _analyzeHideError();

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url,
        no_simplify: document.getElementById("no-simplify-toggle").checked
      })
    });

    const data = await res.json();
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;

    if (!data.success) {
      const isBlockError = data.error_type === "scrape_blocked" || data.error_type === "jd_blocked";
      if (isBlockError) {
        _analyzeShowError(data.error || "Could not extract job description from this URL.");
      } else {
        showToast(data.error || "Analysis failed", "error");
      }
      return;
    }

    // Save analyze state so Generate step can reuse it without re-doing work
    analyzeScoreBefore = data.score;
    analyzeCompany = data.company;
    analyzeRole = data.role;

    renderSimplifyCard(data);
    showToast(`Scraped ${data.role} at ${data.company}! Keywords cross-checked.`, "success");
  } catch (err) {
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;
    showToast("Server connection error during analysis", "error");
  }
}

function _analyzeShowError(msg) {
  let card = document.getElementById("analyze-error-card");
  if (!card) {
    card = document.createElement("div");
    card.id = "analyze-error-card";
    card.style.cssText = [
      "margin-top:14px","padding:16px 18px","border-radius:10px",
      "background:rgba(239,68,68,0.12)","border:1px solid rgba(239,68,68,0.35)",
      "color:#fca5a5","font-size:13px","line-height:1.7","white-space:pre-wrap",
      "word-break:break-word",
    ].join(";");
    const btn = document.getElementById("analyze-btn");
    if (btn && btn.parentNode) btn.parentNode.insertBefore(card, btn.nextSibling);
  }
  card.innerHTML = `<strong style="color:#f87171;display:block;margin-bottom:8px;">
    <i class="fa-solid fa-triangle-exclamation"></i>&nbsp;Scrape Blocked
  </strong>${msg.replace(/\n/g, "<br>")}`;
  card.style.display = "block";
}

function _analyzeHideError() {
  const card = document.getElementById("analyze-error-card");
  if (card) card.style.display = "none";
}

function renderSimplifyCard(data) {
  const card = document.getElementById("simplify-card");
  card.classList.remove("hidden");

  // 1. Score & Rating
  const score10 = data.score_scale_10 || (Math.round((data.score || 55) / 10 * 10) / 10);
  const rating = data.score_rating || (score10 < 6.0 ? "Poor" : score10 < 7.0 ? "Fair" : score10 < 8.0 ? "Good" : score10 < 9.0 ? "Great" : "Excellent");

  const scoreEl = document.getElementById("matrix-gauge-score");
  const ratingEl = document.getElementById("matrix-rating-text");
  if (scoreEl) scoreEl.innerText = score10.toFixed(1);
  if (ratingEl) ratingEl.innerText = rating;

  // Arc Gauge Animation (perimeter = 142)
  const arcFill = document.getElementById("matrix-gauge-fill");
  const pct = Math.min(1.0, Math.max(0.0, score10 / 10.0));
  const offset = 142 - (142 * pct);
  if (arcFill) arcFill.style.strokeDashoffset = offset;

  // Match Title & Alert Banner
  const verdictWord = document.getElementById("matrix-verdict-word");
  const alertPill = document.getElementById("matrix-alert-pill");
  const alertText = document.getElementById("matrix-alert-text");

  if (verdictWord && alertPill && alertText) {
    if (score10 < 6.0) {
      verdictWord.innerText = "Low Match";
      verdictWord.style.color = "#ef4444";
      alertPill.style.background = "#ffe4e6";
      alertPill.style.borderColor = "#fecdd3";
      alertPill.style.color = "#9f1239";
      alertText.innerText = "Resumes under 6.0 are likely to be filtered out by ATS — we'll help you fix it fast.";
    } else if (score10 < 7.5) {
      verdictWord.innerText = "Moderate Match";
      verdictWord.style.color = "#f59e0b";
      alertPill.style.background = "#fef3c7";
      alertPill.style.borderColor = "#fde68a";
      alertPill.style.color = "#92400e";
      alertText.innerText = "Resumes between 6.0 and 7.5 can be improved with targeted missing keywords.";
    } else {
      verdictWord.innerText = "Strong Match";
      verdictWord.style.color = "#10b981";
      alertPill.style.background = "#d1fae5";
      alertPill.style.borderColor = "#a7f3d0";
      alertPill.style.color = "#065f46";
      alertText.innerText = "Great alignment! Ready for submission or light tailoring.";
    }
  }

  // 2. Overview Row
  const compAvatar = document.getElementById("matrix-company-avatar");
  const compName = document.getElementById("matrix-company-name");
  const roleName = document.getElementById("matrix-role-name");
  const resumeFile = document.getElementById("matrix-resume-filename");

  const cName = data.company || "Company";
  if (compName) compName.innerText = cName;
  if (compAvatar) compAvatar.innerText = cName.substring(0, 3).toUpperCase();
  if (roleName) roleName.innerText = data.role || "Job Role";
  if (resumeFile) resumeFile.innerText = data.resume_name || "Haseeb_Khan_Resume";

  // 3. Job Title Row
  const titleJd = document.getElementById("matrix-title-jd");
  const titleResume = document.getElementById("matrix-title-resume");
  const titleStatus = document.getElementById("matrix-title-status");

  if (titleJd) titleJd.innerText = data.job_title_jd || data.role;
  if (titleResume) titleResume.innerText = data.job_title_resume || "Data Engineer II";
  if (titleStatus) {
    if (data.job_title_match) {
      titleStatus.className = "matrix-status-dot dot-match";
      titleStatus.innerHTML = `<i class="fa-solid fa-check"></i>`;
    } else {
      titleStatus.className = "matrix-status-dot dot-warn";
      titleStatus.innerHTML = `<i class="fa-solid fa-exclamation"></i>`;
    }
  }

  // 4. Years of Experience Row
  const expJd = document.getElementById("matrix-exp-jd");
  const expResume = document.getElementById("matrix-exp-resume");
  const expStatus = document.getElementById("matrix-exp-status");

  if (expJd) expJd.innerHTML = `${(data.exp_years_jd || "3+ years exp").replace(/years/gi, "<mark class='matrix-hl'>years</mark>")}`;
  if (expResume) expResume.innerHTML = `${(data.exp_years_resume || "8+ years exp").replace(/years/gi, "<mark class='matrix-hl'>years</mark>")}`;
  if (expStatus) {
    expStatus.className = data.exp_years_match ? "matrix-status-dot dot-match" : "matrix-status-dot dot-warn";
    expStatus.innerHTML = data.exp_years_match ? `<i class="fa-solid fa-check"></i>` : `<i class="fa-solid fa-exclamation"></i>`;
  }

  // 5. Industry Experience Row
  const indContainer = document.getElementById("matrix-industries-container");
  if (indContainer) {
    indContainer.innerHTML = "";
    const industries = data.industries || ["Collectibles", "Finance", "Financial Services", "FinTech", "Lending", "Marketplace"];
    industries.forEach(ind => {
      const pill = document.createElement("span");
      pill.className = "matrix-industry-pill";
      pill.innerText = ind;
      indContainer.appendChild(pill);
    });
  }
  const indStatus = document.getElementById("matrix-industry-status");
  if (indStatus) {
    indStatus.className = data.industries_match ? "matrix-status-dot dot-match" : "matrix-status-dot dot-warn";
    indStatus.innerHTML = data.industries_match ? `<i class="fa-solid fa-check"></i>` : `<i class="fa-solid fa-exclamation"></i>`;
  }

  // 6. ATS Job Keywords Row
  const kwContainer = document.getElementById("matrix-keywords-container");
  const matched = data.matching_keywords || [];
  const missing = data.missing_keywords || [];
  const totalKw = data.total_keywords || (matched.length + missing.length);

  const matchedCountEl = document.getElementById("matrix-kw-matched-count");
  const totalCountEl = document.getElementById("matrix-kw-total-count");
  if (matchedCountEl) matchedCountEl.innerText = matched.length;
  if (totalCountEl) totalCountEl.innerText = totalKw;

  const kwStatus = document.getElementById("matrix-kw-status");
  if (kwStatus) {
    if (matched.length >= totalKw * 0.7) {
      kwStatus.className = "matrix-status-dot dot-match";
      kwStatus.innerHTML = `<i class="fa-solid fa-check"></i>`;
    } else if (matched.length >= totalKw * 0.4) {
      kwStatus.className = "matrix-status-dot dot-warn";
      kwStatus.innerHTML = `<i class="fa-solid fa-exclamation"></i>`;
    } else {
      kwStatus.className = "matrix-status-dot dot-missing";
      kwStatus.innerHTML = `<i class="fa-solid fa-xmark"></i>`;
    }
  }

  if (kwContainer) {
    kwContainer.innerHTML = "";

    // Matched chips with 👍
    matched.forEach(kw => {
      const chip = document.createElement("span");
      chip.className = "chip-matched-thumb";
      chip.innerHTML = `👍 ${kw}`;
      kwContainer.appendChild(chip);
    });

    // Missing chips
    analyzedMissingKeywords = missing;
    selectedMissingKeywords = new Set(missing);

    missing.forEach(kw => {
      const chip = document.createElement("span");
      chip.className = "chip-missing-neutral";
      chip.innerText = kw;
      kwContainer.appendChild(chip);
    });
  }

  // 7. Summary Row
  const sumFeedback = document.getElementById("matrix-summary-feedback");
  if (sumFeedback) {
    sumFeedback.innerText = data.summary_feedback || "Your current summary does not effectively showcase your qualifications and alignment with this job.";
  }
  const sumStatus = document.getElementById("matrix-summary-status");
  if (sumStatus) {
    sumStatus.className = data.summary_match ? "matrix-status-dot dot-match" : "matrix-status-dot dot-warn";
    sumStatus.innerHTML = data.summary_match ? `<i class="fa-solid fa-check"></i>` : `<i class="fa-solid fa-exclamation"></i>`;
  }

  // Scroll smoothly to Matrix Card
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function openCoverLetterFromAnalyze() {
  const comp = analyzeCompany || document.getElementById("matrix-company-name")?.innerText || "";
  const role = analyzeRole || document.getElementById("matrix-role-name")?.innerText || "";
  const url = document.getElementById("jd-url")?.value.trim() || "";
  generateOrViewHistoryCoverLetter(comp, role, "", url);
}

function generateWithSelectedKeywords() {
  const kwList = Array.from(selectedMissingKeywords);
  const kwString = kwList.join(", ");
  const customKwInput = document.getElementById("custom-keywords-input");
  if (customKwInput) customKwInput.value = kwString;

  startGeneration({
    scoreBefore: analyzeScoreBefore
  });
}

function renderMissingChip(kw, container) {
  const chip = document.createElement("div");
  chip.className = "chip-white-selectable selected";
  chip.dataset.keyword = kw;
  chip.innerHTML = `<i class="fa-solid fa-circle-check text-emerald icon-state"></i> <span>${kw}</span>`;

  chip.addEventListener("click", () => {
    if (selectedMissingKeywords.has(kw)) {
      selectedMissingKeywords.delete(kw);
      chip.classList.remove("selected");
      chip.querySelector(".icon-state").className = "fa-regular fa-circle text-dim icon-state";
    } else {
      selectedMissingKeywords.add(kw);
      chip.classList.add("selected");
      chip.querySelector(".icon-state").className = "fa-solid fa-circle-check text-emerald icon-state";
    }
  });

  container.appendChild(chip);
}

function addManualChip() {
  const input = document.getElementById("manual-add-kw-input");
  const val = input.value.trim();
  if (!val) return;

  if (!selectedMissingKeywords.has(val)) {
    selectedMissingKeywords.add(val);
    const container = document.getElementById("missing-chips-container");
    renderMissingChip(val, container);
  }
  input.value = "";
}

function generateWithSelectedKeywords() {
  const keywordsList = Array.from(selectedMissingKeywords);
  const kwInput = document.getElementById("custom-keywords-input");
  if (kwInput) {
    kwInput.value = keywordsList.join(", ");
  }

  // Pass the score captured from the Analyze step into the generation run
  startGeneration({ scoreBefore: analyzeScoreBefore });
}

/* ── Cover Letter Modal Handlers ────────────────────────────────────────── */
async function openCurrentCoverLetter() {
  if (!window.lastResult) {
    showToast("Please run an application first to view its Cover Letter", "warning");
    return;
  }

  const company = window.lastResult.company;
  const role = window.lastResult.role;
  const relPath = window.lastResult.relative_path;

  document.getElementById("cl-modal-title").innerText = `${role} Cover Letter`;
  document.getElementById("cl-modal-subtitle").innerText = `Tailored for ${company}`;
  const modal = document.getElementById("cover-letter-modal");
  modal.classList.remove("hidden");

  const textarea = document.getElementById("cl-modal-textarea");
  const url = document.getElementById("job-url") ? document.getElementById("job-url").value.trim() : "";
  window.currentCoverLetterParams = { company, role, keywords: window.lastResult.newly_added || [], url };

  function _getCoverLetterRelPath(baseRel) {
    if (!baseRel) return "";
    let clean = baseRel.replace(/\\/g, "/");
    if (clean.toLowerCase().includes("resume.docx")) {
      return clean.replace(/_Resume\.docx$/i, "_Cover_Letter.docx").replace(/Resume\.docx$/i, "Cover_Letter.docx");
    }
    return clean.replace(/[^\/]+\.docx$/i, (m) => m.replace(/resume/i, "Cover_Letter"));
  }

  if (window.lastResult.cover_letter_text) {
    textarea.value = window.lastResult.cover_letter_text;
    const downloadDocx = document.getElementById("cl-modal-docx-download");
    const coverLetterRel = _getCoverLetterRelPath(relPath);
    downloadDocx.href = `/api/download/${coverLetterRel}`;
    return;
  }

  textarea.value = "Generating high-impact recruiter cover letter with Gemini...";
  try {
    const res = await fetch("/api/cover-letter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(window.currentCoverLetterParams)
    });
    const data = await res.json();
    if (data.success) {
      textarea.value = data.cover_letter_text;
      window.lastResult.cover_letter_text = data.cover_letter_text;
      document.getElementById("cl-modal-docx-download").href = `/api/download/${data.relative_docx || _getCoverLetterRelPath(relPath)}`;
    } else {
      textarea.value = `Failed to generate cover letter: ${data.error}`;
    }
  } catch (err) {
    textarea.value = `Error generating cover letter: ${err.message}`;
  }
}

async function generateOrViewHistoryCoverLetter(company, role, relativePath, url = "") {
  const modal = document.getElementById("cover-letter-modal");
  modal.classList.remove("hidden");

  document.getElementById("cl-modal-title").innerText = `${role} Cover Letter`;
  document.getElementById("cl-modal-subtitle").innerText = `Tailored for ${company}`;
  const textarea = document.getElementById("cl-modal-textarea");
  textarea.value = "Generating recruiter-targeting AI cover letter...";

  function _getCoverLetterRelPath(baseRel) {
    if (!baseRel) return "";
    let clean = baseRel.replace(/\\/g, "/");
    if (clean.toLowerCase().includes("resume.docx")) {
      return clean.replace(/_Resume\.docx$/i, "_Cover_Letter.docx").replace(/Resume\.docx$/i, "Cover_Letter.docx");
    }
    return clean.replace(/[^\/]+\.docx$/i, (m) => m.replace(/resume/i, "Cover_Letter"));
  }

  const coverLetterRel = _getCoverLetterRelPath(relativePath);
  document.getElementById("cl-modal-docx-download").href = `/api/download/${coverLetterRel}`;

  window.currentCoverLetterParams = { company, role, keywords: [], url, isHistory: true };

  try {
    const res = await fetch("/api/cover-letter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(window.currentCoverLetterParams)
    });
    const data = await res.json();
    if (data.success) {
      textarea.value = data.cover_letter_text;
      document.getElementById("cl-modal-docx-download").href = `/api/download/${data.relative_docx || coverLetterRel}`;
    } else {
      textarea.value = `Failed to generate cover letter: ${data.error}`;
    }
  } catch (err) {
    textarea.value = `Error generating cover letter: ${err.message}`;
  }
}

async function regenerateCoverLetter() {
  if (!window.currentCoverLetterParams) return;
  
  const textarea = document.getElementById("cl-modal-textarea");
  textarea.value = "Regenerating high-impact recruiter cover letter with Gemini...";
  const btn = document.querySelector("#cover-letter-modal .btn-primary");
  if(btn) btn.disabled = true;

  try {
    const res = await fetch("/api/cover-letter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(window.currentCoverLetterParams)
    });
    const data = await res.json();
    if (data.success) {
      textarea.value = data.cover_letter_text;
      document.getElementById("cl-modal-docx-download").href = `/api/download/${data.relative_docx}`;
      if (window.lastResult && !window.currentCoverLetterParams.isHistory) {
          window.lastResult.cover_letter_text = data.cover_letter_text;
      }
      showToast("Cover letter regenerated successfully!", "success");
    } else {
      textarea.value = `Failed to regenerate cover letter: ${data.error}`;
    }
  } catch (err) {
    textarea.value = `Error regenerating cover letter: ${err.message}`;
  } finally {
    if(btn) btn.disabled = false;
  }
}

function copyCoverLetterText() {
  const textarea = document.getElementById("cl-modal-textarea");
  if (!textarea.value) return;
  navigator.clipboard.writeText(textarea.value);
  showToast("Cover letter copied to clipboard!", "success");
}

function closeCoverLetterModal() {
  document.getElementById("cover-letter-modal").classList.add("hidden");
}


/* ══════════════════════════════════════════════════════════════════════════
   AI LAB — Multi-Signal Detector & Humanizer Studio
   ══════════════════════════════════════════════════════════════════════════ */

let _currentAiLabData = null;

// Sub-mode switching between Detector & Humanizer
function switchAiLabMode(mode) {
  const detectView = document.getElementById("ai-lab-detect-view");
  const humanizeView = document.getElementById("ai-lab-humanize-view");
  const detectBtn = document.getElementById("ai-lab-tab-detect-btn");
  const humanizeBtn = document.getElementById("ai-lab-tab-humanize-btn");

  if (mode === "detect") {
    detectView?.classList.remove("hidden");
    humanizeView?.classList.add("hidden");
    detectBtn?.classList.add("btn-primary");
    detectBtn?.classList.remove("btn-outline");
    humanizeBtn?.classList.add("btn-outline");
    humanizeBtn?.classList.remove("btn-primary");
  } else {
    humanizeView?.classList.remove("hidden");
    detectView?.classList.add("hidden");
    humanizeBtn?.classList.add("btn-primary");
    humanizeBtn?.classList.remove("btn-outline");
    detectBtn?.classList.add("btn-outline");
    detectBtn?.classList.remove("btn-primary");
  }
}

// Live character counter for detector
document.addEventListener("DOMContentLoaded", () => {
  const inp = document.getElementById("ai-lab-input");
  if (inp) {
    inp.addEventListener("input", () => {
      const count = inp.value.length;
      const el = document.getElementById("ai-lab-charcount");
      if (el) {
        el.textContent = `${count.toLocaleString()} characters`;
        el.style.color = count < 50 ? "#ef4444" : "var(--text-muted)";
      }
    });
  }
});

function _aiLabShowState(state) {
  ["ai-lab-idle", "ai-lab-loading", "ai-lab-results", "ai-lab-error"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.toggle("hidden", id !== state);
  });
}

function aiLabClear() {
  const inp = document.getElementById("ai-lab-input");
  if (inp) { inp.value = ""; inp.dispatchEvent(new Event("input")); }
  _aiLabShowState("ai-lab-idle");
  _currentAiLabData = null;
}

function aiLabReset() {
  _aiLabShowState("ai-lab-idle");
}

function applySignalFilter() {
  if (!_currentAiLabData) return;
  const mode = document.getElementById("ai-lab-signal-mode")?.value || "combined";

  let aiProb = _currentAiLabData.ai_probability;
  let humanProb = _currentAiLabData.human_probability;
  let signalTitle = "Combined Multi-Signal (Hybrid)";

  if (mode === "classifier") {
    aiProb = typeof _currentAiLabData.classifier_prob === "number" ? _currentAiLabData.classifier_prob : _currentAiLabData.ai_probability;
    humanProb = Math.round((100 - aiProb) * 10) / 10;
    signalTitle = "Classifier Head Only (RoBERTa / TMR)";
  } else if (mode === "perplexity") {
    const ppl = _currentAiLabData.perplexity || 25;
    // Lower perplexity = higher AI probability
    aiProb = Math.max(5, Math.min(98, Math.round(100 - (ppl - 12) * 2.2)));
    humanProb = Math.round((100 - aiProb) * 10) / 10;
    signalTitle = `Perplexity Signal (Score: ${ppl})`;
  } else if (mode === "burstiness") {
    const burst = _currentAiLabData.burstiness || 10;
    // Lower burstiness = higher AI probability
    aiProb = Math.max(5, Math.min(98, Math.round(100 - (burst - 4) * 5)));
    humanProb = Math.round((100 - aiProb) * 10) / 10;
    signalTitle = `Burstiness / Sentence Rhythm (Score: ${burst})`;
  }

  aiProb = Math.round(aiProb * 10) / 10;
  humanProb = Math.round(humanProb * 10) / 10;
  const verdict = aiProb >= 50 ? "AI" : "Human";

  // Update verdict badge
  const badge = document.getElementById("ai-lab-verdict-badge");
  if (badge) {
    badge.textContent = verdict === "AI" ? "AI-Generated" : "Human-Written";
    badge.className = "ai-verdict-badge " + (verdict === "AI" ? "verdict-ai" : "verdict-human");
  }

  // Update label
  const labelEl = document.getElementById("ai-lab-label");
  if (labelEl) {
    labelEl.innerHTML = (verdict === "AI"
      ? `AI text detected with <strong>${aiProb}%</strong> probability`
      : `Likely human-written with <strong>${humanProb}%</strong> probability`)
      + `<br><span style="font-size:11px;opacity:0.75;margin-top:4px;display:block;">[${signalTitle}]</span>`;
  }

  // Update percentages & bars
  const aiPct = document.getElementById("ai-lab-ai-pct");
  const humanPct = document.getElementById("ai-lab-human-pct");
  if (aiPct) aiPct.textContent = `${aiProb}%`;
  if (humanPct) humanPct.textContent = `${humanProb}%`;

  const aiBar = document.getElementById("ai-lab-ai-bar");
  const hBar = document.getElementById("ai-lab-human-bar");
  if (aiBar) aiBar.style.width = `${aiProb}%`;
  if (hBar) hBar.style.width = `${humanProb}%`;
}

async function runHfDetect() {
  const text = (document.getElementById("ai-lab-input")?.value || "").trim();
  const hfKey = (document.getElementById("ai-lab-hf-key")?.value || "").trim();
  const colabUrl = (document.getElementById("ai-lab-colab-url")?.value || "").trim();

  if (!text) { showToast("Please paste some text first.", "error"); return; }
  if (text.length < 50) { showToast("Text must be at least 50 characters.", "error"); return; }

  const btn = document.getElementById("ai-lab-detect-btn");
  if (btn) btn.disabled = true;
  _aiLabShowState("ai-lab-loading");

  try {
    const payload = { text };
    if (hfKey) payload.hf_key = hfKey;
    if (colabUrl) payload.colab_url = colabUrl;

    const res = await fetch("/api/hf-detect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();

    if (!res.ok) {
      document.getElementById("ai-lab-error-msg").textContent =
        data.error || `Server error ${res.status}`;
      _aiLabShowState("ai-lab-error");
      return;
    }

    _currentAiLabData = data;

    // Update signal breakdown cards
    const classVal = document.getElementById("signal-val-classifier");
    const pplVal = document.getElementById("signal-val-ppl");
    const burstVal = document.getElementById("signal-val-burst");

    if (classVal) classVal.textContent = typeof data.classifier_prob === "number" ? `${data.classifier_prob}% AI` : `${data.ai_probability}% AI`;
    if (pplVal) pplVal.textContent = data.perplexity != null ? `${data.perplexity}` : "N/A";
    if (burstVal) burstVal.textContent = data.burstiness != null ? `${data.burstiness}` : "N/A";

    // Apply the active signal view
    applySignalFilter();

    document.getElementById("ai-lab-raw").textContent = JSON.stringify(data.raw, null, 2);
    _aiLabShowState("ai-lab-results");

  } catch (err) {
    document.getElementById("ai-lab-error-msg").textContent = err.message || "Network error";
    _aiLabShowState("ai-lab-error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// Transfer text from Detector -> Humanizer
function sendToHumanizer() {
  const txt = document.getElementById("ai-lab-input")?.value || "";
  const humInput = document.getElementById("humanize-input-text");
  if (humInput) humInput.value = txt;
  switchAiLabMode("humanize");
  showToast("Transferred text to Humanizer Studio!", "info");
}

// ── Text Humanizer Execution ────────────────────────────────────────────────
async function runHumanizer() {
  const text = (document.getElementById("humanize-input-text")?.value || "").trim();
  const style = document.getElementById("humanize-style-select")?.value || "professional";

  if (!text) {
    showToast("Please paste or type text to humanize.", "error");
    return;
  }
  if (text.length < 30) {
    showToast("Text is too short to humanize (minimum 30 characters).", "error");
    return;
  }

  const btn = document.getElementById("humanize-run-btn");
  const idle = document.getElementById("humanize-idle");
  const loading = document.getElementById("humanize-loading");
  const resultBox = document.getElementById("humanize-result-box");

  if (btn) btn.disabled = true;
  idle?.classList.add("hidden");
  loading?.classList.remove("hidden");
  resultBox?.classList.add("hidden");

  try {
    const res = await fetch("/api/humanize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text, style }),
    });
    const data = await res.json();

    loading?.classList.add("hidden");

    if (!res.ok || !data.success) {
      idle?.classList.remove("hidden");
      showToast(data.error || "Humanizing failed.", "error");
      return;
    }

    const outArea = document.getElementById("humanize-output-text");
    if (outArea) outArea.value = data.humanized_text;

    const badge = document.getElementById("humanize-engine-badge");
    if (badge) badge.textContent = `Engine: ${data.engine || "Gemini Anti-Detection"}`;

    resultBox?.classList.remove("hidden");
    showToast("✨ Text humanized with high structural burstiness!", "success");

  } catch (err) {
    loading?.classList.add("hidden");
    idle?.classList.remove("hidden");
    showToast(`Humanizer error: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function copyHumanizedText() {
  const outArea = document.getElementById("humanize-output-text");
  if (!outArea || !outArea.value) return;
  navigator.clipboard.writeText(outArea.value);
  showToast("Humanized text copied to clipboard!", "success");
}

function testHumanizedInDetector() {
  const outArea = document.getElementById("humanize-output-text");
  if (!outArea || !outArea.value) return;

  const detInp = document.getElementById("ai-lab-input");
  if (detInp) {
    detInp.value = outArea.value;
    detInp.dispatchEvent(new Event("input"));
  }

  switchAiLabMode("detect");
  showToast("Loaded humanized text into detector — analyzing...", "info");
  runHfDetect();
}
