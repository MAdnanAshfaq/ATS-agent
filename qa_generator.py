"""
qa_generator.py — Gemini-powered Job Application Questions Copilot.

Answers custom job application questions (Greenhouse, Lever, Workday, Ashby)
grounded in:
1. Candidate's Master Resume (base_resume.json) — Truth & authentic career facts.
2. Job Description & Company Intelligence — Culture, industry domain, mission.
3. Dani's Human-Voice Rules (Rules 0–16) — Zero AI buzzwords, high burstiness, plain strong verbs.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, List, Dict

from google import genai
from google.genai import types

from gemini_client import get_gemini_client
from human_voice_audit import load_ai_tells


def _clean_json(text: str) -> str:
    """Extract and parse valid JSON from LLM response."""
    text = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
    text = re.sub(r'\s*```$', '', text.strip(), flags=re.MULTILINE)
    match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', text)
    if match:
        return match.group(1).strip()
    return text.strip()


def _format_skills_list(skills_data: Any) -> str:
    """Safely format skills whether list of strings, list of dicts, dict of categories, or comma-separated string."""
    if not skills_data:
        return ""
    if isinstance(skills_data, str):
        return skills_data
    items = []
    if isinstance(skills_data, dict):
        for cat, sks in skills_data.items():
            if isinstance(sks, list):
                items.extend([str(s) for s in sks if s])
            elif isinstance(sks, str):
                items.append(f"{cat}: {sks}")
            elif isinstance(sks, dict):
                items.extend([str(v) for v in sks.values() if v])
    elif isinstance(skills_data, list):
        for sk in skills_data:
            if isinstance(sk, str):
                items.append(sk)
            elif isinstance(sk, dict):
                if "skills" in sk and isinstance(sk["skills"], list):
                    items.extend([str(s) for s in sk["skills"] if s])
                elif "name" in sk:
                    items.append(str(sk["name"]))
                elif "items" in sk and isinstance(sk["items"], list):
                    items.extend([str(s) for s in sk["items"] if s])
                else:
                    for val in sk.values():
                        if isinstance(val, list):
                            items.extend([str(s) for s in val if s])
                        elif isinstance(val, str):
                            items.append(val)
            else:
                items.append(str(sk))
    return ", ".join(items[:40])


def split_raw_questions(text: str) -> List[str]:
    """
    Intelligently split pasted questions text into individual, discrete questions.
    Handles question marks, asterisks, bullet points, numbers, and Yes/No options.
    """
    text = str(text or "").replace('\r\n', '\n').replace('\r', '\n')
    raw_blocks = re.split(r'\n\s*\n', text)
    extracted = []

    for block in raw_blocks:
        lines = [l.strip() for l in block.split('\n') if l.strip()]
        if not lines:
            continue
        current_question = []
        for line in lines:
            is_new_q = bool(
                re.match(r'^(?:\d+[\.\)]|\-|\*|Q\d*:?|Question\s*\d*:?)\s+', line, re.IGNORECASE) or
                (current_question and re.search(r'[\?\*]\s*$', str(current_question[-1]))) or
                re.match(r'^(?:Do you|Are you|Can you|Will you|Have you|Is this|Is the|What|Why|How|Tell us|Describe|Please|Due to)\b', line, re.IGNORECASE)
            )
            # Skip solitary Yes/No lines if they are checkboxes from copied web forms
            if line.lower() in ('yes', 'no', 'yes/no', 'n/a', 'true', 'false') and current_question:
                continue
            if is_new_q and current_question:
                extracted.append(' '.join([str(x) for x in current_question if x]))
                current_question = [line]
            else:
                current_question.append(line)
        if current_question:
            extracted.append(' '.join([str(x) for x in current_question if x]))

    final = []
    for q in extracted:
        clean_q = re.sub(r'^(?:\d+[\.\)]|\-|\*|Q\d*:?|Question\s*\d*:?)\s+', '', q).strip()
        if clean_q and len(clean_q) > 6 and clean_q.lower() not in ('yes', 'no', 'n/a'):
            final.append(clean_q)
    return final


def answer_application_questions(
    questions_input: Any,
    base_resume: dict,
    jd_text: str = "",
    company: str = "Target Company",
    role: str = "Software Engineer",
) -> List[Dict[str, Any]]:
    """
    Generate interview-true, human-voiced answers to application-specific questions.

    Returns:
        List of dicts: [
            {
                "question": str,
                "answer": str,
                "word_count": int,
                "char_count": int,
                "tone_type": str
            }
        ]
    """
    # 1. Normalize questions_input into a clean List[str]
    raw_input = questions_input
    if isinstance(raw_input, str):
        s_clean = raw_input.strip()
        if (s_clean.startswith("[") and s_clean.endswith("]")) or (s_clean.startswith("{") and s_clean.endswith("}")):
            try:
                parsed_json = json.loads(s_clean)
                if isinstance(parsed_json, list):
                    raw_input = parsed_json
                elif isinstance(parsed_json, dict) and "questions" in parsed_json:
                    raw_input = parsed_json["questions"]
            except Exception:
                pass

    questions: List[str] = []
    if isinstance(raw_input, str):
        questions = split_raw_questions(raw_input)
    elif isinstance(raw_input, list):
        for q in raw_input:
            if isinstance(q, str):
                cleaned = q.strip()
                if cleaned:
                    questions.append(cleaned)
            elif isinstance(q, dict):
                q_text = q.get("question") or q.get("text") or q.get("title") or q.get("prompt") or ""
                if not q_text:
                    for v in q.values():
                        if isinstance(v, str) and len(v.strip()) > 5:
                            q_text = v.strip()
                            break
                if q_text:
                    questions.append(str(q_text).strip())
            else:
                questions.append(str(q).strip())
    elif raw_input:
        questions = [str(raw_input).strip()]

    if not questions:
        return []

    client = get_gemini_client()
    ai_tells = load_ai_tells()
    banned_words_raw = ai_tells.get("banned_words", [])
    banned_words = ", ".join([str(w) for w in banned_words_raw[:20] if isinstance(w, (str, int, float))])
    cliche_openers_raw = ai_tells.get("cliche_openers", [])
    cliche_openers = ", ".join([str(c) for c in cliche_openers_raw[:15] if isinstance(c, (str, int, float))])

    base_resume = base_resume or {}
    candidate_name = str(base_resume.get("name") or "Candidate")

    summary_raw = base_resume.get("summary", "")
    if isinstance(summary_raw, list):
        summary = " ".join([str(s) for s in summary_raw if s])
    elif isinstance(summary_raw, dict):
        summary = " ".join([f"{k}: {v}" for k, v in summary_raw.items() if v])
    else:
        summary = str(summary_raw or "")

    skills = _format_skills_list(base_resume.get("skills", []))
    experience_raw = base_resume.get("experience", [])
    if isinstance(experience_raw, dict):
        experience_raw = [experience_raw]
    experience_snippet = json.dumps(experience_raw, indent=2, ensure_ascii=False)[:3500]

    system_prompt = f"""You are Dani's Elite Senior Engineer Application Q&A Copilot.
You have been provided with an array of {len(questions)} application screening questions.
You MUST generate a separate, deeply tailored, senior-level answer for EACH question in the array. The output array MUST have exactly {len(questions)} objects.

STRICT EDITORIAL & TECHNICAL GUARDRAILS (Rules 0–16 from ResumeHQ):

1. ANSWER THE EXACT QUESTION DIRECTLY (ZERO RESUME DUMPING):
   - Never simply regurgitate resume bullet points or dump a laundry list of technologies into a single paragraph.
   - Start immediately with a clear, assertive direct thesis answering what was asked.

2. ACCURATE TECHNICAL & DOMAIN DISTINCTION:
   - Detail the actual system architecture, component delivery, API contracts, deployment pipelines, or business outcomes directly from the candidate's verified experience.
   - Ground answers in the candidate's authentic stack and domain (e.g. React/Node/Postgres for Full Stack, PySpark/Cloud for Data, Go/Kubernetes for DevOps, Salesforce/Enterprise CRM for Sales/Go-To-Market).
   - Never conflate simple reporting tools with deep core production systems.

3. REALISTIC & GROUNDED AI USAGE:
   - When asked about using AI tools (Copilot, ChatGPT, LLMs) to improve your work:
     - Ground the answer in what AI tools actually do well: accelerating boilerplate code, unit test mocks, regex, complex queries, or documentation drafting.
     - NEVER claim AI tools did high-level systems architecture, production security compliance, or deep performance optimization that require human judgment.
     - For "what would you change" or challenges: Describe a realistic edge case (e.g. AI generating subtly incorrect assumptions or outdated API signatures), explaining how it reinforced your rule to always write automated tests and never deploy AI code without thorough validation.

4. FOR SHORT FACTUAL / COMPLIANCE QUESTIONS:
   - "Do you have X+ years...", "Are you authorized to work in the US...", "Do you require sponsorship...":
   - Give an immediate, crisp response followed by 1 factual supporting statement grounded in the candidate's resume.
   - Example: "Yes. I have 6+ years of professional engineering experience building production systems with [candidate's core stack]."
   - Example: "Yes, I am legally authorized to work in the United States."
   - Example: "No, I do not require sponsorship now or in the future."

5. FOR "WHY US" / MISSION / CULTURE QUESTIONS:
   - Connect your real professional background directly to {company}'s specific platform, product, or mission. No sycophantic praise or throat-clearing fluff.

6. TONE, WORD ECONOMY & ZERO BANNED WORDS:
   - Word count: 75–130 words per substantive question. Dense with technical reality, zero fluff.
   - Active first-person voice ("I architected...", "I owned...", "I learned...").
   - Strictly banned AI tells: {banned_words}, {cliche_openers}, "testament", "pivotal", "transformative", "seamless", "robust", "delve", "leverage", "in the dynamic realm of", "game-changer".

CANDIDATE CONTEXT:
Name: {candidate_name}
Summary: {summary}
Skills: {skills}
Verified Experience:
{experience_snippet}

TARGET JOB CONTEXT:
Company: {company}
Role: {role}
JD Excerpt:
{jd_text[:2500]}

OUTPUT JSON FORMAT:
Return strictly a JSON array containing EXACTLY {len(questions)} items:
[
  {{
    "question": "Exact text of Question 1",
    "answer": "Direct, substantive, technically grounded answer.",
    "tone_type": "Technical / Behavioral / Factual"
  }}
]"""

    user_prompt = f"""APPLICATION QUESTIONS TO ANSWER:
{json.dumps(questions, indent=2)}

Generate the human-voiced answers as a JSON array now."""

    from gemini_client import get_candidate_models, extract_clean_text, get_standard_genai_config, record_model_failure, record_model_success
    models = get_candidate_models()
    raw_response = None
    for model_name in models:
        try:
            cfg = get_standard_genai_config(model_name=model_name, max_output_tokens=4096, temperature=0.3, top_p=0.88)
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=cfg,
            )
            clean_res = extract_clean_text(response)
            if clean_res:
                record_model_success(model_name)
                raw_response = clean_res
                break
        except Exception as e:
            record_model_failure(model_name, e)
            print(f"[Q&A Copilot] {model_name} error: {e}")
            time.sleep(0.5)

    if not raw_response:
        return []

    try:
        parsed_answers = json.loads(_clean_json(raw_response))
        if isinstance(parsed_answers, dict):
            # If wrapped in an object like {"answers": [...]}
            for v in parsed_answers.values():
                if isinstance(v, list):
                    parsed_answers = v
                    break

        results = []
        for item in parsed_answers:
            if isinstance(item, dict):
                ans = item.get("answer", "").strip()
                # Basic cleanup
                ans = re.sub(r'^(?:Answer:\s*|A:\s*)', '', ans, flags=re.IGNORECASE)
                words = ans.split()
                results.append({
                    "question": item.get("question", "").strip(),
                    "answer": ans,
                    "word_count": len(words),
                    "char_count": len(ans),
                    "tone_type": item.get("tone_type", "Application Q&A")
                })
        return results

    except Exception as e:
        print(f"[Q&A Copilot] JSON Parse error: {e}. Raw text: {raw_response[:200]}")
        return [{
            "question": questions[0] if questions else "Application Question",
            "answer": raw_response.strip(),
            "word_count": len(raw_response.split()),
            "char_count": len(raw_response),
            "tone_type": "Application Q&A"
        }]


if __name__ == "__main__":
    from agent import load_base_resume
    base = load_base_resume()
    sample_q = [
        "Sports are at the core of everything we do here. Tell us about your relationship with them — are you a fan, athlete, Underdog user, or just someone who appreciates a great game?",
        "Describe a time you solved a data pipeline outage and how you prevented it from happening again."
    ]
    res = answer_application_questions(sample_q, base, jd_text="Underdog Fantasy sports gaming platform", company="Underdog", role="Senior Data Engineer")
    print("Q&A Results:", json.dumps(res, indent=2))
