"""
ai_detector.py — Wikipedia AI Writing Detection + Cleanup Loop.
Runs 2 passes of Gemini-powered AI pattern detection and rewriting.
Ensures the final resume reads as naturally human-written.
"""
import json
import os
import re
import time
from typing import Optional
from google import genai
from google.genai import types


def _get_gemini_client():
    """Initialize and return the Gemini client."""
    from google import genai
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not found in .env file.")

    return genai.Client(api_key=api_key)


def _clean_json_response(text: str) -> str:
    """Strip markdown fences from Gemini's response."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    return text.strip()


def _load_ai_signs() -> dict:
    """Load the ai_signs.json rules file."""
    signs_path = os.path.join(os.path.dirname(__file__), "ai_signs.json")
    if not os.path.exists(signs_path):
        raise FileNotFoundError(f"ai_signs.json not found at {signs_path}")
    with open(signs_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def _build_rules_summary(ai_signs: dict) -> str:
    """Build a concise rules summary for the Gemini prompt."""
    lines = []
    for category in ai_signs.get("categories", []):
        lines.append(f"\n## {category['name']}")
        for rule in category.get("rules", []):
            lines.append(f"\n### {rule['name']}")
            lines.append(f"Action: {rule['action']}")
            if rule.get("flags"):
                flags_preview = rule["flags"][:10]
                lines.append(f"Flag words/phrases: {', '.join(flags_preview)}")
            if rule.get("examples"):
                lines.append(f"Examples to avoid: {'; '.join(rule['examples'][:3])}")
    return '\n'.join(lines)


def _validate_structure(original: dict, cleaned: dict) -> bool:
    """Ensure the cleaned resume has the same top-level keys as original."""
    original_keys = {k for k in original.keys() if k != "_raw_text"}
    cleaned_keys = set(cleaned.keys())
    
    required = {"summary", "skills", "experience"}
    if not required.issubset(cleaned_keys):
        return False
    
    # Verify experience count is the same
    if len(cleaned.get("experience", [])) != len(original.get("experience", [])):
        print(f"[Detector] ⚠️  Experience count mismatch: "
              f"{len(original.get('experience', []))} → {len(cleaned.get('experience', []))}")
        # Allow if cleaned has more (sometimes Gemini adds a missing role back)
        # But flag if it loses roles
        if len(cleaned.get("experience", [])) < len(original.get("experience", [])):
            return False
    
    return True


def _check_for_ai_patterns(text: str, ai_signs: dict) -> list:
    """Check text for remaining AI patterns. Returns list of found issues."""
    issues = []
    text_lower = text.lower()
    
    for category in ai_signs.get("categories", []):
        for rule in category.get("rules", []):
            for flag in rule.get("flags", []):
                if flag.lower() in text_lower:
                    issues.append({
                        "rule": rule["name"],
                        "flag": flag,
                        "category": category["name"]
                    })
    
    return issues


def run_detection_pass(
    resume: dict,
    ai_signs: dict,
    pass_number: int,
    client,
    max_retries: int = 3,
) -> dict:
    """
    Run a single detection pass using Gemini.
    Returns the cleaned resume dict.
    """
    rules_summary = _build_rules_summary(ai_signs)
    gemini_instruction = ai_signs.get("gemini_system_instruction", "")
    
    system_prompt = f"""{gemini_instruction}

COMPLETE AI WRITING RULES TO ENFORCE:
{rules_summary}

CRITICAL CONSTRAINTS:
- Do NOT change: company names, job titles, employment dates, school names, graduation dates, 
  actual metrics/numbers, technology names, project names, contact information
- DO change: word choice, sentence structure, phrasing that matches AI patterns above
- Return ONLY valid JSON in exactly the same structure as the input
- No markdown fences, no explanation, just the JSON
- Resume bullets must start with strong past-tense action verbs
- No em dashes (—), no "Not only X but also Y" patterns, no adjective triplets
- Vary bullet point lengths — some short (8-10 words), some longer (15-20 words)"""

    user_prompt = f"""PASS {pass_number} — Detect and rewrite any AI writing patterns.

RESUME TO CLEAN:
{json.dumps(resume, indent=2, ensure_ascii=False)[:6000]}

Check EVERY word against the rules. Rewrite any sentence matching an AI pattern.
Return the full cleaned resume as valid JSON."""

    models = ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.5-flash"]
    print(f"[Detector] Pass {pass_number}: Sending to Gemini...")

    for attempt in range(1, max_retries + 1):
        model_name = models[(attempt - 1) % len(models)]
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)]
                    )
                ],
                config=types.GenerateContentConfig(
                    temperature=0.3,
                    top_p=0.85,
                    max_output_tokens=8192,
                ),
            )
            
            raw_text = response.text
            cleaned_text = _clean_json_response(raw_text)
            cleaned = json.loads(cleaned_text)
            
            if not _validate_structure(resume, cleaned):
                raise ValueError(
                    f"Structure mismatch after Pass {pass_number}. "
                    f"Original keys: {list(resume.keys())}, Cleaned keys: {list(cleaned.keys())}"
                )
            
            print(f"[Detector] Pass {pass_number}: ✅ Clean JSON received (attempt {attempt})")
            return cleaned
        
        except json.JSONDecodeError as e:
            print(f"[Detector] Pass {pass_number}, attempt {attempt}/{max_retries} — JSON error: {e}")
            if attempt < max_retries:
                time.sleep(2)
        
        except ValueError as e:
            print(f"[Detector] Pass {pass_number}, attempt {attempt}/{max_retries} — {e}")
            if attempt < max_retries:
                time.sleep(2)
        
        except Exception as e:
            err_str = str(e)
            print(f"[Detector] Pass {pass_number}, attempt {attempt}/{max_retries} — Error: {err_str}")
            if "RESOURCE_EXHAUSTED" in err_str or "429" in err_str or "503" in err_str:
                print(f"[Detector] Rate limit/high demand hit — waiting 12s before retry...")
                time.sleep(12)
            elif attempt < max_retries:
                time.sleep(2)
    
    print(f"[Detector] ⚠️  Pass {pass_number} failed after {max_retries} attempts. Using previous version.")
    return resume  # Return unchanged if all retries fail


def run_ai_detection_loop(resume: dict, num_passes: int = 2) -> dict:
    """
    Main entry point: Run the full AI detection loop.
    
    Args:
        resume: The rewritten resume dict from rewriter.py
        num_passes: Number of detection passes (default: 2, as per blueprint)
    
    Returns:
        Final cleaned resume dict with AI patterns removed.
    """
    client = _get_gemini_client()
    from google.genai import types
    ai_signs = _load_ai_signs()
    
    print(f"\n[Detector] Starting AI detection loop ({num_passes} passes)...")
    
    # Pre-check: count AI patterns before cleaning
    resume_text = json.dumps(resume)
    initial_issues = _check_for_ai_patterns(resume_text, ai_signs)
    print(f"[Detector] Pre-check: {len(initial_issues)} AI pattern matches found")
    if initial_issues[:5]:
        for issue in initial_issues[:5]:
            print(f"  • [{issue['category']}] '{issue['flag']}' — {issue['rule']}")
        if len(initial_issues) > 5:
            print(f"  ... and {len(initial_issues) - 5} more")
    
    current_resume = resume
    
    for pass_num in range(1, num_passes + 1):
        print(f"\n[Detector] ─── Pass {pass_num}/{num_passes} ───")
        current_resume = run_detection_pass(
            current_resume, ai_signs, pass_num, client
        )
        
        # Post-pass check
        pass_text = json.dumps(current_resume)
        remaining_issues = _check_for_ai_patterns(pass_text, ai_signs)
        print(f"[Detector] Pass {pass_num} complete — {len(remaining_issues)} patterns remaining")
        
        # If clean, exit early
        if not remaining_issues:
            print(f"[Detector] ✅ Resume is clean after pass {pass_num}. Skipping remaining passes.")
            break
    
    # Final check
    final_text = json.dumps(current_resume)
    final_issues = _check_for_ai_patterns(final_text, ai_signs)
    
    if final_issues:
        print(f"\n[Detector] ⚠️  {len(final_issues)} patterns still present after {num_passes} passes:")
        for issue in final_issues[:8]:
            print(f"  • '{issue['flag']}' ({issue['rule']})")
    else:
        print(f"\n[Detector] ✅ All AI patterns eliminated. Resume reads as human-written.")
    
    return current_resume


if __name__ == "__main__":
    """Quick test of the detection loop."""
    import sys
    
    # Load a test resume
    resume_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    if not os.path.exists(resume_path):
        print("ERROR: base_resume.json not found.")
        sys.exit(1)
    
    with open(resume_path, 'r', encoding='utf-8') as f:
        resume = json.load(f)
    
    # Add some AI-pattern phrases to test
    resume["summary"] = (
        "Innovative and transformative software engineer who leveraged cutting-edge technologies "
        "to streamline robust systems. Spearheaded groundbreaking initiatives fostering seamless collaboration."
    )
    
    print("Testing with deliberately AI-sounding summary:")
    print(f"BEFORE: {resume['summary']}\n")
    
    cleaned = run_ai_detection_loop(resume, num_passes=2)
    
    print(f"\nAFTER: {cleaned['summary']}")
