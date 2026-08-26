"""
agent.py — AI Job Application Agent
Main entry point. Orchestrates the full pipeline.

Usage:
    py agent.py --url https://jobs.lever.co/company/role
    py agent.py --url URL --no-simplify        # Skip Simplify extension, use JD keywords only
    py agent.py --url URL --passes 3           # Run 3 AI detection passes (default: 2)
    py agent.py --url URL --output ./output    # Custom output directory

First-time setup:
    1. py -m pip install -r requirements.txt
    2. py -m playwright install chromium
    3. py pdf_to_resume.py    # Parse your PDF resume into base_resume.json
    4. Copy .env.example to .env and add your GEMINI_API_KEY
    5. Make sure Chrome is closed before running (agent uses your Chrome Profile 8)
"""

import argparse
import json
import os
import re
import sys

# Fix Windows terminal encoding for Unicode output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import time
from pathlib import Path
from datetime import datetime


def print_banner():
    """Print the agent startup banner."""
    print()
    print("=" * 60)
    print("  AI JOB APPLICATION AGENT")
    print("  Jalal Khan  |  Gemini 2.5 Flash  |  Real Simplify Scores")
    print("=" * 60)
    print()


def print_step(step: int, name: str):
    """Print a pipeline step header."""
    print()
    print(f"---- STEP {step}: {name} " + "-" * max(0, 45 - len(name)))


def print_success(message: str):
    print(f"  [OK] {message}")


def print_warning(message: str):
    print(f"  [WARN] {message}")


def print_error(message: str):
    print(f"  [ERR] {message}")


def check_prerequisites() -> bool:
    """Check that all required files and configs exist."""
    all_ok = True

    # Check .env
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        print_warning(".env file not found. Copy .env.example to .env and fill in your API key.")
        all_ok = False
    else:
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("GEMINI_API_KEY"):
            print_warning("GEMINI_API_KEY is empty in .env. Get your free key at aistudio.google.com")
            all_ok = False

    # Check base_resume.json
    resume_path = Path(__file__).parent / "base_resume.json"
    if not resume_path.exists():
        print_warning("base_resume.json not found.")
        print("  Run: python pdf_to_resume.py")
        all_ok = False

    # Check ai_signs.json
    signs_path = Path(__file__).parent / "ai_signs.json"
    if not signs_path.exists():
        print_warning("ai_signs.json not found.")
        all_ok = False

    return all_ok


def load_base_resume() -> dict:
    """Load the base resume from base_resume.json."""
    resume_path = Path(__file__).parent / "base_resume.json"
    with open(resume_path, "r", encoding="utf-8") as f:
        return json.load(f)


def extract_keywords_from_jd(jd_text: str, base_resume: dict) -> list:
    """
    Intelligent LLM-based keyword extraction using Gemini.
    Passes BOTH Job Description AND Master Resume to Gemini for semantic ATS comparison.
    """
    try:
        from llm_matcher import analyze_jd_and_resume_with_gemini
        llm_res = analyze_jd_and_resume_with_gemini(jd_text, base_resume)
        missing = llm_res.get("missing_keywords", [])
        if missing:
            print(f"[Agent] Gemini LLM identified {len(missing)} missing hard skills/titles")
            return missing
    except Exception as e:
        print(f"[Agent] LLM keyword extraction note: {e}")

    return []


def _format_keyword_coverage_report(
    missing_keywords: list,
    embedded_keywords: list,
    still_missing: list,
    simplify_score_before: int | None,
) -> str:
    """Format the keyword injection result as a clean report."""
    lines = []
    lines.append("")
    lines.append("  ┌─────────────────────────────────────────────┐")
    lines.append("  │           KEYWORD INJECTION RESULTS          │")
    lines.append("  └─────────────────────────────────────────────┘")

    if simplify_score_before is not None:
        lines.append(f"  Simplify Score (before): {simplify_score_before}%")
        if still_missing:
            remaining_pct = round(
                len(still_missing) / len(missing_keywords) * 100
            ) if missing_keywords else 0
            expected_gain = 100 - remaining_pct
            lines.append(f"  Keywords injected: {len(embedded_keywords)}/{len(missing_keywords)}"
                         f" ({expected_gain}% of missing keywords covered)")
        else:
            lines.append(f"  Keywords injected: {len(embedded_keywords)}/{len(missing_keywords)} (ALL injected)")
            lines.append("  Expected Simplify Score: 90%+")
    else:
        lines.append(f"  Keywords found in JD: {len(missing_keywords)}")
        lines.append(f"  Keywords injected: {len(embedded_keywords)}")

    if embedded_keywords:
        lines.append(f"  Newly added: {', '.join(embedded_keywords[:10])}"
                     + (f"... +{len(embedded_keywords)-10} more" if len(embedded_keywords) > 10 else ""))

    if still_missing:
        lines.append(f"  Still missing ({len(still_missing)}): {', '.join(still_missing)}")
        lines.append("  → Upload .docx to Simplify to verify actual score")
    else:
        lines.append("  → Upload .docx to Simplify to confirm 90%+ score")

    return "\n".join(lines)


def run_pipeline(
    url: str,
    custom_keywords: str = "",
    no_simplify: bool = False,
    passes: int = 2,
    output_dir: str = None,
) -> str:
    """Run full pipeline and return path to generated Word document."""
    from dotenv import load_dotenv
    load_dotenv()

    start_time = time.time()
    
    # ─── STEP 1: Load base resume ─────────────────────────────────────────────
    print_step(1, "Loading Base Resume")
    base_resume = load_base_resume()
    print_success(f"Loaded resume for: {base_resume.get('name', 'Unknown')}")

    # ─── STEP 2: Scrape JD ────────────────────────────────────────────────────
    print_step(2, "Scraping Job Description")
    from scraper import scrape_jd_sync

    try:
        jd_data = scrape_jd_sync(url)
        company = jd_data["company"]
        role = jd_data["role"]
        jd_text = jd_data["jd_text"]
        print_success(f"Company: {company}")
        print_success(f"Role: {role}")
        print_success(f"JD text: {len(jd_text):,} characters")
    except Exception as e:
        print_error(f"JD scraping failed: {e}")
        raise

    # ─── STEP 3: Simplify Score + Keywords ────────────────────────────────────
    missing_keywords = []
    simplify_data = None
    simplify_score_before = None

    user_kws = [k.strip() for k in custom_keywords.replace("\n", ",").replace(";", ",").split(",") if k.strip()] if custom_keywords else []

    if user_kws:
        print_step(3, "Using User-Specified Simplify Keywords")
        missing_keywords = user_kws
        print_success(f"Targeting {len(missing_keywords)} missing keywords: {', '.join(missing_keywords)}")
    elif no_simplify:
        print_step(3, "Simplify Score Reader [SKIPPED - --no-simplify]")
        print_warning("Using JD keyword extraction as fallback (scores will be estimated, not real).")
        missing_keywords = extract_keywords_from_jd(jd_text, base_resume)
        print_success(f"Extracted {len(missing_keywords)} missing keywords from JD text")
        if missing_keywords:
            print(f"  Keywords: {', '.join(missing_keywords[:10])}"
                  + (f"... +{len(missing_keywords)-10} more" if len(missing_keywords) > 10 else ""))
    else:
        print_step(3, "Reading Real Simplify ATS Score")
        print("  Launching Chrome with your Simplify extension (Profile 8)...")
        from simplify_reader import read_simplify_score_sync

        try:
            simplify_data = read_simplify_score_sync(url, company, role)

            if simplify_data.get("success"):
                simplify_score_before = simplify_data["score"]
                missing_keywords = simplify_data["missing_keywords"]
                matching_keywords = simplify_data.get("matching_keywords", [])

                print_success(f"Real Simplify ATS Score: {simplify_score_before}%")
                print_success(f"Keywords missing from resume: {len(missing_keywords)}")
                print_success(f"Keywords already in resume: {len(matching_keywords)}")

                if missing_keywords:
                    print(f"  Missing: {', '.join(missing_keywords[:8])}"
                          + (f"... +{len(missing_keywords)-8} more" if len(missing_keywords) > 8 else ""))
                else:
                    print_success("All JD keywords already in resume!")
            else:
                error = simplify_data.get("error", "Unknown error")
                print_warning(f"Simplify read failed: {error}")
                print_warning("Falling back to JD keyword extraction (scores estimated, not real)")
                missing_keywords = extract_keywords_from_jd(jd_text, base_resume)
                print_success(f"Extracted {len(missing_keywords)} keywords from JD")

        except Exception as e:
            print_warning(f"Simplify reader error: {e}")
            print_warning("Falling back to JD keyword extraction")
            missing_keywords = extract_keywords_from_jd(jd_text, base_resume)

    # ─── STEP 4: Gemini Resume Rewrite ────────────────────────────────────────
    print_step(4, "Rewriting Resume with Gemini (Strict Keyword Injection)")
    from rewriter import rewrite_resume, _check_keyword_coverage

    try:
        rewritten_resume = rewrite_resume(
            base_resume=base_resume,
            jd_text=jd_text,
            missing_keywords=missing_keywords,
            company=company,
            role=role,
        )
        print_success("Resume rewritten successfully")
    except Exception as e:
        print_error(f"Rewriter failed: {e}")
        raise

    # ─── STEP 5: AI Detection Loop ────────────────────────────────────────────
    print_step(5, f"AI Detection Loop ({passes} passes)")
    from ai_detector import run_ai_detection_loop

    try:
        cleaned_resume = run_ai_detection_loop(rewritten_resume, num_passes=passes)
        print_success(f"AI detection loop complete ({passes} passes)")
    except Exception as e:
        print_error(f"AI detector failed: {e}")
        print_warning("Using rewritten resume without AI cleanup")
        cleaned_resume = rewritten_resume

    # ─── STEP 6: Keyword Coverage Report ──────────────────────────────────────
    print_step(6, "Keyword Coverage Report")
    if missing_keywords:
        embedded, still_missing = _check_keyword_coverage(cleaned_resume, missing_keywords)
        coverage_report = _format_keyword_coverage_report(
            missing_keywords=missing_keywords,
            embedded_keywords=embedded,
            still_missing=still_missing,
            simplify_score_before=simplify_score_before,
        )
        print(coverage_report)
    else:
        embedded = []
        still_missing = []
        print_success("No missing keywords to inject (resume already matches JD)")

    # ─── STEP 7: Build Word Document ──────────────────────────────────────────
    print_step(7, "Generating Word Document")
    from scraper import clean_role_title
    role = clean_role_title(role, company)
    for sec in ("education", "certifications", "contact", "name", "projects"):
        if sec in base_resume and (sec not in cleaned_resume or not cleaned_resume[sec]):
            cleaned_resume[sec] = base_resume[sec]

    orig_docx_path = BASE_DIR / "master_resume_original.docx"

    try:
        if orig_docx_path.exists():
            from docx_patcher import patch_docx_with_rewritten_resume
            output_path = patch_docx_with_rewritten_resume(
                original_docx_path=str(orig_docx_path),
                rewritten_resume=cleaned_resume,
                company=company,
                role=role,
                output_dir=output_dir,
            )
            print_success(f"Patched original Canva DOCX template saved: {output_path}")
        else:
            from resume_builder import build_resume_docx
            output_path = build_resume_docx(
                resume=cleaned_resume,
                company=company,
                role=role,
                output_dir=output_dir,
            )
            print_success(f"Word document saved: {output_path}")

        # Automatically convert to PDF
        try:
            from resume_builder import convert_to_pdf
            pdf_out = convert_to_pdf(output_path)
            print_success(f"PDF document saved: {pdf_out}")
        except Exception as pdf_err:
            print_warning(f"PDF conversion note: {pdf_err}")
    except Exception as e:
        print_error(f"Resume builder failed: {e}")
        raise

    # ─── Done ──────────────────────────────────────────────────────────────────
    elapsed = time.time() - start_time

    print()
    print("=" * 60)
    print("  PIPELINE COMPLETE")
    print(f"  Time: {elapsed:.1f}s")
    print(f"  File: {output_path}")
    if simplify_score_before is not None:
        print(f"  Simplify Score Before: {simplify_score_before}%")
        print(f"  Keywords Injected: {len(embedded)}/{len(missing_keywords)}")
        print("  Next: Upload the .docx to Simplify to see your new score")
    print("=" * 60)
    print()

    # Save a run log
    _save_run_log(
        url, company, role, missing_keywords, embedded, still_missing,
        simplify_data, output_path, elapsed
    )

    return output_path


def _save_run_log(
    url, company, role, missing_keywords, embedded_keywords,
    still_missing, simplify_data, output_path, elapsed
):
    """Save a JSON log of this run."""
    log_dir = Path(__file__).parent / "output" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"run_{timestamp}.json"

    coverage_pct = (
        round(len(embedded_keywords) / len(missing_keywords) * 100)
        if missing_keywords else 100
    )

    log_data = {
        "timestamp": datetime.now().isoformat(),
        "url": url,
        "company": company,
        "role": role,
        "simplify_score_before": simplify_data.get("score") if simplify_data else None,
        "simplify_score_source": "real_extension" if (simplify_data and simplify_data.get("success")) else "fallback_jd_extraction",
        "missing_keywords_count": len(missing_keywords),
        "missing_keywords": missing_keywords,
        "embedded_keywords": embedded_keywords,
        "still_missing_keywords": still_missing,
        "keyword_coverage_pct": coverage_pct,
        "output_file": output_path,
        "elapsed_seconds": round(elapsed, 2),
    }

    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2)

    print(f"  [Log] Run log saved: {log_path}")


def main():
    print_banner()

    parser = argparse.ArgumentParser(
        description="AI Job Application Agent — Auto-tailor your resume to any JD",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python agent.py --url https://jobs.lever.co/company/role-id
  python agent.py --url https://www.linkedin.com/jobs/view/123456789/
  python agent.py --url URL --no-simplify
  python agent.py --url URL --passes 3
  python agent.py --url URL --output C:/MyResumes/output
        """,
    )

    parser.add_argument(
        "--url", "-u",
        required=True,
        help="Job description URL (LinkedIn, Lever, Greenhouse, Workday, etc.)",
    )
    parser.add_argument(
        "--no-simplify",
        action="store_true",
        help=(
            "Skip Simplify Chrome extension. Extract keywords from JD text directly. "
            "Note: Scores will be estimated, not the real Simplify ATS score."
        ),
    )
    parser.add_argument(
        "--passes", "-p",
        type=int,
        default=2,
        choices=[1, 2, 3],
        help="Number of AI detection passes (default: 2)",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(Path(__file__).parent / "output"),
        help="Output directory for generated resumes",
    )
    parser.add_argument(
        "--skip-checks",
        action="store_true",
        help="Skip prerequisite checks (for testing)",
    )
    parser.add_argument(
        "--keywords",
        type=str,
        default="",
        help="Optional comma-separated list of exact missing keywords from Simplify (e.g. 'end-to-end, product features, FastAPI')",
    )

    args = parser.parse_args()

    # Validate URL
    if not args.url.startswith(("http://", "https://")):
        print_error(f"Invalid URL: {args.url}")
        print("URL must start with http:// or https://")
        sys.exit(1)

    # Check prerequisites
    if not args.skip_checks:
        print("Checking prerequisites...")
        if not check_prerequisites():
            print()
            print("Setup required. See README.md for instructions.")
            sys.exit(1)
        print_success("All prerequisites OK")

    # Run the pipeline
    try:
        output_path = run_pipeline(
            url=args.url,
            custom_keywords=args.keywords,
            no_simplify=args.no_simplify,
            passes=args.passes,
            output_dir=args.output,
        )

        # Open the output folder in Explorer
        output_folder = str(Path(output_path).parent)
        try:
            import subprocess
            subprocess.Popen(f'explorer "{output_folder}"')
        except Exception:
            pass

        sys.exit(0)

    except KeyboardInterrupt:
        print("\n[Agent] Interrupted by user")
        sys.exit(1)

    except Exception as e:
        print_error(f"Pipeline failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
