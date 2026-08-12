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

# ─── Paths ──────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
CHROME_USER_DATA = r"C:\Users\Dell\AppData\Local\Google\Chrome\User Data"
SIMPLIFY_PROFILE = "Profile 8"
SIMPLIFY_PROFILE_DIR = rf"{CHROME_USER_DATA}\{SIMPLIFY_PROFILE}"
SIMPLIFY_EXT_ID = "pbanhockgagggenencehbnadejlgchfc"

def get_simplify_ext_path() -> str:
    """Find the latest Simplify extension directory dynamically (e.g., 3.0.5_0)."""
    ext_dir = Path(CHROME_USER_DATA) / SIMPLIFY_PROFILE / "Extensions" / SIMPLIFY_EXT_ID
    if ext_dir.exists():
        subdirs = [d for d in ext_dir.iterdir() if d.is_dir()]
        if subdirs:
            latest = sorted(subdirs, key=lambda p: p.stat().st_mtime, reverse=True)[0]
            return str(latest).replace("\\", "/")
    return f"C:/Users/Dell/AppData/Local/Google/Chrome/User Data/{SIMPLIFY_PROFILE}/Extensions/{SIMPLIFY_EXT_ID}/3.0.5_0"

SIMPLIFY_EXT_PATH = get_simplify_ext_path()
TEMP_PROFILE_DIR = str(BASE_DIR / "chrome_profile_simplify")


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
            if item.name.upper() == "LOCK":
                continue
            try:
                shutil.copy2(item, target)
            except Exception:
                try:
                    with open(item, "rb") as f_in, open(target, "wb") as f_out:
                        f_out.write(f_in.read())
                except Exception:
                    pass


def _create_temp_profile() -> str:
    """
    Create a clean temp Chrome profile directory for Playwright.
    Copies Simplify's extension storage (chrome.storage.local) which holds
    user settings, token state, and extension data.
    """
    src = Path(SIMPLIFY_PROFILE_DIR)
    dst_root = Path(TEMP_PROFILE_DIR)
    dst_default = dst_root / "Default"
    dst_default.mkdir(parents=True, exist_ok=True)

    # Copy Simplify extension local storage safely
    ext_storage_src = src / "Local Extension Settings" / SIMPLIFY_EXT_ID
    ext_storage_dst = dst_default / "Local Extension Settings" / SIMPLIFY_EXT_ID
    if ext_storage_src.exists():
        try:
            if ext_storage_dst.exists():
                shutil.rmtree(ext_storage_dst, ignore_errors=True)
            _safe_copytree(ext_storage_src, ext_storage_dst)
            size_kb = sum(f.stat().st_size for f in ext_storage_src.rglob("*") if f.is_file()) // 1024
            print(f"  [Simplify] Copied extension storage ({size_kb}KB)")
        except Exception as e:
            print(f"  [Simplify] Warning copying extension storage: {e}")

    # Copy Local State
    local_state_src = Path(CHROME_USER_DATA) / "Local State"
    local_state_dst = dst_root / "Local State"
    if local_state_src.exists() and not local_state_dst.exists():
        try:
            shutil.copy2(local_state_src, local_state_dst)
        except Exception:
            pass

    return str(dst_root)


# ─── Main Reader ────────────────────────────────────────────────────────────

async def read_simplify_score(job_url: str, company: str = "", role: str = "") -> dict:
    """
    Reads Simplify ATS match score and missing keywords:
    1. Launches Playwright Chromium with Simplify extension.
    2. Opens job application page.
    3. Clicks top 'Resume Score' tab in Simplify extension sidebar.
    4. Parses exact matching and missing keyword chips directly from shadow DOM CSS classes.
    """
    from playwright.async_api import async_playwright

    load_dotenv()
    email = os.getenv("SIMPLIFY_EMAIL", "")
    password = os.getenv("SIMPLIFY_PASSWORD", "")

    ext_path = get_simplify_ext_path()
    if not Path(ext_path).exists():
        return {
            "success": False,
            "score": None,
            "missing_keywords": [],
            "matching_keywords": [],
            "error": f"Simplify extension path not found: {ext_path}",
        }

    temp_profile = _create_temp_profile()

    # Standardize Ashby URLs to /application tab if not already specified
    target_url = job_url
    if "ashbyhq.com" in target_url and not target_url.endswith("/application"):
        target_url = target_url.rstrip("/") + "/application"

    async with async_playwright() as p:
        try:
            print("  [Simplify] Launching Playwright Chromium with Simplify extension...")
            context = await p.chromium.launch_persistent_context(
                user_data_dir=temp_profile,
                headless=False,
                ignore_default_args=["--disable-extensions"],
                args=[
                    f"--disable-extensions-except={ext_path}",
                    f"--load-extension={ext_path}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ],
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

            # Wait for Simplify extension to hydrate local storage token
            await page.wait_for_timeout(4500)

            # Check if shadow root explicitly asks for login
            check_text = await page.evaluate("""() => {
                const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                return host && host.shadowRoot ? host.shadowRoot.textContent : '';
            }""")

            # Step 2: If explicitly unauthenticated, log in on simplify.jobs and return
            if ("Log in" in check_text or "Log In" in check_text) and "Resume" not in check_text and email and password:
                print(f"  [Simplify] Session unauthenticated. Logging into Simplify ({email})...")
                try:
                    await page.goto("https://simplify.jobs/auth/login", wait_until="domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2000)
                    email_input = await page.query_selector("#email, input[name='email']")
                    if email_input:
                        await page.fill("#email, input[name='email']", email)
                        await page.fill("#password, input[name='password']", password)
                        await page.click("button[type='submit']")
                        print("  [Simplify] Credentials submitted, waiting for dashboard redirect...")
                        await page.wait_for_timeout(4000)
                except Exception as auth_err:
                    print(f"  [Simplify] Auth step note: {auth_err}")

                print(f"  [Simplify] Returning to target job URL: {target_url}")
                try:
                    await page.goto(target_url, wait_until="domcontentloaded", timeout=25000)
                except Exception:
                    pass
                await page.wait_for_timeout(6000)

            # Step 3: Wait for Simplify shadow root and expand 'Resume Score' drawer
            print("  [Simplify] Waiting for Simplify shadow root and expanding 'Resume Score' drawer...")
            
            # Wait for shadow root attachment
            shadow_ready = False
            for _ in range(10):
                shadow_ready = await page.evaluate("""() => {
                    const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                    return !!(host && host.shadowRoot);
                }""")
                if shadow_ready:
                    break
                await page.wait_for_timeout(1000)

            if not shadow_ready:
                return {
                    "success": False,
                    "score": None,
                    "missing_keywords": [],
                    "matching_keywords": [],
                    "error": "Simplify extension shadow root was not found on the job page.",
                }

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
                "preview resume", "tailor resume", "jalal_khan_resume", "report", "autofill",
                "resume score", "profile", "feedback", "help", "log in", "login", "simplify"
            }
            missing_keywords = [k for k in missing_keywords if k.lower().strip() not in ui_button_terms]
            matching_keywords = [k for k in matching_keywords if k.lower().strip() not in ui_button_terms]

            print(f"  [Simplify] Real Score Extracted: {score}%")
            print(f"  [Simplify] Missing Keywords ({len(missing_keywords)}): {missing_keywords}")
            print(f"  [Simplify] Matching Keywords ({len(matching_keywords)}): {matching_keywords}")

            return {
                "success": True,
                "score": score,
                "missing_keywords": missing_keywords,
                "matching_keywords": matching_keywords,
                "error": None,
            }

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
