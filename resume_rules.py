"""Deterministic resume rules shared by the pipeline and the resume report.

Every limit and check here is used in two places:
  - danis_engine applies the fixes before delivery, and
  - resume_report measures the same things afterwards,
so when the pipeline says a resume passed, HollaBuddy (which reads the report)
agrees. Nothing in this module calls an LLM.
"""
from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from ats_scoring import keyword_present, resume_json_text

# ── Limits (one place, used by both the pipeline and the report) ──────────────
MAX_NEW_KEYWORDS_PER_BULLET = 2      # job keywords a bullet may carry beyond the master resume
MAX_ADDED_BULLETS_PER_ROLE = 2       # bullets a role may gain over the master resume
ROLE_BULLET_CAPS = (7, 6, 5, 4)      # most recent role first; older roles use the last value
MIN_BULLETS_PER_ROLE = 2
MAX_TOTAL_BULLETS = 22
MAX_PROSE_WORDS = 800                # summary + bullets; about two pages with skills and education
MAX_SKILLS = 40
MAX_NUMBERS_PER_BULLET = 2
MAX_NEW_NUMERIC_CLAIMS = 10
MAX_THEMES = 6
MAX_SUMMARY_KEYWORDS = 5          # job keywords in the summary; more reads as a tool list


# ── Keyword tiers: must-have vs nice-to-have ──────────────────────────────────
_NICE_MARKERS = re.compile(
    r"\b(nice[- ]to[- ]have|a plus|is a plus|are a plus|bonus|preferred|preferably|ideally|"
    r"familiarity|exposure to|desirable|optional|good to have|not required|would be great)\b", re.I)
_NICE_HEADING = re.compile(r"\b(nice[- ]to[- ]have|preferred|bonus|plus|desirable|good to have)\b", re.I)
_REQ_HEADING = re.compile(r"\b(requirements?|required|qualifications|must[- ]have|what you('ll| will) (do|bring|need)|"
                          r"responsibilities|you will|you have|about you|skills)\b", re.I)


def _jd_lines(jd_text: str) -> list[tuple[str, bool]]:
    """Split the JD into sentences tagged with whether they sit in a nice-to-have section."""
    out, in_nice = [], False
    for raw in re.split(r"\n+", jd_text or ""):
        line = raw.strip()
        if not line:
            continue
        is_heading = len(line) <= 70 and (line.endswith(":") or len(line.split()) <= 6)
        if is_heading and _NICE_HEADING.search(line):
            in_nice = True
        elif is_heading and _REQ_HEADING.search(line):
            in_nice = False
        for sent in re.split(r"(?<=[.!?;])\s+", line):
            if sent.strip():
                out.append((sent.strip(), in_nice))
    return out


def split_keyword_tiers(keywords: Iterable[Any], jd_text: str) -> dict[str, list[str]]:
    """must_have: the JD asks for it in at least one sentence outside a nice-to-have
    section without softening words. nice_to_have: every mention is softened
    ("a plus", "preferred", "familiarity with") or sits under a Nice-to-have heading."""
    lines = _jd_lines(jd_text)
    must, nice = [], []
    for kw in dict.fromkeys(str(k).strip() for k in keywords or [] if str(k).strip()):
        mentions = [(s, n) for s, n in lines if keyword_present(kw, s)]
        if mentions and all(n or _NICE_MARKERS.search(s) for s, n in mentions):
            nice.append(kw)
        else:
            must.append(kw)
    return {"must_have": must, "nice_to_have": nice}


# ── Core role themes ──────────────────────────────────────────────────────────
# (name, what the JD says, evidence a resume shows it)
THEMES = [
    ("End-to-end ownership",
     r"end[- ]to[- ]end|\bown(?:s|ing|ership)?\b[^.]{0,40}\b(?:features?|products?|services?|systems?|roadmap)|from (?:design|concept|idea) to (?:production|launch|deployment)",
     r"end[- ]to[- ]end|\bowned\b|\bownership\b|from (?:design|scratch|concept) (?:to|through)|took [^.]{0,40} (?:to|into) production"),
    ("Mentoring and technical leadership",
     r"mentor|coach|technical leadership|tech lead|lead (?:a |the )?team|guide (?:junior|other) engineers|grow (?:the )?team",
     r"mentor|coached|\bled (?:a |the )?(?:team|squad|group)|tech lead|onboarded|trained \d+|guided \d*\s*(?:junior|engineers)"),
    ("Working with product and cross-functional teams",
     r"cross[- ]functional|product (?:managers?|teams?|partners?|owners?)|partner with (?:product|design|business|stakeholders)|collaborat\w* (?:closely )?with (?:product|design|business|stakeholders|data scientists)",
     r"cross[- ]functional|product (?:managers?|teams?|owners?)|with (?:product|design|business|stakeholders|data scientists|analysts)|partnered with|stakeholders?"),
    ("System design and architecture",
     r"architect|system design|design (?:scalable|distributed|resilient)|distributed systems|technical design",
     r"architecture|distributed|system design|\bdesigned\b[^.]{0,60}\b(?:system|platform|service|pipeline|schema|api)s?\b"),
    ("Reliability and production operations",
     r"on[- ]call|reliabilit|observability|monitoring|incident|\bslas?\b|\bslos?\b|uptime|production support",
     r"on[- ]call|incident|monitor|alert|uptime|\bslas?\b|\bslos?\b|observab|reliab|recovery"),
    ("Performance and scale",
     r"scal(?:e|able|ability|ing)\b|performance|latency|high[- ]throughput|large[- ]scale|millions of",
     r"scal(?:e|ed|able|ing)|latency|throughput|faster|performance|\d+(?:\.\d+)?\s*(?:[mkb]|million|billion|tb|gb|pb)\b"),
    ("Data quality and governance",
     r"data quality|governance|lineage|data contracts?|data validation|master data",
     r"data quality|governance|lineage|contracts?|validat|reconcil|tests? (?:on|for) (?:data|pipelines)"),
    ("Security and compliance",
     r"security|compliance|hipaa|soc ?2|gdpr|\bpii\b|\bphi\b|access control|privacy",
     r"security|compliance|hipaa|soc ?2|gdpr|\bpii\b|\bphi\b|access control|encrypt|privacy|audit"),
    ("Shipping user-facing product",
     r"user[- ]facing|customer[- ]facing|product features|front[- ]end|user experience|\bux\b",
     r"user[- ]facing|customer|front[- ]end|\bui\b|\busers?\b|features?\b|dashboards?"),
    ("Putting AI/ML into production",
     r"(?:llm|ai|ml|genai|generative ai|machine learning)[- ]powered|deploy\w* (?:ml|models?|llms?)|mlops|model (?:serving|deployment|evaluation|monitoring)|llm evaluation",
     r"\bmodels?\b|\bllms?\b|inference|evaluation|mlops|deployed[^.]{0,40}model|rag\b|retrieval"),
    ("Testing and engineering quality",
     r"code reviews?|testing|test[- ]driven|unit tests|engineering best practices|code quality",
     r"code reviews?|\btests?\b|testing|ci/cd|reviewed|test coverage"),
]


def extract_core_themes(jd_text: str, limit: int = MAX_THEMES) -> list[str]:
    """3-6 main responsibilities of the job, ranked by how often the JD stresses them."""
    text = jd_text or ""
    scored = []
    for i, (name, jd_pat, _) in enumerate(THEMES):
        hits = len(re.findall(jd_pat, text, re.I))
        if hits:
            scored.append((-hits, i, name))
    scored.sort()
    return [name for _, _, name in scored[:limit]]


def theme_evidence_text(resume: dict) -> str:
    """Summary + bullets of the two most recent roles: where a recruiter looks first."""
    parts = [str(resume.get("summary") or "")]
    for e in [e for e in (resume.get("experience") or []) if isinstance(e, dict)][:2]:
        parts += [str(b) for b in (e.get("bullets") or [])]
    return "\n".join(parts)


def missing_themes(resume: dict, themes: list[str]) -> list[str]:
    text = theme_evidence_text(resume)
    patterns = {name: ev for name, _, ev in THEMES}
    return [t for t in themes if t in patterns and not re.search(patterns[t], text, re.I)]


# ── Numbers and new claims ────────────────────────────────────────────────────
_NUMBER = re.compile(r"\$?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|x\b|[kKmMbB]\b|\+)?")


def _numbers_in(text: str) -> list[str]:
    out = []
    for m in _NUMBER.finditer(text or ""):
        token = m.group(0).strip()
        digits = re.sub(r"[^\d.]", "", token).strip(".")
        # Years (2019) and single digits in dates or versions are not claims.
        if not digits or re.fullmatch(r"(19|20)\d{2}", digits):
            continue
        out.append(token)
    return out


def _norm_number(token: str) -> str:
    return re.sub(r"[^\d.]", "", token).strip(".").lstrip("0") or "0"


def new_claims(master: dict, final: dict) -> list[dict]:
    """Bullets stating numbers (metrics, team size, scale) the master resume never shows."""
    master_numbers = {_norm_number(t) for t in _numbers_in(resume_json_text(master or {}))}
    claims = []
    summary = str(final.get("summary") or "")
    s_nums = [t for t in _numbers_in(summary) if _norm_number(t) not in master_numbers]
    if s_nums:
        claims.append({"company": "Summary", "numbers": s_nums, "bullet": summary})
    for e in final.get("experience") or []:
        if not isinstance(e, dict):
            continue
        for b in e.get("bullets") or []:
            nums = [t for t in _numbers_in(str(b)) if _norm_number(t) not in master_numbers]
            if nums:
                claims.append({"company": e.get("company", ""), "numbers": nums, "bullet": str(b)})
    return claims


def bullets_with_too_many_numbers(final: dict) -> list[str]:
    return [str(b) for e in (final.get("experience") or []) if isinstance(e, dict)
            for b in (e.get("bullets") or []) if len(_numbers_in(str(b))) > MAX_NUMBERS_PER_BULLET]


# ── Keyword stuffing ─────────────────────────────────────────────────────────
def stuffed_bullets(master: dict, final: dict, keywords: list[str]) -> list[dict]:
    """Bullets carrying more than MAX_NEW_KEYWORDS_PER_BULLET job keywords that the
    master resume never showed (the cram-everything-into-one-bullet pattern)."""
    master_text = resume_json_text(master or {})
    new_kws = [k for k in keywords if not keyword_present(k, master_text, allow_aliases=True)]
    out = []
    for e in final.get("experience") or []:
        if not isinstance(e, dict):
            continue
        for b in e.get("bullets") or []:
            hits = [k for k in new_kws if keyword_present(k, str(b))]
            if len(hits) > MAX_NEW_KEYWORDS_PER_BULLET:
                out.append({"company": e.get("company", ""), "keywords": hits, "bullet": str(b)})
    return out


# ── Skills de-duplication ─────────────────────────────────────────────────────
# True synonyms only (PySpark and Spark are different skills, so they are not merged).
_SKILL_SYNONYMS = [
    ["postgresql", "postgres"], ["amazon web services", "aws"], ["google cloud platform", "gcp", "google cloud"],
    ["microsoft azure", "azure"], ["kubernetes", "k8s"], ["javascript", "js"], ["typescript", "ts"],
    ["ci/cd", "cicd", "ci cd", "continuous integration/continuous delivery", "continuous integration and continuous delivery"],
    ["node.js", "nodejs", "node js", "node"], ["react", "react.js", "reactjs"], ["vue", "vue.js", "vuejs"],
    ["next.js", "nextjs"], ["machine learning", "ml"], ["artificial intelligence", "ai"],
    ["large language models", "large language model", "llm", "llms"], ["natural language processing", "nlp"],
    ["rest api", "rest apis", "restful api", "restful apis", "rest"], ["etl", "extract, transform, load"],
    ["apache airflow", "airflow"], ["apache kafka", "kafka"], ["apache spark", "spark"],
    ["infrastructure as code", "iac"], ["github actions", "gh actions"], ["microsoft sql server", "sql server", "mssql"],
    ["power bi", "powerbi"], ["scikit-learn", "sklearn", "scikit learn"], ["tensorflow", "tf"],
    ["retrieval-augmented generation", "retrieval augmented generation", "rag"], ["mongodb", "mongo"],
    ["elasticsearch", "elastic search"], ["amazon s3", "aws s3", "s3"], ["aws lambda", "lambda"],
]
_SYN_INDEX = {term: group[0] for group in _SKILL_SYNONYMS for term in group}


def _skill_base(text: str) -> str:
    t = re.sub(r"\s*/\s*", "/", (text or "").strip().lower())
    t = re.sub(r"\s+", " ", t).strip(" .,;")
    if t.startswith("apache ") and t[7:] in _SYN_INDEX:
        t = t[7:]
    if t in _SYN_INDEX:
        return _SYN_INDEX[t]
    # Plural tolerance: "rest apis" ~ "rest api", "data pipelines" ~ "data pipeline".
    if len(t) > 4 and t.endswith("s") and not t.endswith("ss"):
        singular = t[:-1]
        return _SYN_INDEX.get(singular, singular)
    return t


def skill_keys(skill: str) -> set[str]:
    """Canonical keys for a skill; "Amazon Web Services (AWS)" yields both names' keys."""
    s = str(skill or "")
    keys = {_skill_base(s)}
    m = re.match(r"^(.*?)\s*\((.*?)\)\s*$", s)
    if m:
        keys |= {_skill_base(m.group(1)), _skill_base(m.group(2))}
    return {k for k in keys if k}


def duplicate_skills(skills: list[str]) -> list[list[str]]:
    groups: list[list[str]] = []
    key_to_group: dict[str, int] = {}
    for s in skills or []:
        ks = skill_keys(s)
        idx = next((key_to_group[k] for k in ks if k in key_to_group), None)
        if idx is None:
            groups.append([s])
            idx = len(groups) - 1
        else:
            groups[idx].append(s)
        for k in ks:
            key_to_group[k] = idx
    return [g for g in groups if len(g) > 1]


def dedupe_skills(skills: list[str], jd_text: str = "", keep_first: Optional[list[str]] = None) -> list[str]:
    """Merge near-duplicates (PostgreSQL/Postgres, AWS/Amazon Web Services, CI/CD/CI/ CD).
    The kept spelling is the one the job description uses literally, otherwise the first seen."""
    order: list[list[str]] = []
    key_to_group: dict[str, int] = {}
    for s in skills or []:
        s = str(s).strip()
        if not s:
            continue
        ks = skill_keys(s)
        idx = next((key_to_group[k] for k in ks if k in key_to_group), None)
        if idx is None:
            order.append([s])
            idx = len(order) - 1
        else:
            order[idx].append(s)
        for k in ks:
            key_to_group[k] = idx
    out = []
    for group in order:
        in_jd = [s for s in group if jd_text and keyword_present(s, jd_text)]
        out.append(in_jd[0] if in_jd else group[0])
    return out


def cap_skills(skills: list[str], keywords: list[str], prose: str, limit: int = MAX_SKILLS) -> list[str]:
    """Keep the Skills list readable: job keywords and skills used in bullets stay;
    the least relevant master skills are dropped from the end first."""
    if len(skills) <= limit:
        return skills
    keep = [s for s in skills if any(skill_keys(s) & skill_keys(k) for k in keywords) or keyword_present(s, prose)]
    rest = [s for s in skills if s not in keep]
    room = max(0, limit - len(keep))
    kept_rest = set(rest[:room])
    return [s for s in skills if s in keep or s in kept_rest]


# ── Bullet caps and trimming ──────────────────────────────────────────────────
def role_cap(index: int, master_count: int) -> int:
    by_position = ROLE_BULLET_CAPS[min(index, len(ROLE_BULLET_CAPS) - 1)]
    return max(MIN_BULLETS_PER_ROLE, min(by_position, master_count + MAX_ADDED_BULLETS_PER_ROLE))


def prose_word_count(resume: dict) -> int:
    parts = [str(resume.get("summary") or "")]
    for e in resume.get("experience") or []:
        if isinstance(e, dict):
            parts += [str(b) for b in (e.get("bullets") or [])]
    return len(" ".join(parts).split())


def _bullet_relevance(bullet: str, must: list[str], nice: list[str], theme_patterns: list[str]) -> int:
    score = 3 * sum(1 for k in must if keyword_present(k, bullet))
    score += sum(1 for k in nice if keyword_present(k, bullet))
    score += 2 * sum(1 for p in theme_patterns if re.search(p, bullet, re.I))
    score += 2 if _numbers_in(bullet) else 0  # measurable bullets are worth keeping
    return score


def trim_bullets(final: dict, master: dict, must: list[str], nice: list[str], themes: list[str]) -> tuple[dict, list[str]]:
    """Enforce per-role caps, the total-bullet cap and the length budget by dropping
    the bullets that matter least for this job. A bullet that is the only place a
    must-have keyword appears in prose is never dropped. Returns (resume, dropped)."""
    import json as _json
    out = _json.loads(_json.dumps(final))
    roles = [e for e in (out.get("experience") or []) if isinstance(e, dict)]
    master_roles = [e for e in (master.get("experience") or []) if isinstance(e, dict)]
    theme_patterns = [ev for name, _, ev in THEMES if name in themes]
    dropped: list[str] = []

    def protected(role: dict, idx: int) -> bool:
        bullet = str(role["bullets"][idx])
        others = [str(out.get("summary") or "")]
        for e in roles:
            others += [str(b) for j, b in enumerate(e.get("bullets") or []) if not (e is role and j == idx)]
        other_text = "\n".join(others)
        if any(keyword_present(k, bullet) and not keyword_present(k, other_text) for k in must):
            return True
        # The only evidence of a core theme in the summary or the two most recent
        # roles (where the report looks for it) is kept too.
        role_pos = next(i for i, e in enumerate(roles) if e is role)
        if role_pos < 2 and theme_patterns:
            recent = [str(out.get("summary") or "")]
            for e in roles[:2]:
                recent += [str(b) for j, b in enumerate(e.get("bullets") or []) if not (e is role and j == idx)]
            recent_text = "\n".join(recent)
            if any(re.search(p, bullet, re.I) and not re.search(p, recent_text, re.I) for p in theme_patterns):
                return True
        return False

    def drop_one(role: dict, floor: int) -> bool:
        bl = role.get("bullets") or []
        if len(bl) <= floor:
            return False
        ranked = sorted(range(len(bl)), key=lambda i: (_bullet_relevance(str(bl[i]), must, nice, theme_patterns), -i))
        for i in ranked:
            if not protected(role, i):
                dropped.append(str(bl[i]))
                del bl[i]
                return True
        return False

    for i, role in enumerate(roles):
        mcount = len((master_roles[i].get("bullets") or [])) if i < len(master_roles) else len(role.get("bullets") or [])
        cap = role_cap(i, mcount)
        while len(role.get("bullets") or []) > cap and drop_one(role, cap):
            pass

    def total() -> int:
        return sum(len(e.get("bullets") or []) for e in roles)

    # Total cap and length budget: trim from the oldest roles first.
    while total() > MAX_TOTAL_BULLETS or prose_word_count(out) > MAX_PROSE_WORDS:
        if not any(drop_one(role, MIN_BULLETS_PER_ROLE) for role in reversed(roles)):
            break
    return out, dropped


# ── Summary bridge ────────────────────────────────────────────────────────────
_TITLE_STOP = {"senior", "junior", "lead", "staff", "principal", "sr", "jr", "ii", "iii", "iv", "i",
               "engineer", "developer", "manager", "specialist", "the", "and", "for", "with", "remote"}


def summary_names_target(summary: str, role: str) -> bool:
    words = [w for w in re.findall(r"[a-z0-9+#.]+", (role or "").lower()) if w not in _TITLE_STOP and len(w) > 1]
    if not words:
        return True
    s = (summary or "").lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", s) for w in words)
