/**
 * theme.js — ATS Agent Global Theme Controller
 * Persists theme ('dark' | 'light') in localStorage, prevents FOUC,
 * and synchronizes all theme toggles and WebGL particle backgrounds.
 */
(function () {
  "use strict";

  // 1. Synchronous initial theme application (prevents FOUC)
  function getPreferredTheme() {
    try {
      var stored = localStorage.getItem("ats_theme");
      if (stored === "light" || stored === "dark") {
        return stored;
      }
    } catch (e) {}
    return "dark"; // default theme
  }

  var activeTheme = getPreferredTheme();
  document.documentElement.setAttribute("data-theme", activeTheme);
  document.documentElement.classList.toggle("theme-light", activeTheme === "light");
  document.documentElement.classList.toggle("theme-dark", activeTheme === "dark");

  // 2. Global theme switcher
  window.setAppTheme = function (theme) {
    if (theme !== "light" && theme !== "dark") theme = "dark";
    activeTheme = theme;
    document.documentElement.setAttribute("data-theme", theme);
    document.documentElement.classList.toggle("theme-light", theme === "light");
    document.documentElement.classList.toggle("theme-dark", theme === "dark");

    try {
      localStorage.setItem("ats_theme", theme);
    } catch (e) {}

    // Update all toggle buttons in DOM
    updateToggleButtons(theme);

    // Update Antigravity WebGL Canvas if active
    if (typeof window.setAntigravityTheme === "function") {
      window.setAntigravityTheme(theme);
    }

    // Dispatch custom event for any listening components
    window.dispatchEvent(new CustomEvent("ats-theme-changed", { detail: { theme: theme } }));
  };

  window.toggleAppTheme = function () {
    var current = document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
    var next = current === "light" ? "dark" : "light";
    window.setAppTheme(next);
  };

  function updateToggleButtons(theme) {
    var buttons = document.querySelectorAll(".theme-toggle-btn");
    buttons.forEach(function (btn) {
      btn.setAttribute("data-current-theme", theme);
      btn.title = theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode";
      btn.setAttribute("aria-label", btn.title);

      var icon = btn.querySelector("i");
      if (icon) {
        if (theme === "light") {
          icon.className = "fa-solid fa-moon";
        } else {
          icon.className = "fa-solid fa-sun";
        }
      }

      var text = btn.querySelector(".theme-toggle-label");
      if (text) {
        text.textContent = theme === "light" ? "Dark" : "Light";
      }
    });
  }

  // Update button icons as soon as DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () {
      updateToggleButtons(activeTheme);
    });
  } else {
    updateToggleButtons(activeTheme);
  }
})();
