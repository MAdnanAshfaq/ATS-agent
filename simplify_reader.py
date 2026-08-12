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

    # Copy Simplify extension local storage
    ext_storage_src = src / "Local Extension Settings" / SIMPLIFY_EXT_ID
    ext_storage_dst = dst_default / "Local Extension Settings" / SIMPLIFY_EXT_ID
    if ext_storage_src.exists():
        try:
            if ext_storage_dst.exists():
                shutil.rmtree(ext_storage_dst, ignore_errors=True)
            shutil.copytree(ext_storage_src, ext_storage_dst)
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

            # Step 3: Wait for Simplify shadow root and click top 'Resume Score' tab
            print("  [Simplify] Waiting for Simplify shadow root and switching to 'Resume Score' tab...")
            
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

            # Click top 'Resume Score' tab button
            await page.evaluate("""() => {
                const host = document.querySelector('div.simplify-jobs-shadow-root') || document.querySelector('#simplify-jobs-shadow-root');
                if (!host || !host.shadowRoot) return;
                const buttons = Array.from(host.shadowRoot.querySelectorAll('button'));
                const scoreTab = buttons.find(b => b.textContent.trim() === 'Resume Score');
                if (scoreTab) scoreTab.click();
            }""")
            await page.wait_for_timeout(3500)

            # Step 4: Extract score & exact keyword chips directly from Shadow DOM
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

                // ── Strategy 1: Find elements by CSS class/rounded pills ──
                const allElements = Array.from(host.shadowRoot.querySelectorAll('span, button, div, a, p, li'));

                for (const el of allElements) {
                    const cls = (el.className || '').toString();

                    // Only target leaf-like text nodes (no heavy container divs)
                    if (el.querySelectorAll('div, section, p').length > 0) continue;

                    const txt = el.textContent.replace(/\\s+/g, ' ').trim();
                    if (!txt || txt.length < 2 || txt.length > 60) continue;

                    const lower = txt.toLowerCase();
                    if (lower.includes('resume match') || lower.includes('autofill') || lower.includes('apply') ||
                        lower.includes('submit') || lower.includes('feedback') || lower.includes('report') ||
                        lower.includes('simplify') || lower.includes('login') || lower.startsWith('http')) {
                        continue;
                    }

                    // Check for chip / badge / pill classes in Simplify
                    const isChip = cls.includes('rounded') || cls.includes('chip') || cls.includes('badge') || cls.includes('pill') || cls.includes('tag');

                    if (isChip) {
                        // Clean out any icon text or extra spaces
                        const cleanKw = txt.replace(/^[✓✔✕✖×+•\\-\\s]+/, '').replace(/[✓✔✕✖×+•\\-\\s]+$/, '').trim();
                        if (cleanKw.length >= 2 && cleanKw.length <= 50) {
                            // Determine matched vs missing by color / background / border or section parent
                            const parentText = (el.parentElement ? el.parentElement.textContent : '').toLowerCase();
                            const isMissingSection = parentText.includes('missing') || lower.includes('missing');
                            const isMatchedSection = parentText.includes('matched') || parentText.includes('matching') || lower.includes('matched');

                            if (isMissingSection) {
                                missingKeywords.push(cleanKw);
                            } else if (isMatchedSection) {
                                matchingKeywords.push(cleanKw);
                            } else if (cls.includes('bg-primary') || cls.includes('border-primary') || cls.includes('text-primary') || cls.includes('green') || cls.includes('emerald') || cls.includes('success')) {
                                matchingKeywords.push(cleanKw);
                            } else {
                                missingKeywords.push(cleanKw);
                            }
                        }
                    }
                }

                // ── Strategy 2: Fallback — parse text sections directly from Shadow DOM ──
                if (missingKeywords.length === 0 && matchingKeywords.length === 0) {
                    // Try parsing sections by looking at headers inside shadow root
                    const headers = Array.from(host.shadowRoot.querySelectorAll('h1, h2, h3, h4, h5, h6, strong, b, div'));
                    let currentSection = null;

                    for (const node of headers) {
                        const t = node.textContent.trim().toLowerCase();
                        if (t.includes('missing') && (t.includes('keyword') || t.includes('skill'))) {
                            currentSection = 'missing';
                            continue;
                        }
                        if ((t.includes('matched') || t.includes('matching')) && (t.includes('keyword') || t.includes('skill'))) {
                            currentSection = 'matching';
                            continue;
                        }

                        if (currentSection) {
                            const siblings = Array.from(node.querySelectorAll('span, button, div') || []);
                            for (const sib of siblings) {
                                const kw = sib.textContent.replace(/^[✓✔✕✖×+•\\-\\s]+/, '').trim();
                                if (kw.length >= 2 && kw.length <= 40) {
                                    if (currentSection === 'missing') missingKeywords.push(kw);
                                    else if (currentSection === 'matching') matchingKeywords.push(kw);
                                }
                            }
                        }
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

            # Filter out non-keyword UI text & generic filler words
            skip_terms = {
                "jalal_khan_resume", "report", "autofill", "resume score", "profile", "feedback", "help",
                "responsiveness", "knowledge", "leading", "work", "code", "ensure", "ensuring",
                "optimize", "optimizing", "integrating", "integration", "current", "design",
                "dynamic", "using", "use", "building", "build", "developing", "development",
                "maintaining", "maintenance", "collaborating", "collaboration", "implementing",
                "implementation", "understanding", "working", "deliver", "delivering", "create",
                "creating", "manage", "managing", "management", "provide", "providing",
                "support", "supporting", "help", "helping", "drive", "driving", "write",
                "writing", "test", "testing", "solution", "solutions", "platform", "platforms",
                "system", "systems", "application", "applications", "user", "users", "feature",
                "features", "requirement", "requirements", "quality", "process", "environment",
                "architecture", "teams", "player", "communication", "skills", "ability",
                "strong", "great", "good", "well", "experience", "candidate", "position", "job",
                "opportunity", "company", "including", "required", "preferred", "bonus", "etc"
            }
            missing_keywords = [k for k in missing_keywords if k.lower().strip() not in skip_terms]
            matching_keywords = [k for k in matching_keywords if k.lower().strip() not in skip_terms]

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
