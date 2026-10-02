/* ==========================================================================
   AI Job Application Agent — Single Page App Logic
   ========================================================================== */

let currentRunId = null;
let eventSource = null;
let startTime = null;
let timerInterval = null;
let analyzeCompany = "";
let analyzeRole = "";
let analyzeScoreBefore = null;
let analyzeJdText = "";
let analyzedMissingKeywordContexts = {};

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initHashSync();
  initScrollNavigation();
  initKeyboardNav();
  checkSystemHealth();
  loadSettings();
  loadHistory();
  loadMasterResume();
  initFormListeners();
  checkSimplifyStatus();
});

/* ── Tab Navigation & Synced Routing ────────────────────────────────────── */
function initTabs() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tab;
      switchTab(target);
    });
  });
}

function switchTab(tabId, updateHash = true) {
  if (!tabId) return;

  document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));

  const targetTab = document.querySelector(`.nav-tab[data-tab="${tabId}"]`);
  const targetContent = document.getElementById(`tab-${tabId}`);

  if (targetTab) targetTab.classList.add("active");
  if (targetContent) targetContent.classList.add("active");

  // Always close Quick Navigator on tab switch & reset accumulator
  if (typeof closeScrollCompass === "function") {
    closeScrollCompass();
  }
  if (typeof _scrollCompassState !== "undefined") {
    _scrollCompassState.accumulatedDistance = 0;
    _scrollCompassState.directionChanges = 0;
    _scrollCompassState.recentScrolls = [];
  }

  // Smoothly scroll to top so user lands cleanly on the new tab view
  window.scrollTo({ top: 0, behavior: "smooth" });

  // Synchronize URL Hash without page jump
  if (updateHash) {
    try {
      history.replaceState(null, null, `#${tabId}`);
    } catch (e) {}
  }

  const floatBar = document.getElementById("history-floating-action-bar");
  if (floatBar) {
    if (tabId === "history" && typeof selectedHistoryFiles !== "undefined" && selectedHistoryFiles.size > 0) {
      floatBar.style.display = "block";
      requestAnimationFrame(() => floatBar.classList.remove("hidden"));
    } else {
      floatBar.classList.add("hidden");
      setTimeout(() => { if (floatBar.classList.contains("hidden")) floatBar.style.display = "none"; }, 200);
    }
  }

  if (tabId === "history") loadHistory();
  if (tabId === "setup") checkSystemHealth();
}

/* ── Floating Back to Top & Scroll Progress Engine ──────────────────────── */
function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function initScrollNavigation() {
  const backToTopBtn = document.getElementById("back-to-top-btn");
  const progressCircle = document.getElementById("scroll-progress-circle");
  const appHeader = document.querySelector(".app-header");
  const circumference = 106.81; // 2 * pi * 17

  function onScroll() {
    const scrollY = window.scrollY || document.documentElement.scrollTop;
    const maxScroll = document.documentElement.scrollHeight - window.innerHeight;

    // Toggle Back to Top Button
    if (backToTopBtn) {
      if (scrollY > 260) {
        backToTopBtn.classList.add("visible");
      } else {
        backToTopBtn.classList.remove("visible");
      }

      // Update circular SVG progress indicator
      if (progressCircle && maxScroll > 0) {
        const scrollPercent = Math.min(1, Math.max(0, scrollY / maxScroll));
        const offset = circumference - (scrollPercent * circumference);
        progressCircle.style.strokeDashoffset = offset.toFixed(2);
      }
    }

    // Toggle Scrolled Header Glassmorphism Effect
    if (appHeader) {
      if (scrollY > 15) {
        appHeader.classList.add("scrolled");
      } else {
        appHeader.classList.remove("scrolled");
      }
    }
  }

  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
  initScrollCompassDetector();
}

// ════════════════════════════════════════════════════════════════════════════
// SMART CURSOR SCROLL COMPASS / QUICK NAVIGATOR CONTROLLER
// ════════════════════════════════════════════════════════════════════════════

let _scrollCompassState = {
  isOpen: false,
  mutedUntil: 0,
  lastTriggerTime: 0,
  lastDismissTime: 0,
  recentScrolls: [],
  lastDirection: 0,
  directionChanges: 0,
  accumulatedDistance: 0,
  activeItems: []
};

window._lastMouseX = window.innerWidth / 2;
window._lastMouseY = window.innerHeight / 2;

window.addEventListener("mousemove", (e) => {
  window._lastMouseX = e.clientX;
  window._lastMouseY = e.clientY;
}, { passive: true });

function isFirstTabActive() {
  const firstTab = document.getElementById("tab-new-app");
  return firstTab && firstTab.classList.contains("active");
}

function isNewResumeReady() {
  // 1. STRICT RULE: ONLY on first tab!
  if (!isFirstTabActive()) return false;

  // 2. STRICT RULE: ONLY after the new resume has been created!
  // The results dashboard ("Tailored Resume Ready!") must be actively displayed in the DOM
  const resDash = document.getElementById("results-dashboard");
  if (!resDash || resDash.classList.contains("hidden") || resDash.style.display === "none") {
    return false;
  }

  // And a tailored resume must actually exist in memory (relative_path, docx, or tailored_resume)
  if (!window.lastResult || (!window.lastResult.relative_path && !window.lastResult.tailored_resume)) {
    return false;
  }

  return true;
}

function isAnyModalOpen() {
  const confirmModal = document.getElementById("system-confirm-modal");
  if (confirmModal && confirmModal.style.display === "flex") return true;

  const previewModal = document.getElementById("resume-preview-modal");
  if (previewModal && previewModal.style.display === "flex") return true;

  const liveEditModal = document.getElementById("live-edit-modal");
  if (liveEditModal && liveEditModal.style.display === "flex") return true;

  const clModal = document.getElementById("cover-letter-modal");
  if (clModal && !clModal.classList.contains("hidden")) return true;

  const pwModal = document.getElementById("change-password-modal");
  if (pwModal && pwModal.style.display === "flex") return true;

  const historyModal = document.getElementById("history-refine-modal");
  if (historyModal && historyModal.style.display === "flex") return true;

  return false;
}

// ════════════════════════════════════════════════════════════════════════════
// BESPOKE SYSTEM CONFIRMATION & DIALOG CONTROLLER (REPLACES NATIVE ALERTS)
// ════════════════════════════════════════════════════════════════════════════
let _systemConfirmResolver = null;

function showSystemConfirm(options = {}) {
  return new Promise((resolve) => {
    const modal = document.getElementById("system-confirm-modal");
    const card = document.getElementById("system-dialog-card");
    const titleEl = document.getElementById("system-dialog-title");
    const msgEl = document.getElementById("system-dialog-message");
    const noteEl = document.getElementById("system-dialog-note");
    const noteText = document.getElementById("system-dialog-note-text");
    const iconWrap = document.getElementById("system-dialog-icon-wrap");
    const iconEl = document.getElementById("system-dialog-icon");
    const confirmBtn = document.getElementById("system-dialog-confirm-btn");
    const confirmIcon = document.getElementById("system-dialog-confirm-icon");
    const confirmText = document.getElementById("system-dialog-confirm-text");
    const cancelBtn = document.getElementById("system-dialog-cancel-btn");
    const badgeEl = document.getElementById("system-dialog-badge");

    if (!modal) {
      resolve(window.confirm(options.message || options.title || "Are you sure?"));
      return;
    }

    _systemConfirmResolver = resolve;

    const title = options.title || "Confirm Action";
    const message = options.message || "Are you sure you want to proceed?";
    const note = options.note || "";
    const type = options.type || "danger";
    const confirmLabel = options.confirmText || (type === "danger" ? "Delete" : "Confirm");
    const cancelLabel = options.cancelText || "Cancel";
    const isAlertOnly = !!options.isAlert;

    if (titleEl) titleEl.textContent = title;
    if (msgEl) {
      msgEl.innerHTML = typeof message === "string" ? escapeHtml(message).replace(/\n/g, "<br>") : message;
    }

    if (note && noteEl && noteText) {
      noteText.textContent = note;
      noteEl.style.display = "flex";
    } else if (noteEl) {
      noteEl.style.display = "none";
    }

    if (card) card.className = `system-dialog-card glass-card type-${type}`;
    if (iconWrap) iconWrap.className = `system-dialog-icon-wrap type-${type}`;

    if (type === "danger") {
      if (iconEl) iconEl.className = options.icon || "fa-solid fa-trash-can";
      if (confirmBtn) confirmBtn.className = "btn btn-md system-dialog-confirm btn-danger-action";
      if (confirmIcon) confirmIcon.className = "fa-solid fa-trash-can";
      if (badgeEl) {
        badgeEl.textContent = options.badgeText || "Permanent";
        badgeEl.className = "system-dialog-badge badge-danger";
        badgeEl.style.display = "inline-block";
      }
    } else if (type === "warning") {
      if (iconEl) iconEl.className = options.icon || "fa-solid fa-triangle-exclamation";
      if (confirmBtn) confirmBtn.className = "btn btn-md system-dialog-confirm btn-warning-action";
      if (confirmIcon) confirmIcon.className = "fa-solid fa-triangle-exclamation";
      if (badgeEl) {
        badgeEl.textContent = options.badgeText || "Warning";
        badgeEl.className = "system-dialog-badge badge-warning";
        badgeEl.style.display = "inline-block";
      }
    } else {
      if (iconEl) iconEl.className = options.icon || "fa-solid fa-circle-info";
      if (confirmBtn) confirmBtn.className = "btn btn-md system-dialog-confirm btn-primary-action";
      if (confirmIcon) confirmIcon.className = "fa-solid fa-check";
      if (badgeEl) badgeEl.style.display = "none";
    }

    if (confirmText) confirmText.textContent = confirmLabel;
    if (cancelBtn) {
      cancelBtn.textContent = cancelLabel;
      cancelBtn.style.display = isAlertOnly ? "none" : "inline-flex";
    }

    modal.style.display = "flex";
    modal.classList.remove("hidden");

    setTimeout(() => {
      if (type === "danger" && cancelBtn && !isAlertOnly) {
        cancelBtn.focus();
      } else if (confirmBtn) {
        confirmBtn.focus();
      }
    }, 60);
  });
}

function showSystemAlert(options = {}) {
  return showSystemConfirm({
    ...options,
    isAlert: true,
    confirmText: options.okText || "OK"
  });
}

function closeSystemConfirm(result = false) {
  const modal = document.getElementById("system-confirm-modal");
  if (modal) {
    modal.classList.add("hidden");
    setTimeout(() => {
      modal.style.display = "none";
    }, 160);
  }
  if (_systemConfirmResolver) {
    const res = _systemConfirmResolver;
    _systemConfirmResolver = null;
    res(result);
  }
}

let _scrollTroubleState = {
  lastScrollY: typeof window !== "undefined" ? (window.scrollY || 0) : 0,
  lastScrollTime: Date.now(),
  directionChanges: 0,
  accumulatedDistance: 0,
  lastLegDir: 0,
  lastLegDistance: 0
};

function resetScrollTrouble() {
  _scrollTroubleState.directionChanges = 0;
  _scrollTroubleState.accumulatedDistance = 0;
  _scrollTroubleState.lastLegDir = 0;
  _scrollTroubleState.lastLegDistance = 0;
}

function initScrollCompassDetector() {
  // If user scrolls or uses wheel while already at page end, reset immediately
  window.addEventListener("wheel", (e) => {
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const totalHeight = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
    const maxScroll = Math.max(0, totalHeight - viewportHeight);
    const distanceFromBottom = maxScroll - scrollY;

    // Scrolling down while already near or at page end -> NO SENSE to show menu, reset immediately
    if (distanceFromBottom <= 120 && e.deltaY > 0) {
      resetScrollTrouble();
      return;
    }
    // Scrolling up while already near or at top -> reset immediately
    if (scrollY <= 120 && e.deltaY < 0) {
      resetScrollTrouble();
      return;
    }
  }, { passive: true });

  // Track actual scroll movements to identify when user is having trouble navigating to a point
  window.addEventListener("scroll", () => {
    // 1. STRICT RULE: ONLY on first tab!
    if (!isFirstTabActive()) {
      resetScrollTrouble();
      return;
    }

    // 2. STRICT RULE: ONLY after the new resume has been created!
    if (!isNewResumeReady()) {
      resetScrollTrouble();
      return;
    }

    // 3. Do not trigger if already open, muted, or in cooldown
    if (_scrollCompassState.isOpen) return;

    const now = Date.now();
    if (now < _scrollCompassState.mutedUntil) return;
    if (now - _scrollCompassState.lastTriggerTime < 30000) return; // 30s cooldown after trigger
    if (now - _scrollCompassState.lastDismissTime < 45000) return; // 45s cooldown after user dismiss

    // 4. Do not trigger if typing or inside modal
    if (isAnyModalOpen()) return;
    const activeEl = document.activeElement;
    if (activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.isContentEditable)) {
      return;
    }

    // 5. Boundary guards: Check distance from page end and page top
    const scrollY = window.scrollY || document.documentElement.scrollTop || 0;
    const viewportHeight = window.innerHeight || document.documentElement.clientHeight || 0;
    const totalHeight = document.documentElement.scrollHeight || document.body.scrollHeight || 0;
    const maxScroll = Math.max(0, totalHeight - viewportHeight);
    const distanceFromBottom = maxScroll - scrollY;

    // Ensure page is actually long enough (> 800px scrollable area)
    if (maxScroll < 800) {
      resetScrollTrouble();
      return;
    }

    // CRITICAL: If user is at or near page end (within 120px), scrolling down has no sense to show menu
    if (distanceFromBottom <= 120) {
      resetScrollTrouble();
      _scrollTroubleState.lastScrollY = scrollY;
      _scrollTroubleState.lastScrollTime = now;
      return;
    }

    // CRITICAL: If user is at or near page top (within 120px), reset
    if (scrollY <= 120) {
      resetScrollTrouble();
      _scrollTroubleState.lastScrollY = scrollY;
      _scrollTroubleState.lastScrollTime = now;
      return;
    }

    // Calculate actual pixel movement since last scroll event
    const deltaY = scrollY - _scrollTroubleState.lastScrollY;
    const timeDelta = now - _scrollTroubleState.lastScrollTime;
    _scrollTroubleState.lastScrollY = scrollY;
    _scrollTroubleState.lastScrollTime = now;

    // If user stopped scrolling for > 1.2s, reset leg tracking (actions were not part of a continuous search)
    if (timeDelta > 1200) {
      resetScrollTrouble();
    }

    if (Math.abs(deltaY) < 10) return;

    const currentDir = Math.sign(deltaY); // 1 = down, -1 = up

    if (_scrollTroubleState.lastLegDir === 0) {
      _scrollTroubleState.lastLegDir = currentDir;
      _scrollTroubleState.lastLegDistance = Math.abs(deltaY);
    } else if (_scrollTroubleState.lastLegDir === currentDir) {
      _scrollTroubleState.lastLegDistance += Math.abs(deltaY);
    } else {
      // User reversed direction! (e.g. was scrolling down looking for something, then reversed up)
      // Only count as a reversal if the previous leg was a real scroll (>= 120px)
      if (_scrollTroubleState.lastLegDistance >= 120) {
        _scrollTroubleState.directionChanges++;
      }
      _scrollTroubleState.lastLegDir = currentDir;
      _scrollTroubleState.lastLegDistance = Math.abs(deltaY);
    }

    _scrollTroubleState.accumulatedDistance += Math.abs(deltaY);

    // Having trouble navigating condition:
    // User is oscillating back and forth across content (>= 2 direction reversals within content,
    // e.g. down -> up -> down or up -> down -> up, with >= 700px of actual travel and current leg >= 120px).
    // Must be in the body of the page (> 150px away from top and bottom boundaries).
    const isHuntingForSection = _scrollTroubleState.directionChanges >= 2 &&
                                _scrollTroubleState.accumulatedDistance >= 700 &&
                                _scrollTroubleState.lastLegDistance >= 120 &&
                                distanceFromBottom > 150 &&
                                scrollY > 150;

    if (isHuntingForSection) {
      resetScrollTrouble();
      _scrollCompassState.lastTriggerTime = now;
      openScrollCompass(window._lastMouseX, window._lastMouseY);
    }
  }, { passive: true });
}

function getAvailableCompassItems() {
  const items = [];

  // 1. Job Input & URL
  items.push({
    id: "job-inputs",
    icon: "fa-bullseye",
    color: "#38bdf8",
    label: "Job Input & URL",
    hint: "Target role & JD",
    action: () => {
      const urlInp = document.getElementById("url-input");
      const jdCard = document.getElementById("jd-input-container") || document.querySelector(".job-input-card") || urlInp;
      highlightAndScroll(jdCard, urlInp);
    }
  });

  // 2. ATS Match Score (only if results dashboard is visible)
  const resDash = document.getElementById("results-dashboard");
  if (resDash && !resDash.classList.contains("hidden") && resDash.style.display !== "none") {
    items.push({
      id: "results",
      icon: "fa-chart-pie",
      color: "#f43f5e",
      label: "ATS Match Score",
      hint: "Score & diagnostics",
      action: () => {
        highlightAndScroll(resDash);
      }
    });
  }

  // 3. Refine Copilot (only if refine card exists and is visible)
  const refCard = document.getElementById("refine-copilot-card");
  if (refCard && !refCard.classList.contains("hidden") && refCard.style.display !== "none") {
    items.push({
      id: "refine",
      icon: "fa-wand-magic-sparkles",
      color: "#f59e0b",
      label: "Refine Copilot",
      hint: "Targeted section chips",
      action: () => {
        const refInp = document.getElementById("refine-instruction-input");
        highlightAndScroll(refCard, refInp);
      }
    });
  }

  // 4. Resume Preview & Live Editor (only if tailored resume exists)
  if (window.lastResult && window.lastResult.relative_path) {
    items.push({
      id: "preview",
      icon: "fa-file-pdf",
      color: "#a855f7",
      label: "Resume Preview",
      hint: "In-browser live editor",
      action: () => {
        previewCurrentResume();
      }
    });

    // 5. Cover Letter (only if application exists)
    items.push({
      id: "cover-letter",
      icon: "fa-envelope-open-text",
      color: "#10b981",
      label: "Cover Letter",
      hint: "Generate & download",
      action: () => {
        if (typeof openCurrentCoverLetter === "function") {
          openCurrentCoverLetter();
        } else if (typeof openCoverLetterModal === "function") {
          openCoverLetterModal();
        }
      }
    });
  }

  // 6. Top of Page
  items.push({
    id: "top",
    icon: "fa-arrow-up",
    color: "#0284c7",
    label: "Top of Page",
    hint: "Scroll to top",
    action: () => {
      scrollToTop();
    }
  });

  // 7. Bottom / Live Console
  items.push({
    id: "bottom",
    icon: "fa-terminal",
    color: "#6366f1",
    label: "Bottom / Console",
    hint: "Scroll to bottom",
    action: () => {
      window.scrollTo({ top: document.documentElement.scrollHeight, behavior: "smooth" });
    }
  });

  return items;
}

function openScrollCompass(x, y) {
  // STRICT RULE: Only on first tab after the new resume has been created!
  if (!isNewResumeReady()) return;

  const compass = document.getElementById("quick-scroll-compass");
  const card = document.getElementById("compass-card");
  const grid = document.getElementById("compass-grid");
  if (!compass || !card || !grid) return;

  const items = getAvailableCompassItems();
  _scrollCompassState.activeItems = items;

  // Build grid HTML dynamically based on what actually exists
  grid.innerHTML = items.map((item, index) => `
    <button type="button" class="compass-item" onclick="triggerCompassItemIndex(${index})">
      <div class="compass-item-icon" style="color: ${item.color};"><i class="fa-solid ${item.icon}"></i></div>
      <div class="compass-item-text">
        <span class="compass-item-label">${item.label}</span>
        <span class="compass-item-hint">${item.hint}</span>
      </div>
      <span class="compass-item-key">${index + 1}</span>
    </button>
  `).join("");

  const hintEl = document.getElementById("compass-footer-hint");
  if (hintEl) {
    hintEl.innerHTML = `<i class="fa-solid fa-keyboard"></i> Press <strong>1–${items.length}</strong> • <strong>Esc</strong> to close`;
  }

  const mouseX = (typeof x === "number" && x > 0) ? x : window._lastMouseX || window.innerWidth / 2;
  const mouseY = (typeof y === "number" && y > 0) ? y : window._lastMouseY || window.innerHeight / 2;

  const cardW = 390;
  const cardH = 340;
  const pad = 16;

  let left = mouseX + 12;
  let top = mouseY + 12;

  // Clamp within viewport
  if (left + cardW > window.innerWidth - pad) {
    left = mouseX - cardW - 12;
  }
  if (left < pad) left = pad;

  if (top + cardH > window.innerHeight - pad) {
    top = mouseY - cardH - 12;
  }
  if (top < pad) top = pad;

  card.style.left = left + "px";
  card.style.top = top + "px";

  compass.style.display = "block";
  compass.classList.remove("hidden");
  _scrollCompassState.isOpen = true;
}

function closeScrollCompass(userDismissed = false) {
  const compass = document.getElementById("quick-scroll-compass");
  if (!compass) return;
  compass.classList.add("hidden");
  setTimeout(() => {
    compass.style.display = "none";
  }, 180);
  _scrollCompassState.isOpen = false;
  if (typeof resetScrollTrouble === "function") resetScrollTrouble();
  if (userDismissed) {
    _scrollCompassState.lastDismissTime = Date.now();
  }
}

function muteScrollCompass(seconds = 300) {
  _scrollCompassState.mutedUntil = Date.now() + (seconds * 1000);
  closeScrollCompass(true);
  showToast(`Quick Navigator muted for ${Math.round(seconds / 60)} minutes`, "info");
}

function triggerCompassItemIndex(index) {
  const item = _scrollCompassState.activeItems[index];
  if (!item) return;
  closeScrollCompass(false);
  _scrollCompassState.lastTriggerTime = Date.now();
  if (typeof item.action === "function") {
    item.action();
  }
}

function highlightAndScroll(el, focusEl) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("section-highlight-pulse");
  setTimeout(() => el.classList.remove("section-highlight-pulse"), 1800);
  if (focusEl && typeof focusEl.focus === "function") {
    setTimeout(() => focusEl.focus(), 350);
  }
}

function initHashSync() {
  const validTabs = ["new-app", "history", "setup", "resume", "ai-lab"];
  const initialHash = (window.location.hash || "").replace("#", "").trim();
  if (validTabs.includes(initialHash)) {
    switchTab(initialHash, false);
  }

  window.addEventListener("popstate", () => {
    const hash = (window.location.hash || "").replace("#", "").trim();
    if (validTabs.includes(hash)) {
      switchTab(hash, false);
    } else if (!hash) {
      switchTab("new-app", false);
    }
  });
}

function initKeyboardNav() {
  document.addEventListener("keydown", (e) => {
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : "";
    if (activeTag === "input" || activeTag === "textarea" || (document.activeElement && document.activeElement.isContentEditable)) {
      return;
    }

    // Home key -> Back to Top
    if (e.key === "Home") {
      e.preventDefault();
      scrollToTop();
      return;
    }

    // Alt + 1..5 for instant tab switching
    if (e.altKey && !e.ctrlKey && !e.metaKey) {
      const tabMap = {
        "1": "new-app",
        "2": "history",
        "3": "setup",
        "4": "resume",
        "5": "ai-lab"
      };
      if (tabMap[e.key]) {
        e.preventDefault();
        switchTab(tabMap[e.key]);
      }
    }
  });
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
  const directJdText = opts.directJdText || "";

  const isDirectText = url.includes("\n") || (url.includes(" ") && url.split(" ").length > 3);
  if (url && !isDirectText && !url.startsWith("http://") && !url.startsWith("https://") && !directJdText) {
    url = "https://" + url;
    document.getElementById("jd-url").value = url;
  }

  const customKwElem = document.getElementById("custom-keywords-input");
  const customKeywordsRaw = customKwElem ? customKwElem.value.trim() : "";

  const customBulletsElem = document.getElementById("matrix-custom-bullets-input") || document.getElementById("custom-bullets-input");
  const customBulletsRaw = (opts.customBullets !== undefined) ? opts.customBullets : (customBulletsElem ? customBulletsElem.value.trim() : "");

  const noSimplifyElem = document.getElementById("no-simplify-toggle");
  const noSimplify = noSimplifyElem ? noSimplifyElem.checked : false;

  const passesElem = document.getElementById("ai-passes-select");
  const passes = passesElem ? passesElem.value : "2";

  const outputDirElem = document.getElementById("custom-output-dir");
  const outputDir = outputDirElem ? outputDirElem.value.trim() : "";

  // Use score passed from Analyze step if available, otherwise null (backend will compute)
  const scoreBefore = opts.scoreBefore !== undefined ? opts.scoreBefore : analyzeScoreBefore;

  if (!url && !directJdText) {
    showToast("Please enter a valid job posting URL or paste the job description", "warning");
    return;
  }

  // UI Setup for running state
  const execContainer = document.getElementById("execution-container");
  execContainer.classList.remove("hidden");
  execContainer.scrollIntoView({ behavior: "smooth" });
  const startBtn = document.getElementById("start-btn");
  if (startBtn) startBtn.disabled = true;
  document.getElementById("exec-status-badge").innerHTML = `<i class="fa-solid fa-spinner fa-spin text-cyan"></i> Running Pipeline...`;

  resetPipelineVisuals();
  startTimer();
  clearTerminal();

  logTerminal("info", `[System] Initiating job application run for: ${url || "Direct Job Description"}`);

  const engineModeElem = document.getElementById("engine-mode-select");
  const engineMode = engineModeElem ? engineModeElem.value : "danis_engine";

  const customCompany = (opts.customCompany || analyzeCompany || document.getElementById("matrix-company-name")?.value || "").trim();
  const customRole = (opts.customRole || analyzeRole || document.getElementById("matrix-role-name")?.value || "").trim();

  try {
    const response = await fetch("/api/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url || "Manual Job Description",
        jd_text: directJdText || undefined,
        custom_company: customCompany || undefined,
        custom_role: customRole || undefined,
        custom_keywords: customKeywordsRaw || undefined,
        custom_bullets: customBulletsRaw || undefined,
        engine_mode: engineMode,
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

        const isBotBlock = data.error_type === "bot_block" || 
                           (data.message && (data.message.includes("bot-block") || data.message.includes("JD validation failed") || data.message.includes("captcha")));
        if (isBotBlock) {
          openManualJdModal(data.company, data.role, "pipeline");
        }
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

function getStepScanAnimationSvg() {
  return `
    <div class="step-card-scan-wrap" title="Processing...">
      <svg width="18" height="23" viewBox="0 0 88 112" fill="none">
        <path class="step-scan-outline" d="M12,8 H60 L76,24 V100 Q76,104 72,104 H16 Q12,104 12,100 V12 Q12,8 16,8 Z" />
        <path class="step-scan-outline" d="M60,8 V24 H76" />
        <rect class="step-scan-line step-scan-l1" x="24" y="38" width="40" height="5" rx="2.5" />
        <rect class="step-scan-line step-scan-l2" x="24" y="50" width="34" height="5" rx="2.5" />
        <rect class="step-scan-line step-scan-l3" x="24" y="62" width="38" height="5" rx="2.5" />
        <rect class="step-scan-line step-scan-l4" x="24" y="74" width="28" height="5" rx="2.5" />
        <rect class="step-scan-line step-scan-l5" x="24" y="86" width="36" height="5" rx="2.5" />
        <g class="step-scan-beam">
          <rect x="8" y="28" width="72" height="15" fill="url(#stepScanBeamGradient)" />
        </g>
        <defs>
          <linearGradient id="stepScanBeamGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="#2FA88F" stop-opacity="0" />
            <stop offset="50%" stop-color="#2FA88F" stop-opacity="0.8" />
            <stop offset="100%" stop-color="#2FA88F" stop-opacity="0" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  `;
}

function updateStepState(stepNum, status, message) {
  const card = document.querySelector(`.step-card[data-step="${stepNum}"]`);
  if (!card) return;

  card.className = `step-card ${status}`;

  const statusIcon = card.querySelector(".step-status");
  if (status === "working") {
    statusIcon.innerHTML = getStepScanAnimationSvg();
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
  const startBtn = document.getElementById("start-btn");
  if (startBtn) startBtn.disabled = false;
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

  window.lastResult = res;
}

function downloadCurrentResume(ext = 'docx') {
  if (!window.lastResult || !window.lastResult.relative_path) {
    showToast("Please run an application first or select a file from History to download", "warning");
    return;
  }
  let relPath = window.lastResult.relative_path;
  if (ext === 'pdf') {
    relPath = relPath.replace(/\.(docx|pdf|json)$/i, '.pdf');
  } else if (ext === 'docx') {
    relPath = relPath.replace(/\.(docx|pdf|json)$/i, '.docx');
  }
  const cleanUrl = `/api/download/${encodeURIComponent(relPath).replace(/%2F/g, '/')}?t=${Date.now()}`;
  window.location.href = cleanUrl;
}

const selectedHistoryFiles = new Set();
let allHistoryApplications = [];

async function loadHistory() {
  const grid = document.getElementById("history-grid");
  const toolbar = document.getElementById("history-toolbar");
  const selectAllCb = document.getElementById("select-all-history-cb");
  const searchContainer = document.getElementById("history-search-container");
  if (selectAllCb) selectAllCb.checked = false;
  selectedHistoryFiles.clear();
  updateHistoryToolbarUI();

  try {
    const res = await fetch("/api/history");
    const data = await res.json();
    allHistoryApplications = data.applications || [];

    const historyCountBadge = document.getElementById("history-count");
    if (historyCountBadge) historyCountBadge.textContent = allHistoryApplications.length;

    if (allHistoryApplications.length === 0) {
      grid.innerHTML = `
        <div class="empty-state glass-card">
          <i class="fa-solid fa-folder-open empty-icon"></i>
          <h3>No applications generated yet</h3>
          <p>Run your first application from the New Application tab!</p>
        </div>`;
      if (toolbar) toolbar.classList.add("hidden");
      if (searchContainer) searchContainer.style.display = "none";
      return;
    }

    if (toolbar) toolbar.classList.remove("hidden");
    if (searchContainer) searchContainer.style.display = "flex";

    const searchInput = document.getElementById("history-search-input");
    const currentQuery = searchInput ? searchInput.value.trim() : "";
    renderHistoryCards(filterApplicationsList(allHistoryApplications, currentQuery), currentQuery);

  } catch (err) {
    grid.innerHTML = `<div class="empty-state">Failed to load history: ${err.message}</div>`;
  }
}

function filterApplicationsList(apps, query) {
  if (!query) return apps;
  const q = query.toLowerCase();
  return apps.filter(app => {
    const company = (app.company || "").toLowerCase();
    const role = (app.role || "").toLowerCase();
    const dateStr = new Date(app.timestamp).toLocaleString().toLowerCase();
    const engine = (app.engine_mode || "").toLowerCase();
    const keywords = (app.matching_keywords || []).concat(app.missing_keywords || []).join(" ").toLowerCase();
    const score = `${app.match_score_after || 0}%`;
    return company.includes(q) || role.includes(q) || dateStr.includes(q) || engine.includes(q) || keywords.includes(q) || score.includes(q);
  });
}

function filterHistoryCards(query) {
  const filtered = filterApplicationsList(allHistoryApplications, query);
  renderHistoryCards(filtered, query);
}

function clearHistorySearch() {
  const input = document.getElementById("history-search-input");
  if (input) input.value = "";
  const clearBtn = document.getElementById("history-search-clear-btn");
  if (clearBtn) clearBtn.style.display = "none";
  renderHistoryCards(allHistoryApplications, "");
}

function renderHistoryCards(apps, query = "") {
  const grid = document.getElementById("history-grid");
  const countLabel = document.getElementById("history-search-count");
  const clearBtn = document.getElementById("history-search-clear-btn");

  if (clearBtn) {
    clearBtn.style.display = query ? "block" : "none";
  }

  if (countLabel) {
    countLabel.textContent = query ? `${apps.length} of ${allHistoryApplications.length} found` : `${apps.length} applications`;
  }

  if (apps.length === 0) {
    grid.innerHTML = `
      <div class="empty-state glass-card" style="grid-column: 1 / -1; padding: 40px 20px; text-align: center;">
        <i class="fa-solid fa-filter-circle-xmark empty-icon" style="font-size:36px; color:#94a3b8; margin-bottom:12px;"></i>
        <h3 style="font-size:16px; color:#334155; margin-bottom:6px;">No applications match "${escapeHtml(query)}"</h3>
        <p style="font-size:13px; color:#64748b; margin-bottom:16px;">Try searching for a different company name, role title, keyword, or score.</p>
        <button type="button" class="btn btn-secondary btn-sm" onclick="clearHistorySearch()">Clear Search Filter</button>
      </div>`;
    return;
  }

  grid.innerHTML = "";
  apps.forEach(app => {
    const dateStr = new Date(app.timestamp).toLocaleString();
    const beforeScore = app.score_before != null ? app.score_before : (app.match_score_before != null ? app.match_score_before : (app.simplify_score_before != null ? app.simplify_score_before : 0));
    const afterScore = app.score_after != null ? app.score_after : (app.match_score_after != null ? app.match_score_after : 0);
    const deltaScore = app.score_delta != null ? app.score_delta : (app.match_score_delta != null ? app.match_score_delta : Math.max(0, afterScore - beforeScore));
    const jobUrl = app.url || "";
    const historyDocxRel = (app.relative_file_path || '').replace(/\.(docx|pdf|json)$/i, '.docx');
    const historyPdfRel = (app.relative_file_path || '').replace(/\.(docx|pdf|json)$/i, '.pdf');

    const card = document.createElement("div");
    card.className = "history-card";
    card.id = `history-card-${escapeHtml(app.log_file_name.replace(/[^a-zA-Z0-9_-]/g, '_'))}`;
    card.innerHTML = `
      <div class="history-card-header">
        <div class="flex-align-center gap-sm" style="flex:1; min-width:0;">
          <input type="checkbox" class="history-item-cb" data-filename="${escapeHtml(app.log_file_name)}" ${selectedHistoryFiles.has(app.log_file_name) ? "checked" : ""} onchange="toggleHistoryItemSelection('${escapeHtml(app.log_file_name)}', this.checked)">
          <div style="flex:1; min-width:0;">
            <div class="flex-align-center gap-xs">
              <span class="history-company" id="hist-co-${escapeHtml(app.log_file_name)}">${escapeHtml(app.company)}</span>
              <button class="btn-icon-subtle" title="Edit Company, Role & Link" onclick="openEditHistoryModal('${escapeHtml(app.log_file_name)}', '${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '${escapeHtml(jobUrl)}')">
                <i class="fa-solid fa-pen"></i>
              </button>
            </div>
            <div class="history-role" id="hist-role-${escapeHtml(app.log_file_name)}">${escapeHtml(app.role)}</div>
          </div>
        </div>
        <div class="history-meta-right">
          <div class="history-date">${dateStr}</div>
          ${jobUrl ? `
            <a href="${escapeHtml(jobUrl)}" target="_blank" rel="noopener noreferrer" class="history-job-link-pill" title="View Job Posting: ${escapeHtml(jobUrl)}">
              <i class="fa-solid fa-arrow-up-right-from-square"></i> View Job
            </a>` : `
            <button class="btn-icon-subtle" style="font-size:10.5px; color:var(--accent); text-decoration:underline;" onclick="openEditHistoryModal('${escapeHtml(app.log_file_name)}', '${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '')">
              <i class="fa-solid fa-plus"></i> Add Link
            </button>`
          }
        </div>
      </div>
      <div class="history-scores">
        <div class="score-col">
          <span>Before Score</span>
          <strong>${beforeScore}%</strong>
        </div>
        <div class="score-col">
          <span>After Score</span>
          <strong class="text-emerald">${afterScore}%</strong>
        </div>
        <div class="score-col">
          <span>Delta</span>
          <strong class="text-emerald">+${deltaScore}%</strong>
        </div>
      </div>
      <div class="history-actions">
        <button class="btn btn-blue btn-sm" onclick="openPreviewModal('${escapeHtml(historyDocxRel)}', '${escapeHtml(app.company)}', '${escapeHtml(app.role)}')" title="Preview resume in browser before downloading">
          <i class="fa-solid fa-eye"></i> Preview
        </button>
        <a href="/api/download/${historyDocxRel}" class="btn btn-emerald btn-sm" download>
          <i class="fa-solid fa-download"></i> .docx
        </a>
        ${historyPdfRel ? `<a href="/api/download/${historyPdfRel}" class="btn btn-cyan btn-sm" download><i class="fa-solid fa-file-pdf"></i> .pdf</a>` : ''}
        <button class="btn btn-purple-sm" onclick="openRefineFromHistory('${escapeHtml(app.log_file_name)}', '${escapeHtml(app.output_file)}', '${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '${escapeHtml(jobUrl)}')">
          <i class="fa-solid fa-wand-magic-sparkles"></i> Refine
        </button>
        ${jobUrl ? `
          <a href="${escapeHtml(jobUrl)}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" title="Open Job Posting in new tab">
            <i class="fa-solid fa-arrow-up-right-from-square"></i> Job Link
          </a>
        ` : ''}
        <button class="btn btn-purple-sm" onclick="generateOrViewHistoryCoverLetter('${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '${escapeHtml(app.relative_file_path)}', '${escapeHtml(jobUrl)}')">
          <i class="fa-solid fa-envelope"></i> Cover Letter
        </button>
        <button class="btn btn-secondary btn-sm" onclick="openEditHistoryModal('${escapeHtml(app.log_file_name)}', '${escapeHtml(app.company)}', '${escapeHtml(app.role)}', '${escapeHtml(jobUrl)}')" title="Edit company name, role or job link">
          <i class="fa-solid fa-pen-to-square"></i> Edit
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
  const selectAllCb = document.getElementById("select-all-history-cb");
  if (selectAllCb) selectAllCb.checked = isChecked;
  updateHistoryToolbarUI();
}

function deselectAllHistory() {
  selectedHistoryFiles.clear();
  document.querySelectorAll(".history-item-cb").forEach(cb => {
    cb.checked = false;
  });
  const selectAllCb = document.getElementById("select-all-history-cb");
  if (selectAllCb) selectAllCb.checked = false;
  updateHistoryToolbarUI();
}

function updateHistoryToolbarUI() {
  const count = selectedHistoryFiles.size;
  const countElem = document.getElementById("selected-history-count");
  if (countElem) countElem.textContent = count;
  const btn = document.getElementById("bulk-delete-btn");
  if (btn) btn.disabled = (count === 0);

  // Synchronize Floating Action Bar for Multi-Select History Operations
  const floatBar = document.getElementById("history-floating-action-bar");
  const floatCountText = document.getElementById("hfab-count-text");
  const floatBtnCount = document.getElementById("hfab-btn-count");
  const selectAllCb = document.getElementById("select-all-history-cb");
  const floatSelectAllLabel = document.getElementById("hfab-select-all-label");

  if (floatBar) {
    if (count > 0) {
      if (floatCountText) {
        floatCountText.innerHTML = `<strong>${count}</strong> application${count === 1 ? "" : "s"} selected`;
      }
      if (floatBtnCount) {
        floatBtnCount.textContent = count;
      }
      if (floatSelectAllLabel && selectAllCb) {
        floatSelectAllLabel.textContent = selectAllCb.checked ? "Deselect All" : "Select All";
      }
      floatBar.style.display = "block";
      requestAnimationFrame(() => {
        floatBar.classList.remove("hidden");
      });
    } else {
      floatBar.classList.add("hidden");
      setTimeout(() => {
        if (selectedHistoryFiles.size === 0) {
          floatBar.style.display = "none";
        }
      }, 240);
    }
  }
}

async function deleteHistoryItem(filename) {
  const confirmed = await showSystemConfirm({
    title: "Delete Application History?",
    message: "Are you sure you want to permanently delete this application record?\nThis will hard delete its output folder and generated resume from your computer disk.",
    note: "This action cannot be undone.",
    confirmText: "Delete Application",
    type: "danger",
    icon: "fa-solid fa-trash-can"
  });
  if (!confirmed) return;

  try {
    const res = await fetch(`/api/history/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    });
    const data = await res.json();
    if (data.success) {
      showToast("Application and folder permanently deleted from disk", "success");
      selectedHistoryFiles.delete(filename);
      updateHistoryToolbarUI();
      loadHistory();
    } else {
      showToast(data.error || "Failed to delete item", "error");
    }
  } catch (err) {
    showToast(`Delete failed: ${err.message}`, "error");
  }
}

function openEditHistoryModal(filename, company, role, url) {
  const modal = document.getElementById("edit-history-modal");
  const fnInput = document.getElementById("edit-history-filename");
  const coInput = document.getElementById("edit-history-company");
  const roleInput = document.getElementById("edit-history-role");
  const urlInput = document.getElementById("edit-history-url");

  if (fnInput) fnInput.value = filename || "";
  if (coInput) coInput.value = company || "";
  if (roleInput) roleInput.value = role || "";
  if (urlInput) urlInput.value = url || "";
  updateEditHistoryTestLink(url);

  if (modal) modal.style.display = "flex";
}

function closeEditHistoryModal() {
  const modal = document.getElementById("edit-history-modal");
  if (modal) modal.style.display = "none";
}

function updateEditHistoryTestLink(url) {
  const testBtn = document.getElementById("edit-history-test-link");
  if (!testBtn) return;
  if (url && (url.startsWith("http://") || url.startsWith("https://"))) {
    testBtn.href = url;
    testBtn.style.display = "inline-flex";
  } else {
    testBtn.style.display = "none";
  }
}

async function saveEditHistory() {
  const filename = (document.getElementById("edit-history-filename")?.value || "").trim();
  const company = (document.getElementById("edit-history-company")?.value || "").trim();
  const role = (document.getElementById("edit-history-role")?.value || "").trim();
  const url = (document.getElementById("edit-history-url")?.value || "").trim();

  if (!filename) {
    showToast("Missing log filename", "error");
    return;
  }
  if (!company || !role) {
    showToast("Please provide both Company Name and Role Title", "warning");
    return;
  }

  const saveBtn = document.getElementById("save-edit-history-btn");
  if (saveBtn) {
    saveBtn.disabled = true;
    saveBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Saving...';
  }

  try {
    const res = await fetch("/api/history/update", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ filename, company, role, url })
    });
    const data = await res.json();
    if (data.success) {
      showToast("Application details updated successfully!", "success");
      closeEditHistoryModal();
      await loadHistory();
    } else {
      showToast(data.error || "Failed to update application", "error");
    }
  } catch (err) {
    showToast(`Update error: ${err.message}`, "error");
  } finally {
    if (saveBtn) {
      saveBtn.disabled = false;
      saveBtn.innerHTML = '<i class="fa-solid fa-floppy-disk"></i> Save Changes';
    }
  }
}

async function deleteSelectedHistoryBatch() {
  const count = selectedHistoryFiles.size;
  if (count === 0) return;

  const confirmed = await showSystemConfirm({
    title: `Delete ${count} Selected Application${count === 1 ? "" : "s"}?`,
    message: `You are about to permanently delete ${count} application record${count === 1 ? "" : "s"} and their generated output folders from your computer disk.`,
    note: "All generated Word resumes, PDFs, and match score logs will be permanently deleted.",
    confirmText: `Delete ${count} Application${count === 1 ? "" : "s"}`,
    type: "danger",
    icon: "fa-solid fa-trash-can"
  });
  if (!confirmed) return;

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
      updateHistoryToolbarUI();
      loadHistory();
    } else {
      showToast(`Bulk delete failed: ${data.error}`, "error");
    }
  } catch (err) {
    showToast(`Error performing bulk delete: ${err.message}`, "error");
  }
}

async function confirmClearAllHistory() {
  const confirmed = await showSystemConfirm({
    title: "Clear ALL Application History?",
    message: "Are you sure you want to permanently delete ALL application records and remove all generated application folders from your computer?",
    note: "⚠️ PERMANENT HARD DELETE: This will remove every generated resume, PDF, and application log. This cannot be undone.",
    confirmText: "Wipe All History",
    type: "danger",
    icon: "fa-solid fa-dumpster-fire"
  });
  if (!confirmed) return;

  try {
    const res = await fetch("/api/history/clear_all", {
      method: "POST"
    });
    const data = await res.json();
    if (data.success) {
      showToast(data.message || "All history and folders deleted from disk.", "success");
      selectedHistoryFiles.clear();
      updateHistoryToolbarUI();
      loadHistory();
    } else {
      showToast(data.error || "Failed to clear history", "error");
    }
  } catch (err) {
    showToast(`Error clearing history: ${err.message}`, "error");
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
  function safeKeyAttr(str) {
    return String(str || "").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  function createKeyRowElement(kData, idx) {
    const row = document.createElement("div");
    row.className = "gemini-key-row glass-panel";
    row.style.cssText = "background: rgba(15, 23, 42, 0.65); border: 1px solid rgba(255,255,255,0.12); border-radius: 8px; padding: 10px 12px; margin-bottom: 0.5rem; transition: all 0.2s;";

    const labelVal = kData.label || (idx === 0 ? "Google Account 1 (Primary)" : idx === 1 ? "Google Account 2 (Backup)" : `Google Account ${idx + 1}`);
    const keyVal = kData.key || "";

    row.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
        <span class="key-index-badge" style="font-size: 0.78rem; font-weight: 600; color: #a5b4fc; display: flex; align-items: center; gap: 6px;">
          <i class="fa-solid fa-key" style="font-size: 0.75rem;"></i> Key #${idx + 1}
        </span>
        <button type="button" class="btn-remove-key" style="background: none; border: none; color: #f87171; cursor: pointer; font-size: 0.75rem; padding: 2px 6px; border-radius: 4px;" title="Remove this key slot">
          <i class="fa-solid fa-trash-can"></i> Remove
        </button>
      </div>
      <div style="display: grid; grid-template-columns: minmax(140px, 180px) 1fr; gap: 8px;">
        <input type="text" class="form-input key-label-input" placeholder="Account nickname (e.g. Personal Gmail)" value="${safeKeyAttr(labelVal)}" style="font-size: 0.82rem; padding: 6px 10px; background: rgba(0,0,0,0.25);">
        <div style="position: relative; display: flex; align-items: center;">
          <input type="password" class="form-input key-val-input" placeholder="AIzaSy... paste Gemini API key" value="${safeKeyAttr(keyVal)}" style="font-size: 0.82rem; padding: 6px 36px 6px 10px; font-family: monospace; width: 100%; background: rgba(0,0,0,0.25);">
          <button type="button" class="btn-toggle-key-eye" title="Show / Hide API Key" style="position: absolute; right: 6px; background: none; border: none; color: #94a3b8; cursor: pointer; padding: 4px; font-size: 0.85rem;">
            <i class="fa-solid fa-eye"></i>
          </button>
        </div>
      </div>
    `;

    // Toggle password eye button
    const eyeBtn = row.querySelector(".btn-toggle-key-eye");
    const keyInput = row.querySelector(".key-val-input");
    eyeBtn.addEventListener("click", () => {
      const isPass = keyInput.type === "password";
      keyInput.type = isPass ? "text" : "password";
      eyeBtn.innerHTML = isPass ? '<i class="fa-solid fa-eye-slash" style="color:#38bdf8;"></i>' : '<i class="fa-solid fa-eye"></i>';
    });

    // Remove row button
    const removeBtn = row.querySelector(".btn-remove-key");
    removeBtn.addEventListener("click", () => {
      const container = document.getElementById("gemini-keys-container");
      if (container.querySelectorAll(".gemini-key-row").length <= 1) {
        keyInput.value = "";
        row.querySelector(".key-label-input").value = "Google Account 1 (Primary)";
        showToast("Cleared key. At least one key slot is kept active.", "info");
        return;
      }
      row.remove();
      // Re-index remaining rows
      container.querySelectorAll(".gemini-key-row").forEach((r, i) => {
        const badge = r.querySelector(".key-index-badge");
        if (badge) badge.innerHTML = `<i class="fa-solid fa-key" style="font-size: 0.75rem;"></i> Key #${i + 1}`;
      });
    });

    return row;
  }

  try {
    const res = await fetch("/api/settings");
    const data = await res.json();

    const container = document.getElementById("gemini-keys-container");
    if (container) {
      container.innerHTML = "";
      let keysList = data.GEMINI_API_KEYS || [];
      if (!Array.isArray(keysList) || keysList.length === 0) {
        keysList = [];
        if (data.GEMINI_API_KEY) keysList.push({ key: data.GEMINI_API_KEY, label: "Google Account 1 (Primary)" });
        if (data.GEMINI_API_KEY_2) keysList.push({ key: data.GEMINI_API_KEY_2, label: "Google Account 2 (Backup)" });
      }
      if (keysList.length === 0) {
        keysList = [
          { key: "", label: "Google Account 1 (Primary)" },
          { key: "", label: "Google Account 2 (Backup)" }
        ];
      }
      keysList.forEach((kData, idx) => {
        container.appendChild(createKeyRowElement(kData, idx));
      });
    }

    const addBtn = document.getElementById("add-gemini-key-btn");
    if (addBtn && !addBtn.dataset.bound) {
      addBtn.dataset.bound = "true";
      addBtn.addEventListener("click", () => {
        const c = document.getElementById("gemini-keys-container");
        if (c) {
          const count = c.querySelectorAll(".gemini-key-row").length;
          c.appendChild(createKeyRowElement({ key: "", label: `Google Account ${count + 1}` }, count));
        }
      });
    }

    const emailInput = document.getElementById("simplify-email-input");
    const passInput = document.getElementById("simplify-pass-input");
    const outDirInput = document.getElementById("custom-output-dir");

    if (emailInput) emailInput.value = data.SIMPLIFY_EMAIL || "";
    if (passInput) passInput.value = data.SIMPLIFY_PASSWORD || "";
    if (outDirInput) outDirInput.value = data.OUTPUT_DIR || "";

    // Toggle eye for simplify password
    document.querySelectorAll(".btn-toggle-eye").forEach(btn => {
      if (!btn.dataset.bound) {
        btn.dataset.bound = "true";
        btn.addEventListener("click", () => {
          const targetId = btn.dataset.target;
          const targetInp = document.getElementById(targetId);
          if (targetInp) {
            const isPass = targetInp.type === "password";
            targetInp.type = isPass ? "text" : "password";
            btn.innerHTML = isPass ? '<i class="fa-solid fa-eye-slash" style="color:#38bdf8;"></i>' : '<i class="fa-solid fa-eye"></i>';
          }
        });
      }
    });
  } catch (err) {
    console.error("Failed to load settings", err);
  }

  const form = document.getElementById("settings-form");
  if (form && !form.dataset.bound) {
    form.dataset.bound = "true";
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      // Collect all dynamic Gemini API keys
      const keyRows = document.querySelectorAll("#gemini-keys-container .gemini-key-row");
      const geminiKeysList = [];
      keyRows.forEach(r => {
        const k = r.querySelector(".key-val-input")?.value.trim() || "";
        const l = r.querySelector(".key-label-input")?.value.trim() || "";
        if (k) {
          geminiKeysList.push({ key: k, label: l });
        }
      });

      const email = document.getElementById("simplify-email-input")?.value.trim() || "";
      const pass = document.getElementById("simplify-pass-input")?.value.trim() || "";

      try {
        const res = await fetch("/api/settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            GEMINI_API_KEYS: geminiKeysList,
            GEMINI_API_KEY: geminiKeysList[0]?.key || "",
            GEMINI_API_KEY_2: geminiKeysList[1]?.key || "",
            SIMPLIFY_EMAIL: email,
            SIMPLIFY_PASSWORD: pass,
          }),
        });
        const data = await res.json();
        if (data.success) {
          showToast(`Settings saved! ${geminiKeysList.length} Gemini API keys active in pool with auto-failover.`, "success");
          checkSystemHealth();
          if (typeof checkHollaBuddyApiHealth === "function") {
            checkHollaBuddyApiHealth();
          }
        } else {
          showToast("Failed to save settings", "error");
        }
      } catch (err) {
        showToast(`Error saving settings: ${err.message}`, "error");
      }
    });
  }
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
            <input type="text" id="vr-name" class="vr-input" value="${escapeHtml(name)}" placeholder="e.g. Alex Morgan">
          </div>
          <div class="vr-field">
            <label class="vr-label">Location</label>
            <input type="text" id="vr-location" class="vr-input" value="${escapeHtml(location)}" placeholder="e.g. San Francisco, CA">
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
        <div class="vr-section-header" style="flex-wrap:wrap; gap:8px;">
          <div class="vr-section-title"><i class="fa-solid fa-briefcase"></i> Work Experience (${experience.length})</div>
          <div style="display:flex; align-items:center; gap:8px;">
            <button type="button" class="btn btn-secondary btn-sm" onclick="copyAllExperienceBullets()" style="border-radius:8px; font-size:12px; padding:4px 12px;">
              <i class="fa-regular fa-copy"></i> Copy All Job Bullets
            </button>
            <button type="button" class="vr-btn-add" onclick="addExperienceRole()"><i class="fa-solid fa-plus"></i> Add Role</button>
          </div>
        </div>
        <div id="vr-experience-list" style="display:flex; flex-direction:column; gap:14px;">
          ${experience.map((exp, roleIdx) => `
            <div class="vr-item-card" data-role-idx="${roleIdx}">
              <div class="vr-item-card-header">
                <span style="font-weight:700; color:var(--text-main); font-size:14px;">Role #${roleIdx + 1}: ${escapeHtml(exp.title || 'Position')} (${escapeHtml(exp.company || 'Company')})</span>
                <div style="display:flex; align-items:center; gap:6px;">
                  <button type="button" class="btn-chip" style="font-size:11.5px; padding:3px 10px; border-radius:6px; background:#f1f5f9; color:#0f172a; border:1px solid #cbd5e1; cursor:pointer;" onclick="copyRoleBullets(${roleIdx})">
                    <i class="fa-regular fa-copy"></i> Copy Description
                  </button>
                  <button type="button" class="vr-btn-delete" onclick="removeExperienceRole(${roleIdx})"><i class="fa-solid fa-trash"></i> Delete Role</button>
                </div>
              </div>
              <div class="vr-grid-2">
                <div class="vr-field">
                  <label class="vr-label">Job Title</label>
                  <input type="text" class="vr-input vr-exp-title" value="${escapeHtml(exp.title || '')}" placeholder="e.g. Senior Software Engineer">
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
                  <input type="text" class="vr-input vr-edu-institution" value="${escapeHtml(edu.institution || '')}" placeholder="e.g. Stanford University">
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

function copyRoleBullets(roleIdx) {
  const container = document.querySelector(`.vr-exp-bullets-container[data-role-idx="${roleIdx}"]`);
  let bullets = [];
  if (container) {
    const textareas = container.querySelectorAll('.vr-exp-bullet');
    textareas.forEach(ta => {
      const val = ta.value.trim();
      if (val) bullets.push(`• ${val.replace(/^[•\-\*]\s*/, '')}`);
    });
  }
  if (bullets.length === 0 && currentMasterResumeData?.experience?.[roleIdx]) {
    const exp = currentMasterResumeData.experience[roleIdx];
    (exp.bullets || []).forEach(b => {
      const val = b.trim();
      if (val) bullets.push(`• ${val.replace(/^[•\-\*]\s*/, '')}`);
    });
  }

  if (bullets.length === 0) {
    showToast("No bullet points found for this role.", "warning");
    return;
  }

  const output = bullets.join('\n');
  navigator.clipboard.writeText(output);
  showToast(`Copied ${bullets.length} bullet points to clipboard!`, 'success');
}

function copyAllExperienceBullets() {
  const list = document.getElementById("vr-experience-list");
  let bullets = [];

  if (list) {
    const textareas = list.querySelectorAll('.vr-exp-bullet');
    textareas.forEach(ta => {
      const val = ta.value.trim();
      if (val) bullets.push(`• ${val.replace(/^[•\-\*]\s*/, '')}`);
    });
  }

  // Fallback to memory if DOM textareas are empty
  if (bullets.length === 0 && currentMasterResumeData?.experience) {
    currentMasterResumeData.experience.forEach(exp => {
      (exp.bullets || []).forEach(b => {
        const val = b.trim();
        if (val) bullets.push(`• ${val.replace(/^[•\-\*]\s*/, '')}`);
      });
    });
  }

  if (bullets.length === 0) {
    showToast("No job description bullets found to copy.", "warning");
    return;
  }

  const output = bullets.join('\n');
  navigator.clipboard.writeText(output);
  showToast(`Copied all ${bullets.length} job description bullets to clipboard!`, 'success');
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

  const progressCard = document.getElementById("resume-upload-progress-card");
  const uploadPrompt = document.getElementById("resume-upload-prompt");
  const visualCard = document.getElementById("visual-resume-card");
  const jsonCard = document.getElementById("json-editor-card");
  const actionsBar = document.getElementById("resume-actions-bar");
  const bar = document.getElementById("resume-upload-bar");
  const pctLabel = document.getElementById("upload-progress-pct");
  const mainLabel = document.getElementById("upload-progress-label");
  const subLabel = document.getElementById("upload-progress-sub");

  // Show progress card, hide everything else
  if (uploadPrompt) uploadPrompt.classList.add("hidden");
  if (visualCard) visualCard.classList.add("hidden");
  if (jsonCard) jsonCard.classList.add("hidden");
  if (actionsBar) actionsBar.classList.add("hidden");
  progressCard.classList.remove("hidden");

  mainLabel.textContent = `Uploading ${file.name}…`;
  subLabel.textContent = "Sending file to server…";

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
  subLabel.textContent = "Extracting skills, experience, education…";
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
  subLabel.textContent = data.message || data.error || "";

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
  const confirmed = await showSystemConfirm({
    title: "Delete Master Resume?",
    message: "Are you sure you want to delete your Master Resume from the system?",
    note: "You will need to upload or paste a new master resume before generating future applications.",
    confirmText: "Delete Master Resume",
    type: "danger",
    icon: "fa-solid fa-file-excel"
  });
  if (!confirmed) return;

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

/* ── Simplify-Style Interactive Keyword Cross-Check ─────────────────────── */
/* ── Simplify-Style Interactive Keyword Cross-Check ─────────────────────── */
let analyzedMissingKeywords = [];
let selectedMissingKeywords = new Set();
let analyzeAbortController = null;

function stopAnalyzeJob() {
  if (analyzeAbortController) {
    analyzeAbortController.abort();
    analyzeAbortController = null;
  }
  const analyzeBtn = document.getElementById("analyze-btn");
  const stopBtn = document.getElementById("analyze-stop-btn");
  if (analyzeBtn) {
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;
  }
  if (stopBtn) stopBtn.classList.add("hidden");
  setAnalyzeConsoleState("idle", "Analysis stopped");
  appendAnalyzeConsoleLine("⏹ Analysis cancelled by user.", "warning");
  showToast("Analysis stopped. You can paste the job manually or try another link.", "info");
}

function resetJobApplication() {
  // If analyzing, stop it immediately
  if (analyzeAbortController) {
    analyzeAbortController.abort();
    analyzeAbortController = null;
  }

  // 1. Reset input fields
  const urlInput = document.getElementById("jd-url");
  if (urlInput) urlInput.value = "";
  const kwInput = document.getElementById("custom-keywords-input");
  if (kwInput) kwInput.value = "";
  const bulletsInput = document.getElementById("matrix-custom-bullets-input") || document.getElementById("custom-bullets-input");
  if (bulletsInput) bulletsInput.value = "";

  // 1b. Reset Application Questions Copilot input & generated answers
  const qaInput = document.getElementById("qa-copilot-input");
  if (qaInput) qaInput.value = "";
  const qaContainer = document.getElementById("qa-answers-container");
  if (qaContainer) {
    qaContainer.innerHTML = "";
    qaContainer.classList.add("hidden");
  }

  // 1c. Reset Refinement Copilot
  const refineInput = document.getElementById("refine-input");
  if (refineInput) refineInput.value = "";
  const refineStatusBox = document.getElementById("refine-status-box");
  if (refineStatusBox) refineStatusBox.classList.add("hidden");
  const refineStatusText = document.getElementById("refine-status-text");
  if (refineStatusText) refineStatusText.textContent = "";

  // 2. Hide platform badge
  const badge = document.getElementById("detected-platform-badge");
  if (badge) badge.classList.add("hidden");

  // 3. Reset buttons
  const analyzeBtn = document.getElementById("analyze-btn");
  if (analyzeBtn) {
    analyzeBtn.disabled = false;
    analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;
  }
  const stopBtn = document.getElementById("analyze-stop-btn");
  if (stopBtn) stopBtn.classList.add("hidden");

  // 4. Hide error card & simplify card & execution container & matrix card & results dashboard
  _analyzeHideError();
  const simplifyCard = document.getElementById("simplify-card");
  if (simplifyCard) simplifyCard.classList.add("hidden");
  const matrixCard = document.getElementById("analyze-matrix-card");
  if (matrixCard) matrixCard.classList.add("hidden");
  const execContainer = document.getElementById("execution-container");
  if (execContainer) execContainer.classList.add("hidden");
  const pBar = document.getElementById("pipeline-progress-bar");
  if (pBar) pBar.style.width = "0%";
  const resultsDash = document.getElementById("results-dashboard");
  if (resultsDash) resultsDash.classList.add("hidden");

  // Close preview modal if open
  if (typeof closePreviewModal === "function") {
    closePreviewModal();
  }

  // 5. Clear global state
  window.lastResult = null;
  window.lastGeneratedRun = null;
  window._currentRunDir = null;
  analyzeScoreBefore = null;
  analyzeCompany = "";
  analyzeRole = "";
  analyzeJdText = "";
  currentCompany = "";
  currentRole = "";
  currentJdText = "";
  hollabuddyActiveJob = null;
  analyzedMissingKeywords = [];
  selectedMissingKeywords.clear();

  // 6. Reset console drawer
  clearAnalyzeConsole();
  setAnalyzeConsoleState("idle", "Idle");
  toggleAnalyzeConsole(false);

  // 7. Focus on URL input
  if (urlInput) {
    urlInput.focus();
    urlInput.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  showToast("Ready for new job! Enter URL or click 'Manual Paste'.", "info");
}

async function analyzeJobKeywords(opts = {}) {
  let url = document.getElementById("jd-url").value.trim();
  const directJdText = opts.directJdText || "";

  if (!url && !directJdText) {
    showToast("Please enter a job URL or paste the job description text", "warning");
    return;
  }
  const isDirectText = url.includes("\n") || (url.includes(" ") && url.split(" ").length > 3);
  if (!isDirectText && !url.startsWith("http://") && !url.startsWith("https://") && !directJdText) {
    url = "https://" + url;
    document.getElementById("jd-url").value = url;
  }

  const analyzeBtn = document.getElementById("analyze-btn");
  const stopBtn = document.getElementById("analyze-stop-btn");
  if (analyzeBtn) {
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Analyzing...`;
  }
  if (stopBtn) stopBtn.classList.remove("hidden");

  // Abort any prior request and initialize new controller
  if (analyzeAbortController) {
    analyzeAbortController.abort();
  }
  analyzeAbortController = new AbortController();

  // Reset any previous tailored resume state so Quick Navigator never triggers during or after analysis
  const resDash = document.getElementById("results-dashboard");
  if (resDash) resDash.classList.add("hidden");
  window.lastResult = null;
  if (typeof closeScrollCompass === "function") closeScrollCompass(true);

  // Clear any previous inline error and activate inline live terminal drawer
  _analyzeHideError();
  clearAnalyzeConsole();
  setAnalyzeConsoleState("running", "Analyzing job posting...");
  toggleAnalyzeConsole(true); // Auto-open drawer so user sees what backend is doing!
  initConsoleStream(); // Ensure live SSE stream is active

  const targetLabel = isDirectText ? `Direct Job Description (${(directJdText || url).length} chars)` : url;
  appendAnalyzeConsoleLine(`🚀 Target: ${targetLabel}`, "analyze");
  appendAnalyzeConsoleLine(`🔍 Connecting to scraper & ATS evaluation pipeline...`, "scraper");

  try {
    const res = await fetch("/api/analyze", {
      method: "POST",
      signal: analyzeAbortController.signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: url || "Manual Job Description",
        jd_text: directJdText || undefined,
        company: opts.customCompany || undefined,
        role: opts.customRole || undefined,
        no_simplify: document.getElementById("no-simplify-toggle").checked
      })
    });

    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      throw new Error(`Server returned HTTP ${res.status}: ${text ? text.slice(0, 200) : "Empty response from server"}`);
    }

    if (analyzeBtn) {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;
    }
    if (stopBtn) stopBtn.classList.add("hidden");

    if (!data.success) {
      setAnalyzeConsoleState("error", "Analysis failed");
      appendAnalyzeConsoleLine(`❌ ${data.error || "Analysis failed."}`, "error");

      const isBlockError = data.error_type === "scrape_blocked" || data.error_type === "jd_blocked" || (data.error && (data.error.includes("bot-block") || data.error.includes("CAPTCHA")));
      if (isBlockError) {
        _analyzeShowError(data.error || "Could not extract job description from this URL.");
        openManualJdModal(data.company, data.role, "analyze");
      } else {
        showToast(data.error || "Analysis failed", "error");
      }
      return;
    }

    // Save analyze state so Generate step can reuse it without re-doing work
    analyzeScoreBefore = data.score;
    analyzeCompany = data.company;
    analyzeRole = data.role;
    analyzeJdText = data.jd_text || "";

    setAnalyzeConsoleState("success", `Complete: ${data.role} @ ${data.company} (${data.score}%)`);
    appendAnalyzeConsoleLine(`✅ Successfully analyzed ${data.role} at ${data.company}!`, "success");
    appendAnalyzeConsoleLine(`🎯 ATS Score: ${data.score}% | Matched: ${data.matching_keywords ? data.matching_keywords.length : 0} | Missing: ${data.missing_keywords ? data.missing_keywords.length : 0}`, "success");

    renderSimplifyCard(data);
    showToast(`Scraped ${data.role} at ${data.company}! Keywords cross-checked.`, "success");
    openReviewConfirmModal(data);
  } catch (err) {
    if (err.name === "AbortError") {
      return; // Handled cleanly by stopAnalyzeJob()
    }
    if (analyzeBtn) {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = `<i class="fa-solid fa-magnifying-glass"></i> Analyze & Cross-Check`;
    }
    if (stopBtn) stopBtn.classList.add("hidden");
    setAnalyzeConsoleState("error", "Connection error");
    appendAnalyzeConsoleLine(`❌ Connection error: ${err.message}`, "error");
    showToast("Server connection error during analysis", "error");
  } finally {
    analyzeAbortController = null;
    if (stopBtn) stopBtn.classList.add("hidden");
  }
}

function _analyzeShowError(msg) {
  let card = document.getElementById("analyze-error-card");
  if (!card) {
    card = document.createElement("div");
    card.id = "analyze-error-card";
    card.style.cssText = [
      "margin-top:14px", "padding:16px 18px", "border-radius:10px",
      "background:rgba(239,68,68,0.12)", "border:1px solid rgba(239,68,68,0.35)",
      "color:#fca5a5", "font-size:13px", "line-height:1.7", "white-space:pre-wrap",
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
  if (card) card.remove();
}

/* ── Manual Job Description Fallback Modal ───────────────────────────────── */
let manualJdSource = "pipeline";

function openManualJdModal(company = "", role = "", source = "pipeline") {
  manualJdSource = source;
  const modal = document.getElementById("manual-jd-modal");
  if (!modal) return;

  const titleEl = document.getElementById("manual-jd-title");
  const subtitleEl = document.getElementById("manual-jd-subtitle");
  const iconEl = document.getElementById("manual-jd-icon");
  const iconBadge = document.getElementById("manual-jd-icon-badge");
  const noticeText = document.getElementById("manual-jd-notice-text");

  if (source === "manual_click" || source === "user") {
    if (titleEl) titleEl.innerText = "Paste Job Description Manually";
    if (subtitleEl) subtitleEl.innerText = "Directly paste job text to bypass LinkedIn, Wellfound, or bot-blocks";
    if (iconEl) iconEl.className = "fa-solid fa-paste";
    if (iconBadge) {
      iconBadge.style.background = "rgba(56, 189, 248, 0.15)";
      iconBadge.style.color = "#38bdf8";
      iconBadge.style.borderColor = "rgba(56, 189, 248, 0.35)";
    }
    if (noticeText) noticeText.innerText = "Paste the full job posting text below. The AI pipeline will extract technical skills, calculate your ATS match score, and tailor your resume without any web scraper delays.";
  } else {
    if (titleEl) titleEl.innerText = "Bot-Protection Detected on Portal";
    if (subtitleEl) subtitleEl.innerText = "Target site blocked automated scraping (403 / Captcha / Login Wall)";
    if (iconEl) iconEl.className = "fa-solid fa-shield-halved";
    if (iconBadge) {
      iconBadge.style.background = "var(--warn-dim)";
      iconBadge.style.color = "var(--warn)";
      iconBadge.style.borderColor = "var(--warn-border)";
    }
    if (noticeText) noticeText.innerText = "Copy the job text directly from your open browser tab and paste it below. The pipeline will automatically parse hard/soft skills, extract ATS keywords, and tailor your resume without losing your progress.";
  }

  const compInput = document.getElementById("manual-jd-company");
  const roleInput = document.getElementById("manual-jd-role");
  const txtArea = document.getElementById("manual-jd-text");
  const charCount = document.getElementById("manual-jd-charcount");

  // Clean company & role placeholders
  const isBadComp = !company || company.toLowerCase().includes("careers navitus") || company.toLowerCase().includes("target company");
  const isBadRole = !role || role.toLowerCase().includes("confirm you are human");

  const cleanComp = (!isBadComp) ? company : (analyzeCompany || "");
  const cleanRole = (!isBadRole) ? role : (analyzeRole || "");

  if (compInput) compInput.value = cleanComp;
  if (roleInput) roleInput.value = cleanRole;
  if (txtArea) {
    txtArea.value = "";
    if (charCount) charCount.textContent = "0 characters";
  }

  modal.classList.remove("hidden");
  setTimeout(() => txtArea && txtArea.focus(), 150);
}

function closeManualJdModal() {
  const modal = document.getElementById("manual-jd-modal");
  if (modal) modal.classList.add("hidden");
}

function continuePipelineWithManualJd() {
  const txtArea = document.getElementById("manual-jd-text");
  const text = (txtArea ? txtArea.value : "").trim();
  if (!text || text.length < 50) {
    showToast("Please paste the job description text (minimum 50 characters)", "warning");
    return;
  }

  const customCompany = document.getElementById("manual-jd-company")?.value.trim() || "";
  const customRole = document.getElementById("manual-jd-role")?.value.trim() || "";

  // Set the visual input box so user sees what's being run
  const urlBox = document.getElementById("jd-url");
  if (urlBox) {
    urlBox.value = customRole && customCompany 
      ? `[Direct] ${customRole} @ ${customCompany}`
      : `[Direct Text] Job Description (${text.length.toLocaleString()} chars)`;
  }

  closeManualJdModal();
  showToast("Resuming pipeline with pasted Job Description...", "info");

  startGeneration({
    directJdText: text,
    customCompany: customCompany || undefined,
    customRole: customRole || undefined,
  });
}

function continueAnalyzeWithManualJd() {
  const txtArea = document.getElementById("manual-jd-text");
  const text = (txtArea ? txtArea.value : "").trim();
  if (!text || text.length < 50) {
    showToast("Please paste the job description text (minimum 50 characters)", "warning");
    return;
  }

  const customCompany = document.getElementById("manual-jd-company")?.value.trim() || "";
  const customRole = document.getElementById("manual-jd-role")?.value.trim() || "";

  // Set the visual input box so user sees what's being analyzed
  const urlBox = document.getElementById("jd-url");
  if (urlBox) {
    urlBox.value = customRole && customCompany 
      ? `[Direct] ${customRole} @ ${customCompany}`
      : `[Direct Text] Job Description (${text.length.toLocaleString()} chars)`;
  }

  closeManualJdModal();
  _analyzeHideError();
  showToast("Cross-checking ATS matrix with pasted Job Description...", "info");

  analyzeJobKeywords({
    directJdText: text,
    customCompany: customCompany || undefined,
    customRole: customRole || undefined,
  });
}

/* ── Post-Analysis Review & Confirm Modal Handlers ───────────────────────── */
function openReviewConfirmModal(data) {
  const modal = document.getElementById("review-confirm-modal");
  if (!modal) return;

  const compInput = document.getElementById("review-company-input");
  const roleInput = document.getElementById("review-role-input");
  const scoreBadge = document.getElementById("review-score-badge");
  const kwCount = document.getElementById("review-kw-count");

  const company = data.company || analyzeCompany || "Target Company";
  const role = data.role || analyzeRole || "Target Role";
  const score = data.score || 70;
  const rating = data.score_rating || (score >= 80 ? "Great" : score >= 70 ? "Good" : "Fair");

  if (compInput) compInput.value = company;
  if (roleInput) roleInput.value = role;
  if (scoreBadge) {
    scoreBadge.innerText = `${score}% (${rating})`;
    scoreBadge.style.color = score >= 75 ? "#10b981" : score >= 60 ? "#f59e0b" : "#ef4444";
  }
  if (kwCount) {
    const matched = data.matching_keywords ? data.matching_keywords.length : 0;
    const missing = data.missing_keywords ? data.missing_keywords.length : 0;
    kwCount.innerText = `${matched} Matched • ${missing} Missing`;
  }

  modal.classList.remove("hidden");
  setTimeout(() => compInput && compInput.focus(), 150);
}

function closeReviewConfirmModal() {
  const modal = document.getElementById("review-confirm-modal");
  if (modal) modal.classList.add("hidden");
}

function confirmReviewAndOpenMatrix() {
  const comp = document.getElementById("review-company-input")?.value.trim();
  const role = document.getElementById("review-role-input")?.value.trim();
  if (comp) {
    analyzeCompany = comp;
    const el = document.getElementById("matrix-company-name");
    if (el) { if (el.tagName === "INPUT") el.value = comp; else el.innerText = comp; }
  }
  if (role) {
    analyzeRole = role;
    const el = document.getElementById("matrix-role-name");
    if (el) { if (el.tagName === "INPUT") el.value = role; else el.innerText = role; }
  }

  closeReviewConfirmModal();
  const card = document.getElementById("simplify-card");
  if (card) card.scrollIntoView({ behavior: "smooth", block: "start" });
  showToast("Review the ATS Matrix and uncheck/add keywords below before tailoring.", "info");
}

function confirmReviewAndTailor() {
  const comp = document.getElementById("review-company-input")?.value.trim();
  const role = document.getElementById("review-role-input")?.value.trim();
  if (comp) {
    analyzeCompany = comp;
    const el = document.getElementById("matrix-company-name");
    if (el) { if (el.tagName === "INPUT") el.value = comp; else el.innerText = comp; }
  }
  if (role) {
    analyzeRole = role;
    const el = document.getElementById("matrix-role-name");
    if (el) { if (el.tagName === "INPUT") el.value = role; else el.innerText = role; }
  }

  closeReviewConfirmModal();
  showToast("Confirmed! Tailoring resume with verified company and role...", "info");
  generateWithSelectedKeywords();
}

/* ── Simplify Connection Status, Test & Clipboard Helpers ────────────────── */
async function checkSimplifyStatus() {
  try {
    const res = await fetch("/api/simplify/status");
    const data = await res.json();
    const pill = document.getElementById("simplify-status-pill");
    const label = document.getElementById("simplify-status-label");
    if (data.success && label) {
      if (data.extension_found) {
        label.textContent = data.has_credentials
          ? `Simplify: Active (${data.account_email})`
          : `Simplify: Bundled Cloud Extension Ready (${data.version})`;
        if (pill) {
          pill.style.background = "rgba(16, 185, 129, 0.15)";
          pill.style.borderColor = "rgba(16, 185, 129, 0.35)";
          pill.style.color = "#34d399";
        }
      } else {
        label.textContent = "Simplify: Extension Directory Not Found";
        if (pill) {
          pill.style.background = "rgba(239, 68, 68, 0.15)";
          pill.style.borderColor = "rgba(239, 68, 68, 0.35)";
          pill.style.color = "#f87171";
        }
      }
    }
  } catch (e) {
    console.warn("checkSimplifyStatus note:", e);
  }
}

async function testSimplifyConnection() {
  const btn = document.getElementById("btn-test-simplify");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin text-cyan"></i> Testing...`;
  }
  try {
    const res = await fetch("/api/simplify/test", { method: "POST" });
    const text = await res.text();
    let data;
    try {
      data = JSON.parse(text);
    } catch (parseErr) {
      throw new Error(`Server returned HTTP ${res.status}: ${text ? text.slice(0, 200) : "Empty response from server"}`);
    }
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-plug-circle-check text-cyan"></i> Test Simplify Connection`;
    }
    if (data.success) {
      showToast(`✅ ${data.message}`, "success");
      const label = document.getElementById("simplify-status-label");
      if (label) label.textContent = `Simplify: Verified (${data.extension_name} ${data.version})`;
    } else {
      showToast(`⚠️ ${data.error || "Simplify test failed"}`, "warning");
    }
  } catch (err) {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<i class="fa-solid fa-plug-circle-check text-cyan"></i> Test Simplify Connection`;
    }
    showToast(`Test failed: ${err.message}`, "error");
  }
}

function copyBookmarkletCode() {
  const link = document.getElementById("simplify-bookmarklet-link");
  if (!link || !link.href) {
    showToast("Bookmarklet code not found", "error");
    return;
  }
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(link.href).then(() => {
      showToast("📋 Bookmarklet code copied! In Chrome: Right-click Bookmarks Bar ➔ Add Page ➔ Paste URL.", "success");
    }).catch(() => {
      _execCopyFallback(link.href);
    });
  } else {
    _execCopyFallback(link.href);
  }
}

function _execCopyFallback(text) {
  const dummy = document.createElement("textarea");
  dummy.value = text;
  document.body.appendChild(dummy);
  dummy.select();
  document.execCommand("copy");
  document.body.removeChild(dummy);
  showToast("📋 Bookmarklet code copied to clipboard!", "success");
}

// Known multi-word tech & ATS skill phrases to preserve when splitting space-separated dumps
const _KNOWN_MULTI_WORD_PHRASES = [
  "machine learning", "deep learning", "data science", "data engineering", "data analytics",
  "cloud computing", "rest api", "rest apis", "restful api", "restful apis",
  "ci/cd", "ci / cd", "unit testing", "integration testing", "system testing",
  "front end", "back end", "full stack", "frontend development", "backend development",
  "prompt engineering", "natural language processing", "computer vision", "generative ai",
  "artificial intelligence", "business intelligence", "agile methodology", "scrum master",
  "object oriented programming", "software development lifecycle", "sdlc",
  "version control", "test driven development", "tdd", "continuous integration", "continuous deployment",
  "relational database", "nosql database", "distributed systems", "microservices architecture",
  "event driven architecture", "message queue", "search engine optimization", "seo",
  "user experience", "user interface", "ui/ux", "ui / ux",
  "project management", "product management", "supply chain", "customer relationship management",
  "big data", "data warehouse", "data lake", "business analyst", "quality assurance"
];

function parseKeywordsList(rawText) {
  if (!rawText || typeof rawText !== "string") return [];
  let text = rawText.trim();

  // 1. Strip conversational introductory garbage from Gemini or ChatGPT or Job Postings:
  // e.g. "Here are the keywords from the job posting:", "Keywords extracted from the job description:",
  // "Certainly! Here is a list of ATS keywords:", "Relevant keywords:"
  text = text.replace(/^(?:(?:certainly|sure|here\s+(?:are|is)(?:\s+the)?|extracted|suggested|relevant|recommended)?\s*(?:keywords?|skills?|technologies|ats\s+keywords?|key\s+terms?)(?:\s+(?:extracted\s+)?from\s+(?:the\s+)?(?:job|jd|description|posting|role|resume))?(?:\s*\(\d+\))?[:\s-]+)+/i, "");

  // Strip markdown formatting like bold **keyword** or *keyword* or `code`
  text = text.replace(/[\*`]+/g, "");

  // Strip outer JSON array brackets if present: ['a', 'b'] or [a, b]
  text = text.replace(/^\[\s*|\s*\]$/g, "");

  // First, replace numbered list markers like '1. ', '2) ', '[1]', '(1)' with commas
  text = text.replace(/(?:^|\s+)(?:\d+[\.\)]|\[\d+\]|\(\d+\))\s+/g, ", ");
  
  // Replace bullets, middle dots, and symbols with commas
  // \u00B7 is · (middle dot), \u2022 is • (bullet)
  text = text.replace(/[\r\n;|•●○▪▫■□◆◇◦∙⁃‣▶✓✔·⋅・\t]+/g, ", ");
  
  // Replace dashes/slashes/pluses/and/& with spaces around them with commas (preserves CI/CD, TCP/IP, C++)
  text = text.replace(/\s+[\-\–\—\‒\―\/\\]\s+/g, ", ");
  text = text.replace(/\s+\+\s+/g, ", ");
  text = text.replace(/\s+(?:and|&)\s+/gi, ", ");
  
  // Replace 2 or more spaces with commas (from copied HTML chips/columns)
  text = text.replace(/\s{2,}/g, ", ");

  // CHECK: If text does NOT contain commas (or only 1 token so far),
  // but contains multiple space-separated words (e.g. Gemini space-separated list):
  // "Python FastApi Docker AWS Kubernetes PostgreSQL GraphQL Redis"
  // or "Python FastAPI Docker Machine Learning Kubernetes CI/CD"
  if (!text.includes(",")) {
    const rawWords = text.trim().split(/\s+/).filter(w => w.length > 0);
    // If there are 3 or more space-separated words, treat as space-separated keyword dump
    if (rawWords.length >= 3) {
      let transformed = text;
      // Protect quoted phrases first: "machine learning" -> "machine_learning"
      transformed = transformed.replace(/["']([^"']+)["']/g, (m, p1) => p1.replace(/\s+/g, "_SPACE_"));

      // Protect known multi-word phrases
      for (const phrase of _KNOWN_MULTI_WORD_PHRASES) {
        const regex = new RegExp("\\b" + phrase.replace(/[\/\\]/g, "\\$&") + "\\b", "gi");
        transformed = transformed.replace(regex, (match) => match.replace(/\s+/g, "_SPACE_"));
      }

      // Now split remaining spaces into commas!
      transformed = transformed.replace(/\s+/g, ", ");
      // Restore protected spaces
      text = transformed.replace(/_SPACE_/g, " ");
    }
  }

  // Split on commas
  const rawItems = text.split(/,+/);
  const cleaned = [];
  const seen = new Set();
  
  for (let item of rawItems) {
    if (!item) continue;
    let kw = item.trim()
      .replace(/^[\s\-\*\•\·\●\▪\▫\◆\–\—\+]+/, "")
      .replace(/^["'`]+|["'`]+$/g, "")
      .replace(/[,;:]+$/, "")
      .trim();
    if (kw && kw.length > 1 && !seen.has(kw.toLowerCase())) {
      seen.add(kw.toLowerCase());
      cleaned.push(kw);
    }
  }
  return cleaned;
}

function handleCustomKeywordsPaste(event) {
  const pasted = (event.clipboardData || window.clipboardData)?.getData("text");
  if (!pasted) return;
  const items = parseKeywordsList(pasted);
  if (items.length > 1) {
    event.preventDefault();
    const input = document.getElementById("custom-keywords-input");
    if (!input) return;
    const cleanStr = items.join(", ");
    const curVal = input.value.trim();
    if (curVal) {
      input.value = curVal.endsWith(",") ? `${curVal} ${cleanStr}` : `${curVal}, ${cleanStr}`;
    } else {
      input.value = cleanStr;
    }
    showToast(`✨ Auto-separated & formatted ${items.length} pasted keywords!`, "success");
  }
}

function formatCustomKeywordsOnBlur() {
  const input = document.getElementById("custom-keywords-input");
  if (!input) return;
  const val = input.value.trim();
  if (!val) return;
  const items = parseKeywordsList(val);
  if (items.length > 1) {
    const formatted = items.join(", ");
    if (formatted !== val) {
      input.value = formatted;
    }
  }
}

async function pasteSimplifyFromClipboard() {
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      const text = await navigator.clipboard.readText();
      if (!text || text.trim().length === 0) {
        showToast("Clipboard is empty. Copy keywords from Simplify first!", "warning");
        return;
      }
      const input = document.getElementById("custom-keywords-input");
      if (input) {
        const parsed = parseKeywordsList(text);
        if (parsed.length > 1) {
          input.value = parsed.join(", ");
          showToast(`✨ Auto-detected and formatted ${parsed.length} keywords from clipboard!`, "success");
        } else {
          input.value = text.trim();
          showToast("Pasted keywords into Simplify Missing Keywords field!", "success");
        }
        input.focus();
      }
    } else {
      showToast("Clipboard access not available in this browser context. Please paste manually into the input box.", "info");
    }
  } catch (err) {
    showToast("Could not read clipboard. Please paste manually into the input box.", "warning");
  }
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
  const rName = data.role || "Job Role";

  if (compName) {
    if (compName.tagName === "INPUT") compName.value = cName;
    else compName.innerText = cName;
  }
  if (compAvatar) compAvatar.innerText = cName.substring(0, 3).toUpperCase();
  if (roleName) {
    if (roleName.tagName === "INPUT") roleName.value = rName;
    else roleName.innerText = rName;
  }
  if (resumeFile) resumeFile.innerText = data.resume_name || "Master_Resume";

  // 3. Job Title Row
  const titleJd = document.getElementById("matrix-title-jd");
  const titleResume = document.getElementById("matrix-title-resume");
  const titleStatus = document.getElementById("matrix-title-status");

  if (titleJd) titleJd.innerText = data.job_title_jd || data.role;
  if (titleResume) titleResume.innerText = data.job_title_resume || "Current Role";
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
  const matchedContainer = document.getElementById("matrix-matched-container");
  const missingContainer = document.getElementById("matrix-missing-container");
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

  // Matched chips (👍)
  if (matchedContainer) {
    matchedContainer.innerHTML = "";
    if (matched.length === 0) {
      matchedContainer.innerHTML = `<span style="font-size:13px; color:#94a3b8; font-style:italic;">None identified yet</span>`;
    } else {
      matched.forEach(kw => {
        const chip = document.createElement("span");
        chip.className = "chip-matched-thumb";
        chip.innerHTML = `👍 ${kw}`;
        matchedContainer.appendChild(chip);
      });
    }
  }

  // Missing chips (Interactive Selectable + Addable with JD sentence context)
  analyzedMissingKeywords = missing;
  analyzedMissingKeywordContexts = data.missing_keyword_contexts || {};
  selectedMissingKeywords = new Set(missing);

  if (missingContainer) {
    missingContainer.innerHTML = "";
    if (missing.length === 0) {
      if (matched.length > 0) {
        missingContainer.innerHTML = `<span style="font-size:13px; color:#10b981; font-weight:600;">🎉 Master resume matches all required job skills!</span>`;
      } else {
        missingContainer.innerHTML = `<span style="font-size:13px; color:#94a3b8; font-style:italic;">No missing skills identified yet. Add custom keywords below to inject.</span>`;
      }
    } else {
      missing.forEach(kw => {
        const ctx = analyzedMissingKeywordContexts[kw] || "";
        renderMatrixMissingChip(kw, missingContainer, ctx);
      });
    }
  }

  updateMatrixSelectionCounters();

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

function renderMatrixMissingChip(kw, container, contextText = "") {
  const chip = document.createElement("div");
  const isSelected = selectedMissingKeywords.has(kw);
  chip.className = "chip-missing-selectable " + (isSelected ? "" : "deselected");
  chip.dataset.keyword = kw;

  let contextSnippet = "";
  if (contextText) {
    const escapedCtx = contextText.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    chip.title = `JD Context: "${contextText}"`;
    contextSnippet = `<span class="chip-ctx-indicator" style="margin-left:6px; color:#38bdf8; font-size:11px; cursor:help;" title="JD Context: ${escapedCtx}"><i class="fa-solid fa-circle-info"></i></span>`;
  }

  chip.innerHTML = `<i class="fa-solid ${isSelected ? 'fa-circle-check text-emerald' : 'fa-circle text-muted'} icon-state"></i> <span>${kw}</span>${contextSnippet}`;

  chip.addEventListener("click", (e) => {
    // If user clicked the info icon specifically, don't toggle selection
    if (e.target.closest(".chip-ctx-indicator")) {
      e.stopPropagation();
      showToast(`JD Context: "${contextText}"`, "info");
      return;
    }
    if (selectedMissingKeywords.has(kw)) {
      selectedMissingKeywords.delete(kw);
      chip.classList.add("deselected");
      chip.querySelector(".icon-state").className = "fa-regular fa-circle text-muted icon-state";
    } else {
      selectedMissingKeywords.add(kw);
      chip.classList.remove("deselected");
      chip.querySelector(".icon-state").className = "fa-solid fa-circle-check text-emerald icon-state";
    }
    updateMatrixSelectionCounters();
  });

  container.appendChild(chip);
}

function updateMatrixSelectionCounters() {
  const count = selectedMissingKeywords.size;
  const badge = document.getElementById("matrix-selected-count-badge");
  const btnCount = document.getElementById("matrix-btn-kw-count");
  if (badge) badge.innerText = `${count} selected`;
  if (btnCount) btnCount.innerText = `${count}`;
}

function selectAllMatrixChips(state) {
  const container = document.getElementById("matrix-missing-container");
  if (!container) return;

  const chips = container.querySelectorAll(".chip-missing-selectable");
  chips.forEach(chip => {
    const kw = chip.dataset.keyword;
    if (state) {
      selectedMissingKeywords.add(kw);
      chip.classList.remove("deselected");
      const icon = chip.querySelector(".icon-state");
      if (icon) icon.className = "fa-solid fa-circle-check text-emerald icon-state";
    } else {
      selectedMissingKeywords.delete(kw);
      chip.classList.add("deselected");
      const icon = chip.querySelector(".icon-state");
      if (icon) icon.className = "fa-regular fa-circle text-muted icon-state";
    }
  });

  updateMatrixSelectionCounters();
}

function handleMatrixManualKwPaste(event) {
  const pasted = (event.clipboardData || window.clipboardData)?.getData("text");
  if (!pasted) return;
  const items = parseKeywordsList(pasted);
  if (items.length > 0) {
    event.preventDefault();
    const input = document.getElementById("matrix-manual-kw-input");
    if (input) input.value = "";
    addMatrixManualChip(pasted);
  }
}

function addMatrixManualChip(overrideText = null) {
  const input = document.getElementById("matrix-manual-kw-input");
  const rawVal = overrideText !== null ? overrideText : (input ? input.value : "");
  if (!rawVal || !rawVal.trim()) return;

  const container = document.getElementById("matrix-missing-container");
  if (!container) return;

  const keywords = parseKeywordsList(rawVal);
  if (keywords.length === 0) return;

  let addedCount = 0;
  const addedNames = [];

  keywords.forEach(kw => {
    if (!selectedMissingKeywords.has(kw)) {
      selectedMissingKeywords.add(kw);
      renderMatrixMissingChip(kw, container);
      addedCount++;
      addedNames.push(kw);
    }
  });

  if (addedCount > 0) {
    updateMatrixSelectionCounters();
    if (addedCount === 1) {
      showToast(`Added '${addedNames[0]}' to keyword injection list!`, "success");
    } else {
      const sample = addedNames.slice(0, 3).join(", ") + (addedNames.length > 3 ? ` +${addedNames.length - 3} more` : "");
      showToast(`✨ Auto-detected & added ${addedCount} separate keywords (${sample})!`, "success");
    }
  } else {
    showToast("Keyword(s) already in the list!", "info");
  }

  if (input && overrideText === null) {
    input.value = "";
  }
}

function onCompanyEdited(newVal) {
  analyzeCompany = (newVal || "").trim();
  const compAvatar = document.getElementById("matrix-company-avatar");
  if (compAvatar && analyzeCompany) {
    compAvatar.innerText = analyzeCompany.substring(0, 3).toUpperCase();
  }
}

function onRoleEdited(newVal) {
  analyzeRole = (newVal || "").trim();
  const titleJd = document.getElementById("matrix-title-jd");
  if (titleJd && analyzeRole) {
    titleJd.innerText = analyzeRole;
  }
}

function openCoverLetterFromAnalyze() {
  const comp = (analyzeCompany || document.getElementById("matrix-company-name")?.value || document.getElementById("matrix-company-name")?.innerText || "").trim();
  const role = (analyzeRole || document.getElementById("matrix-role-name")?.value || document.getElementById("matrix-role-name")?.innerText || "").trim();
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

function toggleCustomBulletsDrawer() {
  const body = document.getElementById("custom-bullets-body");
  const arrow = document.getElementById("custom-bullets-arrow");
  if (!body) return;
  if (body.style.display === "none") {
    body.style.display = "block";
    if (arrow) arrow.style.transform = "rotate(0deg)";
  } else {
    body.style.display = "none";
    if (arrow) arrow.style.transform = "rotate(-90deg)";
  }
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
    if (/resume/i.test(clean)) {
      return clean.replace(/resume/i, "Cover_Letter");
    }
    return clean.replace(/\.(docx|pdf|json)$/i, "_Cover_Letter.docx");
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
    if (/resume/i.test(clean)) {
      return clean.replace(/resume/i, "Cover_Letter");
    }
    return clean.replace(/\.(docx|pdf|json)$/i, "_Cover_Letter.docx");
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
  if (btn) btn.disabled = true;

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
    if (btn) btn.disabled = false;
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

async function downloadEditedCoverLetter() {
  const textarea = document.getElementById("cl-modal-textarea");
  const text = textarea ? textarea.value.trim() : "";
  if (!text) {
    showToast("No cover letter text to download.", "warning");
    return;
  }

  const btn = document.getElementById("cl-modal-docx-download");
  const origHtml = btn ? btn.innerHTML : "";
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving & Downloading...`;
  }

  const company = (window.currentCoverLetterParams?.company || window.lastResult?.company || "Target Company").trim();
  const role = (window.currentCoverLetterParams?.role || window.lastResult?.role || "Target Role").trim();

  try {
    const res = await fetch("/api/cover-letter/save", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cover_letter_text: text,
        company,
        role,
      }),
    });
    const data = await res.json();
    if (data.success && data.relative_docx) {
      if (window.lastResult) {
        window.lastResult.cover_letter_text = text;
      }
      window.location.href = `/api/download/${data.relative_docx}`;
      showToast("Cover letter updated with your edits and downloaded!", "success");
    } else {
      showToast(data.error || "Failed to save cover letter changes.", "error");
    }
  } catch (err) {
    showToast(`Error saving cover letter: ${err.message}`, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }
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

/* =========================================================================
   Application Questions Copilot (Human-Voiced Q&A)
   ========================================================================= */

function toggleQACopilotDrawer() {
  const body = document.getElementById("qa-copilot-body");
  const arrow = document.getElementById("qa-copilot-arrow");
  if (!body) return;
  const isHidden = body.style.display === "none";
  body.style.display = isHidden ? "block" : "none";
  if (arrow) arrow.style.transform = isHidden ? "rotate(0deg)" : "rotate(-90deg)";
}

function insertPresetQA(questionText) {
  const input = document.getElementById("qa-copilot-input");
  if (!input) return;
  if (input.value.trim()) {
    input.value += "\n" + questionText;
  } else {
    input.value = questionText;
  }
  // Ensure drawer is open
  const body = document.getElementById("qa-copilot-body");
  if (body) body.style.display = "block";
  input.focus();
}

async function generateApplicationAnswers() {
  const input = document.getElementById("qa-copilot-input");
  const container = document.getElementById("qa-answers-container");
  const btn = document.getElementById("qa-copilot-generate-btn");

  if (!input || !input.value.trim()) {
    showToast("Please enter or select at least one question to answer.", "warning");
    return;
  }

  const questions = input.value.trim();
  const company = (analyzeCompany || currentCompany || document.getElementById("matrix-company-title")?.textContent || "Target Company").trim();
  const role = (analyzeRole || currentRole || document.getElementById("matrix-role-title")?.textContent || "Target Role").trim();
  const jd_text = analyzeJdText || currentJdText || document.getElementById("jd-url")?.value || "";

  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Crafting Human-Voiced Answers...`;

  try {
    const res = await fetch("/api/answer-questions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        questions,
        company,
        role,
        jd_text,
      }),
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "Failed to generate answers.");
    }

    if (!data.answers || data.answers.length === 0) {
      showToast("No answers could be generated.", "warning");
      return;
    }

    // Render Answers Cards
    container.innerHTML = "";
    container.classList.remove("hidden");

    data.answers.forEach((item, idx) => {
      const card = document.createElement("div");
      card.className = "qa-answer-card";
      card.style.cssText = `
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
      `;

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:10px; margin-bottom:8px;">
          <div style="font-weight:700; color:#0f172a; font-size:13.5px; line-height:1.4;">
            <span style="color:#0891b2; margin-right:6px;">Q${idx + 1}:</span> ${escapeHtml(item.question)}
          </div>
          <span class="badge" style="font-size:11px; padding:2px 8px; border-radius:6px; background:#f1f5f9; color:#475569; white-space:nowrap;">
            ${escapeHtml(item.tone_type || "Application Q&A")}
          </span>
        </div>
        <div style="font-size:13px; color:#334155; line-height:1.6; white-space:pre-wrap; background:#f8fafc; padding:12px 14px; border-radius:8px; border-left:3px solid #06b6d4; margin-bottom:10px;" id="qa-ans-text-${idx}">
${escapeHtml(item.answer)}
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-size:11.5px; color:#94a3b8;">
            <i class="fa-solid fa-align-left"></i> ${item.word_count || item.answer.split(' ').length} words  ·  ${item.char_count || item.answer.length} chars
          </span>
          <button type="button" class="btn btn-secondary btn-sm" onclick="copyQAText(${idx}, this)" style="border-radius:6px; font-weight:600; padding:4px 12px; font-size:12px;">
            <i class="fa-regular fa-copy"></i> Copy Answer
          </button>
        </div>
      `;
      container.appendChild(card);
    });

    showToast(`Generated ${data.answers.length} human-voiced answers!`, "success");
    container.scrollIntoView({ behavior: "smooth", block: "nearest" });

  } catch (err) {
    showToast(`Error: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-wand-magic-sparkles"></i> Generate Human-Voiced Answers`;
  }
}

function copyQAText(idx, btnElement) {
  const textElem = document.getElementById(`qa-ans-text-${idx}`);
  if (!textElem) return;
  const text = textElem.textContent.trim();
  navigator.clipboard.writeText(text);
  
  const origHtml = btnElement.innerHTML;
  btnElement.innerHTML = `<i class="fa-solid fa-check text-emerald"></i> Copied!`;
  btnElement.style.borderColor = "#10b981";
  showToast("Copied answer to clipboard!", "success");
  
  setTimeout(() => {
    btnElement.innerHTML = origHtml;
    btnElement.style.borderColor = "";
  }, 2000);
}

/* ── RESUME REFINEMENT COPILOT (INTERACTIVE REVISIONS) ───────────────────── */

function applyRefinePreset(text) {
  const input = document.getElementById("refine-instruction-input");
  if (!input) return;
  const current = input.value.trim();
  if (current) {
    input.value = `${current}; ${text}`;
  } else {
    input.value = text;
  }
  input.focus();
}

async function submitResumeRefinement() {
  const input = document.getElementById("refine-instruction-input");
  const btn = document.getElementById("refine-submit-btn");
  const spinner = document.getElementById("refine-btn-spinner");
  const icon = document.getElementById("refine-btn-icon");
  const btnText = document.getElementById("refine-btn-text");
  const statusBox = document.getElementById("refine-status-box");
  const statusText = document.getElementById("refine-status-text");

  const instruction = (input ? input.value : "").trim();
  if (!instruction) {
    showToast("Please describe what you want to change in the resume.", "warning");
    if (input) input.focus();
    return;
  }

  const lastRes = window.lastResult || {};
  const folderPath = lastRes.folder_path || "";
  const company = lastRes.company || analyzeCompany || "";
  const role = lastRes.role || analyzeRole || "";
  const url = lastRes.url || (document.getElementById("job-url-input") ? document.getElementById("job-url-input").value.trim() : "");
  const currentResume = lastRes.tailored_resume || null;

  if (!folderPath && !company) {
    showToast("No active application found to refine. Please run an application first or pick one from History.", "warning");
    return;
  }

  // Set loading state
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove("hidden");
  if (icon) icon.classList.add("hidden");
  if (btnText) btnText.textContent = "Revising & Rebuilding (~2s)...";

  try {
    const res = await fetch("/api/refine-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instruction: instruction,
        folder_path: folderPath,
        company: company,
        role: role,
        url: url,
        current_resume: currentResume,
        jd_text: (window.lastResult && window.lastResult.jd_text) ? window.lastResult.jd_text : (analyzeJdText || ""),
      }),
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "Failed to refine resume");
    }

    // Update window.lastResult with rebuilt documents and resume data
    if (window.lastResult) {
      window.lastResult.output_file = data.output_file;
      window.lastResult.relative_path = data.relative_path;
      window.lastResult.relative_pdf = data.relative_pdf;
      if (data.updated_resume) {
        window.lastResult.tailored_resume = data.updated_resume;
      }
    }

    // Show change summary in UI
    if (statusBox && statusText) {
      statusText.innerHTML = `<strong><i class="fa-solid fa-circle-check text-emerald"></i> Fix Applied:</strong> ${escHtml(data.change_summary || "Revisions applied and Word (.docx) & PDF documents rebuilt!")}<div style="margin-top:5px; font-size:11.5px; color:var(--cyan); display:flex; align-items:center; gap:6px;"><i class="fa-solid fa-arrow-rotate-left"></i> Textbox cleared — ready for your next instruction!</div>`;
      statusBox.classList.remove("hidden");
    }

    // Clear instruction textarea so user can start doing the next fix
    if (input) {
      input.value = "";
    }
    if (typeof updateRefineReviewBar === "function") {
      updateRefineReviewBar();
    }

    showToast("Resume revised & documents rebuilt! Textbox cleared for next fix.", "success");

    // Refresh history list silently in background
    loadHistory();

  } catch (err) {
    console.error("[Refine Error]", err);
    showToast(`Refinement failed: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add("hidden");
    if (icon) icon.classList.remove("hidden");
    if (btnText) btnText.textContent = "Apply Fixes & Rebuild";
  }
}

/* ── HISTORY RESUME REFINEMENT MODAL ─────────────────────────────────────── */

function openRefineFromHistory(logFileName, outputFile, company, role, jobUrl) {
  const modal = document.getElementById("history-refine-modal");
  if (!modal) return;

  const fnInput = document.getElementById("hist-refine-filename");
  const ofInput = document.getElementById("hist-refine-output-file");
  const coInput = document.getElementById("hist-refine-company");
  const roInput = document.getElementById("hist-refine-role");
  const urlInput = document.getElementById("hist-refine-url");
  const title = document.getElementById("hist-refine-modal-title");
  const sub = document.getElementById("hist-refine-modal-sub");
  const textInput = document.getElementById("hist-refine-input");
  const statusBox = document.getElementById("hist-refine-status-box");

  if (fnInput) fnInput.value = logFileName || "";
  if (ofInput) ofInput.value = outputFile || "";
  if (coInput) coInput.value = company || "";
  if (roInput) roInput.value = role || "";
  if (urlInput) urlInput.value = jobUrl || "";

  if (title) title.textContent = `Refine Resume — ${company || 'Application'}`;
  if (sub) sub.textContent = role ? `Role: ${role}` : "Tell Copilot what to adjust, add, or remove";
  if (textInput) textInput.value = "";
  if (statusBox) statusBox.classList.add("hidden");

  modal.style.display = "flex";
  if (textInput) textInput.focus();
}

function closeHistoryRefineModal() {
  const modal = document.getElementById("history-refine-modal");
  if (modal) modal.style.display = "none";
}

function applyHistRefinePreset(text) {
  const input = document.getElementById("hist-refine-input");
  if (!input) return;
  const current = input.value.trim();
  if (current) {
    input.value = `${current}; ${text}`;
  } else {
    input.value = text;
  }
  input.focus();
}

async function submitHistoryRefinement() {
  const input = document.getElementById("hist-refine-input");
  const btn = document.getElementById("hist-refine-submit-btn");
  const icon = document.getElementById("hist-refine-icon");
  const btnText = document.getElementById("hist-refine-btn-text");
  const statusBox = document.getElementById("hist-refine-status-box");
  const statusText = document.getElementById("hist-refine-status-text");

  const instruction = (input ? input.value : "").trim();
  if (!instruction) {
    showToast("Please describe what you want to change in the resume.", "warning");
    if (input) input.focus();
    return;
  }

  const outputFile = (document.getElementById("hist-refine-output-file")?.value || "").trim();
  const company = (document.getElementById("hist-refine-company")?.value || "").trim();
  const role = (document.getElementById("hist-refine-role")?.value || "").trim();
  const url = (document.getElementById("hist-refine-url")?.value || "").trim();

  // If outputFile points to .docx, get its directory
  let folderPath = outputFile;
  if (folderPath && (folderPath.endsWith(".docx") || folderPath.endsWith(".pdf"))) {
    folderPath = folderPath.replace(/[/\\][^/\\]+$/, "");
  }

  if (btn) btn.disabled = true;
  if (icon) icon.className = "fa-solid fa-spinner fa-spin";
  if (btnText) btnText.textContent = "Revising & Rebuilding (~2s)...";

  try {
    const res = await fetch("/api/refine-resume", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        instruction: instruction,
        folder_path: folderPath,
        company: company,
        role: role,
        url: url,
        jd_text: (window.lastResult && window.lastResult.jd_text) ? window.lastResult.jd_text : (window.analyzeJdText || ""),
      }),
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "Failed to refine resume");
    }

    if (statusBox && statusText) {
      statusText.innerHTML = `<strong><i class="fa-solid fa-circle-check text-emerald"></i> Fix Applied:</strong> ${escHtml(data.change_summary || "Revisions applied and Word (.docx) & PDF documents rebuilt!")}<div style="margin-top:5px; font-size:11.5px; color:var(--cyan); display:flex; align-items:center; gap:6px;"><i class="fa-solid fa-arrow-rotate-left"></i> Textbox cleared — ready for your next instruction!</div>`;
      statusBox.classList.remove("hidden");
    }

    // Clear instruction textarea so user can start doing the next fix
    if (input) {
      input.value = "";
    }

    showToast("Resume revised and documents rebuilt! Textbox cleared.", "success");

    // Refresh history cards so download links point to newly rebuilt files
    await loadHistory();

  } catch (err) {
    console.error("[History Refine Error]", err);
    showToast(`Refinement failed: ${err.message}`, "error");
  } finally {
    if (btn) btn.disabled = false;
    if (icon) icon.className = "fa-solid fa-bolt";
    if (btnText) btnText.textContent = "Apply Fixes & Rebuild";
  }
}

/* ==========================================================================
   Universal In-Browser Resume Preview Modal
   ========================================================================== */
function hidePreviewLoader() {
  const loader = document.getElementById("preview-loader");
  if (loader) loader.style.display = "none";
  if (window._previewLoaderTimeout) {
    clearTimeout(window._previewLoaderTimeout);
    window._previewLoaderTimeout = null;
  }
}

function printPreviewFrame() {
  const frame = document.getElementById("resume-preview-frame");
  if (frame && frame.contentWindow) {
    try {
      frame.contentWindow.focus();
      frame.contentWindow.print();
    } catch (e) {
      window.print();
    }
  } else {
    window.print();
  }
}

// ════════════════════════════════════════════════════════════════════════════
// LIVE PDF / PAPER RESUME WYSIWYG EDITOR
// ════════════════════════════════════════════════════════════════════════════

window._previewEditState = {
  active: true,
  hasUnsaved: false,
  filePath: "",
  company: "",
  role: "",
  originalHtml: ""
};

function togglePreviewEditMode() {
  const state = window._previewEditState;
  state.active = !state.active;

  const btn = document.getElementById("preview-edit-mode-btn");
  const label = document.getElementById("preview-edit-mode-label");
  const editorBar = document.getElementById("preview-editor-bar");

  if (state.active) {
    if (btn) {
      btn.style.background = "rgba(56, 189, 248, 0.15)";
      btn.style.borderColor = "rgba(56, 189, 248, 0.5)";
      btn.style.color = "var(--cyan)";
    }
    if (label) label.textContent = "Edit Mode: ON";
    if (editorBar) editorBar.style.display = "flex";
  } else {
    if (btn) {
      btn.style.background = "";
      btn.style.borderColor = "";
      btn.style.color = "";
    }
    if (label) label.textContent = "Edit Mode: OFF";
    if (editorBar) editorBar.style.display = "none";
  }

  const frame = document.getElementById("resume-preview-frame");
  if (frame && frame.contentWindow && typeof frame.contentWindow.enableEditor === "function") {
    frame.contentWindow.enableEditor(state.active);
  }
}

function onPreviewDocEdited() {
  window._previewEditState.hasUnsaved = true;

  const badge = document.getElementById("preview-unsaved-badge");
  if (badge) badge.style.display = "inline-block";

  const discardBtn = document.getElementById("preview-discard-btn");
  if (discardBtn) discardBtn.style.display = "inline-flex";

  const saveBtn = document.getElementById("preview-save-btn");
  if (saveBtn) saveBtn.style.display = "inline-flex";

  const statusPill = document.getElementById("preview-status-pill");
  if (statusPill) {
    statusPill.innerHTML = `<i class="fa-solid fa-pen-nib text-amber" style="color:#f59e0b;"></i> <span style="color:#f59e0b;">Unsaved edits</span>`;
  }
}

function togglePreviewAiDrawer(forceState) {
  const sidebar = document.getElementById("preview-ai-sidebar");
  const aiBtn = document.getElementById("preview-ai-polish-btn");
  if (!sidebar) return;
  const isHidden = sidebar.style.display === "none" || !sidebar.style.display;
  const show = typeof forceState === "boolean" ? forceState : isHidden;
  sidebar.style.display = show ? "flex" : "none";
  if (aiBtn) {
    if (show) {
      aiBtn.style.background = "rgba(245,158,11,0.2)";
      aiBtn.style.borderColor = "#f59e0b";
      aiBtn.style.boxShadow = "0 0 10px rgba(245,158,11,0.25)";
    } else {
      aiBtn.style.background = "";
      aiBtn.style.borderColor = "rgba(245,158,11,0.35)";
      aiBtn.style.boxShadow = "";
    }
  }
  if (show) {
    const inp = document.getElementById("preview-ai-instruction-input");
    if (inp) {
      setTimeout(() => {
        inp.focus();
      }, 50);
    }
  }
}

const AI_MENTION_TARGETS = [
  { tag: "@summary", name: "Professional Summary", icon: "fa-align-left", color: "#38bdf8", bg: "rgba(56,189,248,0.15)", desc: "Elevator pitch, executive intro & core value" },
  { tag: "@skills", name: "Technical Skills", icon: "fa-code", color: "#c084fc", bg: "rgba(168,85,247,0.15)", desc: "Add, categorize, replace or remove technical skills" },
  { tag: "@experience", name: "Work Experience", icon: "fa-briefcase", color: "#34d399", bg: "rgba(16,185,129,0.15)", desc: "Target role achievements, metrics & responsibilities" },
  { tag: "@all", name: "Everything Else / Global", icon: "fa-wand-magic-sparkles", color: "#fbbf24", bg: "rgba(245,158,11,0.15)", desc: "Holistic tone polish across all sections of document" },
  { tag: "@education", name: "Education", icon: "fa-graduation-cap", color: "#38bdf8", bg: "rgba(14,165,233,0.15)", desc: "Degree titles, institutions & graduation dates" },
  { tag: "@projects", name: "Projects", icon: "fa-folder-tree", color: "#818cf8", bg: "rgba(99,102,241,0.15)", desc: "Key project descriptions, links & tech stack" },
  { tag: "@certifications", name: "Certifications", icon: "fa-certificate", color: "#fb923c", bg: "rgba(251,146,60,0.15)", desc: "Professional credentials & industry licenses" },
  { tag: "@title", name: "Target Role / Headline", icon: "fa-id-badge", color: "#f472b6", bg: "rgba(244,114,182,0.15)", desc: "Subtitle headline under candidate name" }
];

let _activeMentionIndex = 0;
let _currentMentionTargets = [];

function getAvailableMentionTargets() {
  const targets = [...AI_MENTION_TARGETS];
  const resume = (window.lastResult && window.lastResult.tailored_resume) ? window.lastResult.tailored_resume : null;
  if (resume && Array.isArray(resume.experience)) {
    resume.experience.forEach(exp => {
      const comp = exp.company || "";
      if (comp && comp.trim()) {
        const cleanComp = comp.trim();
        if (!targets.some(t => t.name === cleanComp)) {
          targets.push({
            tag: `@experience/${cleanComp}`,
            name: cleanComp,
            icon: "fa-building",
            color: "#10b981",
            bg: "rgba(16,185,129,0.15)",
            desc: `Target bullets specifically for ${cleanComp}`
          });
        }
      }
    });
  }
  return targets;
}

function renderMentionDropdown(targets, activeIndex = 0) {
  const popup = document.getElementById("preview-ai-mention-popup");
  if (!popup) return;

  if (!targets || targets.length === 0) {
    popup.style.display = "none";
    _currentMentionTargets = [];
    return;
  }

  _currentMentionTargets = targets;
  _activeMentionIndex = Math.max(0, Math.min(activeIndex, targets.length - 1));

  let html = `
    <div class="preview-ai-mention-header">
      <span><i class="fa-solid fa-at" style="margin-right: 4px;"></i> Select Target Section</span>
      <span style="font-size: 10px; font-weight: 500; opacity: 0.85;">↑↓ navigate · ↵ select</span>
    </div>
  `;

  targets.forEach((target, idx) => {
    const isActive = idx === _activeMentionIndex;
    html += `
      <div class="preview-ai-mention-item ${isActive ? 'active' : ''}" data-index="${idx}" onmousedown="event.preventDefault(); selectMentionItem('${target.tag}');">
        <span class="mention-tag-pill" style="color: ${target.color}; background: ${target.bg}; border: 1px solid ${target.color}40;">
          <i class="fa-solid ${target.icon}" style="margin-right: 4px; font-size: 10px;"></i>${escapeHtml(target.tag)}
        </span>
        <div style="flex: 1; min-width: 0;">
          <div style="font-size: 12px; font-weight: 600; line-height: 1.2;">${escapeHtml(target.name)}</div>
          <div class="mention-desc" style="font-size: 10.5px; opacity: 0.75; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(target.desc)}</div>
        </div>
      </div>
    `;
  });

  popup.innerHTML = html;
  popup.style.display = "flex";

  const activeEl = popup.querySelector(`.preview-ai-mention-item[data-index="${_activeMentionIndex}"]`);
  if (activeEl) {
    activeEl.scrollIntoView({ block: "nearest" });
  }
}

function hideMentionPopup() {
  const popup = document.getElementById("preview-ai-mention-popup");
  if (popup) popup.style.display = "none";
  _currentMentionTargets = [];
}

function selectMentionItem(tag) {
  const input = document.getElementById("preview-ai-instruction-input");
  if (!input) return;
  const pos = input.selectionStart || 0;
  const textBefore = input.value.substring(0, pos);
  const textAfter = input.value.substring(pos);
  const atIndex = textBefore.lastIndexOf("@");
  if (atIndex !== -1) {
    const newTextBefore = textBefore.substring(0, atIndex) + tag + " ";
    input.value = newTextBefore + textAfter;
    input.selectionStart = input.selectionEnd = newTextBefore.length;
  } else {
    insertSidebarTag(tag + " ");
  }
  hideMentionPopup();
  input.focus();
}

function handleSidebarInstructionInput(event) {
  const input = event.target;
  if (!input) return;

  const pos = input.selectionStart || 0;
  const textBefore = input.value.substring(0, pos);
  const match = textBefore.match(/@([a-zA-Z0-9_\-\/]*)$/);

  if (match) {
    const query = match[1].toLowerCase();
    const allTargets = getAvailableMentionTargets();
    const filtered = allTargets.filter(t =>
      t.tag.toLowerCase().includes('@' + query) ||
      t.name.toLowerCase().includes(query) ||
      t.desc.toLowerCase().includes(query)
    );
    renderMentionDropdown(filtered, 0);
  } else {
    hideMentionPopup();
  }
}

function handleSidebarInstructionKeydown(event) {
  const popup = document.getElementById("preview-ai-mention-popup");
  const isPopupVisible = popup && popup.style.display !== "none" && _currentMentionTargets.length > 0;

  if (isPopupVisible) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      _activeMentionIndex = (_activeMentionIndex + 1) % _currentMentionTargets.length;
      renderMentionDropdown(_currentMentionTargets, _activeMentionIndex);
      return;
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      _activeMentionIndex = (_activeMentionIndex - 1 + _currentMentionTargets.length) % _currentMentionTargets.length;
      renderMentionDropdown(_currentMentionTargets, _activeMentionIndex);
      return;
    } else if (event.key === "Enter" || event.key === "Tab") {
      event.preventDefault();
      if (_currentMentionTargets[_activeMentionIndex]) {
        selectMentionItem(_currentMentionTargets[_activeMentionIndex].tag);
      }
      return;
    } else if (event.key === "Escape") {
      event.preventDefault();
      hideMentionPopup();
      return;
    }
  }

  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    applyPreviewAiInstruction();
  }
}

function insertSidebarTag(tag) {
  const input = document.getElementById("preview-ai-instruction-input");
  if (!input) return;
  const start = input.selectionStart || 0;
  const end = input.selectionEnd || 0;
  const val = input.value;
  input.value = val.substring(0, start) + tag + val.substring(end);
  input.focus();
  input.selectionStart = input.selectionEnd = start + tag.length;
  hideMentionPopup();
}

function clearSidebarInstruction() {
  const input = document.getElementById("preview-ai-instruction-input");
  if (input) {
    input.value = "";
    input.focus();
  }
  hideMentionPopup();
  const statusBox = document.getElementById("preview-ai-status-box");
  if (statusBox) statusBox.style.display = "none";
}

function extractResumeFromPreviewDoc() {
  const frame = document.getElementById("resume-preview-frame");
  const doc = frame?.contentDocument || frame?.contentWindow?.document;
  if (!doc) return null;

  // Clone baseline tailored resume or fallback object
  let base = {};
  if (window.lastResult && window.lastResult.tailored_resume) {
    try {
      base = JSON.parse(JSON.stringify(window.lastResult.tailored_resume));
    } catch (_) {
      base = {};
    }
  }

  // 1. Candidate Name & Target Role
  const nameEl = doc.querySelector('.candidate-name[data-edit="name"]') || doc.querySelector(".candidate-name");
  if (nameEl && nameEl.innerText.trim()) {
    base.name = nameEl.innerText.trim();
  }

  const roleEl = doc.querySelector('.target-role[data-edit="target_role"]') || doc.querySelector(".target-role");
  if (roleEl && roleEl.innerText.trim()) {
    base.target_role = roleEl.innerText.trim();
  }

  // 1b. Contact Information
  const contactLines = doc.querySelectorAll('.contact-line');
  if (contactLines && contactLines.length > 0) {
    const contactObj = Object.assign({}, base.contact || {});
    contactLines.forEach(cl => {
      const mailto = cl.querySelector('a[href^="mailto:"]');
      if (mailto && mailto.innerText.trim()) contactObj.email = mailto.innerText.trim();
      cl.querySelectorAll('a').forEach(a => {
        const href = (a.getAttribute('href') || '').toLowerCase();
        const text = a.innerText.trim();
        if (href.includes('linkedin.com') || text.includes('linkedin.com')) contactObj.linkedin = text;
        else if (href.includes('github.com') || text.includes('github.com')) contactObj.github = text;
      });
      const parts = cl.innerText.split('|').map(s => s.trim()).filter(Boolean);
      parts.forEach(p => {
        if (/[\+]?\d[\d\s\-()]{7,}\d/.test(p)) contactObj.phone = p;
        else if (p.includes('@') && !contactObj.email) contactObj.email = p;
        else if (!p.includes('linkedin') && !p.includes('github') && !p.includes('http') && p.length > 2 && p.length < 50) {
          if (!contactObj.location) contactObj.location = p;
        }
      });
    });
    if (Object.keys(contactObj).length > 0) {
      base.contact = contactObj;
    }
  }

  // 2. Section Headings
  const headings = {};
  doc.querySelectorAll('.section-title').forEach(el => {
    const text = el.innerText.trim();
    const sec = el.getAttribute('data-section');
    if (sec && text) {
      headings[sec] = text;
    } else if (text) {
      const low = text.toLowerCase();
      if (low.includes("summary") || low.includes("profile")) headings.summary = text;
      else if (low.includes("skill") || low.includes("competenc") || low.includes("technolog")) headings.skills = text;
      else if (low.includes("experience") || low.includes("employment") || low.includes("work")) headings.experience = text;
      else if (low.includes("education") || low.includes("academic")) headings.education = text;
      else if (low.includes("project")) headings.projects = text;
      else if (low.includes("certif")) headings.certifications = text;
    }
  });
  if (Object.keys(headings).length > 0) {
    base.section_headings = Object.assign(base.section_headings || {}, headings);
  }

  // 3. Professional Summary
  const summaryEl = doc.querySelector('.summary-text[data-edit="summary"]') || doc.querySelector(".summary-text");
  if (summaryEl) {
    base.summary = summaryEl.innerText.trim();
  }

  // 4. Technical Skills
  const catEls = doc.querySelectorAll(".skill-category");
  if (catEls && catEls.length > 0) {
    const skillsList = [];
    catEls.forEach(catEl => {
      const listEl = catEl.querySelector('.skill-category-list[data-edit="skills-list"]') || catEl.querySelector(".skill-category-list");
      let rawText = listEl ? listEl.innerText : catEl.innerText;
      rawText = rawText.replace(/^[^:]+:\s*/, "");
      const parsed = parseKeywordsList(rawText);
      parsed.forEach(k => {
        if (!skillsList.map(s => s.toLowerCase()).includes(k.toLowerCase())) {
          skillsList.push(k);
        }
      });
    });
    if (skillsList.length > 0) {
      base.skills = skillsList;
    }
  }

  // 5. Experience Roles & Bullets
  const expEntries = doc.querySelectorAll('.entry-item.exp-item, .entry-item');
  const extractedExp = [];

  expEntries.forEach(entry => {
    const bulletsList = entry.querySelectorAll('.bullet-item[data-edit="bullet"], .bullet-item, li');
    const titleEl = entry.querySelector('.role-title, .two-col-left');
    const datesEl = entry.querySelector('.role-dates, .two-col-right');
    const compEl = entry.querySelector('.role-company, .sub-left');
    const locEl = entry.querySelector('.role-location, .sub-right');

    if (bulletsList.length > 0 && titleEl) {
      const expItem = {};
      if (titleEl) expItem.title = titleEl.innerText.trim();
      if (datesEl) expItem.dates = datesEl.innerText.trim();
      if (compEl) expItem.company = compEl.innerText.trim();
      if (locEl) expItem.location = locEl.innerText.trim();

      const bullets = [];
      bulletsList.forEach(li => {
        const text = li.innerText.trim();
        if (text.length > 2) {
          bullets.push(text);
        }
      });
      expItem.bullets = bullets;
      extractedExp.push(expItem);
    }
  });

  // Fallback for docx_to_html layouts without .entry-item wrapper
  if (extractedExp.length === 0) {
    let inExpSection = false;
    let currentItem = null;
    const sheet = doc.querySelector('.resume-sheet') || doc.body;

    Array.from(sheet.children).forEach(el => {
      if (el.classList.contains('section-title')) {
        const titleText = (el.innerText || '').toLowerCase();
        if (titleText.includes('experience') || titleText.includes('employment') || titleText.includes('work')) {
          inExpSection = true;
        } else {
          if (inExpSection && currentItem && currentItem.title) {
            extractedExp.push(currentItem);
            currentItem = null;
          }
          inExpSection = false;
        }
        return;
      }

      if (!inExpSection) return;

      if (el.classList.contains('two-col-line')) {
        const tEl = el.querySelector('.two-col-left');
        const dEl = el.querySelector('.two-col-right');
        if (tEl && tEl.innerText.trim()) {
          if (currentItem && currentItem.title) extractedExp.push(currentItem);
          currentItem = {
            title: tEl.innerText.trim(),
            dates: dEl ? dEl.innerText.trim() : "",
            company: "",
            location: "",
            bullets: []
          };
        }
      } else if (el.classList.contains('sub-line') && currentItem) {
        const cEl = el.querySelector('.sub-left');
        const lEl = el.querySelector('.sub-right');
        if (cEl && cEl.innerText.trim()) currentItem.company = cEl.innerText.trim();
        if (lEl && lEl.innerText.trim()) currentItem.location = lEl.innerText.trim();
      } else if (el.classList.contains('bullet-list') && currentItem) {
        el.querySelectorAll('li').forEach(li => {
          const bText = li.innerText.trim();
          if (bText.length > 2) currentItem.bullets.push(bText);
        });
      }
    });
    if (currentItem && currentItem.title) extractedExp.push(currentItem);
  }

  if (extractedExp.length > 0) {
    base.experience = extractedExp;
  }

  return base;
}

async function savePreviewEdits(optionalInstruction = "") {
  const saveBtn = document.getElementById("preview-save-btn");
  const spinner = document.getElementById("preview-save-spinner");
  const icon = document.getElementById("preview-save-icon");
  const label = document.getElementById("preview-save-label");
  const statusPill = document.getElementById("preview-status-pill");

  const updatedResume = extractResumeFromPreviewDoc();
  if (!updatedResume) {
    showToast("Could not access document content to save", "warning");
    return false;
  }

  if (saveBtn) saveBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (icon) icon.style.display = "none";
  if (label) label.textContent = "Saving...";
  if (statusPill) {
    statusPill.innerHTML = `<span class="spinner-small" style="display:inline-block; vertical-align:middle; margin-right:4px;"></span> <span>Saving changes...</span>`;
  }

  try {
    const state = window._previewEditState;
    const res = await fetch("/api/save-preview-edits", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        relative_path: state.filePath,
        updated_resume: updatedResume,
        instruction: optionalInstruction,
        company: state.company,
        role: state.role,
        jd_text: (window.lastResult && window.lastResult.jd_text) ? window.lastResult.jd_text : (window.analyzeJdText || "")
      })
    });

    const data = await res.json();
    if (data.success) {
      state.hasUnsaved = false;

      // Update baseline tailored resume in client memory
      if (data.updated_resume) {
        if (!window.lastResult) window.lastResult = {};
        window.lastResult.tailored_resume = data.updated_resume;
        if (data.relative_path) window.lastResult.relative_path = data.relative_path;
        if (data.relative_pdf) window.lastResult.relative_pdf = data.relative_pdf;
      }

      // Update download buttons
      const cacheBuster = `?t=${Date.now()}`;
      const pdfBtn = document.getElementById("preview-download-pdf-btn");
      const docxBtn = document.getElementById("preview-download-docx-btn");
      const extBtn = document.getElementById("preview-external-btn");

      if (data.relative_pdf && pdfBtn) {
        pdfBtn.href = `/api/download/${encodeURIComponent(data.relative_pdf).replace(/%2F/g, '/')}${cacheBuster}`;
      }
      if (data.relative_path && docxBtn) {
        docxBtn.href = `/api/download/${encodeURIComponent(data.relative_path).replace(/%2F/g, '/')}${cacheBuster}`;
      }
      if (data.relative_path && extBtn) {
        extBtn.href = `/api/preview/${encodeURIComponent(data.relative_path).replace(/%2F/g, '/')}${cacheBuster}`;
      }

      const badge = document.getElementById("preview-unsaved-badge");
      if (badge) badge.style.display = "none";

      const discardBtn = document.getElementById("preview-discard-btn");
      if (discardBtn) discardBtn.style.display = "none";

      if (statusPill) {
        statusPill.innerHTML = `<i class="fa-solid fa-circle-check text-emerald" style="color:#10b981;"></i> <span style="color:#10b981;">Changes saved</span>`;
      }

      showToast("Changes saved successfully!", "success");

      // Reload frame to show visual updates
      const frame = document.getElementById("resume-preview-frame");
      if (frame) {
        const loader = document.getElementById("preview-loader");
        if (loader) loader.style.display = "flex";
        const currentUrl = new URL(frame.src, window.location.origin);
        currentUrl.searchParams.set("t", Date.now());
        frame.src = currentUrl.toString();
      }
      window._lastSaveError = "";
      return true;
    } else {
      const errMsg = data.error || "Failed to save edits";
      window._lastSaveError = errMsg;
      showToast(errMsg, "error");
      if (statusPill) {
        statusPill.innerHTML = `<i class="fa-solid fa-circle-exclamation text-rose" style="color:#ef4444;"></i> <span style="color:#ef4444;">Save failed</span>`;
      }
      return false;
    }
  } catch (err) {
    const errMsg = "Network error while saving edits: " + err.message;
    window._lastSaveError = errMsg;
    showToast(errMsg, "error");
    if (statusPill) {
      statusPill.innerHTML = `<i class="fa-solid fa-circle-exclamation text-rose" style="color:#ef4444;"></i> <span style="color:#ef4444;">Network error</span>`;
    }
    return false;
  } finally {
    if (saveBtn) saveBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (icon) icon.style.display = "inline-block";
    if (label) label.textContent = "Save";
  }
}

async function applyPreviewAiInstruction() {
  const input = document.getElementById("preview-ai-instruction-input");
  const instruction = input ? input.value.trim() : "";
  if (!instruction) {
    showToast("Please paste or type recommendations or instructions for the AI", "info");
    if (input) input.focus();
    return;
  }

  const applyBtn = document.getElementById("preview-ai-apply-btn");
  const spinner = document.getElementById("preview-ai-apply-spinner");
  const icon = document.getElementById("preview-ai-apply-icon");
  const label = document.getElementById("preview-ai-apply-label");
  const statusBox = document.getElementById("preview-ai-status-box");
  const statusContent = document.getElementById("preview-ai-status-content");

  // Keep sidebar OPEN so user sees active progress!
  togglePreviewAiDrawer(true);

  if (applyBtn) applyBtn.disabled = true;
  if (spinner) spinner.style.display = "inline-block";
  if (icon) icon.style.display = "none";
  if (label) label.textContent = "Polishing & Rebuilding...";

  if (statusBox && statusContent) {
    statusBox.style.display = "block";
    statusBox.style.background = "rgba(245, 158, 11, 0.12)";
    statusBox.style.borderColor = "rgba(245, 158, 11, 0.35)";
    statusBox.style.color = "#fbbf24";
    statusContent.innerHTML = `<span class="spinner-small" style="display:inline-block; vertical-align:middle; margin-right:6px;"></span> <span>AI is analyzing &amp; rewriting your resume...</span>`;
  }

  try {
    const success = await savePreviewEdits(instruction);
    if (success) {
      if (statusBox && statusContent) {
        statusBox.style.background = "rgba(16, 185, 129, 0.12)";
        statusBox.style.borderColor = "rgba(16, 185, 129, 0.35)";
        statusBox.style.color = "#34d399";
        statusContent.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Polish applied successfully! Document rebuilt.</span>`;
      }
    } else {
      const errMsg = window._lastSaveError || "Could not apply polish. Check connection or reload.";
      if (statusBox && statusContent) {
        statusBox.style.background = "rgba(239, 68, 68, 0.12)";
        statusBox.style.borderColor = "rgba(239, 68, 68, 0.35)";
        statusBox.style.color = "#f87171";
        statusContent.innerHTML = `<i class="fa-solid fa-triangle-exclamation"></i> <span>${escapeHtml(errMsg)}</span>`;
      }
    }
  } catch (err) {
    if (statusBox && statusContent) {
      statusBox.style.background = "rgba(239, 68, 68, 0.12)";
      statusBox.style.borderColor = "rgba(239, 68, 68, 0.35)";
      statusBox.style.color = "#f87171";
      statusContent.innerHTML = `<i class="fa-solid fa-circle-exclamation"></i> <span>Error: ${escapeHtml(err.message)}</span>`;
    }
  } finally {
    if (applyBtn) applyBtn.disabled = false;
    if (spinner) spinner.style.display = "none";
    if (icon) icon.style.display = "inline-block";
    if (label) label.textContent = "Polish & Rebuild Document";
  }
}

function discardPreviewEdits() {
  const state = window._previewEditState;
  const frame = document.getElementById("resume-preview-frame");
  if (!frame) return;

  const currentUrl = new URL(frame.src, window.location.origin);
  currentUrl.searchParams.set("t", Date.now());
  frame.src = currentUrl.toString();

  state.hasUnsaved = false;
  const badge = document.getElementById("preview-unsaved-badge");
  if (badge) badge.style.display = "none";
  const discardBtn = document.getElementById("preview-discard-btn");
  if (discardBtn) discardBtn.style.display = "none";
  const statusPill = document.getElementById("preview-status-pill");
  if (statusPill) {
    statusPill.innerHTML = `<i class="fa-solid fa-rotate-left"></i> <span>Changes discarded</span>`;
    setTimeout(() => {
      statusPill.innerHTML = `<i class="fa-solid fa-circle-check"></i> <span>Ready to edit</span>`;
    }, 2000);
  }
  showToast("Reverted edits back to saved document.", "info");
}

function openPreviewModal(filePath, company = "Tailored Resume", role = "Document Preview") {
  if (!filePath) {
    showToast("No resume document file available for preview", "warning");
    return;
  }
  const modal = document.getElementById("resume-preview-modal");
  const frame = document.getElementById("resume-preview-frame");
  const loader = document.getElementById("preview-loader");
  const title = document.getElementById("preview-modal-title");
  const subtitle = document.getElementById("preview-modal-subtitle");
  const pdfBtn = document.getElementById("preview-download-pdf-btn");
  const docxBtn = document.getElementById("preview-download-docx-btn");
  const extBtn = document.getElementById("preview-external-btn");

  if (!modal || !frame) return;

  if (title) title.textContent = company || "Resume Document";
  if (subtitle) subtitle.textContent = role ? `${role} · Live PDF/Paper Editor` : "Live PDF/Paper Editor";

  // Normalize path
  let cleanPath = (filePath || '').replace(/\\/g, '/');
  window._previewEditState.filePath = cleanPath;
  window._previewEditState.company = company || "";
  window._previewEditState.role = role || "";
  window._previewEditState.hasUnsaved = false;

  // Reset UI status
  const badge = document.getElementById("preview-unsaved-badge");
  if (badge) badge.style.display = "none";
  const discardBtn = document.getElementById("preview-discard-btn");
  if (discardBtn) discardBtn.style.display = "none";
  const saveBtn = document.getElementById("preview-save-btn");
  if (saveBtn) saveBtn.style.display = "inline-flex";
  const aiBtn = document.getElementById("preview-ai-polish-btn");
  if (aiBtn) aiBtn.style.display = "inline-flex";
  const editorBar = document.getElementById("preview-editor-bar");
  if (editorBar) editorBar.style.display = window._previewEditState.active ? "flex" : "none";
  const statusPill = document.getElementById("preview-status-pill");
  if (statusPill) {
    statusPill.innerHTML = `<i class="fa-solid fa-circle-check text-emerald" style="color:#10b981;"></i> <span>Ready to edit</span>`;
  }

  const cacheBuster = `?t=${Date.now()}`;
  const previewUrl = `/api/preview/${encodeURIComponent(cleanPath).replace(/%2F/g, '/')}${cacheBuster}`;
  const pdfDownloadUrl = `/api/download/${encodeURIComponent(cleanPath.replace(/\.(docx|pdf|json)$/i, '.pdf')).replace(/%2F/g, '/')}${cacheBuster}`;
  const docxDownloadUrl = `/api/download/${encodeURIComponent(cleanPath.replace(/\.(docx|pdf|json)$/i, '.docx')).replace(/%2F/g, '/')}${cacheBuster}`;

  if (pdfBtn) pdfBtn.href = pdfDownloadUrl;
  if (docxBtn) docxBtn.href = docxDownloadUrl;
  if (extBtn) extBtn.href = previewUrl;

  if (loader) {
    loader.style.display = "flex";
    if (window._previewLoaderTimeout) clearTimeout(window._previewLoaderTimeout);
    window._previewLoaderTimeout = setTimeout(() => {
      hidePreviewLoader();
    }, 3500);
  }

  frame.onload = function() {
    hidePreviewLoader();
    try {
      if (frame.contentWindow && typeof frame.contentWindow.enableEditor === "function") {
        frame.contentWindow.enableEditor(window._previewEditState.active);
      }
    } catch (_) {}
  };
  frame.onerror = hidePreviewLoader;
  frame.src = previewUrl;

  // Reset AI Polish sidebar
  togglePreviewAiDrawer(false);
  const statusBox = document.getElementById("preview-ai-status-box");
  if (statusBox) statusBox.style.display = "none";

  modal.style.display = "flex";
  document.body.style.overflow = "hidden";
}

function closePreviewModal() {
  const modal = document.getElementById("resume-preview-modal");
  const frame = document.getElementById("resume-preview-frame");
  hidePreviewLoader();
  togglePreviewAiDrawer(false);
  if (modal) modal.style.display = "none";
  if (frame) frame.src = "about:blank";
  document.body.style.overflow = "";
}

function previewCurrentResume() {
  if (!window.lastResult || !window.lastResult.relative_path) {
    showToast("Please run an application first or select an item from History to preview", "warning");
    return;
  }
  const company = window.lastResult.company || "Tailored Resume";
  const role = window.lastResult.role || "Document Preview";
  openPreviewModal(window.lastResult.relative_path, company, role);
}

function previewMasterResume() {
  openPreviewModal("master_resume", "Master Resume Profile", "Authentic Candidate Base Profile");
}

// Close preview or password modal or compass or system dialog on ESC, Save preview edits on Ctrl+S, Open Compass on Ctrl+G
document.addEventListener("keydown", (e) => {
  // Handle Bespoke System Confirm Modal with Enter / Escape
  const sysModal = document.getElementById("system-confirm-modal");
  if (sysModal && sysModal.style.display === "flex") {
    if (e.key === "Escape") {
      e.preventDefault();
      closeSystemConfirm(false);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      if (document.activeElement && document.activeElement.id === "system-dialog-cancel-btn") {
        closeSystemConfirm(false);
      } else {
        closeSystemConfirm(true);
      }
      return;
    }
  }

  // If Quick Scroll Compass is open
  if (typeof _scrollCompassState !== "undefined" && _scrollCompassState.isOpen) {
    if (e.key === "Escape") {
      e.preventDefault();
      closeScrollCompass(true);
      return;
    }
    const num = parseInt(e.key, 10);
    if (!isNaN(num) && num >= 1 && num <= _scrollCompassState.activeItems.length) {
      e.preventDefault();
      triggerCompassItemIndex(num - 1);
      return;
    }
  }

  // Ctrl+G / Cmd+G to open Quick Navigator manually (STRICT: Only after new resume has been created)
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "g" && !e.shiftKey) {
    const activeEl = document.activeElement;
    const isTyping = activeEl && (activeEl.tagName === "INPUT" || activeEl.tagName === "TEXTAREA" || activeEl.isContentEditable);
    if (!isTyping && !isAnyModalOpen() && typeof isNewResumeReady === "function" && isNewResumeReady()) {
      e.preventDefault();
      if (_scrollCompassState && _scrollCompassState.isOpen) {
        closeScrollCompass(true);
      } else {
        openScrollCompass(window._lastMouseX, window._lastMouseY);
      }
      return;
    }
  }

  if (e.key === "Escape") {
    // If in history with active selections, Escape deselects all
    if (typeof selectedHistoryFiles !== "undefined" && selectedHistoryFiles.size > 0) {
      const activeTab = document.querySelector(".nav-tab.active");
      if (activeTab && activeTab.dataset.tab === "history") {
        deselectAllHistory();
        return;
      }
    }

    const pModal = document.getElementById("resume-preview-modal");
    if (pModal && pModal.style.display === "flex") {
      closePreviewModal();
    }
    const pwModal = document.getElementById("change-password-modal");
    if (pwModal && pwModal.style.display === "flex") {
      closePasswordModal();
    }
  } else if ((e.ctrlKey || e.metaKey) && e.key === "s") {
    const pModal = document.getElementById("resume-preview-modal");
    if (pModal && pModal.style.display === "flex") {
      e.preventDefault();
      savePreviewEdits();
    }
  }
});

/* ==========================================================================
   HollaBuddy AI Career Copilot & Interview Wingman Controller
   ========================================================================== */
let hollabuddyChatHistory = [];
let hollabuddyActiveJob = null;

function toggleHollaBuddy(forceOpen, evt) {
  if (evt && typeof evt.stopPropagation === "function") {
    evt.stopPropagation();
  }
  const drawer = document.getElementById("hollabuddy-drawer");
  const launcher = document.getElementById("hollabuddy-companion") || document.getElementById("hollabuddy-launcher");
  if (!drawer) return;

  const isOpen = !drawer.classList.contains("hidden");
  const shouldOpen = forceOpen !== undefined ? forceOpen : !isOpen;

  if (shouldOpen) {
    drawer.classList.remove("hidden");
    if (launcher) launcher.classList.add("active");
    setTimeout(() => {
      const input = document.getElementById("hollabuddy-input");
      if (input) input.focus();
    }, 150);
    updateHollaBuddyJobContext();
    // Auto-check API health each time the drawer opens
    checkHollaBuddyApiHealth();
  } else {
    drawer.classList.add("hidden");
    if (launcher) launcher.classList.remove("active");
  }
}

/**
 * Live-ping /api/gemini/health and render a per-key status bar
 * inside the HollaBuddy drawer header.
 */
async function checkHollaBuddyApiHealth() {
  const bar    = document.getElementById("hollabuddy-api-health-bar");
  const keysEl = document.getElementById("hb-health-keys");
  const icon   = document.getElementById("hollabuddy-health-icon");

  if (!bar || !keysEl) return;

  // Show bar with spinner
  bar.classList.remove("hidden");
  keysEl.innerHTML = `<span class="hb-health-checking"><i class="fa-solid fa-spinner fa-spin"></i> Checking…</span>`;
  if (icon) { icon.className = "fa-solid fa-spinner fa-spin"; }

  try {
    const res = await fetch("/api/gemini/health");
    if (!res.ok || res.redirected) {
      if (res.status === 401 || res.status === 403 || res.redirected) {
        keysEl.innerHTML = `<span class="hb-health-none" style="font-size:0.75rem;"><i class="fa-solid fa-lock" style="opacity:.6"></i> Please log in</span>`;
        return;
      }
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();

    const statusColor = {
      ok:              "#22c55e",
      quota_exhausted: "#f59e0b",
      transient:       "#f59e0b",   // 503 server busy = amber, NOT a key error
      invalid:         "#ef4444",
      error:           "#ef4444",
      unconfigured:    "#64748b",
    };
    const statusIcon = {
      ok:              "fa-check-circle",
      quota_exhausted: "fa-triangle-exclamation",
      transient:       "fa-clock",             // amber clock = temporarily unavailable
      invalid:         "fa-xmark-circle",
      error:           "fa-xmark-circle",
      unconfigured:    "fa-circle-dashed",
    };
    // Friendly tooltip explaining what each status means
    const statusTip = {
      ok:              "Key is active and responding normally",
      quota_exhausted: "This key has hit its free-tier rate limit — wait a minute or add another key",
      transient:       "Gemini's servers were momentarily busy — your key is correctly configured and will work fine",
      invalid:         "This key is invalid or was revoked — re-copy it from aistudio.google.com",
      error:           "Unexpected error — try refreshing",
      unconfigured:    "No key configured",
    };

    if (!data.keys || data.keys.length === 0) {
      keysEl.innerHTML = `<span class="hb-health-none"><i class="fa-solid fa-key" style="opacity:.4"></i> No keys configured</span>`;
      if (icon) icon.className = "fa-solid fa-signal" + " hb-icon-red";
      return;
    }

    keysEl.innerHTML = data.keys.map((k, i) => {
      const isActive = i === data.active_index;
      const col  = statusColor[k.status]  || "#64748b";
      const ico  = statusIcon[k.status]   || "fa-circle";
      const tip  = statusTip[k.status]    || k.label || "";
      const name = k.name || (k.env === "GEMINI_API_KEY" ? "Key 1" : k.env === "GEMINI_API_KEY_2" ? "Key 2" : `Key ${i+1}`);
      const activeBadge = isActive ? `<span class="hb-active-badge">ACTIVE</span>` : "";
      return `
        <span class="hb-key-pill" style="--key-col:${col}" title="${tip}">
          <i class="fa-solid ${ico}" style="color:${col};font-size:.7rem;"></i>
          <span class="hb-key-name">${name}</span>
          <span class="hb-key-masked">${k.masked}</span>
          ${activeBadge}
          <span class="hb-key-status-label">${k.label}</span>
        </span>`;
    }).join("");


    // Update the header signal icon
    if (icon) {
      if (data.ok) {
        icon.className = "fa-solid fa-signal hb-icon-green";
        icon.title = "API Keys OK";
      } else {
        icon.className = "fa-solid fa-triangle-exclamation hb-icon-amber";
        icon.title = "API Key issue — click to check";
      }
    }
  } catch (err) {
    keysEl.innerHTML = `<span class="hb-health-checking" style="color:#ef4444"><i class="fa-solid fa-xmark"></i> Health check failed</span>`;
    if (icon) icon.className = "fa-solid fa-signal hb-icon-red";
    console.warn("[HollaBuddy Health]", err);
  }
}


/* ==========================================================================
   HollaBuddy Living Interactive Companion (Lottie, Thrust Drag & Physics)
   ========================================================================== */
function initInteractiveHollaBuddy() {
  const container = document.getElementById("hollabuddy-companion");
  const canvas = document.getElementById("hollabuddy-lottie-canvas");
  const stage = document.getElementById("hb-stage");
  const flame = document.getElementById("hb-rocket-flame");
  const hotspotL = document.getElementById("hotspot-hand-l");
  const hotspotR = document.getElementById("hotspot-hand-r");
  const hotspotBody = document.getElementById("hotspot-body");
  const speech = document.getElementById("hb-speech-bubble");

  if (!container || !canvas || !stage || !flame) return;
  if (typeof lottie === "undefined") {
    console.warn("[HollaBuddy] Lottie library not loaded yet, retrying in 300ms...");
    setTimeout(initInteractiveHollaBuddy, 300);
    return;
  }

  // 1. Initialize Lottie Animation (Preserve all internal layers intact)
  let botAnim = null;
  const lottieConfig = {
    container: canvas,
    renderer: "svg",
    loop: true,
    autoplay: true,
    path: "/static/hollabuddy-bot.json",
  };

  try {
    botAnim = lottie.loadAnimation(lottieConfig);
  } catch (err) {
    console.warn("[HollaBuddy] Local Lottie load error, trying fallback remote URL...", err);
    lottieConfig.path = "https://lottie.host/a0a3e050-db0c-44be-bc89-1b6145620772/bbPYTuDKgM.json";
    botAnim = lottie.loadAnimation(lottieConfig);
  }

  // 2. Position Restoration & Viewport Clamping
  const defaultW = 168;
  const defaultH = 134;
  let posX = window.innerWidth - defaultW - 28;
  let posY = window.innerHeight - defaultH - 24;
  try {
    const saved = JSON.parse(localStorage.getItem("hollabuddy_pos"));
    if (saved && typeof saved.x === "number" && typeof saved.y === "number") {
      posX = Math.max(10, Math.min(window.innerWidth - defaultW - 10, saved.x));
      posY = Math.max(10, Math.min(window.innerHeight - defaultH - 10, saved.y));
    }
  } catch (e) {}

  container.style.left = posX + "px";
  container.style.top = posY + "px";

  // Re-clamp on window resize
  window.addEventListener("resize", () => {
    const curX = container.offsetLeft;
    const curY = container.offsetTop;
    const clampedX = Math.max(10, Math.min(window.innerWidth - container.offsetWidth - 10, curX));
    const clampedY = Math.max(10, Math.min(window.innerHeight - container.offsetHeight - 10, curY));
    container.style.left = clampedX + "px";
    container.style.top = clampedY + "px";
  });

  // 3. Natural 3D Head & Body Cursor Tracking (tilts whole character toward cursor without tampering with SVG eyes)
  window.addEventListener("mousemove", (e) => {
    if (isDragging || isGiggling) return;

    const rect = container.getBoundingClientRect();
    const botCenterX = rect.left + rect.width * 0.5;
    const botCenterY = rect.top + rect.height * 0.45;

    const normX = (e.clientX - botCenterX) / (window.innerWidth / 2);
    const normY = (e.clientY - botCenterY) / (window.innerHeight / 2);

    const tiltY = Math.max(-8, Math.min(8, normX * 8));
    const tiltX = Math.max(-6, Math.min(6, -normY * 6));

    if (!stage.classList.contains("giggle-wiggle") && !stage.classList.contains("landing-bounce") && !stage.classList.contains("hand-wave-perk")) {
      stage.style.transform = `perspective(500px) rotateY(${tiltY}deg) rotateX(${tiltX}deg)`;
    }
  });

  // 4. Draggable with Rocket Flame & Physics
  let isDragging = false;
  let hasMoved = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let initBotX = 0;
  let initBotY = 0;
  let lastX = 0;
  let lastY = 0;
  let lastTime = 0;
  let flameAngle = 0;

  function startDrag(clientX, clientY) {
    isDragging = true;
    hasMoved = false;
    dragStartX = clientX;
    dragStartY = clientY;
    initBotX = container.offsetLeft;
    initBotY = container.offsetTop;
    lastX = clientX;
    lastY = clientY;
    lastTime = performance.now();

    stage.classList.remove("idle-float", "landing-bounce", "hand-wave-perk");
    container.classList.add("is-dragging");
  }

  function onDragMove(clientX, clientY) {
    if (!isDragging) return;
    const dist = Math.hypot(clientX - dragStartX, clientY - dragStartY);
    if (dist > 5) hasMoved = true;

    if (!hasMoved) return;

    const dx = clientX - dragStartX;
    const dy = clientY - dragStartY;

    let newX = initBotX + dx;
    let newY = initBotY + dy;

    // Viewport clamp
    newX = Math.max(10, Math.min(window.innerWidth - container.offsetWidth - 10, newX));
    newY = Math.max(10, Math.min(window.innerHeight - container.offsetHeight - 10, newY));

    container.style.left = newX + "px";
    container.style.top = newY + "px";

    // Rocket flame physics & dynamic tilt
    const now = performance.now();
    const dt = Math.max(1, now - lastTime);
    const vx = (clientX - lastX) / dt;
    const vy = (clientY - lastY) / dt;
    const speed = Math.hypot(vx, vy);

    if (speed > 0.05) {
      // Flame points OPPOSITE to movement direction
      const moveAngle = (Math.atan2(vy, vx) * 180) / Math.PI;
      flameAngle = moveAngle - 90; // Default flame points straight down (90deg)
      flame.style.transform = `rotate(${flameAngle}deg)`;
      flame.classList.add("active");

      // Character body tilts into drag direction
      const tilt = Math.max(-14, Math.min(14, vx * 12));
      stage.style.transform = `rotate(${tilt}deg) scale(1.05)`;
    }

    lastX = clientX;
    lastY = clientY;
    lastTime = now;
  }

  function endDrag() {
    if (!isDragging) return;
    isDragging = false;
    container.classList.remove("is-dragging");
    flame.classList.remove("active");
    stage.style.transform = "";

    if (hasMoved) {
      // Landing bounce
      stage.classList.add("landing-bounce");
      setTimeout(() => {
        stage.classList.remove("landing-bounce");
        if (!isGiggling) stage.classList.add("idle-float");
      }, 600);

      // Save position
      try {
        localStorage.setItem("hollabuddy_pos", JSON.stringify({
          x: container.offsetLeft,
          y: container.offsetTop,
        }));
      } catch (e) {}
    } else {
      stage.classList.add("idle-float");
      // Click action: Toggle Drawer!
      toggleHollaBuddy();
      showSpeech("Ready to tailor & prep! 🚀", 1400);
    }
  }

  container.addEventListener("pointerdown", (e) => {
    if (e.target.closest(".hb-speech-bubble")) return;
    try {
      container.setPointerCapture(e.pointerId);
    } catch (err) {}
    startDrag(e.clientX, e.clientY);
  });

  window.addEventListener("pointermove", (e) => {
    onDragMove(e.clientX, e.clientY);
  });

  window.addEventListener("pointerup", () => {
    endDrag();
  });
  window.addEventListener("pointercancel", () => {
    endDrag();
  });

  // 5. Natural Hand Reactions & Cheerful Wave Bounce
  let waveTimer = null;
  function triggerHandReaction(isLeft) {
    if (isDragging) return;

    // Cheer up Lottie arm wave loop speed!
    if (botAnim && typeof botAnim.setSpeed === "function") {
      botAnim.setSpeed(1.6);
      clearTimeout(waveTimer);
      waveTimer = setTimeout(() => {
        if (!isGiggling && botAnim) botAnim.setSpeed(1.0);
      }, 900);
    }

    // Playful cheer bounce on character stage (hands remain anatomically connected to body!)
    stage.classList.remove("idle-float", "hand-wave-perk");
    void stage.offsetWidth;
    stage.classList.add("hand-wave-perk");
    setTimeout(() => {
      stage.classList.remove("hand-wave-perk");
      if (!isDragging && !isGiggling) stage.classList.add("idle-float");
    }, 650);

    const rect = (isLeft ? hotspotL : hotspotR).getBoundingClientRect();
    spawnParticles(["👋", "✨", "⭐", "💫"], rect.left + rect.width / 2, rect.top);
    showSpeech(isLeft ? "Hey friend! 👋" : "High five! Let's tailor! ⭐");
  }

  if (hotspotL) hotspotL.addEventListener("pointerenter", () => triggerHandReaction(true));
  if (hotspotR) hotspotR.addEventListener("pointerenter", () => triggerHandReaction(false));

  // 6. Realistic Belly Tickle Engine (Rapid scrubbing/direction reversals)
  let tickleMoves = [];
  let isGiggling = false;
  let giggleTimer = null;

  if (hotspotBody) {
    hotspotBody.addEventListener("pointermove", (e) => {
      if (isDragging || isGiggling) return;

      const now = performance.now();
      tickleMoves.push({ x: e.clientX, y: e.clientY, t: now });
      tickleMoves = tickleMoves.filter((m) => now - m.t < 600);

      // Require at least 5 movement points within 600ms
      if (tickleMoves.length >= 5) {
        let reversals = 0;
        let lastDx = 0;
        for (let i = 1; i < tickleMoves.length; i++) {
          const dx = tickleMoves[i].x - tickleMoves[i - 1].x;
          if (Math.abs(dx) > 3.5) {
            if (lastDx !== 0 && ((dx > 0 && lastDx < 0) || (dx < 0 && lastDx > 0))) {
              reversals++;
            }
            lastDx = dx;
          }
        }

        // At least 2 rapid back-and-forth direction reversals needed to count as a tickle
        if (reversals >= 2) {
          triggerTickleGiggle();
          tickleMoves = [];
        }
      }
    });
  }

  function triggerTickleGiggle() {
    if (isGiggling) return;
    isGiggling = true;

    // 1. Accelerate Lottie animation to high-energy excited laugh!
    if (botAnim && typeof botAnim.setSpeed === "function") {
      botAnim.setSpeed(2.0);
    }

    // 2. Playful laughter vibration with squash & stretch
    stage.classList.remove("idle-float", "hand-wave-perk");
    void stage.offsetWidth;
    stage.classList.add("giggle-wiggle");

    // 3. Spawn laughter emojis & sparkles from belly
    const rect = hotspotBody.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    spawnParticles(["😆", "✨", "💖", "🥰", "🤭"], cx, cy, 7);

    // 4. Playful speech bubble
    const gigglePhrases = [
      "Hahaha! Stop, that tickles! 😆",
      "Hehehe! Can't stop giggling! 🥰",
      "Tickle attack! Let's get back to work! 🚀"
    ];
    showSpeech(gigglePhrases[Math.floor(Math.random() * gigglePhrases.length)], 1800);

    // 5. Smooth recovery back to idle
    clearTimeout(giggleTimer);
    giggleTimer = setTimeout(() => {
      stage.classList.remove("giggle-wiggle");
      if (!isDragging) stage.classList.add("idle-float");
      if (botAnim && typeof botAnim.setSpeed === "function") {
        botAnim.setSpeed(1.0);
      }
      isGiggling = false;
    }, 1500);
  }

  // 7. Particle Spawner
  function spawnParticles(emojis, originX, originY, count = 4) {
    for (let i = 0; i < count; i++) {
      const p = document.createElement("span");
      p.className = "hb-particle";
      p.textContent = emojis[Math.floor(Math.random() * emojis.length)];
      p.style.left = originX + "px";
      p.style.top = originY + "px";

      const dx = (Math.random() - 0.5) * 60;
      const dy = -(25 + Math.random() * 45);
      p.style.setProperty("--p-dx", dx + "px");
      p.style.setProperty("--p-dy", dy + "px");

      document.body.appendChild(p);
      setTimeout(() => p.remove(), 900);
    }
  }

  // 8. Speech Bubble Controller
  let speechTimer = null;
  function showSpeech(text, duration = 1400) {
    if (!speech) return;
    speech.textContent = text;
    speech.classList.add("visible");
    clearTimeout(speechTimer);
    speechTimer = setTimeout(() => {
      speech.classList.remove("visible");
    }, duration);
  }
}

function updateHollaBuddyJobContext() {
  const badge = document.getElementById("hollabuddy-mode-badge");
  const sub = document.getElementById("hollabuddy-context-sub");

  let activeCo = analyzeCompany;
  let activeRo = analyzeRole;
  if (!activeCo && window.lastResult) {
    activeCo = window.lastResult.company;
    activeRo = window.lastResult.role;
  }

  if (activeCo && activeRo) {
    hollabuddyActiveJob = {
      company: activeCo,
      role: activeRo,
      url: document.getElementById("job-url-input") ? document.getElementById("job-url-input").value : "",
      jd_text: analyzeJdText || "",
    };
    if (badge) {
      badge.innerHTML = `<i class="fa-solid fa-crosshairs text-cyan"></i> Active Target: <strong>${escapeHtml(activeRo)}</strong> @ ${escapeHtml(activeCo)}`;
    }
    if (sub) {
      sub.innerHTML = `<i class="fa-solid fa-circle-check text-emerald"></i> Resume & ${escapeHtml(activeCo)} Context Connected`;
    }
  } else {
    hollabuddyActiveJob = null;
    if (badge) {
      badge.innerHTML = `<i class="fa-solid fa-briefcase text-cyan"></i> Standalone Career Copilot (Available Anytime)`;
    }
    if (sub) {
      sub.innerHTML = `<i class="fa-solid fa-bolt text-emerald"></i> Master Resume Connected · Instant Answers`;
    }
  }
}

function handleHollaBuddyKey(e) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    sendHollaBuddyMessage();
  }
}

function handleHollaBuddyInput(textarea) {
  if (!textarea) return;

  // Auto-resize dynamically between 42px and 220px
  if (!textarea.classList.contains("expanded")) {
    textarea.style.height = "auto";
    const newHeight = Math.min(Math.max(textarea.scrollHeight, 40), 220);
    textarea.style.height = newHeight + "px";
  }

  updateHollaBuddyMetaBar(textarea.value);
}

function handleHollaBuddyPaste(e) {
  const textarea = e.target;
  setTimeout(() => {
    handleHollaBuddyInput(textarea);
    // If pasted text is large, ensure comfortable viewing
    if (textarea.value.length > 80 || textarea.value.includes("\n")) {
      const meta = document.getElementById("hollabuddy-input-meta");
      if (meta) meta.classList.remove("hidden");
    }
  }, 10);
}

function updateHollaBuddyMetaBar(val) {
  const meta = document.getElementById("hollabuddy-input-meta");
  const charSpan = document.getElementById("hollabuddy-char-count");
  const wordSpan = document.getElementById("hollabuddy-word-count");
  if (!meta) return;

  const len = val.length;
  if (len > 0) {
    meta.classList.remove("hidden");
    const words = val.trim().split(/\s+/).filter(Boolean).length;
    if (charSpan) charSpan.textContent = `${len} character${len === 1 ? '' : 's'}`;
    if (wordSpan) wordSpan.textContent = `${words} word${words === 1 ? '' : 's'}`;
  } else {
    meta.classList.add("hidden");
  }
}

function clearHollaBuddyInputText() {
  const input = document.getElementById("hollabuddy-input");
  if (input) {
    input.value = "";
    input.classList.remove("expanded");
    input.style.height = "auto";
    input.focus();
  }
  const wrap = document.getElementById("hollabuddy-input-wrap");
  if (wrap) wrap.classList.remove("wrap-expanded");
  const icon = document.getElementById("hollabuddy-expand-icon");
  if (icon) icon.className = "fa-solid fa-up-right-and-down-left-from-center";
  updateHollaBuddyMetaBar("");
}

function toggleHollaBuddyInputExpand() {
  const textarea = document.getElementById("hollabuddy-input");
  const icon = document.getElementById("hollabuddy-expand-icon");
  const wrap = document.getElementById("hollabuddy-input-wrap");
  if (!textarea) return;

  const isExpanded = textarea.classList.toggle("expanded");
  if (wrap) wrap.classList.toggle("wrap-expanded", isExpanded);

  if (isExpanded) {
    textarea.style.height = "220px";
    if (icon) icon.className = "fa-solid fa-down-left-and-up-right-to-center";
    textarea.focus();
  } else {
    if (icon) icon.className = "fa-solid fa-up-right-and-down-left-from-center";
    handleHollaBuddyInput(textarea);
  }
}

function sendHollaBuddyPrompt(promptText) {
  const input = document.getElementById("hollabuddy-input");
  if (input) {
    input.value = promptText;
    handleHollaBuddyInput(input);
  }
  // Make sure drawer is open
  toggleHollaBuddy(true);
  sendHollaBuddyMessage();
}

async function sendHollaBuddyMessage() {
  const input = document.getElementById("hollabuddy-input");
  if (!input) return;
  const message = input.value.trim();
  if (!message) return;

  input.value = "";
  input.classList.remove("expanded");
  input.style.height = "auto";
  updateHollaBuddyMetaBar("");
  const wrap = document.getElementById("hollabuddy-input-wrap");
  if (wrap) wrap.classList.remove("wrap-expanded");
  const icon = document.getElementById("hollabuddy-expand-icon");
  if (icon) icon.className = "fa-solid fa-up-right-and-down-left-from-center";

  // Append user message
  appendHollaBuddyMessage("user", message);

  // Show typing indicator
  const typing = document.getElementById("hollabuddy-typing");
  const sendBtn = document.getElementById("hollabuddy-send-btn");
  if (typing) typing.classList.remove("hidden");
  if (sendBtn) sendBtn.disabled = true;

  scrollHollaBuddyToBottom();

  try {
    const payload = {
      message: message,
      history: hollabuddyChatHistory,
      company: hollabuddyActiveJob ? hollabuddyActiveJob.company : "",
      role: hollabuddyActiveJob ? hollabuddyActiveJob.role : "",
      url: hollabuddyActiveJob ? hollabuddyActiveJob.url : "",
      jd_text: hollabuddyActiveJob ? hollabuddyActiveJob.jd_text : "",
    };

    const res = await fetch("/api/hollabuddy/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "Failed to get reply from HollaBuddy");
    }

    hollabuddyChatHistory.push({ role: "user", content: message });
    hollabuddyChatHistory.push({ role: "assistant", content: data.reply });

    // Render with special quota-exhausted banner if needed
    if (data.error_code === "quota_exhausted") {
      appendHollaBuddyQuotaBanner(data.reply, data.keys_in_pool || 1, data.suggested_followups);
    } else {
      appendHollaBuddyMessage("assistant", data.reply, data.suggested_followups);
    }

  } catch (err) {
    console.error("[HollaBuddy Error]", err);
    const isQuota = /quota|rate.?limit|429|exhausted/i.test(err.message);
    if (isQuota) {
      appendHollaBuddyQuotaBanner(
        "⚠️ Your Gemini API key appears to have hit its quota limit. Please wait a moment or add a second key in **Settings**.",
        1,
        ["Open Settings", "Try again in a moment"]
      );
    } else {
      appendHollaBuddyMessage(
        "assistant",
        `⚠️ **Couldn't reach Gemini right now.** ${err.message}\n\nCheck your internet connection or try again in a moment.`
      );
    }
  } finally {
    if (typing) typing.classList.add("hidden");
    if (sendBtn) sendBtn.disabled = false;
    scrollHollaBuddyToBottom();
  }
}

/** Show a styled amber quota-exhausted warning card inside the HollaBuddy drawer */
function appendHollaBuddyQuotaBanner(replyMarkdown, keyCount, followups = []) {
  const container = document.getElementById("hollabuddy-messages");
  if (!container) return;

  const keyLabel = keyCount > 1
    ? `All <strong>${keyCount} API keys</strong> have hit their quota`
    : `Your <strong>Gemini API key</strong> has used up its credits`;

  const formattedBody = formatHollaBuddyMarkdown(replyMarkdown);

  let followupsHtml = "";
  if (followups && followups.length > 0) {
    followupsHtml = `
      <div class="hollabuddy-followups">
        ${followups.map(f => `<button type="button" class="hollabuddy-followup-chip" data-prompt="${escapeHtml(f)}">${escapeHtml(f)}</button>`).join("")}
      </div>`;
  }

  const banner = document.createElement("div");
  banner.className = "hollabuddy-msg hollabuddy-msg-bot";
  banner.innerHTML = `
    <div class="hollabuddy-msg-avatar" style="background:rgba(245,158,11,0.15);color:#f59e0b;">
      <i class="fa-solid fa-triangle-exclamation"></i>
    </div>
    <div class="hollabuddy-bubble hollabuddy-bubble-bot hollabuddy-quota-banner">
      <div class="hollabuddy-quota-header">
        <i class="fa-solid fa-key" style="color:#f59e0b;margin-right:6px;"></i>
        <strong>API Quota Limit Reached</strong>
      </div>
      <div class="hollabuddy-bubble-content" style="margin-top:8px;">${formattedBody}</div>
      <div class="hollabuddy-quota-actions">
        <a href="#" onclick="openSettingsTab();return false;" class="hb-quota-btn hb-quota-btn-primary">
          <i class="fa-solid fa-gear"></i> Open Settings
        </a>
        <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener" class="hb-quota-btn hb-quota-btn-secondary">
          <i class="fa-solid fa-arrow-up-right-from-square"></i> Get Free Key
        </a>
      </div>
      ${followupsHtml}
    </div>
  `;
  container.appendChild(banner);
  scrollHollaBuddyToBottom();
}

function appendHollaBuddyMessage(role, text, followups = []) {
  const container = document.getElementById("hollabuddy-messages");
  if (!container) return;

  const msgDiv = document.createElement("div");
  msgDiv.className = `hollabuddy-msg hollabuddy-msg-${role === "user" ? "user" : "bot"}`;

  if (role === "user") {
    msgDiv.innerHTML = `
      <div class="hollabuddy-bubble hollabuddy-bubble-user">
        <p>${escapeHtml(text)}</p>
      </div>
      <div class="hollabuddy-msg-avatar hollabuddy-user-avatar">
        <i class="fa-solid fa-user"></i>
      </div>
    `;
  } else {
    const formattedHtml = formatHollaBuddyMarkdown(text);

    let followupsHtml = "";
    if (followups && followups.length > 0) {
      followupsHtml = `
        <div class="hollabuddy-followups">
          ${followups.map(f => `<button type="button" class="hollabuddy-followup-chip" data-prompt="${escapeHtml(f)}">${escapeHtml(f)}</button>`).join("")}
        </div>
      `;
    }

    msgDiv.dataset.rawText = text;
    msgDiv.innerHTML = `
      <div class="hollabuddy-msg-avatar">
        <i class="fa-solid fa-robot"></i>
      </div>
      <div class="hollabuddy-bubble hollabuddy-bubble-bot">
        <div class="hollabuddy-bubble-content">${formattedHtml}</div>
        <div class="hollabuddy-bubble-actions">
          <button type="button" class="hollabuddy-humanize-btn" title="Refine with Dani's Human Voice engine to maximize burstiness and remove all AI tells">
            <i class="fa-solid fa-wand-magic-sparkles"></i> Humanize
          </button>
          <button type="button" class="hollabuddy-copy-btn" title="Copy answer to clipboard">
            <i class="fa-regular fa-copy"></i> Copy Answer
          </button>
        </div>
        ${followupsHtml}
      </div>
    `;

    // Attach click listeners cleanly via JS — eliminates double-box HTML injection bug
    const copyBtn = msgDiv.querySelector(".hollabuddy-copy-btn");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => copyHollaBuddyText(copyBtn, msgDiv.dataset.rawText || text));
    }

    const humanizeBtn = msgDiv.querySelector(".hollabuddy-humanize-btn");
    if (humanizeBtn) {
      humanizeBtn.addEventListener("click", () => humanizeHollaBuddyBubble(humanizeBtn, msgDiv));
    }

    msgDiv.querySelectorAll(".hollabuddy-followup-chip").forEach(chip => {
      chip.addEventListener("click", () => {
        const promptText = chip.getAttribute("data-prompt");
        if (promptText) sendHollaBuddyPrompt(promptText);
      });
    });
  }

  container.appendChild(msgDiv);
  scrollHollaBuddyToBottom();
}

function formatHollaBuddyMarkdown(text) {
  if (!text) return "";

  // 1. Extract code blocks first so inner content is completely preserved
  const codeBlocks = [];
  let processed = text.replace(/```([a-zA-Z0-9_-]*)\r?\n([\s\S]*?)```/g, (match, lang, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: (lang || "").trim(), code: (code || "").trim() });
    return `\n\n__HB_CODE_${idx}__\n\n`;
  });

  // Also catch code blocks without newline immediately after backticks
  processed = processed.replace(/```([\s\S]*?)```/g, (match, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push({ lang: "", code: (code || "").trim() });
    return `\n\n__HB_CODE_${idx}__\n\n`;
  });

  let html = escapeHtml(processed);

  // 2. Bold and Italic
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');

  // 3. Inline code
  html = html.replace(/`([^`\n]+)`/g, '<code class="hollabuddy-inline-code">$1</code>');

  // 4. Headings: ###, ##, #
  html = html.replace(/^###\s+(.+)$/gm, '<h4 class="hollabuddy-heading">$1</h4>');
  html = html.replace(/^##\s+(.+)$/gm, '<h3 class="hollabuddy-heading">$1</h3>');
  html = html.replace(/^#\s+(.+)$/gm, '<h2 class="hollabuddy-heading">$1</h2>');

  // 5. Parse Markdown Tables (| Col 1 | Col 2 |)
  html = html.replace(/((?:^\|[^\r\n]+\|\r?\n)+)/gm, (tableText) => {
    const lines = tableText.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return tableText;

    let divIdx = -1;
    for (let i = 0; i < lines.length; i++) {
      if (/^\|[\s\-:|]+\|$/.test(lines[i])) {
        divIdx = i;
        break;
      }
    }
    if (divIdx === -1) return tableText;

    const parseCells = (line, tag) => {
      const raw = line.split("|").slice(1, -1);
      return `<tr>${raw.map(c => `<${tag}>${c.trim()}</${tag}>`).join("")}</tr>`;
    };

    const thead = `<thead>${lines.slice(0, divIdx).map(l => parseCells(l, "th")).join("")}</thead>`;
    const tbody = `<tbody>${lines.slice(divIdx + 1).map(l => parseCells(l, "td")).join("")}</tbody>`;

    return `\n\n<div class="hollabuddy-table-wrap"><table class="hollabuddy-table">${thead}${tbody}</table></div>\n\n`;
  });

  // 6. Blockquotes (> lines)
  html = html.replace(/((?:^&gt;\s?[^\r\n]+\r?\n?)+)/gm, (quoteText) => {
    const cleanLines = quoteText.split(/\r?\n/)
      .map(l => l.replace(/^&gt;\s?/, '').trim())
      .filter(Boolean);
    return `\n\n<blockquote class="hollabuddy-quote"><p>${cleanLines.join('</p><p>')}</p></blockquote>\n\n`;
  });

  // 7. Bullet lists (- item, * item, • item)
  html = html.replace(/((?:^\s*[-•*]\s+[^\r\n]+\r?\n?)+)/gm, (listText) => {
    const items = listText.split(/\r?\n/)
      .map(l => l.replace(/^\s*[-•*]\s+/, '').trim())
      .filter(Boolean);
    return `\n\n<ul class="hollabuddy-list">${items.map(it => `<li>${it}</li>`).join("")}</ul>\n\n`;
  });

  // 8. Numbered lists (1. item)
  html = html.replace(/((?:^\s*\d+\.\s+[^\r\n]+\r?\n?)+)/gm, (listText) => {
    const items = listText.split(/\r?\n/)
      .map(l => l.replace(/^\s*\d+\.\s+/, '').trim())
      .filter(Boolean);
    return `\n\n<ol class="hollabuddy-list">${items.map(it => `<li>${it}</li>`).join("")}</ol>\n\n`;
  });

  // 9. Process Paragraphs (split by double newlines)
  const sections = html.split(/\n\s*\n/).map(s => s.trim()).filter(Boolean);
  html = sections.map(sec => {
    if (/^<(blockquote|div|table|ul|ol|h2|h3|h4)/i.test(sec) || /^__HB_CODE_\d+__$/.test(sec)) {
      return sec;
    }
    return `<p>${sec.replace(/\r?\n/g, '<br>')}</p>`;
  }).join("\n");

  // 10. Restore Code Blocks
  codeBlocks.forEach((b, idx) => {
    const escapedCode = escapeHtml(b.code);
    const langBadge = b.lang ? `<div class="hollabuddy-code-lang">${escapeHtml(b.lang)}</div>` : "";
    const replacement = `<div class="hollabuddy-code-wrap">${langBadge}<pre class="hollabuddy-code"><code>${escapedCode}</code></pre></div>`;
    html = html.replace(`__HB_CODE_${idx}__`, replacement);
  });

  return html;
}

function copyHollaBuddyText(btn, text) {
  // Strip code fences and blockquote markers for clean pasting
  let clean = (text || "")
    .replace(/```[a-zA-Z0-9_-]*\r?\n?/gi, '')
    .replace(/^>\s?/gm, '')
    .trim();

  navigator.clipboard.writeText(clean).then(() => {
    const originalHtml = btn.innerHTML;
    btn.innerHTML = `<i class="fa-solid fa-check text-emerald"></i> Copied!`;
    btn.classList.add("copied");
    setTimeout(() => {
      btn.innerHTML = originalHtml;
      btn.classList.remove("copied");
    }, 2000);
  }).catch(() => {
    showToast("Failed to copy to clipboard", "warning");
  });
}

async function humanizeHollaBuddyBubble(btn, msgDiv) {
  if (btn.classList.contains("loading")) return;
  const currentRaw = msgDiv.dataset.rawText || "";
  if (!currentRaw || currentRaw.trim().length < 25) {
    showToast("Text is too short to humanize.", "info");
    return;
  }

  const contentEl = msgDiv.querySelector(".hollabuddy-bubble-content");
  if (!contentEl) return;

  const originalHtml = btn.innerHTML;
  btn.classList.add("loading");
  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Humanizing...`;

  try {
    const res = await fetch("/api/humanize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: currentRaw, style: "professional" }),
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || "Failed to humanize text");
    }

    const humanized = data.humanized_text || currentRaw;
    msgDiv.dataset.rawText = humanized;
    contentEl.innerHTML = formatHollaBuddyMarkdown(humanized);

    btn.classList.remove("loading");
    btn.classList.add("humanized");
    btn.innerHTML = `<i class="fa-solid fa-check"></i> Humanized ✨`;
    btn.title = "Refined with Dani's Anti-AI Human Voice Engine";

    // Add or update badge
    let badge = msgDiv.querySelector(".hollabuddy-human-badge");
    if (!badge) {
      badge = document.createElement("span");
      badge.className = "hollabuddy-human-badge";
      badge.innerHTML = `<i class="fa-solid fa-feather-pointed"></i> Dani's Voice`;
      const actions = msgDiv.querySelector(".hollabuddy-bubble-actions");
      if (actions) actions.insertBefore(badge, actions.firstChild);
    }
    showToast("Answer humanized with Dani's voice!", "success");
  } catch (err) {
    console.error("[HollaBuddy Humanize Error]", err);
    btn.classList.remove("loading");
    btn.disabled = false;
    btn.innerHTML = originalHtml;
    showToast("Could not humanize: " + err.message, "warning");
  }
}

function clearHollaBuddyChat() {
  hollabuddyChatHistory = [];
  const container = document.getElementById("hollabuddy-messages");
  if (container) {
    container.innerHTML = `
      <div class="hollabuddy-msg hollabuddy-msg-bot">
        <div class="hollabuddy-msg-avatar">
          <i class="fa-solid fa-robot"></i>
        </div>
        <div class="hollabuddy-bubble">
          <p>Chat cleared! I'm still right here with your master resume loaded. What can I help you draft or prepare?</p>
        </div>
      </div>
    `;
  }
}

function scrollHollaBuddyToBottom() {
  const container = document.getElementById("hollabuddy-messages");
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   LIVE BACKEND CONSOLE & INLINE JOB ANALYSIS TERMINAL CONTROLLER
   ═══════════════════════════════════════════════════════════════════════════ */

/* ── 1. Tab 1 Inline Job Analysis Terminal ── */
let analyzeConsoleExpanded = false;

function toggleAnalyzeConsole(forceState) {
  const drawer = document.getElementById("analyze-console-drawer");
  const btn = document.getElementById("analyze-console-toggle-btn");
  if (!drawer || !btn) return;

  if (typeof forceState === "boolean") {
    analyzeConsoleExpanded = forceState;
  } else {
    analyzeConsoleExpanded = !analyzeConsoleExpanded;
  }

  if (analyzeConsoleExpanded) {
    drawer.classList.remove("hidden");
    btn.classList.add("expanded");
  } else {
    drawer.classList.add("hidden");
    btn.classList.remove("expanded");
  }
}

function setAnalyzeConsoleState(status, message) {
  const btn = document.getElementById("analyze-console-toggle-btn");
  const badge = document.getElementById("analyze-status-badge");
  const hint = document.getElementById("analyze-btn-hint");
  if (!badge || !btn) return;

  btn.classList.remove("active-running", "has-error");
  badge.className = "toggle-badge";

  if (status === "running") {
    btn.classList.add("active-running");
    badge.classList.add("badge-running");
    badge.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Analyzing`;
    if (hint) hint.textContent = message || "Backend active · Scraping & evaluating...";
  } else if (status === "success") {
    badge.classList.add("badge-success");
    badge.innerHTML = `<i class="fa-solid fa-check"></i> Complete`;
    if (hint) hint.textContent = message || "Analysis complete · Click arrow to view details";
  } else if (status === "error") {
    btn.classList.add("has-error");
    badge.classList.add("badge-error");
    badge.innerHTML = `<i class="fa-solid fa-xmark"></i> Error`;
    if (hint) hint.textContent = message || "Analysis failed · Check terminal below";
  } else {
    badge.classList.add("badge-idle");
    badge.textContent = "Idle";
    if (hint) hint.textContent = message || "Click Analyze & Cross-Check to start";
  }
}

function appendAnalyzeConsoleLine(text, category = "general") {
  const body = document.getElementById("analyze-terminal-body");
  if (!body) return;

  const line = document.createElement("div");
  line.className = "terminal-line";

  const timeStr = new Date().toTimeString().split(" ")[0];
  const timeSpan = document.createElement("span");
  timeSpan.className = "t-time";
  timeSpan.textContent = `[${timeStr}]`;

  const tagSpan = document.createElement("span");
  tagSpan.className = `t-tag t-tag-${category}`;
  tagSpan.textContent = category.toUpperCase();

  const msgSpan = document.createElement("span");
  msgSpan.className = `t-msg ${category === 'error' ? 't-msg-error' : (category === 'success' ? 't-msg-success' : (category === 'warning' ? 't-msg-warning' : ''))}`;
  msgSpan.textContent = text;

  line.appendChild(timeSpan);
  line.appendChild(tagSpan);
  line.appendChild(msgSpan);

  body.appendChild(line);
  body.scrollTop = body.scrollHeight;
}

function clearAnalyzeConsole() {
  const body = document.getElementById("analyze-terminal-body");
  if (body) {
    body.innerHTML = `
      <div class="terminal-line system-msg">
        <span class="t-prefix">$</span> Ready. Click "Analyze & Cross-Check" above to monitor live scraper and ATS keywords.
      </div>
    `;
  }
}

function copyAnalyzeConsole() {
  const body = document.getElementById("analyze-terminal-body");
  if (!body) return;
  const text = body.innerText;
  navigator.clipboard.writeText(text).then(() => {
    showToast("Analysis terminal logs copied to clipboard!", "success");
  }).catch(() => {
    showToast("Failed to copy logs", "warning");
  });
}


/* ── 2. Universal Live Console (Side / Header Drawer) ── */
let universalConsoleOpen = false;
let universalConsoleMaximized = false;
let consoleEventSource = null;
let consoleLogsBuffer = [];
let consoleCurrentFilter = "all";
let consoleSearchQuery = "";
let consoleHasFetchedInitial = false;

function toggleUniversalConsole(forceState, evt) {
  if (evt && typeof evt.stopPropagation === "function") {
    evt.stopPropagation();
  }
  const drawer = document.getElementById("universal-console-drawer");
  const launcher = document.getElementById("universal-console-launcher");
  const headerBtn = document.getElementById("header-console-btn");
  const backdrop = document.getElementById("universal-console-backdrop");
  if (!drawer) return;

  if (typeof forceState === "boolean") {
    universalConsoleOpen = forceState;
  } else {
    universalConsoleOpen = !universalConsoleOpen;
  }

  if (universalConsoleOpen) {
    drawer.classList.remove("hidden");
    if (backdrop) backdrop.classList.remove("hidden");
    if (launcher) launcher.classList.add("active");
    if (headerBtn) headerBtn.classList.add("active");

    if (!consoleHasFetchedInitial) {
      fetchRecentConsoleLogs();
      consoleHasFetchedInitial = true;
    }
    initConsoleStream();

    setTimeout(() => {
      const searchInput = document.getElementById("console-search-input");
      if (searchInput && document.activeElement !== searchInput) searchInput.focus();
    }, 200);
  } else {
    drawer.classList.add("hidden");
    if (backdrop) backdrop.classList.add("hidden");
    if (launcher) launcher.classList.remove("active");
    if (headerBtn) headerBtn.classList.remove("active");
  }
}

// Global Escape key listener to close Live Console drawer
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && universalConsoleOpen) {
    toggleUniversalConsole(false);
  }
});

function toggleConsoleMaximize() {
  const drawer = document.getElementById("universal-console-drawer");
  const maxBtn = document.getElementById("console-max-btn");
  if (!drawer) return;
  universalConsoleMaximized = !universalConsoleMaximized;
  if (universalConsoleMaximized) {
    drawer.classList.add("maximized");
    if (maxBtn) maxBtn.innerHTML = `<i class="fa-solid fa-compress"></i>`;
  } else {
    drawer.classList.remove("maximized");
    if (maxBtn) maxBtn.innerHTML = `<i class="fa-solid fa-expand"></i>`;
  }
}

async function fetchRecentConsoleLogs() {
  try {
    const res = await fetch("/api/console/logs?limit=300");
    const data = await res.json();
    if (data.success && Array.isArray(data.logs)) {
      consoleLogsBuffer = data.logs;
      renderUniversalConsoleLogs();
      updateConsoleStatus();
    }
  } catch (err) {
    console.warn("Failed to fetch initial console logs", err);
  }
}

function initConsoleStream() {
  if (consoleEventSource && consoleEventSource.readyState !== EventSource.CLOSED) {
    return;
  }

  const statusElem = document.getElementById("console-stream-status");
  if (statusElem) statusElem.textContent = "Connecting to live SSE stream...";

  try {
    consoleEventSource = new EventSource("/api/console/stream");

    consoleEventSource.onopen = () => {
      if (statusElem) statusElem.innerHTML = `<span class="live-dot-green"></span> Live Connected (Render SSE)`;
    };

    consoleEventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type === "init") {
          if (statusElem) statusElem.innerHTML = `<span class="live-dot-green"></span> Live Connected (Render SSE)`;
          return;
        }
        if (payload.type === "ping") {
          return;
        }
        if (payload.type === "clear") {
          consoleLogsBuffer = [];
          renderUniversalConsoleLogs();
          return;
        }
        if (payload.type === "log" && payload.text) {
          consoleLogsBuffer.push(payload);
          if (consoleLogsBuffer.length > 2000) {
            consoleLogsBuffer.shift();
          }

          // Mirror live analyze/scraper logs into Tab 1 inline drawer
          if (payload.category === "analyze" || payload.category === "scraper") {
            appendAnalyzeConsoleLine(payload.text, payload.category);
          }

          appendUniversalConsoleEntry(payload);
          updateConsoleStatus(payload.time);
        }
      } catch (e) {
        console.error("Console event parse error", e);
      }
    };

    consoleEventSource.onerror = () => {
      if (statusElem) statusElem.textContent = "Reconnecting to live console...";
    };
  } catch (err) {
    if (statusElem) statusElem.textContent = "Console stream unavailable";
  }
}

function updateConsoleStatus(lastTime) {
  const counter = document.getElementById("console-log-counter");
  const bufferCount = document.getElementById("console-buffer-count");
  const lastEvent = document.getElementById("console-last-event-time");

  if (counter) counter.textContent = `${consoleLogsBuffer.length} lines`;
  if (bufferCount) bufferCount.textContent = `${consoleLogsBuffer.length} / 2,000 lines`;
  if (lastEvent && lastTime) lastEvent.textContent = `Last update: ${lastTime}`;
}

function filterConsole(category) {
  consoleCurrentFilter = category;
  document.querySelectorAll(".console-filter-btn").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.filter === category);
  });
  renderUniversalConsoleLogs();
}

function handleConsoleSearch(val) {
  consoleSearchQuery = (val || "").toLowerCase().trim();
  renderUniversalConsoleLogs();
}

function matchesFilter(entry) {
  if (consoleCurrentFilter !== "all") {
    if (consoleCurrentFilter === "error") {
      if (entry.category !== "error" && !entry.text.toLowerCase().includes("error") && !entry.text.toLowerCase().includes("exception") && !entry.text.toLowerCase().includes("traceback")) {
        return false;
      }
    } else if (entry.category !== consoleCurrentFilter) {
      return false;
    }
  }
  if (consoleSearchQuery) {
    const text = (entry.text || "").toLowerCase();
    const cat = (entry.category || "").toLowerCase();
    if (!text.includes(consoleSearchQuery) && !cat.includes(consoleSearchQuery)) {
      return false;
    }
  }
  return true;
}

function renderUniversalConsoleLogs() {
  const container = document.getElementById("universal-console-body");
  if (!container) return;

  container.innerHTML = "";
  const filtered = consoleLogsBuffer.filter(matchesFilter);

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="terminal-line system-msg">
        <span class="t-prefix">ℹ</span> No console log lines matching current filter.
      </div>
    `;
    return;
  }

  const fragment = document.createDocumentFragment();
  filtered.forEach(entry => {
    const line = createLogLineElement(entry);
    fragment.appendChild(line);
  });
  container.appendChild(fragment);

  const autoScroll = document.getElementById("console-autoscroll-chk")?.checked ?? true;
  if (autoScroll) {
    container.scrollTop = container.scrollHeight;
  }

  const counter = document.getElementById("console-log-counter");
  if (counter) {
    counter.textContent = `${filtered.length} of ${consoleLogsBuffer.length} lines`;
  }
}

function createLogLineElement(entry) {
  const line = document.createElement("div");
  line.className = "terminal-line";

  const timeSpan = document.createElement("span");
  timeSpan.className = "t-time";
  timeSpan.textContent = `[${entry.time || "--:--:--"}]`;

  const tagSpan = document.createElement("span");
  const cat = entry.category || "general";
  tagSpan.className = `t-tag t-tag-${cat}`;
  tagSpan.textContent = cat.toUpperCase();

  const msgSpan = document.createElement("span");
  msgSpan.className = `t-msg ${cat === 'error' ? 't-msg-error' : (cat === 'success' ? 't-msg-success' : (cat === 'warning' ? 't-msg-warning' : ''))}`;
  msgSpan.textContent = entry.text;

  line.appendChild(timeSpan);
  line.appendChild(tagSpan);
  line.appendChild(msgSpan);
  return line;
}

function appendUniversalConsoleEntry(entry) {
  if (!matchesFilter(entry)) return;
  const container = document.getElementById("universal-console-body");
  if (!container) return;

  const line = createLogLineElement(entry);
  container.appendChild(line);

  const autoScroll = document.getElementById("console-autoscroll-chk")?.checked ?? true;
  if (autoScroll) {
    container.scrollTop = container.scrollHeight;
  }
}

async function clearUniversalConsole() {
  try {
    await fetch("/api/console/clear", { method: "POST" });
    consoleLogsBuffer = [];
    renderUniversalConsoleLogs();
    showToast("Console cleared", "info");
  } catch (err) {
    consoleLogsBuffer = [];
    renderUniversalConsoleLogs();
  }
}

function copyUniversalConsole() {
  const container = document.getElementById("universal-console-body");
  if (!container) return;
  const text = container.innerText;
  navigator.clipboard.writeText(text).then(() => {
    showToast("All console logs copied to clipboard!", "success");
  }).catch(() => {
    showToast("Failed to copy console logs", "warning");
  });
}

// Automatically start background SSE connection and check for bookmarklet prefill
function checkUrlAutoFill() {
  try {
    const params = new URLSearchParams(window.location.search);
    const urlParam = params.get("url");
    const keywordsParam = params.get("keywords");
    const scoreParam = params.get("score");
    const companyParam = params.get("company");
    const roleParam = params.get("role");

    if (urlParam || keywordsParam || scoreParam) {
      if (urlParam) {
        const urlInput = document.getElementById("jd-url");
        if (urlInput) urlInput.value = decodeURIComponent(urlParam);
      }
      if (keywordsParam) {
        const kwInput = document.getElementById("custom-keywords-input");
        if (kwInput) kwInput.value = decodeURIComponent(keywordsParam);
      }
      if (scoreParam) {
        analyzeScoreBefore = parseInt(scoreParam) || 75;
      }
      if (companyParam) analyzeCompany = decodeURIComponent(companyParam);
      if (roleParam) analyzeRole = decodeURIComponent(roleParam);

      showToast("⚡ Auto-loaded job and Simplify keywords from your browser!", "success");

      // Switch to Tab 1 if not active
      switchTab("new-app");

      // Clean URL query string without reloading page
      window.history.replaceState({}, document.title, window.location.pathname);
    }
  } catch (e) {
    console.warn("checkUrlAutoFill note:", e);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", () => {
    setTimeout(initConsoleStream, 1500);
    setTimeout(checkUrlAutoFill, 300);
    initInteractiveHollaBuddy();
  });
} else {
  setTimeout(initConsoleStream, 1500);
  setTimeout(checkUrlAutoFill, 300);
  initInteractiveHollaBuddy();
}

/* ==========================================================================
   ATS Agent Launch & Reload Splash Reveal Animation
   ========================================================================== */
let atsSplashTimer = null;

function dismissAtsSplash() {
  const splash = document.getElementById("ats-app-splash");
  if (!splash || splash.classList.contains("splash-revealed")) return;
  if (atsSplashTimer) clearTimeout(atsSplashTimer);
  splash.classList.add("splash-revealed");
  setTimeout(() => {
    if (splash.parentNode) splash.parentNode.removeChild(splash);
  }, 550);
}

function initAtsSplash() {
  const splash = document.getElementById("ats-app-splash");
  if (!splash) return;

  // Dismiss on keydown
  const keyHandler = () => {
    dismissAtsSplash();
    window.removeEventListener("keydown", keyHandler);
  };
  window.addEventListener("keydown", keyHandler);

  // Automatically trigger the see-through reveal after full zoom animation plays
  atsSplashTimer = setTimeout(() => {
    dismissAtsSplash();
  }, 2250);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initAtsSplash);
} else {
  initAtsSplash();
}

/* ── Change Password Modal Handlers ─────────────────────────────────────── */
function openPasswordModal() {
  const modal = document.getElementById("change-password-modal");
  if (!modal) return;
  const currInput = document.getElementById("curr-pass-input");
  const newInput = document.getElementById("new-pass-input");
  const confirmInput = document.getElementById("confirm-pass-input");
  const errBox = document.getElementById("change-pass-error");
  const succBox = document.getElementById("change-pass-success");

  if (currInput) currInput.value = "";
  if (newInput) newInput.value = "";
  if (confirmInput) confirmInput.value = "";
  if (errBox) errBox.style.display = "none";
  if (succBox) succBox.style.display = "none";

  modal.style.display = "flex";
  setTimeout(() => {
    if (currInput) currInput.focus();
  }, 100);
}

function closePasswordModal() {
  const modal = document.getElementById("change-password-modal");
  if (modal) modal.style.display = "none";
}

function togglePasswordVisibility(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const icon = btn.querySelector("i");
  if (input.type === "password") {
    input.type = "text";
    if (icon) {
      icon.className = "fa-regular fa-eye-slash";
    }
  } else {
    input.type = "password";
    if (icon) {
      icon.className = "fa-regular fa-eye";
    }
  }
}

async function submitChangePassword() {
  const currInput = document.getElementById("curr-pass-input");
  const newInput = document.getElementById("new-pass-input");
  const confirmInput = document.getElementById("confirm-pass-input");
  const errBox = document.getElementById("change-pass-error");
  const errText = document.getElementById("change-pass-error-text");
  const succBox = document.getElementById("change-pass-success");
  const submitBtn = document.getElementById("change-pass-submit-btn");
  const submitIcon = document.getElementById("change-pass-submit-icon");
  const submitText = document.getElementById("change-pass-submit-text");

  const currentPassword = currInput ? currInput.value : "";
  const newPassword = newInput ? newInput.value : "";
  const confirmPassword = confirmInput ? confirmInput.value : "";

  if (errBox) errBox.style.display = "none";
  if (succBox) succBox.style.display = "none";

  if (!currentPassword) {
    if (errBox && errText) {
      errText.textContent = "Please enter your current password.";
      errBox.style.display = "block";
    }
    if (currInput) currInput.focus();
    return;
  }

  if (!newPassword) {
    if (errBox && errText) {
      errText.textContent = "Please enter a new password.";
      errBox.style.display = "block";
    }
    if (newInput) newInput.focus();
    return;
  }

  if (newPassword.length < 6) {
    if (errBox && errText) {
      errText.textContent = "New password must be at least 6 characters long.";
      errBox.style.display = "block";
    }
    if (newInput) newInput.focus();
    return;
  }

  if (newPassword !== confirmPassword) {
    if (errBox && errText) {
      errText.textContent = "New passwords do not match. Please verify.";
      errBox.style.display = "block";
    }
    if (confirmInput) confirmInput.focus();
    return;
  }

  // Set loading state
  if (submitBtn) submitBtn.disabled = true;
  if (submitIcon) submitIcon.className = "fa-solid fa-spinner fa-spin";
  if (submitText) submitText.textContent = "Updating...";

  try {
    const res = await fetch("/api/change_password", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
      }),
    });
    const data = await res.json().catch(() => ({}));

    if (res.ok && data.success) {
      if (succBox) succBox.style.display = "block";
      if (typeof showToast === "function") {
        showToast("Password updated successfully!", "success");
      }
      if (currInput) currInput.value = "";
      if (newInput) newInput.value = "";
      if (confirmInput) confirmInput.value = "";

      setTimeout(() => {
        closePasswordModal();
      }, 1200);
    } else {
      const msg = data.error || data.message || "Failed to update password. Please check your current password.";
      if (errBox && errText) {
        errText.textContent = msg;
        errBox.style.display = "block";
      }
      if (typeof showToast === "function") {
        showToast(msg, "error");
      }
    }
  } catch (err) {
    const msg = `Network error: ${err.message}`;
    if (errBox && errText) {
      errText.textContent = msg;
      errBox.style.display = "block";
    }
    if (typeof showToast === "function") {
      showToast(msg, "error");
    }
  } finally {
    if (submitBtn) submitBtn.disabled = false;
    if (submitIcon) submitIcon.className = "fa-solid fa-key";
    if (submitText) submitText.textContent = "Update Password";
  }
}

// Ensure global attachment for inline event handlers
window.openPasswordModal = openPasswordModal;
window.closePasswordModal = closePasswordModal;
window.togglePasswordVisibility = togglePasswordVisibility;
window.submitChangePassword = submitChangePassword;


/* ── SECTION COMMENT APPENDER & LIVE REVIEW BAR ───────────────────────────── */

function appendSectionComment(sectionTag) {
  const input = document.getElementById("refine-instruction-input");
  if (!input) return;
  const current = input.value.trim();
  const cursor = `${sectionTag} `;
  if (current) {
    input.value = current + "\n" + cursor;
  } else {
    input.value = cursor;
  }
  input.focus();
  // Move cursor to end
  input.setSelectionRange(input.value.length, input.value.length);
  updateRefineReviewBar();
}

function clearRefineInstruction() {
  const input = document.getElementById("refine-instruction-input");
  if (input) {
    input.value = "";
    input.focus();
  }
  updateRefineReviewBar();
}

function updateRefineReviewBar() {
  const input = document.getElementById("refine-instruction-input");
  const detectedGroup = document.getElementById("refine-detected-tags");
  const remainingGroup = document.getElementById("refine-remaining-tags");
  if (!detectedGroup || !remainingGroup) return;

  const val = (input ? input.value : "").trim();

  // Canonical list of sections with corresponding tags and colors
  const canonicalSections = [
    { id: "summary", tag: "@(Summary)", label: "Summary", colorClass: "badge-summary", icon: "fa-id-badge", regex: /(@\(summary\)|\@summary|\[summary\])/i },
    { id: "skills", tag: "@(Skills)", label: "Skills", colorClass: "badge-skills", icon: "fa-code", regex: /(@\(skills\)|\@skills|\[skills\])/i },
    { id: "experience", tag: "@(Experience)", label: "Experience", colorClass: "badge-experience", icon: "fa-briefcase", regex: /(@\(experience(?:[^\)]*)\)|\@experience|\[experience[^\]]*\])/i },
    { id: "title", tag: "@(Title)", label: "Headline", colorClass: "badge-title", icon: "fa-signature", regex: /(@\(title\)|\@title|\[title\])/i },
    { id: "bullets", tag: "@(All Bullets)", label: "All Bullets", colorClass: "badge-bullets", icon: "fa-list-ul", regex: /(@\(all(?:[^\)]*)\)|\@all|\[all bullets\])/i },
  ];

  const detected = [];
  const remaining = [];

  canonicalSections.forEach(sec => {
    if (sec.regex.test(val)) {
      detected.push(sec);
    } else {
      remaining.push(sec);
    }
  });

  // Render detected tags
  if (detected.length === 0) {
    detectedGroup.innerHTML = `
      <span class="refine-review-label"><i class="fa-solid fa-list-check text-cyan"></i> Active Targets:</span>
      <span style="color:var(--t3); font-size:11.5px;" id="refine-no-tags-hint">${val ? "No @() section tags detected — applies globally." : "No @() section tags detected yet. Click chips above or type @(Section)."}</span>
    `;
  } else {
    let badgesHtml = detected.map(sec => `
      <span class="refine-review-badge ${sec.colorClass}">
        <i class="fa-solid ${sec.icon}"></i> ${sec.tag} <i class="fa-solid fa-check" style="font-size:10px; margin-left:2px;"></i>
      </span>
    `).join("");

    detectedGroup.innerHTML = `
      <span class="refine-review-label"><i class="fa-solid fa-list-check text-cyan"></i> Active Targets (${detected.length}):</span>
      ${badgesHtml}
    `;
  }

  // Render remaining tags
  if (remaining.length === 0) {
    remainingGroup.innerHTML = `
      <span class="refine-review-label" style="color:#10b981;"><i class="fa-solid fa-circle-check"></i> All 5 key sections targeted!</span>
      <button type="button" class="btn-micro" onclick="clearRefineInstruction()" style="margin-left:6px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); border-radius:4px; padding:2px 8px; color:var(--t2); cursor:pointer;"><i class="fa-solid fa-xmark"></i> Clear</button>
    `;
  } else {
    let remainingHtml = remaining.map(sec => `
      <button type="button" class="refine-review-badge badge-unselected" onclick="appendSectionComment('${sec.tag}')" title="Click to add ${sec.tag}">
        + ${sec.tag}
      </button>
    `).join("");

    remainingGroup.innerHTML = `
      <span class="refine-review-label" style="color:var(--t3);">Check &amp; add left:</span>
      ${remainingHtml}
      ${val ? '<button type="button" class="btn-micro" onclick="clearRefineInstruction()" style="margin-left:6px; background:rgba(255,255,255,0.06); border:1px solid rgba(255,255,255,0.15); border-radius:4px; padding:2px 8px; color:var(--t2); cursor:pointer;" title="Clear instruction box"><i class="fa-solid fa-xmark"></i> Clear</button>' : ''}
    `;
  }
}

// Make available globally for inline HTML events
window.appendSectionComment = appendSectionComment;
window.clearRefineInstruction = clearRefineInstruction;
window.updateRefineReviewBar = updateRefineReviewBar;

/* ── JD RESPONSIBILITIES PASTE DRAWER ─────────────────────────────────────── */

function toggleJDResponsibilitiesDrawer() {
  const drawer = document.getElementById("jd-responsibilities-drawer");
  const arrow = document.getElementById("jd-resp-arrow");
  if (!drawer) return;
  const isOpen = drawer.style.display !== "none";
  drawer.style.display = isOpen ? "none" : "block";
  if (arrow) arrow.style.transform = isOpen ? "rotate(0deg)" : "rotate(90deg)";
}

async function weaveJDResponsibilities() {
  const textarea = document.getElementById("jd-responsibilities-textarea");
  const rawText = (textarea ? textarea.value : "").trim();
  if (!rawText) {
    showToast("Please paste job description responsibilities first.", "warning");
    textarea && textarea.focus();
    return;
  }

  // Parse lines — strip bullet markers
  const lines = rawText.split("\n")
    .map(l => l.replace(/^[\u2022\u2023\u25aa\u25ab\u25cf\u2013\u2014\*\-\u25b8\u25ba]\s*/u, "").trim())
    .filter(l => l.length > 5);

  if (lines.length === 0) {
    showToast("No valid responsibility lines found — please check the input.", "warning");
    return;
  }

  // Build a structured instruction and send to the main refinement input
  const instruction = `[EXPERIENCE/Most Recent Role] Weave ALL of the following job description responsibilities into my experience bullets (every single one must appear):\n${lines.map((l, i) => `${i+1}. ${l}`).join("\n")}`;

  const mainInput = document.getElementById("refine-instruction-input");
  if (mainInput) {
    mainInput.value = instruction;
  }

  // Auto-submit
  showToast(`Weaving ${lines.length} JD responsibilities into your resume...`, "info");
  await submitResumeRefinement();
}

/* ── LIVE EDIT MODAL ───────────────────────────────────────────────────────── */

function openLiveEditModal() {
  const modal = document.getElementById("live-edit-modal");
  if (!modal) return;

  const resume = (window.lastResult && window.lastResult.tailored_resume) || null;
  if (!resume) {
    showToast("Please generate a tailored resume first, then open Live Edit.", "warning");
    return;
  }

  _renderLiveEditSections(resume);

  const statusEl = document.getElementById("live-edit-status");
  if (statusEl) statusEl.style.display = "none";

  modal.style.display = "flex";
  document.body.style.overflow = "hidden";
}

function closeLiveEditModal() {
  const modal = document.getElementById("live-edit-modal");
  if (modal) modal.style.display = "none";
  document.body.style.overflow = "";
}

function _renderLiveEditSections(resume) {
  const container = document.getElementById("live-edit-sections");
  if (!container) return;

  const editableStyle = "width:100%; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:8px; padding:10px 12px; font-size:13px; color:var(--t0); resize:vertical; outline:none; font-family:inherit; box-sizing:border-box; line-height:1.6;";

  let html = "";

  // ── Summary (Cyan / Sky) ──
  html += `<div style="background:rgba(56,189,248,0.03); border:1px solid rgba(56,189,248,0.25); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:10px;" data-section="summary">
    <div style="font-size:11px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:#38bdf8; display:flex; align-items:center; justify-content:space-between;">
      <span><i class="fa-solid fa-id-badge" style="margin-right:6px;"></i>Professional Summary</span>
      <span class="refine-review-badge badge-summary">@(Summary)</span>
    </div>
    <textarea class="le-field" data-key="summary" style="${editableStyle}" rows="3" placeholder="Your professional summary...">${escHtml(resume.summary || "")}</textarea>
    <div style="font-size:11.5px; color:#38bdf8; display:flex; align-items:center; gap:5px;"><i class="fa-solid fa-comment-dots"></i> Tell AI how to rewrite summary (leave blank to keep direct edit above):</div>
    <textarea class="le-ai-comment" data-target="@(Summary)" style="width:100%; background:rgba(56,189,248,0.06); border:1px solid rgba(56,189,248,0.3); border-radius:8px; padding:8px 12px; font-size:12px; color:#7dd3fc; resize:vertical; outline:none; font-family:inherit; box-sizing:border-box; line-height:1.5;" rows="2" placeholder="e.g. Focus on data engineering and pipeline automation, cut corporate jargon, keep to 2 sentences"></textarea>
  </div>`;

  // ── Skills (Emerald) ──
  const skillsStr = Array.isArray(resume.skills) ? resume.skills.join(", ") : (resume.skills || "");
  html += `<div style="background:rgba(52,211,153,0.03); border:1px solid rgba(52,211,153,0.25); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:10px;" data-section="skills">
    <div style="font-size:11px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:#34d399; display:flex; align-items:center; justify-content:space-between;">
      <span><i class="fa-solid fa-code" style="margin-right:6px;"></i>Skills</span>
      <span class="refine-review-badge badge-skills">@(Skills)</span>
    </div>
    <textarea class="le-field" data-key="skills" style="${editableStyle}" rows="3" placeholder="Comma-separated skills...">${escHtml(skillsStr)}</textarea>
    <div style="font-size:11.5px; color:#34d399; display:flex; align-items:center; gap:5px;"><i class="fa-solid fa-comment-dots"></i> Tell AI what to do with skills (leave blank to keep direct edit above):</div>
    <textarea class="le-ai-comment" data-target="@(Skills)" style="width:100%; background:rgba(52,211,153,0.06); border:1px solid rgba(52,211,153,0.3); border-radius:8px; padding:8px 12px; font-size:12px; color:#6ee7b7; resize:vertical; outline:none; font-family:inherit; box-sizing:border-box; line-height:1.5;" rows="2" placeholder="e.g. Replace all skills with: Python, SQL, Spark, Kafka, Airflow, AWS, Docker, Kubernetes"></textarea>
  </div>`;

  // ── Experience (Amber) ──
  const experiences = resume.experience || [];
  experiences.forEach((exp, idx) => {
    const company = exp.company || `Role ${idx + 1}`;
    const title = exp.title || exp.role || "";
    const dates = exp.dates || "";
    const bullets = Array.isArray(exp.bullets) ? exp.bullets.join("\n") : "";
    html += `<div style="background:rgba(251,191,36,0.03); border:1px solid rgba(251,191,36,0.25); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:10px;" data-section="exp-${idx}">
      <div style="font-size:11px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:#fbbf24; display:flex; align-items:center; justify-content:space-between;">
        <span><i class="fa-solid fa-briefcase" style="margin-right:6px;"></i>${escHtml(company)} — ${escHtml(title)} <span style="font-weight:400; color:var(--t2); text-transform:none;">${escHtml(dates)}</span></span>
        <span class="refine-review-badge badge-experience">@(Experience/${escHtml(company)})</span>
      </div>
      <textarea class="le-field" data-key="experience.${idx}.bullets" style="${editableStyle}" rows="5" placeholder="One bullet per line...">${escHtml(bullets)}</textarea>
      <div style="font-size:11.5px; color:#fbbf24; display:flex; align-items:center; gap:5px;"><i class="fa-solid fa-comment-dots"></i> Tell AI what to do with these bullets:</div>
      <textarea class="le-ai-comment" data-target="@(Experience/${company})" style="width:100%; background:rgba(251,191,36,0.06); border:1px solid rgba(251,191,36,0.3); border-radius:8px; padding:8px 12px; font-size:12px; color:#fde68a; resize:vertical; outline:none; font-family:inherit; box-sizing:border-box; line-height:1.5;" rows="2" placeholder="e.g. Add quantified metrics to every bullet and front-load business impact"></textarea>
    </div>`;
  });

  // ── Job Title / Headline (Violet) ──
  html += `<div style="background:rgba(192,132,252,0.03); border:1px solid rgba(192,132,252,0.25); border-radius:12px; padding:16px; display:flex; flex-direction:column; gap:10px;" data-section="title">
    <div style="font-size:11px; font-weight:700; letter-spacing:0.08em; text-transform:uppercase; color:#c084fc; display:flex; align-items:center; justify-content:space-between;">
      <span><i class="fa-solid fa-signature" style="margin-right:6px;"></i>Headline / Target Role</span>
      <span class="refine-review-badge badge-title">@(Title)</span>
    </div>
    <input class="le-field" data-key="target_role" style="${editableStyle.replace('resize:vertical;','')} height:38px;" type="text" value="${escHtml(resume.target_role || "")}" placeholder="e.g. Senior Data Engineer">
    <div style="font-size:11.5px; color:#c084fc; display:flex; align-items:center; gap:5px;"><i class="fa-solid fa-comment-dots"></i> Tell AI what headline to use:</div>
    <textarea class="le-ai-comment" data-target="@(Title)" style="width:100%; background:rgba(192,132,252,0.06); border:1px solid rgba(192,132,252,0.3); border-radius:8px; padding:8px 12px; font-size:12px; color:#e9d5ff; resize:vertical; outline:none; font-family:inherit; box-sizing:border-box; line-height:1.5;" rows="1" placeholder="e.g. Senior Cloud Data Architect"></textarea>
  </div>`;

  container.innerHTML = html;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function applyLiveEdits() {
  const applyBtn = document.getElementById("live-edit-apply-btn");
  const applySpinner = document.getElementById("live-edit-apply-spinner");
  const applyIcon = document.getElementById("live-edit-apply-icon");
  const applyText = document.getElementById("live-edit-apply-text");
  const statusEl = document.getElementById("live-edit-status");
  const statusText = document.getElementById("live-edit-status-text");

  const resume = (window.lastResult && window.lastResult.tailored_resume) || null;
  if (!resume) {
    showToast("No resume loaded — please generate a resume first.", "warning");
    return;
  }

  // ── Collect AI comments (Tell AI boxes) ──
  const aiComments = [];
  document.querySelectorAll(".le-ai-comment").forEach(el => {
    const val = el.value.trim();
    const target = el.getAttribute("data-target") || "";
    if (val) {
      aiComments.push(`${target} ${val}`);
    }
  });

  // ── Collect direct edits and merge into the resume JSON ──
  const updatedResume = JSON.parse(JSON.stringify(resume)); // deep clone

  document.querySelectorAll(".le-field").forEach(el => {
    const key = el.getAttribute("data-key") || "";
    const val = (el.tagName === "TEXTAREA" ? el.value : el.value).trim();

    if (key === "summary") {
      updatedResume.summary = val;
    } else if (key === "skills") {
      // Parse comma-separated, newlines, or bullets
      updatedResume.skills = parseKeywordsList(val);
    } else if (key === "target_role") {
      updatedResume.target_role = val;
    } else if (key.startsWith("experience.")) {
      const parts = key.split(".");
      const idx = parseInt(parts[1]);
      const field = parts[2];
      if (!isNaN(idx) && updatedResume.experience && updatedResume.experience[idx]) {
        if (field === "bullets") {
          updatedResume.experience[idx].bullets = val.split("\n").map(b => b.trim()).filter(b => b.length > 3);
        }
      }
    }
  });

  // ── If there are AI comments, send to refinement API with the directly-edited resume as current ──
  if (aiComments.length > 0) {
    // Build structured instruction from AI comments
    const instruction = aiComments.join("\n");

    if (applyBtn) applyBtn.disabled = true;
    if (applySpinner) applySpinner.style.display = "inline-block";
    if (applyIcon) applyIcon.style.display = "none";
    if (applyText) applyText.textContent = "Applying AI instructions...";

    try {
      const lastRes = window.lastResult || {};
      const res = await fetch("/api/refine-resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: instruction,
          folder_path: lastRes.folder_path || "",
          company: lastRes.company || "",
          role: lastRes.role || "",
          url: lastRes.url || "",
          current_resume: updatedResume, // use the directly-edited version as base
          jd_text: (lastRes && lastRes.jd_text) ? lastRes.jd_text : (window.analyzeJdText || ""),
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || "Refinement failed");

      if (window.lastResult) {
        window.lastResult.output_file = data.output_file;
        window.lastResult.relative_path = data.relative_path;
        window.lastResult.relative_pdf = data.relative_pdf;
        if (data.updated_resume) {
          window.lastResult.tailored_resume = data.updated_resume;
          // Re-render the live edit panel with updated data
          _renderLiveEditSections(data.updated_resume);
        }
      }

      if (statusEl) { statusEl.style.display = "flex"; }
      if (statusText) statusText.textContent = data.change_summary || "All changes applied and resume rebuilt!";
      showToast("Live edits applied & resume rebuilt!", "success");
      loadHistory();

    } catch (err) {
      showToast(`Live Edit failed: ${err.message}`, "error");
    } finally {
      if (applyBtn) applyBtn.disabled = false;
      if (applySpinner) applySpinner.style.display = "none";
      if (applyIcon) applyIcon.style.display = "inline";
      if (applyText) applyText.textContent = "Apply All & Rebuild";
    }

  } else {
    // No AI comments — only direct edits. Save directly and rebuild.
    if (applyBtn) applyBtn.disabled = true;
    if (applyText) applyText.textContent = "Saving direct edits...";

    try {
      const lastRes = window.lastResult || {};

      // Build a trivial instruction that signals direct edit pass-through (no AI rewrite needed for changed fields)
      // We'll send the directly-edited resume and ask AI to just preserve it as-is
      const res = await fetch("/api/refine-resume", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          instruction: "Apply the direct edits I made to this resume exactly as provided. Do not change any content — preserve all text exactly as given in the CURRENT TAILORED RESUME. Just rebuild the documents.",
          folder_path: lastRes.folder_path || "",
          company: lastRes.company || "",
          role: lastRes.role || "",
          current_resume: updatedResume,
          jd_text: "",
        }),
      });

      const data = await res.json();
      if (!res.ok || !data.success) throw new Error(data.error || "Save failed");

      if (window.lastResult) {
        window.lastResult.output_file = data.output_file;
        window.lastResult.relative_path = data.relative_path;
        window.lastResult.relative_pdf = data.relative_pdf;
        if (data.updated_resume) {
          window.lastResult.tailored_resume = data.updated_resume;
        }
      }

      if (statusEl) { statusEl.style.display = "flex"; }
      if (statusText) statusText.textContent = "Direct edits saved and resume rebuilt!";
      showToast("Direct edits saved & resume rebuilt!", "success");
      loadHistory();

    } catch (err) {
      showToast(`Save failed: ${err.message}`, "error");
    } finally {
      if (applyBtn) applyBtn.disabled = false;
      if (applyText) applyText.textContent = "Apply All & Rebuild";
    }
  }
}

// Close live edit on ESC
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    const leModal = document.getElementById("live-edit-modal");
    if (leModal && leModal.style.display === "flex") {
      closeLiveEditModal();
    }
  }
});

// Expose new functions globally
window.appendSectionComment = appendSectionComment;
window.toggleJDResponsibilitiesDrawer = toggleJDResponsibilitiesDrawer;
window.weaveJDResponsibilities = weaveJDResponsibilities;
window.openLiveEditModal = openLiveEditModal;
window.closeLiveEditModal = closeLiveEditModal;
window.applyLiveEdits = applyLiveEdits;
