"""
scraper.py — Job Description scraper using Playwright + BeautifulSoup
Supports: LinkedIn, Lever, Greenhouse, Workday, Wellfound, and generic ATS portals.
"""
import asyncio
import re
import sys
from typing import Optional
from bs4 import BeautifulSoup

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


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
            "div[class*='ashby-job-posting']",
            "div[class*='JobPosting']",
            "div[class*='jobPosting']",
            "div[class*='posting']",
            "div[class*='job-description']",
            "main",
            "#app",
        ],
        "title": ["h1", "h1[class*='title']", "title"],
        "company": ["h2", "[class*='company']", "[class*='organization']"],
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
    """
    stripped = text.strip()
    if len(stripped) < 500:
        return False, (
            f"Extracted only {len(stripped)} characters — suspiciously short for a real JD. "
            "The site likely returned a bot-block or error page instead of the job description."
        )

    # Real bot-block error pages are short (< 2000 chars) and contain explicit blocking phrases
    if len(stripped) < 2000:
        ERROR_SIGNATURES = [
            "403 forbidden", "access denied", "just a moment...",
            "enable javascript to continue", "verify you are human",
            "please verify you are a human", "checking your browser before accessing",
            "attention required! | cloudflare", "error 403", "you have been blocked",
            "security check to continue", "human verification",
            "temporary unavailable", "502 bad gateway", "page not found", "404 not found"
        ]
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
    
    # adp: myjobs.adp.com/company/cx/...
    adp = re.search(r'myjobs\.adp\.com/([^/]+)', url)
    if adp:
        c_slug = adp.group(1)
        if "wwt" in c_slug.lower():
            return "World Wide Technology (WWT)"
        clean_name = re.sub(r'^confidential', '', c_slug, flags=re.I).replace('-', ' ').title().strip()
        if clean_name:
            return clean_name

    # hiringcafe: hiringcafe.com/job/data-architect-pythian-united-states-u5oaoprwa4zazma8
    hiringcafe = re.search(r'hiringcafe\.com/job/([a-z0-9-]+)', url.lower())
    if hiringcafe:
        slug = hiringcafe.group(1)
        slug_parts = slug.split('-')
        if len(slug_parts) >= 3 and len(slug_parts[-1]) >= 8:
            slug_parts = slug_parts[:-1]
        loc_words = {"united", "states", "usa", "us", "remote", "hybrid", "onsite", "california", "texas", "new", "york", "ohio", "florida", "georgia", "illinois", "virginia", "washington", "full", "time", "part", "east", "west"}
        filtered = [p for p in slug_parts if p not in loc_words]
        if filtered:
            return filtered[-1].title()

    # generic: extract domain, but ignore aggregator job board domains
    AGGREGATOR_DOMAINS = {"hiringcafe", "indeed", "ziprecruiter", "linkedin", "dice", "glassdoor", "builtin", "handshake", "careerbuilder", "monster", "simplyhired", "jobvite"}
    domain = re.search(r'https?://(?:www\.|jobs\.|myjobs\.)?([^./]+)', url)
    if domain and domain.group(1).lower() not in AGGREGATOR_DOMAINS:
        return domain.group(1).replace('-', ' ').title()
    
    return "Target Company"


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


def fetch_json_ld_via_http(url: str) -> Optional[dict]:
    """
    Fast, reliable HTTP fetch that extracts Schema.org/JobPosting JSON-LD.
    Used by AshbyHQ, Lever, Greenhouse, and major ATS platforms.
    Bypasses headless browser bot-detection entirely in 150ms.
    """
    try:
        import urllib.request
        from bs4 import BeautifulSoup
        import json

        check_url = url
        if "ashbyhq.com" in check_url and check_url.endswith("/application"):
            check_url = check_url[:-12]

        req = urllib.request.Request(
            check_url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="ignore")

        soup = BeautifulSoup(html, "lxml")
        for s in soup.find_all("script", type="application/ld+json"):
            raw = s.string or s.get_text()
            if not raw or "JobPosting" not in raw:
                continue
            try:
                data = json.loads(raw)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    if "@graph" in data:
                        items = data["@graph"]
                    else:
                        items = [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") in ("JobPosting", "http://schema.org/JobPosting", "https://schema.org/JobPosting"):
                        title = clean_role_title(item.get("title", "").strip())
                        org = item.get("hiringOrganization", {})
                        company = ""
                        if isinstance(org, dict):
                            company = org.get("name", "").strip()
                        elif isinstance(org, str):
                            company = org.strip()
                        if not company:
                            company = extract_company_from_url(url)

                        desc = item.get("description", "")
                        if desc:
                            d_soup = BeautifulSoup(desc, "lxml")
                            clean_desc = clean_text(d_soup.get_text("\n"))
                            if len(clean_desc) >= 500:
                                folder_name = f"{slugify(company)}_{slugify(title)}"[:80]
                                return {
                                    "url": url,
                                    "company": company,
                                    "role": title,
                                    "jd_text": clean_desc,
                                    "folder_name": folder_name,
                                }
            except Exception:
                continue
    except Exception as e:
        print(f"[Scraper] JSON-LD HTTP fetch note: {e}")
    return None


async def solve_captcha_interactively(p, url: str) -> Optional[str]:
    """
    When headless Playwright hits a CAPTCHA or Cloudflare challenge,
    launches a visible browser window on screen so the user can solve it immediately.
    Monitors the page until genuine job description content is detected.
    """
    print(f"[Scraper] 🛡 Security challenge / CAPTCHA detected. Launching visible browser for interactive resolution...")
    try:
        browser = await p.chromium.launch(
            headless=False,
            args=[
                '--no-sandbox',
                '--disable-blink-features=AutomationControlled',
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 850},
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25000)
        except Exception:
            pass

        print("[Scraper] 👁 Browser window is open on your desktop. If a captcha/human check is present, please solve it...")

        # Poll up to 30 seconds (20 checks * 1.5s)
        for _ in range(20):
            await asyncio.sleep(1.5)
            try:
                content = await page.content()
                soup = BeautifulSoup(content, 'lxml')
                for tag in soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'iframe', 'svg']):
                    tag.decompose()
                txt = clean_text(soup.get_text('\n'))
                is_valid, _ = validate_jd_extraction(txt)
                if is_valid and len(txt) >= 800:
                    print(f"[Scraper] ✅ Captcha challenge resolved successfully! Captured {len(txt)} characters.")
                    await context.close()
                    await browser.close()
                    return content
            except Exception:
                pass

        print("[Scraper] Interactive verification window closed or timed out.")
        await context.close()
        await browser.close()
    except Exception as e:
        print(f"[Scraper] Interactive verification note: {e}")
    return None


# ─── Intelligent Job Description Cache ───────────────────────────────────────
import json
import time
from pathlib import Path

CACHE_FILE = Path(__file__).parent / "jd_cache.json"
_MEM_CACHE = {}

def get_cached_jd(url: str, max_age_hours: float = 24.0) -> Optional[dict]:
    """Retrieve verified cached JD data for a URL if available and fresh."""
    clean_url = sanitize_jd_url(url.rstrip("/"))
    now = time.time()

    # 1. Memory cache
    if clean_url in _MEM_CACHE:
        entry = _MEM_CACHE[clean_url]
        if now - entry.get("timestamp", 0) < max_age_hours * 3600:
            return entry.get("data")

    # 2. Disk cache
    if CACHE_FILE.exists():
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
                if clean_url in disk_data:
                    entry = disk_data[clean_url]
                    if now - entry.get("timestamp", 0) < max_age_hours * 3600:
                        _MEM_CACHE[clean_url] = entry
                        return entry.get("data")
        except Exception:
            pass
    return None

def save_cached_jd(url: str, data: dict):
    """Save verified clean JD data to memory and disk cache."""
    if not data or len(data.get("jd_text", "")) < 800:
        return
    clean_url = sanitize_jd_url(url.rstrip("/"))
    entry = {
        "timestamp": time.time(),
        "data": data
    }
    _MEM_CACHE[clean_url] = entry
    try:
        disk_data = {}
        if CACHE_FILE.exists():
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                disk_data = json.load(f)
        disk_data[clean_url] = entry
        # Keep newest 100 entries
        if len(disk_data) > 100:
            sorted_items = sorted(disk_data.items(), key=lambda x: x[1].get("timestamp", 0), reverse=True)
            disk_data = dict(sorted_items[:100])
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(disk_data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[Scraper Cache] Note saving cache: {e}")


def slugify(text: str) -> str:
    """Convert text to a safe folder name."""
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '_', text)
    return text.strip('_')


async def scrape_jd(url: str, force_refresh: bool = False) -> dict:
    """
    Main scraping function with intelligent caching.
    Reuses verified scraped JDs to avoid launching redundant browser sessions.
    """
    from playwright.async_api import async_playwright

    scrape_url = url.rstrip("/")

    # ── Sanitize URL first: strip login-redirect params and /candidate path segments ──
    scrape_url = sanitize_jd_url(scrape_url)

    if "ashbyhq.com" in scrape_url and scrape_url.endswith("/application"):
        scrape_url = scrape_url[:-12]

    # ── Check Cache First ──
    if not force_refresh:
        cached = get_cached_jd(scrape_url)
        if cached and len(cached.get("jd_text", "")) >= 100:
            print(f"[Scraper Cache] [CACHED] Reusing cached JD for {cached.get('role')} at {cached.get('company')} (Zero network delay, no browser popup)")
            return cached

    # Fast path for Notion pages via Notion REST API
    if "notion.site" in scrape_url or "notion.so" in scrape_url:
        notion_data = fetch_notion_via_api(scrape_url)
        if notion_data:
            save_cached_jd(scrape_url, notion_data)
            return notion_data

    # Fast path for Schema.org/JobPosting JSON-LD (AshbyHQ, Lever, Greenhouse, etc.)
    json_ld_data = fetch_json_ld_via_http(scrape_url)
    if json_ld_data and len(json_ld_data.get("jd_text", "")) >= 500:
        print(f"[Scraper] ⚡ Extracted verified JobPosting JSON-LD for {json_ld_data.get('role')} at {json_ld_data.get('company')} ({len(json_ld_data.get('jd_text'))} chars)")
        save_cached_jd(scrape_url, json_ld_data)
        save_cached_jd(url, json_ld_data)
        return json_ld_data

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

        # Allow SPA JavaScript / iframes (Greenhouse / Lever / Notion / React) time to hydrate
        await asyncio.sleep(4)
        
        # Get full page HTML from main frame and any embedded iframes (e.g. Greenhouse embeds)
        html_chunks = []
        try:
            main_html = await page.content()
            html_chunks.append(main_html)
            title = await page.title()
        except Exception:
            main_html = ""
            title = ""

        # Check if headless Playwright hit a bot-block / captcha challenge
        is_blocked = False
        try:
            body_txt = (await page.inner_text("body") or "").lower()
            for sig in ["verify you are human", "let's confirm you are human", "attention required", "checking your browser before accessing", "security check to continue", "human verification", "captcha"]:
                if sig in body_txt and len(body_txt) < 1500:
                    is_blocked = True
                    break
        except Exception:
            pass

        for frame in page.frames:
            if frame != page.main_frame:
                try:
                    f_content = await frame.content()
                    if f_content and len(f_content) > 300:
                        print(f"[Scraper] Detected embedded job frame ({len(f_content)} chars): {frame.url[:80]}")
                        html_chunks.append(f_content)
                except Exception:
                    pass

        html = "\n\n".join(html_chunks) if html_chunks else main_html

        print(f"[Scraper DEBUG] Raw HTML fetched len: {len(html)}")
        await context.close()
        await browser.close()

        # If headless mode hit a verification challenge, open interactive browser window immediately
        if is_blocked:
            interactive_html = await solve_captcha_interactively(p, scrape_url)
            if interactive_html:
                main_html = interactive_html
                html_chunks = [interactive_html]
                html = interactive_html
    
    # Parse each HTML chunk with BeautifulSoup to extract the richest content (e.g. from embedded Greenhouse/Lever frames)
    best_jd_text = ""
    best_role = ""
    best_company = extract_company_from_url(scrape_url)

    for chunk in html_chunks:
        if not chunk or len(chunk) < 200:
            continue
        c_soup = BeautifulSoup(chunk, 'lxml')
        for tag in c_soup.find_all(['script', 'style', 'nav', 'header', 'footer', 'noscript', 'iframe', 'svg']):
            tag.decompose()
        
        # Check platform and generic selectors on this frame
        frame_text = ""
        platform_sels = PLATFORM_SELECTORS.get(platform, {}).get("jd", []) if platform else []
        combined_sels = platform_sels + ["#content", ".content", "#app", "main", "article", "[class*='job-description']", "[id*='content']", "body"]
        for sel in combined_sels:
            el = c_soup.select_one(sel)
            if el:
                candidate_txt = el.get_text(separator='\n').strip()
                if len(candidate_txt) > len(frame_text):
                    frame_text = candidate_txt

        if len(frame_text) > len(best_jd_text):
            best_jd_text = clean_text(frame_text)
            # Try to extract role title from this frame
            for sel in ["h1.app-title", "h1.job-title", "h1", "h2", "title"]:
                r_el = c_soup.select_one(sel)
                if r_el and len(r_el.get_text().strip()) > 3:
                    cand_role = clean_role_title(r_el.get_text().strip())
                    is_valid, _ = validate_role_title(cand_role)
                    if is_valid:
                        best_role = cand_role
                        break
            # Try to extract company
            for sel in [".company-name", "[class*='company']", ".posting-category"]:
                co_el = c_soup.select_one(sel)
                if co_el and len(co_el.get_text().strip()) > 2:
                    best_company = co_el.get_text().strip()
                    break

    jd_text = best_jd_text
    role = best_role
    company = best_company or extract_company_from_url(scrape_url)

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
                    print(f"[Scraper] [OK] Jina Reader extracted {len(jd_text)} chars")
                    # Extract role title from Jina markdown header if available
                    title_m = re.search(r'^Title:\s*(.+)$', raw_markdown, re.MULTILINE)
                    if title_m:
                        extracted_role = clean_role_title(title_m.group(1).strip())
                        if extracted_role and extracted_role.lower() not in ("software engineer", "jobs", "careers", "apply"):
                            role = extracted_role
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

    # ── Resolve true hiring company (avoid job board aggregator names) ──
    JOB_BOARD_NAMES = {
        "hiringcafe", "indeed", "ziprecruiter", "linkedin", "dice",
        "glassdoor", "builtin", "handshake", "careerbuilder", "monster", "simplyhired", "jobvite", "target company", "unknown company"
    }

    if not company or company.lower().replace(" ", "") in JOB_BOARD_NAMES or (role and company.lower() == role.lower()):
        # 1. From Page Title: e.g. "Data Architect at Pythian · Remote" or "Senior Data Engineer at Saint"
        if title:
            t_clean = re.sub(r'\s*[-–—|]\s*(?:HiringCafe|Indeed|LinkedIn|ZipRecruiter|Glassdoor|BuiltIn).*$', '', title, flags=re.I).strip()
            if " at " in t_clean:
                cand_co = t_clean.split(" at ", 1)[1].split("·")[0].split("•")[0].split("-")[0].split("|")[0].strip()
                if cand_co and cand_co.lower().replace(" ", "") not in JOB_BOARD_NAMES:
                    company = cand_co
            elif " - " in t_clean:
                cand_co = t_clean.split(" - ", 1)[1].split("·")[0].split("•")[0].split("|")[0].strip()
                if cand_co and cand_co.lower().replace(" ", "") not in JOB_BOARD_NAMES and len(cand_co) < 35:
                    company = cand_co

        # 2. From DOM / JD: e.g. "About Pythian" or "About Saint"
        if not company or company.lower().replace(" ", "") in JOB_BOARD_NAMES:
            about_m = re.search(r'(?:About|Company:)\s+([A-Z][a-zA-Z0-9\s&,\.]{2,30})(?:\n|\r|\.|\s*—)', jd_text)
            if about_m:
                cand_co = about_m.group(1).strip()
                if cand_co.lower().replace(" ", "") not in JOB_BOARD_NAMES and "the role" not in cand_co.lower() and "this job" not in cand_co.lower():
                    company = cand_co

        # 3. Fallback to URL parsing
        if not company or company.lower().replace(" ", "") in JOB_BOARD_NAMES:
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

    # Save to persistent cache so future runs reuse this verified extract
    save_cached_jd(scrape_url, result)
    save_cached_jd(url, result)

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
