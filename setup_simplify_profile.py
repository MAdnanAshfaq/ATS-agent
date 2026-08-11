"""
setup_simplify_profile.py — One-time setup: creates a dedicated Chrome profile for Simplify.
Run this ONCE before using the agent.

Instructions:
1. Run: python setup_simplify_profile.py
2. A Chrome window opens
3. Go to Chrome Web Store and install the Simplify extension
4. Log into simplify.jobs
5. Close the window
6. The profile is saved and will be reused by the agent.
"""
import asyncio
import os
from pathlib import Path


CHROME_PROFILE_DIR = os.path.join(os.path.dirname(__file__), "chrome_profile")


async def setup():
    from playwright.async_api import async_playwright
    
    profile_path = Path(CHROME_PROFILE_DIR)
    profile_path.mkdir(parents=True, exist_ok=True)
    
    print("=" * 60)
    print("SIMPLIFY CHROME PROFILE SETUP")
    print("=" * 60)
    print(f"Profile will be saved to: {CHROME_PROFILE_DIR}")
    print()
    print("A Chrome window will open. Please:")
    print("1. Go to: https://chromewebstore.google.com/")
    print("   Search for 'Simplify Jobs' and install the extension")
    print("2. Go to: https://simplify.jobs and log in with your account")
    print("3. Navigate to a job and check that the Simplify extension shows a score")
    print("4. CLOSE the Chrome window when done")
    print()
    print("Opening Chrome now...")
    
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(profile_path),
            headless=False,
            channel="chrome",
            args=[
                "--no-first-run",
                "--no-default-browser-check",
            ],
            viewport={"width": 1400, "height": 900},
            slow_mo=100,
        )
        
        page = await context.new_page()
        await page.goto("https://simplify.jobs", wait_until="domcontentloaded", timeout=30000)
        
        print("\n[Setup] Chrome is open. Complete setup steps, then close the browser.")
        print("[Setup] Waiting for you to close the browser...")
        
        # Wait until the browser is closed by the user
        try:
            while True:
                await asyncio.sleep(2)
                pages = context.pages
                if not pages:
                    break
        except Exception:
            pass
        
        try:
            await context.close()
        except Exception:
            pass
    
    print(f"\n[Setup] ✅ Chrome profile saved to: {CHROME_PROFILE_DIR}")
    print("[Setup] You can now run: python agent.py --url YOUR_JD_URL")


if __name__ == "__main__":
    asyncio.run(setup())
