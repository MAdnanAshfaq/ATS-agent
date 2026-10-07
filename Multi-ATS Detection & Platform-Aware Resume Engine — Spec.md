# Feature Spec — Multi-ATS Detection & Platform-Aware Resume Compliance Engine

**Target repo:** `github.com/MAdnanAshfaq/ATS-agent` **Agent:** Antigravity (or equivalent coding agent) **Existing system:** 4-agent pipeline — Researcher → Writer → Auditor → Editor — governed by Rule 0 (zero hallucination / truth-grounding) and a dual-gate philosophy: every resume must pass the algorithmic ATS parser **and** survive a human recruiter's skim, without sacrificing either.

---

## 1. Objective

Right now the pipeline optimizes each resume against a single generic notion of "the ATS." In reality, every major Applicant Tracking System parses, scores, and ranks resumes using a **different engine with different rules** — what satisfies Greenhouse can get silently down-ranked by Workday, and what Taleo demands can be irrelevant to Lever.

Build a **platform-detection + platform-aware rules layer** that sits across all four existing agents, so that every resume the system produces is tuned to the *specific* ATS the candidate is applying through — falling back to a safe, strictest-common-denominator profile when the platform can't be identified.

This must not replace the existing dual-gate (ATS + human) logic — it is an additional dimension layered on top of it. A platform-specific optimization that damages human readability is a regression, not a feature.

---

## 2. ATS Platform Registry (encode as data, not hardcoded logic)

Create a config file — `ats_registry.json` (or `.yaml`) — listing every supported platform as a structured record. This registry is the single source of truth; every agent reads from it, nothing hardcodes platform names inline.

| Platform | URL signature | Matching style | Title weighting | Format tolerance | Keyword density ceiling | Cover letter scored? | Notable quirk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Workday | `myworkdayjobs.com` | Exact-match + weighted scoring, increasingly layered with HiredScore AI relevance | Heavy — strongly weights exact title match | Strict (improved since 2024, still strictest major platform) | \~1.5% | No (shown to human, not scored) | Expects dates as MM/YYYY; skills matched against requisition's explicit required/preferred lists |
| Greenhouse | `greenhouse.io` | Semantic/contextual ("managed projects" ≈ "project management"), plus "match intelligence" AI | Lower — structured scorecards matter more than algorithmic title match | Most tolerant of the majors | \~2–3% | **Yes** | One of only two platforms where the cover letter feeds the score |
| Lever | `lever.co` | AI "Talent Fit" matching + CRM signals | Moderate | Tolerant, headline-driven extraction | \~2–3% | No (separate tab, zero scoring impact) | — |
| iCIMS | `icims.com` | Boolean-heavy — recruiters build literal queries | Moderate | Modern parser with OCR fallback | \~1.5–2% | No | Structurally similar to Workday under the hood |
| Oracle Taleo | `taleo.net` | Legacy, algorithm-heavy; blends screening-question answers *with* keyword match into one % score | High | Strictest/oldest — **no tables**, cells parsed in unpredictable order | \~1.5% | Merged into resume text (risk: triggers density penalty) | Full month-name dates (not MM/YYYY) |
| SAP SuccessFactors | `successfactors.com` | Parsed and scored, cover letter weighted lower than resume | Moderate | Enterprise-strict | \~1.5–2% | Yes, but lower weight | Default for SAP-stack employers; strong in Europe/MEA/Asia |
| Ashby | `ashbyhq.com` | Capable ML parser | Moderate | Tolerant, but **punishes over-designed PDFs** specifically | \~2–3% | Optional | Common at YC/AI-company postings |
| SmartRecruiters | `smartrecruiters.com` | AI ranking layer on top of parsing | Moderate | Format and keywords weighted roughly equally | \~2% | Optional | Strong in Europe |
| Workable | `workable.com` | Capable parser + AI screening layer | Moderate | Tolerant | \~2% | Optional | SMB/mid-market, strong UK/EU |
| BambooHR | `bamboohr.com` | Simple, SMB-oriented | Lower | Generally forgiving | \~2–3% | Optional | Perfect ATS score matters less at this scale |
| Jobvite | `jobvite.com` | Simple, mid-market US | Lower | Generally forgiving | \~2–3% | Optional | Mid-market alternative to Workday/Greenhouse |
| **Unknown / undetected** | — | Assume literal matching (safer) | Assume high | Assume strict | **1.5% hard ceiling** | Generate one, short, keyword-light | See Safe Mode, §5 |

> Note for whoever reviews this: exact market-share figures for these vendors vary by source and shift over time — don't hardcode a "market share" weight into any ranking logic. The registry above should be treated as a living config the team updates, not a one-time hardcode.

---

## 3. Architecture — where this plugs in

```
[Job posting URL] 
      │
      ▼
 ┌─────────────────┐
 │  ATS Detector    │  NEW — runs before Researcher
 └────────┬─────────┘
          │  ats_profile (from registry, or "unknown" → safe mode)
          ▼
 ┌─────────────────┐
 │ Researcher Agent │  extended: builds Keyword Evidence Matrix,
 │                  │  pulls canonical title variants, carries ats_profile forward
 └────────┬─────────┘
          ▼
 ┌─────────────────┐
 │  Writer Agent    │  extended: branches phrasing/density/date-format/
 │                  │  cover-letter decisions off ats_profile
 └────────┬─────────┘
          ▼
 ┌─────────────────┐
 │  Auditor Agent   │  extended: density check against platform ceiling,
 │                  │  parse-safety simulation, title-match check,
 │                  │  knockout-question pre-check
 └────────┬─────────┘
          ▼
 ┌─────────────────┐
 │  Editor Agent    │  extended: enforces hard format constraints
 │  (export/patch)  │  (tables/columns/graphics) per platform at patch time
 └─────────────────┘
```

The `ats_profile` object should be threaded through the whole pipeline's shared state (whatever state object or context dict already passes between your four agents) — every downstream agent reads it, none re-derives it.

---

## 4. Component-level requirements

### 4.1 ATS Detector (new module)

- **Input:** the job application URL (and/or any posting metadata already scraped).
- **Logic:** substring-match the URL's domain against the `url_signature` field in the registry. First match wins. No match → `platform: "unknown"`, `mode: "safe"`.
- **Output:** an `ats_profile` object with every field from the matched registry row (or the "Unknown / undetected" row's safe-mode defaults).
- **Edge case:** some employers run Workday/Greenhouse etc. on a custom domain (white-labeled career site) with no vendor string in the URL — if the detector can't find a signature, don't guess from styling or content; fall back to `unknown` honestly rather than a false positive. A wrong platform match is worse than no match, because it applies the wrong rules confidently.

### 4.2 Platform Rule Engine

- A thin accessor layer over the registry — e.g. `get_profile(platform_key)` — so agents never read the JSON/YAML file directly or duplicate parsing logic.
- Should expose typed fields (not raw strings) for anything an agent branches on: `keyword_density_ceiling: float`, `allows_tables: bool`, `date_format: enum`, `cover_letter_scored: bool`, `title_weight: enum("low"|"moderate"|"high")`.

### 4.3 Researcher Agent (extend)

- Call the ATS Detector first; attach `ats_profile` to pipeline state.
- Build a **Keyword Evidence Matrix** from the JD, classifying each extracted term into:
  - Hard skill / certification (highest weight everywhere)
  - Soft/culture keyword (relevant mainly to screening questions, not scoring)
  - Canonical title variants (pull industry-standard title phrasing so a title mismatch — e.g. candidate's actual title vs. JD's title — can be flagged before the Writer touches it)
- This matrix is platform-agnostic; the *consumption* of it is what varies downstream.

### 4.4 Writer Agent (extend)

Branch on `ats_profile` for:

- **Keyword density target:** aim for 2–4 occurrences of each top keyword, but never exceed `ats_profile.keyword_density_ceiling`.
- **Phrasing strategy:** if `title_weight` is "high" (Workday, Taleo) or `matching_style` is literal/Boolean (iCIMS), prioritize exact JD phrase matches. If `matching_style` is semantic (Greenhouse, Lever, Ashby), the literal phrase should still appear once (covers the exact-match floor every platform still rewards) but natural paraphrase can carry more of the document.
- **Date formatting:** MM/YYYY for Workday; full month name for Taleo; flexible elsewhere — don't let a single global date format bleed across every export.
- **Title handling:** under Rule 0, never silently rewrite the candidate's actual title to match the JD's. If `title_weight` is high and a true equivalence exists, echo the JD's exact title language; otherwise add a truthful parenthetical (e.g., "Client Happiness Specialist (Customer Success Manager equivalent)") rather than fabricate.
- **Cover letter generation:** always generate one when `ats_profile.cover_letter_scored` is true; make it optional elsewhere; when the platform merges it into resume text for scoring (Taleo), keep it short and keyword-light so it doesn't push the combined document over the density ceiling.

### 4.5 Auditor Agent (extend) — this is where most of the new value lives

Add four checks, all gated by `ats_profile`:

1. **Density calculator** — count occurrences of each top keyword ÷ total resume word count. Flag anything over `ats_profile.keyword_density_ceiling` as a stuffing risk, and anything at zero for a top-5 keyword as under-optimized.
2. **Parse-safety simulator** — strip the patched resume down to plain text the way the target platform's parser would, and confirm name/email/phone and section headers still extract cleanly and in the right order. If `ats_profile.allows_tables` is false, hard-fail on any table/column/text-box in the document — don't just warn.
3. **Title-match check** — compare candidate's resume title against the JD's canonical title (from the Researcher's matrix). If `title_weight` is "high" and there's a mismatch with no truthful equivalence noted, flag it for review rather than silently shipping.
4. **Knockout-question pre-check** — before auto-submitting, scan the application page for binary/dropdown screening questions and compare against the candidate's master profile. A disqualifying mismatch should skip or flag the application rather than waste a submission that'll auto-archive unread. (On Taleo specifically, remember these answers blend into the *scored* percentage, not just a pass/fail gate — treat a weak-but-not-disqualifying answer as a soft density/score risk too, not only a binary knockout.)

### 4.6 Editor / Export Agent (extend)

- Enforce the hard format constraints from `ats_profile` **at patch time**, not just as an Auditor warning — if `allows_tables` is false, the exported docx must not contain tables, multi-column sections, text boxes, or contact info embedded in a header/footer graphic, full stop.
- This applies universally regardless of platform: never put contact info only inside a graphic or header element, since multiple parsers (Workday, Taleo) are known to lose it there.

---

## 5. Safe Mode (unknown platform)

When detection fails, do **not** default to the most permissive settings. Default to the strictest common denominator across the whole registry:

- Date format: MM/YYYY
- Tables/columns/text boxes: none
- Keyword density ceiling: 1.5%
- Keyword phrasing: literal JD phrase present at least once *and* a natural paraphrase nearby (covers both literal and semantic matchers at once)
- Cover letter: generate one, short, keyword-light
- Title handling: treat as high title-weight (safer to match exactly when truthful, than to assume it doesn't matter)

---

## 6. Shared state / data model

Add an `ats_profile` object to whatever shared pipeline state already exists. Suggested shape (adapt field names to match existing conventions in the repo rather than introducing a parallel naming scheme):

```json
{
  "platform": "greenhouse",
  "detected": true,
  "matching_style": "semantic",
  "title_weight": "low",
  "allows_tables": true,
  "date_format": "flexible",
  "keyword_density_ceiling": 0.03,
  "cover_letter_scored": true,
  "quirks": ["feeds cover letter into score"]
}
```

For the unknown case: `"platform": "unknown", "detected": false, "mode": "safe"`, with the Safe Mode values from §5 populated into the same fields so downstream agents never need an `if unknown` branch — they just read the profile.

---

## 7. Acceptance criteria / test cases

Implement and pass at minimum:

1. Given a Workday URL and a resume where the candidate's actual title doesn't match the JD title with no equivalence noted → Auditor flags title mismatch.
2. Given a Taleo URL and a resume containing a table → Editor refuses to export until the table is removed; Auditor's parse-safety check fails loudly, not silently.
3. Given a Greenhouse application with no cover letter → Writer generates one before the Auditor runs (since Greenhouse scores it).
4. Given an unrecognized custom domain → `ats_profile.detected == false`, Safe Mode values applied, and the resume still exports successfully with the 1.5% density ceiling enforced.
5. Given a JD keyword count that would push density to 5% if inserted at the Writer's default rate → Auditor catches it pre-export and the Writer's output is revised down, not just flagged after the fact.
6. Given a Taleo screening question answered "weak but not disqualifying" → system logs this as a score risk (not just a pass), distinct from how a Newton-style binary knockout is logged.

---

## 8. Non-negotiable constraints

- **Rule 0 holds everywhere in this feature.** No title rewriting, no fabricated keyword claims, no invented certifications — ever, regardless of how much it would help a specific platform's score. Truthful equivalence framing (parenthetical) is the only tool available for title mismatches.
- **Never trade human readability for platform score.** If a platform-specific optimization would make the resume read worse to a human recruiter, the dual-gate philosophy wins — don't ship it.
- **The registry is data, not code.** Platform names, thresholds, and quirks must live in the config file, not scattered through conditional logic in the four agents. Updating a platform's rules later should mean editing one JSON/YAML entry, not hunting through agent code.

---

## 9. Deliverables expected from the agent

- `ats_registry.json` (or `.yaml`) — the platform table from §2.
- `ats_detector.py` (or equivalent) — URL-signature matching + safe-mode fallback.
- `platform_rules.py` (or equivalent) — typed accessor over the registry.
- Modifications to the existing Researcher, Writer, Auditor, and Editor modules to consume `ats_profile` as described in §4.
- Unit tests covering every case in §7.
- A short summary at the end of the change: which files were created/modified, and confirmation all §7 tests pass.