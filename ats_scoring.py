"""ats_scoring.py - Deterministic, file-based ATS keyword scoring.

One scoring function is used for BOTH sides of the before/after comparison:
  * before = the master resume (its DOCX when present, else its JSON)
  * after  = the DOCX file actually delivered to the user
so the delta shown in the UI is a real, reproducible measurement — never an
LLM's opinion of its own rewrite and never a made-up fallback number.

Matching is literal (case-insensitive, plural tolerant, separator tolerant),
because exact-match ATS platforms (Workday, Taleo, iCIMS) only count the term
as written in the job description. Aliases ("K8s" for "Kubernetes") count as
evidence that the candidate HAS a skill, but not as an ATS match.
"""
from __future__ import annotations

import re
import zipfile
from typing import Any, Dict, Iterable, List, Optional

# Equivalent spellings: used only to decide whether the master resume already
# shows a skill (for the interview-prep list), never to award ATS credit.
_ALIAS_GROUPS = [
    ["javascript", "js"],
    ["typescript", "ts"],
    ["postgresql", "postgres"],
    ["kubernetes", "k8s"],
    ["ci/cd", "cicd", "continuous integration", "continuous delivery", "continuous deployment"],
    ["machine learning", "ml"],
    ["artificial intelligence", "ai"],
    ["amazon web services", "aws"],
    ["google cloud platform", "gcp", "google cloud"],
    ["microsoft azure", "azure"],
    ["rest api", "rest apis", "restful api", "restful apis", "restful"],
    ["node.js", "nodejs", "node"],
    ["react", "react.js", "reactjs"],
    ["large language models", "large language model", "llm", "llms"],
    ["natural language processing", "nlp"],
    ["extract, transform, load", "etl"],
    ["apache spark", "spark", "pyspark"],
    ["apache kafka", "kafka"],
    ["apache airflow", "airflow"],
    ["infrastructure as code", "iac"],
    ["user interface", "ui"],
    ["object-oriented programming", "oop"],
]
_ALIAS_INDEX: Dict[str, List[str]] = {}
for _group in _ALIAS_GROUPS:
    for _term in _group:
        _ALIAS_INDEX.setdefault(_term, [])
        _ALIAS_INDEX[_term].extend(t for t in _group if t != _term)


def normalize_text(text: str) -> str:
    """Lowercase and unify the characters that break naive matching."""
    if not text:
        return ""
    t = str(text)
    t = t.replace(" ", " ").replace("‑", "-")
    t = re.sub(r"[‐‒–—―]", "-", t)
    t = t.replace("’", "'").replace("‘", "'")
    return t.lower()


def _keyword_pattern(keyword: str) -> Optional[re.Pattern]:
    kw = normalize_text(keyword).strip()
    if not kw:
        return None
    parts = []
    for ch in kw:
        if ch.isspace():
            parts.append(r"[\s\-]+")
        elif ch == "-":
            parts.append(r"[\s\-]?")
        elif ch == "/":
            parts.append(r"\s*/\s*")
        else:
            parts.append(re.escape(ch))
    body = "".join(parts)
    # Collapse runs created by consecutive whitespace in the keyword itself.
    body = re.sub(r"(\[\\s\\-\]\+)+", r"[\\s\\-]+", body)
    if len(kw) > 3 and kw.endswith("s") and kw[-2].isalpha() and body.endswith("s"):
        # Plural keyword ("ETL Pipelines") also matches the singular form.
        body = body[:-1]
        plural = r"(?:s|es)?"
    else:
        plural = r"(?:s|es)?" if kw[-1].isalnum() else ""
    # Custom boundaries so C++, C#, .NET, Node.js and CI/CD match correctly,
    # and a single letter like "R" does not match inside "R&D".
    return re.compile(r"(?<![a-z0-9&])" + body + plural + r"(?![a-z0-9+#&])")


def keyword_present(keyword: str, text: str, allow_aliases: bool = False) -> bool:
    """True if `keyword` appears in `text` as a whole term (literal by default)."""
    norm = normalize_text(text)
    pat = _keyword_pattern(keyword)
    if pat is not None and pat.search(norm):
        return True
    if allow_aliases:
        for alias in _ALIAS_INDEX.get(normalize_text(keyword).strip(), []):
            ap = _keyword_pattern(alias)
            if ap is not None and ap.search(norm):
                return True
    return False


def jd_spelling(keyword: str, jd_text: str) -> str:
    """Return the keyword as the job description itself spells it (casing,
    punctuation), falling back to the keyword unchanged."""
    pat = _keyword_pattern(keyword)
    if pat is None or not jd_text:
        return keyword
    norm = normalize_text(jd_text)
    if len(norm) != len(jd_text):
        return keyword
    m = pat.search(norm)
    return jd_text[m.start():m.end()].strip() if m else keyword


def dedupe_keywords(keywords: Iterable[Any]) -> List[str]:
    seen, out = set(), []
    for kw in keywords or []:
        k = str(kw or "").strip()
        if k and k.lower() not in seen:
            seen.add(k.lower())
            out.append(k)
    return out


def score_text(text: str, keywords: Iterable[Any]) -> Dict[str, Any]:
    """Literal keyword coverage of `text`: score = matched / total * 100."""
    kws = dedupe_keywords(keywords)
    matched = [k for k in kws if keyword_present(k, text)]
    missing = [k for k in kws if k not in matched]
    score = round(100 * len(matched) / len(kws)) if kws else None
    return {"score": score, "matched": matched, "missing": missing, "total": len(kws)}


def resume_json_text(resume: Dict[str, Any]) -> str:
    """Flatten the visible text of a resume dict (no internal _keys)."""
    if not isinstance(resume, dict):
        return str(resume or "")
    parts: List[str] = []

    def walk(value: Any):
        if isinstance(value, dict):
            for k, v in value.items():
                if not str(k).startswith("_"):
                    walk(v)
        elif isinstance(value, (list, tuple)):
            for v in value:
                walk(v)
        elif value is not None:
            parts.append(str(value))

    walk(resume)
    return "\n".join(parts)


def resume_prose_text(resume: Dict[str, Any]) -> str:
    """Summary + experience/project bullets only: where a keyword shows real use."""
    if not isinstance(resume, dict):
        return ""
    parts = [str(resume.get("summary") or "")]
    for exp in resume.get("experience") or []:
        if isinstance(exp, dict):
            parts.extend(str(b) for b in exp.get("bullets") or [])
    for pr in resume.get("projects") or []:
        if isinstance(pr, dict):
            parts.append(str(pr.get("description") or ""))
            parts.extend(str(b) for b in pr.get("bullets") or [])
    return "\n".join(parts)


# ── DOCX inspection ────────────────────────────────────────────────────────────

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _para_text(p_el) -> str:
    return "".join(t.text or "" for t in p_el.iter(_W + "t"))


def extract_docx_text(docx_path: str) -> str:
    """Text an ATS parser reliably reads: body paragraphs and table cells,
    in document order. Text boxes, headers and footers are excluded on purpose
    (many parsers skip them) and reported by `docx_parse_findings` instead."""
    from docx import Document

    doc = Document(str(docx_path))
    lines: List[str] = []
    body = doc.element.body
    for block in body.iterchildren():
        tag = block.tag
        if tag == _W + "p":
            if block.find(".//" + _W + "txbxContent") is not None:
                # Keep the paragraph's own runs, drop text-box content.
                own = [t.text or "" for t in block.iter(_W + "t")
                       if not any(a.tag == _W + "txbxContent" for a in t.iterancestors())]
                lines.append("".join(own))
            else:
                lines.append(_para_text(block))
        elif tag == _W + "tbl":
            for cell_p in block.iter(_W + "p"):
                lines.append(_para_text(cell_p))
    return "\n".join(l for l in lines if l.strip())


def docx_parse_findings(docx_path: str) -> List[Dict[str, str]]:
    """Layout features that common ATS parsers misread, found in the actual file."""
    from docx import Document

    findings: List[Dict[str, str]] = []
    try:
        doc = Document(str(docx_path))
    except Exception as e:
        return [{"severity": "critical", "issue": f"File could not be opened as DOCX: {e}"}]

    body = doc.element.body
    txbx_text = []
    for tb in body.iter(_W + "txbxContent"):
        t = " ".join(_para_text(p) for p in tb.iter(_W + "p")).strip()
        if t:
            txbx_text.append(t)
    if txbx_text:
        sample = txbx_text[0][:60]
        findings.append({"severity": "critical",
                         "issue": f"{len(txbx_text)} text box(es) hold resume text (e.g. \"{sample}\"); many ATS parsers skip text boxes entirely."})

    if len(doc.tables) > 0:
        findings.append({"severity": "warning",
                         "issue": f"{len(doc.tables)} table(s) in the layout; older parsers (Taleo, iCIMS) can read cells out of order."})

    for cols in body.iter(_W + "cols"):
        num = cols.get(_W + "num")
        if num and num.isdigit() and int(num) > 1:
            findings.append({"severity": "warning",
                             "issue": f"{num}-column section; parsers may interleave the columns line by line."})
            break

    contact_re = re.compile(r"@|\+?\d[\d\s().-]{7,}\d|linkedin\.com", re.I)
    for section in doc.sections:
        for part in (section.header, section.footer):
            try:
                txt = " ".join(p.text for p in part.paragraphs)
            except Exception:
                txt = ""
            if txt and contact_re.search(txt):
                findings.append({"severity": "warning",
                                 "issue": "Contact details sit in the page header/footer; some ATS parsers ignore headers, so email or phone may not be captured."})
                break
        else:
            continue
        break

    body_text = normalize_text(extract_docx_text(docx_path))
    for label, alts in (("Experience", ("experience", "employment", "work history")),
                        ("Education", ("education", "academic")),
                        ("Skills", ("skills", "technical skills", "competencies"))):
        if not any(a in body_text for a in alts):
            findings.append({"severity": "warning",
                             "issue": f"No standard \"{label}\" heading found; ATS section detection relies on standard headings."})

    try:
        with zipfile.ZipFile(str(docx_path)) as z:
            if any(n.startswith("word/media/") for n in z.namelist()) and len(body_text) < 400:
                findings.append({"severity": "critical",
                                 "issue": "Very little readable text but embedded images; the resume may be an image the ATS cannot read."})
    except Exception:
        pass

    return findings


def score_docx(docx_path: str, keywords: Iterable[Any]) -> Dict[str, Any]:
    """Score the delivered file and attach its parse findings."""
    text = extract_docx_text(docx_path)
    result = score_text(text, keywords)
    result["source"] = "delivered_docx"
    result["parse_findings"] = docx_parse_findings(docx_path)
    return result


def keywords_added_beyond(master_resume: Dict[str, Any], final_text: str, keywords: Iterable[Any]) -> List[str]:
    """Keywords present in the final resume that the master resume never showed
    (not even by alias). These are the claims to prepare for in interviews."""
    master_text = resume_json_text(master_resume)
    return [k for k in dedupe_keywords(keywords)
            if keyword_present(k, final_text) and not keyword_present(k, master_text, allow_aliases=True)]
