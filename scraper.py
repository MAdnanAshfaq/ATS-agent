"""
scraper.py — Job Description scraper using Playwright + BeautifulSoup
Supports: LinkedIn, Lever, Greenhouse, Workday, Wellfound, and generic ATS portals.
"""
import asyncio
import re
from typing import Optional
from bs4 import BeautifulSoup


# Platform-specific selectors for clean JD extraction
PLATFORM_SELECTORS = {
    "linkedin.com": {
        "jd": [
            ".jobs-description__content",
            ".job-view-layout__content",
            ".jobs-box__html-content",
            "[class*='description__text']",
        ],
        "title": [".jobs-unified-top-card__job-title", "h1.t-24"],
        "company": [".jobs-unified-top-card__company-name", ".topcard__org-name-link"],
    },
    "lever.co": {
        "jd": [".content", ".posting-page .section-wrapper"],
        "title": [".posting-headline h2"],
        "company": [".posting-headline .posting-category"],
    },
    "greenhouse.io": {
        "jd": ["#content", ".content"],
        "title": ["h1.app-title"],
        "company": [".company-name"],
    },
    "myworkdayjobs.com": {
        "jd": ["[data-automation-id='jobPostingDescription']"],
        "title": ["[data-automation-id='jobPostingHeader']"],
        "company": ["[data-automation-id='company']"],
    },
    "workday.com": {
        "jd": ["[data-automation-id='jobPostingDescription']"],
        "title": ["[data-automation-id='jobPostingHeader']"],
        "company": [],
    },
    "wellfound.com": {
        "jd": [".job-description", ".styles_description__"],
        "title": ["h1"],
        "company": [".styles_company__"],
    },
    "ashbyhq.com": {
        "jd": [
            "div[class*='job-posting']",
            "div[class*='posting']",
            "main",
            "#app",
        ],
        "title": ["h1"],
        "company": ["h2", "[class*='company']"],
    },
    "notion.site": {
        "jd": ["main", ".notion-scroller", ".notion-page-content", "body"],
        "title": ["h1.notion-header__title", "h1", "title"],
        "company": [".notion-header__company"],
    },
    "notion.so": {
        "jd": ["main", ".notion-scroller", ".notion-page-content", "body"],
        "title": ["h1.notion-header__title", "h1", "title"],
        "company": [".notion-header__company"],
    },
    "smartrecruiters.com": {
        "jd": [".job-sections", "[class*='job-description']"],
        "title": ["h1.job-title"],
        "company": ["[class*='company-name']"],
    },
    "icims.com": {
        "jd": [".iCIMS_JobContent"],
        "title": ["h1.iCIMS_Header"],
        "company": [],
    },
}

GENERIC_JD_SELECTORS = [
    "main", "article", ".job-description", "#job-description",
    "[class*='description']", "[class*='job-details']", "[id*='description']",
    ".posting-content", ".job-content", "#jobDescriptionText",
]


def detect_platform(url: str) -> Optional[str]:
    """Detect which ATS platform the URL belongs to."""
    for platform in PLATFORM_SELECTORS:
        if platform in url:
            return platform
    return None


def sanitize_jd_url(url: str) -> str:
    """
    Strip login-redirect segments and auth/tracking query params from ATS URLs
    so the scraper hits the actual job posting, not a login or application form.

    Examples fixed:
      iCIMS:  /jobs/9070/data-analytics-engineer/candidate?from=login&csrf=... → /jobs/9070/data-analytics-engineer
      Generic: ?from=login&token=xxx&redirect=... → base URL only
    """
    from urllib.parse import urlparse, urlencode, parse_qs

    # Path segments that indicate an application/login page, not the JD itself
    PATH_JUNK_SEGMENTS = (
        "/candidate", "/apply", "/application", "/login", "/submit",
        "/confirm", "/register", "/auth",
    )
    # Query params that signal a redirect/session, not the JD content
    AUTH_PARAMS = {
        "from", "csrf", "hashed", "uploadresume", "token", "redirect",
        "session", "returnurl", "returnto", "state", "nonce", "code",
    }

    parsed = urlparse(url)
    path = parsed.path

    # Strip trailing junk path segments (e.g. /candidate, /apply)
    for seg in PATH_JUNK_SEGMENTS:
        if path.lower().endswith(seg):
            path = path[: -len(seg)]
            break  # Only strip one segment at a time; re-check iteratively
        # Also handle mid-path: /jobs/123/title/candidate → /jobs/123/title
        idx = path.lower().find(seg + "/")
        if idx >= 0:
            path = path[:idx]
            break

    # Strip auth/tracking query params
    qs = parse_qs(parsed.query, keep_blank_values=False)
    clean_qs = {k: v for k, v in qs.items() if k.lower() not in AUTH_PARAMS}
    clean_query = urlencode(clean_qs, doseq=True)

    # Rebuild URL
    clean_url = parsed._replace(path=path, query=clean_query).geturl()
    if clean_url != url:
        print(f"[Scraper] URL sanitized: {url} → {clean_url}")
    return clean_url


def clean_text(text: str) -> str:
    """Remove excess whitespace, unicode artifacts, and normalize text."""
    if not text:
        return ""
    # Normalize whitespace
    text = re.sub(r'\r\n|\r', '\n', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    # Remove unicode artifacts
    text = text.replace('\u00a0', ' ')
    text = text.replace('\u2019', "'")
    text = text.replace('\u2018', "'")
    text = text.replace('\u201c', '"')
    text = text.replace('\u201d', '"')
    text = text.replace('\u2013', '-')
    text = text.replace('\u2014', '-')

    # Strip short EEOC / Legal Disclaimer / Form Field noise lines (< 150 chars)
    clean_lines = []
    for line in text.split('\n'):
        l_lower = line.lower().strip()
        if len(line) < 150 and any(noise in l_lower for noise in [
            "equal opportunity employer", "affirmative action", "veteran status",
            "paperwork reduction act", "executive order", "readjustment assistance",
            "vietnam era", "race, color, religion", "sexual orientation", "gender identity",
            "disability status", "cover letter drag", "gender select", "profile education add",
            "experience add resume", "personal information first"
        ]):
            continue
        clean_lines.append(line)

    return "\n".join(clean_lines).strip()


def clean_role_title(role: str, company: str = "") -> str:
    """Clean job role title by removing parenthetical suffixes, brackets, location tags, ATS noise words, etc."""
    if not role:
        return "Software Engineer"
    
    # 1. Remove bracketed / parenthetical text e.g. (Databricks), [Remote], (AI/ML)
    role = re.sub(r'[\(\[\{].*?[\)\]\}]', '', role)
    
    # 2. Handle prefix noise like 'Job Application for AI Engineer'
    role = re.sub(r'^(?:job application for|job posting for|opening for|hiring for|apply for)\s+', '', role, flags=re.IGNORECASE)
    
    # 3. Handle 'Role at Company' or 'Role @ Company'
    role = re.split(r'\s+(?:at|@)\s+', role, flags=re.IGNORECASE)[0]
    
    # 4. Handle pipes/dashes: 'AI Engineer | Careers | Tradeify' -> 'AI Engineer'
    parts = [p.strip() for p in re.split(r'\s*[|•–—]\s*', role) if p.strip()]
    noise_words = {
        'careers', 'jobs', 'job', 'opportunities', 'hiring', 'apply', 'openings',
        'working at', 'overview', 'job description', 'lever', 'greenhouse', 'ashby',
        'workday', 'smartrecruiters', 'linkedin', 'join us', 'career', 'employment',
        'recruitment', 'work with us', 'portal'
    }
    valid_parts = []
    for p in parts:
        p_clean = p.strip(' -–—|/,:;')
        if p_clean.lower() in noise_words:
            continue
        if company and p_clean.lower() == company.lower():
            continue
        valid_parts.append(p_clean)
    
    role = valid_parts[0] if valid_parts else (parts[0] if parts else role)
    
    # 5. Remove trailing suffixes like '- Remote', ' - Full Time', ' - US'
    role = re.sub(r'\s*[-–—|/]\s*(?:remote|hybrid|onsite|full[- ]?time|contract|part[- ]?time|intern|internship|us|usa|uk|canada|emea|latam|apac|tier\s*\d+|l\d+|level\s*\d+|requisition\s*#?\s*\d+|req\s*#?\s*\d+|req\d+|job\s*id\s*\d+|careers?).*$', '', role, flags=re.IGNORECASE)
    
    # 6. Strip leftover punctuation and spaces
    role = re.sub(r'\s+', ' ', role).strip(' -–—|/,:;')
    
    return role or "Software Engineer"


def validate_jd_extraction(text: str) -> tuple[bool, str]:
    """
    Gate that catches bot-block/error pages masquerading as JD content.
    Returns (is_valid, reason).
    A 403 error page is typically 200-600 chars; a real JD is almost always 800+.
    """
    ERROR_SIGNATURES = [
        "403 forbidden", "access denied", "just a moment",
        "enable javascript", "captcha", "robot",
        "checking your browser", "attention required", "error 403",
        "you have been blocked", "security check", "cloudflare",
        "verify you are human", "ddos protection",
        "browser check", "your request has been blocked",
        "human verification", "please verify", "are you a human",
        "temporary unavailable", "service unavailable", "502 bad gateway",
        "page not found", "404 not found",
    ]
    # Role titles that indicate we scraped a CAPTCHA or error page, not a job posting
    BOT_ROLE_TITLES = {
        "human verification", "access denied", "just a moment",
        "403 forbidden", "error", "captcha", "attention required",
        "security check", "checking your browser", "please wait",
        "page not found", "404", "502",
    }
    stripped = text.strip()
    if len(stripped) < 800:
        return False, (
            f"Extracted only {len(stripped)} characters — suspiciously short for a real JD. "
            "The site likely returned a bot-block or error page instead of the job description."
        )
    text_lower = stripped.lower()
    for sig in ERROR_SIGNATURES:
        if sig in text_lower:
            return False, f"Content matches a known error/bot-block pattern: '{sig}'"
    return True, "OK"


def validate_role_title(role: str) -> tuple[bool, str]:
    """Check if the extracted role title looks like a real job title, not a CAPTCHA/error page."""
    BOT_ROLE_TITLES = {
        "human verification", "access denied", "just a moment",
        "403 forbidden", "error", "captcha", "attention required",
        "security check", "checking your browser", "please wait",
        "page not found", "404", "502", "loading", "redirecting",
        "verification required", "login", "sign in", "signin",
    }
    role_lower = role.strip().lower()
    for bad in BOT_ROLE_TITLES:
        if bad in role_lower:
            return False, f"Role title '{role}' looks like a bot-block page, not a real job title."
    return True, "OK"



def extract_company_from_url(url: str) -> str:
    """Try to extract company name from URL."""
    # lever: jobs.lever.co/company/role
    lever = re.search(r'lever\.co/([^/]+)', url)
    if lever:
        return lever.group(1).replace('-', ' ').title()
    
    # greenhouse: boards.greenhouse.io/company
    greenhouse = re.search(r'greenhouse\.io/([^/]+)', url)
    if greenhouse:
        return greenhouse.group(1).replace('-', ' ').title()
    
    # wellfound: wellfound.com/company/company-name/jobs/role
    wellfound = re.search(r'wellfound\.com/company/([^/]+)', url)
    if wellfound:
        return wellfound.group(1).replace('-', ' ').title()
    
    # ashby: jobs.ashbyhq.com/company/role
    ashby = re.search(r'ashbyhq\.com/([^/]+)', url)
    if ashby:
        return ashby.group(1).replace('-', ' ').title()
    
    # notion: company.notion.site/role
    notion = re.search(r'https?://([^/]+)\.notion\.(?:site|so)', url)
    if notion:
        name = notion.group(1).replace('-', ' ').title()
        if name.lower().endswith("ai"):
            name = name[:-2].strip().title()
        if name and name.lower() != "www":
            return name
    
    # generic: extract domain
    domain = re.search(r'https?://(?:www\.|jobs\.)?([^./]+)', url)
    if domain:
        return domain.group(1).replace('-', ' ').title()
    
    return "Unknown Company"


def fetch_notion_via_api(url: str) -> Optional[dict]:
    """Instant 200ms REST API fetch for Notion pages (.notion.site or .notion.so)."""
    match = re.search(r'([a-f0-9]{32})', url)
    if not match:
        return None
    page_id = match.group(1)
    uuid_str = f"{page_id[:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:]}"
    try:
        import requests
        api_url = "https://www.notion.so/api/v3/loadPageChunk"
        payload = {"pageId": uuid_str, "chunkIndex": 0, "limit": 100, "verticalColumns": False}
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36"
        }
        res = requests.post(api_url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            blocks = res.json().get("recordMap", {}).get("block", {})
            text_lines = []
            role = ""
            for b_id, b_obj in blocks.items():
                val = b_obj.get("value", {})
                if isinstance(val, dict) and "value" in val:
                    val = val["value"]
                if isinstance(val, dict) and "properties" in val:
                    title_prop = val["properties"].get("title", [])
                    line_parts = []
                    for chunk in title_prop:
                        if isinstance(chunk, list) and len(chunk) > 0 and isinstance(chunk[0], str):
                            line_parts.append(chunk[0])
                    if line_parts:
                        line_str = "".join(line_parts).strip()
                        if not role and len(line_str) < 80 and "career" not in line_str.lower():
                            role = line_str
                        text_lines.append(line_str)
            full_txt = "\n".join(text_lines)
            full_txt = clean_text(full_txt)
            if len(full_txt) >= 100:
                company = extract_company_from_url(url)
                if not role or role.lower() == company.lower():
                    role = "Full Stack Engineer"
                folder_name = f"{slugify(company)}_{slugify(role)}"[:80]
                print(f"[Scraper] Instant Notion API extraction ({len(full_txt)} chars)")
                return {
                    "url": url,
                    "company": company,
                    "role": role,
                    "jd_text": full_txt,
                    "folder_name": folder_name,
                }
    except Exception as e:
        print(f"[Scraper] Notion API fallback note: {e}")
    return None


def slugify(text: str) -> str:
    """Convert text to a safe folder name."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_')


async def scrape_jd(url: str) -> dict:
    """
    Main scraping function.
    """
    from playwright.async_api import async_playwright
    
    scrape_url = url.rstrip("/")

    # ── Sanitize URL first: strip login-redirect params and /candidate path segments ──
    scrape_url = sanitize_jd_url(scrape_url)

    if "ashbyhq.com" in scrape_url and scrape_url.endswith("/application"):
        scrape_url = scrape_url[:-12]

    # Fast path for Notion pages via Notion REST API
    if "notion.site" in scrape_url or "notion.so" in scrape_url:
        notion_data = fetch_notion_via_api(scrape_url)
        if notion_data:
            return notion_data

    print(f"[Scraper] Opening: {scrape_url}")
    platform = detect_platform(scrape_url)
    if platform:
        print(f"[Scraper] Detected platform: {platform}")
    else:
        print("[Scraper] Unknown platform — using generic extraction")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
                '--disable-dev-shm-usage',
            ]
        )
        # Use a realistic browser context to avoid bot-detection fingerprinting
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="America/New_York",
            viewport={"width": 1280, "height": 800},
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        page = await context.new_page()

        # Smart navigation using wait_until="domcontentloaded"
        try:
            await page.goto(scrape_url, wait_until="domcontentloaded", timeout=15000)
        except Exception as e:
            print(f"[Scraper] Page goto note: {e} — proceeding with rendered DOM")

        # Allow SPA JavaScript (Notion / React / Vue) 4s to hydrate the DOM
        await asyncio.sleep(4)
        
        # Get full page HTML safely (handles client-side navigation/redirects)
        html = ""
        title = ""
        try:
            html = await page.content()
            title = await page.title()
        except Exception:
            await asyncio.sleep(2)
            try:
                html = await page.content()
                title = await page.title()
            except Exception as nav_err:
                print(f"[Scraper] Content fetch error: {nav_err}")

        if title and ("just a moment" in title.lower() or "attention required" in title.lower()):
            await asyncio.sleep(2.5)
            try:
                html = await page.content()
                title = await page.title()
            except Exception:
                pass

        print(f"[Scraper DEBUG] Raw HTML fetched len: {len(html)}")
        await context.close()
        await browser.close()
    
    # Parse with BeautifulSoup
    soup = BeautifulSoup(html, 'lxml')
    
    # Remove noise elements (keep noscript for Notion/SPA fallbacks)
    for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'iframe', 'svg']):
        tag.decompose()
    
    jd_text = ""
    role = ""
    company = extract_company_from_url(scrape_url)
    
    # Platform-specific extraction
    if platform and platform in PLATFORM_SELECTORS:
        selectors = PLATFORM_SELECTORS[platform]
        
        # Extract JD
        for sel in selectors.get("jd", []):
            el = soup.select_one(sel)
            if el:
                txt = el.get_text(separator='\n').strip()
                print(f"[Scraper DEBUG] Selector '{sel}' found element with {len(txt)} raw chars")
                if len(txt) >= 100:
                    jd_text = txt
                    print(f"[Scraper] Extracted JD via selector: {sel} ({len(txt)} chars)")
                    break
        
        # Extract role title
        for sel in selectors.get("title", []):
            el = soup.select_one(sel)
            if el:
                role = el.get_text().strip()
                break
        
        # Extract company name
        for sel in selectors.get("company", []):
            el = soup.select_one(sel)
            if el:
                company = el.get_text().strip()
                break
    
    # Fallback: generic selectors
    if not jd_text:
        for sel in GENERIC_JD_SELECTORS:
            el = soup.select_one(sel)
            if el and len(el.get_text()) > 200:
                jd_text = el.get_text(separator='\n')
                print(f"[Scraper] Extracted JD via generic selector: {sel}")
                break
    
    # Last resort: full body text
    if not jd_text or len(jd_text) < 100:
        print("[Scraper] Warning: Using full body text — may include noise")
        body = soup.find('body')
        if body:
            jd_text = body.get_text(separator='\n')
            jd_text = clean_text(jd_text)

    # HTTP Fallback if Playwright returned insufficient text
    if not jd_text or len(jd_text) < 100:
        try:
            import urllib.request
            print("[Scraper] Playwright yielded < 100 chars — trying HTTP fetch fallback...")
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36'}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_html = resp.read().decode('utf-8', errors='ignore')
                raw_soup = BeautifulSoup(raw_html, 'lxml')
                for tag in raw_soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'iframe', 'svg']):
                    tag.decompose()
                b = raw_soup.find('body') or raw_soup
                txt = clean_text(b.get_text(separator='\n'))
                if len(txt) >= 100:
                    jd_text = txt
                    print(f"[Scraper] ✅ HTTP fallback extracted {len(jd_text)} chars")
        except Exception as http_err:
            print(f"[Scraper] HTTP fallback note: {http_err}")
            
    # Jina Reader API fallback — bypasses bot-protection via Jina's rendering proxy
    # Trigger threshold raised to 800: anything shorter is likely a bot-block page, not a partial JD
    if not jd_text or len(jd_text) < 800:
        try:
            import urllib.request
            print(f"[Scraper] Extracted only {len(jd_text)} chars — trying Jina Reader API (bot-bypass)...")
            jina_url = "https://r.jina.ai/" + url
            req = urllib.request.Request(
                jina_url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/125.0.0.0 Safari/537.36',
                    'Accept': 'text/plain,text/html,*/*',
                    'Accept-Language': 'en-US,en;q=0.9',
                }
            )
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw_markdown = resp.read().decode('utf-8', errors='ignore')
                txt = clean_text(raw_markdown)
                if len(txt) >= 800:
                    jd_text = txt
                    print(f"[Scraper] ✅ Jina Reader extracted {len(jd_text)} chars")
                else:
                    print(f"[Scraper] Jina Reader also returned short content ({len(txt)} chars)")
        except Exception as jina_err:
            print(f"[Scraper] Jina Reader fallback note: {jina_err}")
    
    # Extract role from page title if not found
    if not role:
        # Common patterns: "Role at Company | Platform" or "Company - Role"
        title_patterns = [
            r'^(.+?)\s+(?:at|@)\s+(.+?)(?:\s*[\|\-]|$)',
            r'^(.+?)\s*[\|\-]\s*(.+?)(?:\s*[\|\-]|$)',
        ]
        for pat in title_patterns:
            m = re.match(pat, title)
            if m:
                role = m.group(1).strip()
                if not company or company == extract_company_from_url(url):
                    company = m.group(2).strip()
                break
        if not role:
            role = title.split('|')[0].split('-')[0].strip()

    # Clean role title from parentheses / brackets / location suffixes
    role = clean_role_title(role)

    # Fallback company name if identical to role
    if not company or (role and company.lower() == role.lower()):
        company = extract_company_from_url(scrape_url)

    jd_text = clean_text(jd_text)

    # ── Validation gate 1: reject bot-block pages ──
    is_valid, reason = validate_jd_extraction(jd_text)
    if not is_valid:
        raise RuntimeError(
            f"JD validation failed: {reason}\n"
            "The career site blocked the scraper or requires login.\n"
            "Fix: Paste the job description text manually into the 'Missing Keywords' field, "
            "or copy the JD text and re-run with --no-simplify."
        )

    # ── Validation gate 2: reject CAPTCHA/error page role titles ──
    role_ok, role_reason = validate_role_title(role)
    if not role_ok:
        raise RuntimeError(
            f"JD validation failed: {role_reason}\n"
            "The URL appears to point to a login/CAPTCHA page, not the job posting.\n"
            "Fix: Open the job in your browser, copy the direct job posting URL "
            "(without /candidate or ?from=login), and paste that instead."
        )

    # Warn on borderline-short JDs (may be partial capture)
    if len(jd_text) < 1500:
        print(f"[Scraper] ⚠ Short JD extracted ({len(jd_text)} chars) — may be partial. Continuing.")

    # Build safe folder name
    folder_name = f"{slugify(company)}_{slugify(role)}"[:80]

    result = {
        "url": url,
        "company": company,
        "role": role,
        "jd_text": jd_text,
        "folder_name": folder_name,
    }

    print(f"[Scraper] [OK] Company: {company}")
    print(f"[Scraper] [OK] Role: {role}")
    print(f"[Scraper] [OK] JD text: {len(jd_text)} characters")

    return result


# Synchronous wrapper for non-async contexts
def scrape_jd_sync(url: str) -> dict:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import nest_asyncio
        nest_asyncio.apply()
        return loop.run_until_complete(scrape_jd(url))
    else:
        return asyncio.run(scrape_jd(url))


if __name__ == "__main__":
    import sys
    test_url = sys.argv[1] if len(sys.argv) > 1 else input("Enter JD URL: ")
    result = scrape_jd_sync(test_url)
    print("\n--- JD TEXT (first 1000 chars) ---")
    print(result['jd_text'][:1000])
