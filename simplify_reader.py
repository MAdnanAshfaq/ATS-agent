"""
simplify_reader.py — Real Simplify Chrome Extension Integration.

Works while Chrome is open. Uses Playwright Chromium with the Simplify extension
loaded from Profile 8. Reads your real Simplify ATS match score and exact missing keywords
directly from Simplify's shadow DOM by switching to the 'Resume Score' tab.
"""

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# ─── Paths & Dynamic Discovery ───────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
SIMPLIFY_EXT_ID = "pbanhockgagggenencehbnadejlgchfc"
TEMP_PROFILE_DIR = str(BASE_DIR / "chrome_profile_simplify")

def get_chrome_user_data_dir() -> Path:
    """Dynamically get the Chrome User Data directory for the current OS/user."""
    user_home = Path(os.environ.get("USERPROFILE", str(Path.home())))
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "Google" / "Chrome" / "User Data"
        if candidate.exists():
            return candidate
    candidate = user_home / "AppData" / "Local" / "Google" / "Chrome" / "User Data"
    if candidate.exists():
        return candidate
    return candidate


def find_simplify_installation() -> dict:
    """
    Search for Simplify extension:
    1. Search local Chrome profiles (Default, Profile 1..N) in Chrome User Data (Windows / macOS) for user login session.
    2. Fallback to bundled extension inside project repository (universal for Render Linux & cloud).
    Can be overridden by SIMPLIFY_PROFILE in .env.
    """
    load_dotenv()

    chrome_data = get_chrome_user_data_dir()
    env_profile = os.getenv("SIMPLIFY_PROFILE", "").strip()

    # 1. First search local Chrome profiles (preserves authentic login cookies and saved resumes)
    if chrome_data.exists():
        profiles_to_check = []
        if env_profile:
            profiles_to_check.append(chrome_data / env_profile)

        for item in chrome_data.iterdir():
            if item.is_dir() and (item.name == "Default" or item.name.startswith("Profile")):
                if item not in profiles_to_check:
                    profiles_to_check.append(item)

        candidates = []
        for prof_dir in profiles_to_check:
            ext_dir = prof_dir / "Extensions" / SIMPLIFY_EXT_ID
            if ext_dir.exists():
                subdirs = [d for d in ext_dir.iterdir() if d.is_dir()]
                if subdirs:
                    latest = sorted(subdirs, key=lambda p: p.stat().st_mtime, reverse=True)[0]
                    candidates.append({
                        "profile_dir": str(prof_dir),
                        "profile_name": prof_dir.name,
                        "ext_path": str(latest).replace("\\", "/"),
                        "mtime": latest.stat().st_mtime,
                        "error": None
                    })
        if candidates:
            # Pick profile with newest modified extension/cookies
            candidates.sort(key=lambda x: x["mtime"], reverse=True)
            chosen = candidates[0]
            del chosen["mtime"]
            return chosen

    # 2. Fallback to bundled extension in project root (universal for Render Linux & cloud)
    bundled = BASE_DIR / "simplify_extension"
    if bundled.exists() and (bundled / "manifest.json").exists():
        return {
            "profile_dir": None,
            "profile_name": "Bundled Cloud Extension",
            "ext_path": str(bundled).replace("\\", "/"),
            "error": None
        }

    return {"profile_dir": None, "profile_name": None, "ext_path": None, "error": f"Simplify extension ({SIMPLIFY_EXT_ID}) not found in any Chrome profile in {chrome_data}"}


# ─── Temp Profile Builder ───────────────────────────────────────────────────

def _safe_copytree(src: Path, dst: Path):
    """Safely copy directory tree ignoring locked files like LOCK."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            if item.name.upper() in ("LOCK", "LOCKFILE", "LOG", "LOG.OLD"):
                continue
            try:
                shutil.copy2(item, target)
            except Exception:
                try:
                    with open(item, "rb") as f_in, open(target, "wb") as f_out:
                        f_out.write(f_in.read())
                except Exception:
                    pass


def _create_temp_profile(profile_dir: Optional[str] = None) -> str:
    """
    Create a clean temp Chrome profile directory for Playwright.
    Selectively copies Simplify's extension storage and cookies so the authenticated
    session is preserved without copying gigabytes of unrelated browser data.
    """
    dst_root = Path(TEMP_PROFILE_DIR)
    dst_default = dst_root / "Default"
    dst_default.mkdir(parents=True, exist_ok=True)

    if profile_dir and Path(profile_dir).exists():
        src = Path(profile_dir)
        cookies_dst = dst_default / "Network" / "Cookies"
        # If cloned recently (< 30 mins) and cookies exist, reuse immediately to avoid disk lag
        if cookies_dst.exists() and (time.time() - cookies_dst.stat().st_mtime) < 1800:
            return str(dst_root)

        # 1. Selective Simplify Extension Settings
        ext_settings_src = src / "Local Extension Settings" / SIMPLIFY_EXT_ID
        ext_settings_dst = dst_default / "Local Extension Settings" / SIMPLIFY_EXT_ID
        if ext_settings_src.exists():
            _safe_copytree(ext_settings_src, ext_settings_dst)

        # 2. Network Cookies
        net_src = src / "Network"
        net_dst = dst_default / "Network"
        if net_src.exists():
            _safe_copytree(net_src, net_dst)

        # 3. Local Storage leveldb
        ls_src = src / "Local Storage"
        ls_dst = dst_default / "Local Storage"
        if ls_src.exists():
            _safe_copytree(ls_src, ls_dst)

        # 4. Selective IndexedDB (only Simplify-related databases)
        idb_src = src / "IndexedDB"
        idb_dst = dst_default / "IndexedDB"
        if idb_src.exists():
            idb_dst.mkdir(parents=True, exist_ok=True)
            for item in idb_src.iterdir():
                if "simplify" in item.name.lower() or SIMPLIFY_EXT_ID in item.name.lower():
                    target = idb_dst / item.name
                    if item.is_dir():
                        _safe_copytree(item, target)
                    else:
                        shutil.copy2(item, target)

        size_kb = sum(f.stat().st_size for f in dst_default.rglob("*") if f.is_file()) // 1024
        print(f"  [Simplify] ⚡ Cloned lightweight profile state from {src.name} ({size_kb}KB total)")

    # Copy Local State if present
    chrome_data = get_chrome_user_data_dir()
    local_state_src = chrome_data / "Local State"
    local_state_dst = dst_root / "Local State"
    if local_state_src.exists() and not local_state_dst.exists():
        try:
            shutil.copy2(local_state_src, local_state_dst)
        except Exception:
            pass

    return str(dst_root)


# ─── Simplify Cache ─────────────────────────────────────────────────────────
import time

SIMPLIFY_CACHE_FILE = BASE_DIR / "simplify_cache.json"
_SIMPLIFY_MEM_CACHE = {}

def get_cached_simplify_score(url: str, max_age_hours: float = 24.0) -> Optional[dict]:
    """Retrieve verified cached Simplify ATS score if available."""
    clean_url = url.rstrip("/")
    now = time.time()
    if clean_url in _SIMPLIFY_MEM_CACHE:
        entry = _SIMPLIFY_MEM_CACHE[clean_url]
        if now - entry.get("timestamp", 0) < max_age_hours * 3600:
            return entry.get("data")
    if SIMPLIFY_CACHE_FILE.exists():
        try:
            with open(SIMPLIFY_CACHE_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
                if clean_url in disk_data:
                    entry = disk_data[clean_url]
                    if now - entry.get("timestamp", 0) < max_age_hours * 3600:
                        _SIMPLIFY_MEM_CACHE[clean_url] = entry
                        return entry.get("data")
        except Exception:
            pass
    return None

def save_cached_simplify_score(url: str, data: dict):
    """Save verified Simplify score & keywords to memory and disk cache."""
    if not data or not data.get("success"):
        return
    clean_url = url.rstrip("/")
    entry = {
        "timestamp": time.time(),
        "data": data
    }
    _SIMPLIFY_MEM_CACHE[clean_url] = entry
    try:
        disk_data = {}
        if SIMPLIFY_CACHE_FILE.exists():
            with open(SIMPLIFY_CACHE_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
        disk_data[clean_url] = entry
        if len(disk_data) > 100:
            sorted_items = sorted(disk_data.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)
            disk_data = dict(sorted_items[:100])
        with open(SIMPLIFY_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(disk_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Simplify Cache] Note saving cache: {e}")


# ─── Main Reader ────────────────────────────────────────────────────────────

async def read_simplify_score(job_url: str, company: str = "", role: str = "", force_refresh: bool = False) -> dict:
    """
    Reads Simplify ATS match score and missing keywords with intelligent caching:
    1. Checks cache first to avoid redundant browser launches.
    2. Launches Playwright Chromium with Simplify extension only when necessary.
    """
    from playwright.async_api import async_playwright

    # ── Check Cache First ──
    if not force_refresh:
        cached = get_cached_simplify_score(job_url)
        if cached and cached.get("success"):
            print(f"  [Simplify Cache] ⚡ Reusing verified Simplify score ({cached.get('score')}%) for {job_url} (No browser launch)")
            return cached

    load_dotenv()
    email = os.getenv("SIMPLIFY_EMAIL", "")
    password = os.getenv("SIMPLIFY_PASSWORD", "")

    installation = find_simplify_installation()
    if installation.get("error") or not installation.get("ext_path"):
        return {
            "success": False,
            "score": None,
            "missing_keywords": [],
            "matching_keywords": [],
            "error": installation.get("error") or "Simplify extension path not found",
        }

    ext_path = installation["ext_path"]
    profile_dir = installation["profile_dir"]

    # If no local Chrome profile and no credentials in .env, don't spin up empty browser that will time out
    if not profile_dir and not (email and password):
        print("  [Simplify] Bundled extension is unauthenticated without credentials. Skipping browser launch (use 1-Click Bookmarklet or paste keywords).")
        return {
            "success": False,
            "score": None,
            "missing_keywords": [],
            "matching_keywords": [],
            "error": "Simplify extension unauthenticated. Use 1-Click Bookmarklet to sync instantly.",
        }

    print(f"  [Simplify] Using profile '{installation.get('profile_name')}' ({ext_path})")

    temp_profile = _create_temp_profile(profile_dir)

    # Standardize Ashby URLs to /application tab if not already specified
    target_url = job_url
    if "ashbyhq.com" in target_url and not target_url.endswith("/application"):
        target_url = target_url.rstrip("/") + "/application"

    use_headless = (os.environ.get("RENDER") == "true" or
                    sys.platform != "win32" or
                    os.environ.get("HEADLESS_SIMPLIFY", "").lower() == "true")

    launch_args = [
        f"--disable-extensions-except={ext_path}",
        f"--load-extension={ext_path}",
        "--no-first-run",
        "--no-default-browser-check",
    ]
    if use_headless:
        launch_args.extend([
            "--headless=new",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ])

    async with async_playwright() as p:
        try:
            print(f"  [Simplify] Launching Playwright Chromium with Simplify extension (headless={use_headless})...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=temp_profile,
                headless=False,
                ignore_default_args=["--disable-extensions"],
                args=launch_args,
            )
        except Exception as e:
            return {
                "success": False,
                "score": None,
                "missing_keywords": [],
                "matching_keywords": [],
                "error": f"Failed to launch Playwright browser context: {e}",
            }

        try:
            page = await context.new_page()

            # Step 1: Navigate to target job URL directly
            print(f"  [Simplify] Navigating to target job URL: {target_url}")
            try:
                await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
            except Exception as nav_err:
                print(f"  [Simplify] Navigation note: {nav_err}")

            # Step 2: Dynamic wait for Simplify extension shadow root (checks every 500ms up to 2.5s)
            shadow_ready = False
            for _ in range(5):
                shadow_ready = await page.evaluate("""() => {
                    const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                    return !!(host && host.shadowRoot);
                }""")
                if shadow_ready:
                    break
                await page.wait_for_timeout(500)

            if not shadow_ready:
                return {
                    "success": False,
                    "score": None,
                    "missing_keywords": [],
                    "matching_keywords": [],
                    "error": "Simplify extension shadow root was not active on this job page.",
                }

            # Check if shadow root explicitly asks for login
            check_text = await page.evaluate("""() => {
                const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                return host && host.shadowRoot ? host.shadowRoot.textContent : '';
            }""")

            if ("Log in" in check_text or "Log In" in check_text) and "Resume" not in check_text and email and password:
                print(f"  [Simplify] Session unauthenticated. Logging into Simplify ({email})...")
                try:
                    await page.goto("https://simplify.jobs/auth/login", wait_until="domcontentloaded", timeout=12000)
                    await page.wait_for_timeout(1500)
                    email_input = await page.query_selector("#email, input[name='email']")
                    if email_input:
                        await page.fill("#email, input[name='email']", email)
                        await page.fill("#password, input[name='password']", password)
                        await page.click("button[type='submit']")
                        print("  [Simplify] Credentials submitted, waiting for redirect...")
                        await page.wait_for_timeout(3000)
                except Exception as auth_err:
                    print(f"  [Simplify] Auth step note: {auth_err}")

                print(f"  [Simplify] Returning to target job URL: {target_url}")
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
                except Exception:
                    pass
                await page.wait_for_timeout(2000)

            # Step 3a: Click top 'Resume Score' tab button
            await page.evaluate("""() => {
                const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                if (!host || !host.shadowRoot) return;
                const buttons = Array.from(host.shadowRoot.querySelectorAll('button, a, div, span'));
                const scoreTab = buttons.find(b => b.textContent.trim() === 'Resume Score');
                if (scoreTab) scoreTab.click();
            }""")
            await page.wait_for_timeout(1500)

            # Step 3b: Click 'View resume score' sub-button to expand the full keyword drawer
            await page.evaluate("""() => {
                const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                if (!host || !host.shadowRoot) return;
                const buttons = Array.from(host.shadowRoot.querySelectorAll('button'));
                const viewScoreBtn = buttons.find(b => (b.getAttribute('aria-label') || '').toLowerCase().includes('view resume score') ||
                                                      b.textContent.toLowerCase().includes('only matches'));
                if (viewScoreBtn) viewScoreBtn.click();
            }""")
            await page.wait_for_timeout(2500)

            # Step 4: Extract exact score & exact keyword chips directly from expanded Shadow DOM
            extraction = {"found": False}
            for attempt in range(6):
                extraction = await page.evaluate("""() => {
                    const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                    if (!host || !host.shadowRoot) return { found: false };

                    const fullText = host.shadowRoot.textContent || '';

                    let score = null;
                    const scoreMatch = fullText.match(/(\\d{1,3})\\s*(?:Low|Strong|Excellent|\\s*%|\\s*Resume Match)/i) || fullText.match(/(?:Score|Match)[^\\d]*(\\d{1,3})/i);
                    if (scoreMatch) {
                        const parsed = parseInt(scoreMatch[1]);
                        if (parsed >= 0 && parsed <= 100) score = parsed;
                    }

                    const missingKeywords = [];
                    const matchingKeywords = [];

                    // Target Simplify rounded-full chip spans
                    const chipSpans = Array.from(host.shadowRoot.querySelectorAll('span.rounded-full, span[class*="rounded-full"]'));

                    for (const el of chipSpans) {
                        const txt = el.textContent.replace(/\\s+/g, ' ').trim();
                        if (!txt || txt.length < 2 || txt.length > 50) continue;

                        const cls = (el.className || '').toString();

                        // Matched chips have bg-primary-lightest / border-primary-dark
                        if (cls.includes('bg-primary-lightest') || cls.includes('border-primary-dark') || cls.includes('text-primary-dark')) {
                            matchingKeywords.push(txt);
                        }
                        // Missing chips have bg-white / border-[#eceff5]
                        else if (cls.includes('bg-white') || cls.includes('border-[#eceff5]') || cls.includes('border-[#e2e8f0]')) {
                            missingKeywords.push(txt);
                        }
                        else {
                            // Fallback based on text color or class
                            if (cls.includes('primary') || cls.includes('emerald')) matchingKeywords.push(txt);
                            else missingKeywords.push(txt);
                        }
                    }

                    return {
                        found: true,
                        score,
                        missingKeywords: [...new Set(missingKeywords)],
                        matchingKeywords: [...new Set(matchingKeywords)],
                        fullTextSnippet: fullText.substring(0, 500)
                    };
                }""")

                if extraction.get("found") and (extraction.get("missingKeywords") or extraction.get("matchingKeywords")):
                    break
                await page.wait_for_timeout(1000)

            if not extraction.get("found"):
                print("  [Simplify] Simplify shadow root not found in DOM.")
                return {
                    "success": False,
                    "score": None,
                    "missing_keywords": [],
                    "matching_keywords": [],
                    "error": "Simplify extension overlay was not found on the job page.",
                }

            score = extraction.get("score")
            missing_keywords = extraction.get("missingKeywords", [])
            matching_keywords = extraction.get("matchingKeywords", [])

            # Only filter out Simplify extension UI button texts (never filter tech/domain terms)
            ui_button_terms = {
                "preview resume", "tailor resume", "candidate_resume", "resume", "report", "autofill",
                "resume score", "profile", "feedback", "help", "log in", "login", "simplify"
            }
            missing_keywords = [k for k in missing_keywords if k.lower().strip() not in ui_button_terms]
            matching_keywords = [k for k in matching_keywords if k.lower().strip() not in ui_button_terms]

            print(f"  [Simplify] Real Score Extracted: {score}%")
            print(f"  [Simplify] Missing Keywords ({len(missing_keywords)}): {missing_keywords}")
            print(f"  [Simplify] Matching Keywords ({len(matching_keywords)}): {matching_keywords}")

            result = {
                "success": True,
                "score": score,
                "missing_keywords": missing_keywords,
                "matching_keywords": matching_keywords,
                "error": None,
            }

            # Save to persistent cache so future runs reuse this score without browser popups
            save_cached_simplify_score(job_url, result)

            return result

        finally:
            await context.close()


def read_simplify_score_sync(job_url: str, company: str = "", role: str = "") -> dict:
    """Synchronous wrapper around read_simplify_score()."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    return loop.run_until_complete(read_simplify_score(job_url, company, role))


# ─── Quick Test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    test_url = sys.argv[1] if len(sys.argv) > 1 else "https://jobs.ashbyhq.com/infinity-constellation/135ae1c1-8665-484c-99a4-7086b05d20b5/application"
    print(f"\nTesting simplify_reader.py on: {test_url}\n")
    res = read_simplify_score_sync(test_url)
    print("\nFINAL RESULT:")
    print(json.dumps(res, indent=2))
