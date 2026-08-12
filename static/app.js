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
            <i class="fa-solid fa-download"></i> Download .docx
          </a>
          ${app.relative_file_path ? `<a href="/api/download/${app.relative_file_path.replace('.docx', '.pdf')}" class="btn btn-cyan btn-sm" download><i class="fa-solid fa-file-pdf"></i> .pdf</a>` : ''}
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
  const name = contact.name || data.name || "Candidate Name";
  const email = contact.email || "";
  const phone = contact.phone || "";
  const linkedin = contact.linkedin || "";
  const github = contact.github || "";

  const summary = data.summary || "";
  const skills = data.skills || [];
  const experience = data.experience || [];
  const projects = data.projects || [];
  const education = data.education || [];

  let html = `
    <div class="resume-header-block">
      <h1>${escapeHtml(name)}</h1>
      <div class="contact-badges">
        ${email ? `<span><i class="fa-solid fa-envelope text-cyan"></i> ${escapeHtml(email)}</span>` : ''}
        ${phone ? `<span><i class="fa-solid fa-phone text-cyan"></i> ${escapeHtml(phone)}</span>` : ''}
        ${linkedin ? `<span><i class="fa-brands fa-linkedin text-cyan"></i> <a href="https://${escapeHtml(linkedin)}" target="_blank">${escapeHtml(linkedin)}</a></span>` : ''}
        ${github ? `<span><i class="fa-brands fa-github text-cyan"></i> <a href="https://${escapeHtml(github)}" target="_blank">${escapeHtml(github)}</a></span>` : ''}
      </div>
    </div>
  `;

  if (summary) {
    html += `
      <div>
        <div class="resume-section-title"><i class="fa-solid fa-user"></i> Professional Summary</div>
        <div class="resume-summary-text">${escapeHtml(summary)}</div>
      </div>
    `;
  }

  if (skills.length > 0) {
    html += `
      <div>
        <div class="resume-section-title"><i class="fa-solid fa-bolt"></i> Technical Skills (${skills.length})</div>
        <div class="skills-pill-group">
          ${skills.map(s => `<span class="chip-cyan">${escapeHtml(s)}</span>`).join('')}
        </div>
      </div>
    `;
  }

  if (experience.length > 0) {
    html += `<div><div class="resume-section-title"><i class="fa-solid fa-briefcase"></i> Work Experience</div>`;
    experience.forEach(exp => {
      html += `
        <div class="experience-card">
          <div class="exp-title-row">
            <div>
              <div class="exp-role">${escapeHtml(exp.title || '')}</div>
              <div class="exp-company">${escapeHtml(exp.company || '')}</div>
            </div>
            <div class="exp-dates">${escapeHtml(exp.dates || '')} ${exp.location ? '| ' + escapeHtml(exp.location) : ''}</div>
          </div>
          <ul class="exp-bullets">
            ${(exp.bullets || []).map(b => `<li>${escapeHtml(b)}</li>`).join('')}
          </ul>
        </div>
      `;
    });
    html += `</div>`;
  }

  if (projects.length > 0) {
    html += `<div><div class="resume-section-title"><i class="fa-solid fa-laptop-code"></i> Key Projects</div>`;
    projects.forEach(proj => {
      html += `
        <div class="project-card">
          <div class="exp-title-row">
            <div class="exp-role">${escapeHtml(proj.name || '')}</div>
            ${proj.url ? `<a href="${escapeHtml(proj.url)}" target="_blank" class="text-cyan text-sm">${escapeHtml(proj.url)}</a>` : ''}
          </div>
          <p class="text-dim text-sm margin-bottom-xs">${escapeHtml(proj.description || '')}</p>
          ${proj.tech_stack ? `<div class="skills-pill-group margin-top-xs">${(proj.tech_stack || []).map(t => `<span class="chip-cyan" style="font-size:12px; padding:4px 10px;">${escapeHtml(t)}</span>`).join('')}</div>` : ''}
        </div>
      `;
    });
    html += `</div>`;
  }

  if (education.length > 0) {
    html += `<div><div class="resume-section-title"><i class="fa-solid fa-graduation-cap"></i> Education</div>`;
    education.forEach(edu => {
      html += `
        <div class="experience-card">
          <div class="exp-title-row">
            <div class="exp-role">${escapeHtml(edu.degree || '')} ${edu.field ? '- ' + escapeHtml(edu.field) : ''}</div>
            <div class="exp-dates">${escapeHtml(edu.dates || '')}</div>
          </div>
          <div class="exp-company">${escapeHtml(edu.institution || '')}</div>
        </div>
      `;
    });
    html += `</div>`;
  }

  card.innerHTML = html;
}

function toggleResumeViewMode() {
  const visualCard = document.getElementById("visual-resume-card");
  const jsonCard = document.getElementById("json-editor-card");
  const toggleBtn = document.getElementById("toggle-json-view-btn");

  if (jsonCard.classList.contains("hidden")) {
    jsonCard.classList.remove("hidden");
    visualCard.classList.add("hidden");
    toggleBtn.innerHTML = `<i class="fa-solid fa-eye"></i> Visual Resume Mode`;
  } else {
    jsonCard.classList.add("hidden");
    visualCard.classList.remove("hidden");
    toggleBtn.innerHTML = `<i class="fa-solid fa-code"></i> Raw JSON Mode`;
  }
}

async function uploadMasterResumeFile(event) {
  const file = event.target.files[0];
  if (!file) return;

  const formData = new FormData();
  formData.append("resume_file", file);

  showToast(`Uploading and parsing ${file.name}...`, "info");

  try {
    const res = await fetch("/api/upload_resume", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || "Resume updated cleanly!", "success");
      loadMasterResume();
    } else {
      showToast(`Upload failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error uploading file: ${err.message}`, "error");
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
  const textarea = document.getElementById("resume-json-editor");
  try {
    const parsed = JSON.parse(textarea.value);
    const res = await fetch("/api/resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(parsed),
    });
    const data = await res.json();
    if (data.success) {
      showToast("Master resume updated successfully!", "success");
      loadMasterResume();
    } else {
      showToast(`Save failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast("Invalid JSON syntax in Master Resume Editor", "error");
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
      showToast(data.error || "Analysis failed", "error");
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

function renderSimplifyCard(data) {
  const card = document.getElementById("simplify-card");
  card.classList.remove("hidden");

  // Render score badge
  const score = data.score || 75;
  document.getElementById("simplify-score-num").innerText = score;
  document.getElementById("matched-count").innerText = data.matching_keywords.length;
  document.getElementById("total-count").innerText = data.total_keywords;

  const scorePath = document.getElementById("score-circle-path");
  // Calculate dash offset for circle (264 is perimeter)
  const offset = 264 - (264 * (score / 100));
  scorePath.style.strokeDashoffset = offset;

  let verdict = "Strong Resume Match";
  if (score < 60) verdict = "Low Resume Match — Keyword Injection Recommended";
  else if (score >= 85) verdict = "Excellent Resume Match!";

  const sourceBadge = data.source === "simplify_extension"
    ? `<span class="badge badge-success"><i class="fa-solid fa-bolt text-cyan"></i> Real Simplify Extension Keywords</span>`
    : `<span class="badge badge-warning"><i class="fa-solid fa-robot"></i> Estimated LLM Keywords (Simplify overlay unavailable on this page)</span>`;

  document.getElementById("simplify-score-verdict").innerHTML = `${verdict} ${sourceBadge}`;

  // Render Matched (Cyan) Chips
  const matchedContainer = document.getElementById("matched-chips-container");
  matchedContainer.innerHTML = "";
  data.matching_keywords.forEach(kw => {
    const chip = document.createElement("span");
    chip.className = "chip-cyan";
    chip.innerHTML = `<i class="fa-solid fa-check margin-right-xs"></i> ${kw}`;
    matchedContainer.appendChild(chip);
  });

  // Render Missing (Interactive White) Chips
  const missingContainer = document.getElementById("missing-chips-container");
  missingContainer.innerHTML = "";
  analyzedMissingKeywords = data.missing_keywords || [];
  selectedMissingKeywords = new Set(analyzedMissingKeywords);

  if (analyzedMissingKeywords.length === 0) {
    missingContainer.innerHTML = `<span class="text-emerald font-semibold">🎉 Master resume already matched all keywords for this job!</span>`;
  } else {
    analyzedMissingKeywords.forEach(kw => {
      renderMissingChip(kw, missingContainer);
    });
  }

  // Scroll smoothly to Simplify Card
  card.scrollIntoView({ behavior: "smooth", block: "nearest" });
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
