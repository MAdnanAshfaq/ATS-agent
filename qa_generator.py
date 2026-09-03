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


def answer_application_questions(
    questions_input: str | List[str],
    base_resume: dict,
    jd_text: str = "",
    company: str = "Target Company",
    role: str = "Data Engineer",
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
                "tone_type": str (e.g. "Culture / Passion", "Behavioral STAR", "Technical Experience")
            }
        ]
    """
def split_raw_questions(text: str) -> List[str]:
    """
    Intelligently split pasted questions text into individual, discrete questions.
    Handles question marks, asterisks, bullet points, numbers, and Yes/No options.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
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
                (current_question and re.search(r'[\?\*]\s*$', current_question[-1])) or
                re.match(r'^(?:Do you|Are you|Can you|Will you|Have you|Is this|Is the|What|Why|How|Tell us|Describe|Please|Due to)\b', line, re.IGNORECASE)
            )
            # Skip solitary Yes/No lines if they are checkboxes from copied web forms
            if line.lower() in ('yes', 'no', 'yes/no', 'n/a', 'true', 'false') and current_question:
                continue
            if is_new_q and current_question:
                extracted.append(' '.join(current_question))
                current_question = [line]
            else:
                current_question.append(line)
        if current_question:
            extracted.append(' '.join(current_question))

    final = []
    for q in extracted:
        clean_q = re.sub(r'^(?:\d+[\.\)]|\-|\*|Q\d*:?|Question\s*\d*:?)\s+', '', q).strip()
        if clean_q and len(clean_q) > 6 and clean_q.lower() not in ('yes', 'no', 'n/a'):
            final.append(clean_q)
    return final


def answer_application_questions(
    questions_input: str | List[str],
    base_resume: dict,
    jd_text: str = "",
    company: str = "Target Company",
    role: str = "Data Engineer",
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
    if isinstance(questions_input, str):
        questions = split_raw_questions(questions_input)
    else:
        questions = list(questions_input)

    if not questions:
        return []

    client = get_gemini_client()
    ai_tells = load_ai_tells()
    banned_words = ", ".join(ai_tells.get("banned_words", [])[:20])
    cliche_openers = ", ".join(ai_tells.get("cliche_openers", [])[:15])

    candidate_name = base_resume.get("name", "Candidate")
    summary = base_resume.get("summary", "")
    skills = ", ".join(base_resume.get("skills", [])[:25])
    experience_snippet = json.dumps(base_resume.get("experience", []), indent=2, ensure_ascii=False)[:3500]

    system_prompt = f"""You are Dani's Elite Senior Engineer Application Q&A Copilot.
You have been provided with an array of {len(questions)} application screening questions.
You MUST generate a separate, deeply tailored, senior-level answer for EACH question in the array. The output array MUST have exactly {len(questions)} objects.

STRICT EDITORIAL & TECHNICAL GUARDRAILS (Rules 0–16 from ResumeHQ):

1. ANSWER THE EXACT QUESTION DIRECTLY (ZERO RESUME DUMPING):
   - Never simply regurgitate resume bullet points or dump a laundry list of 8 technologies into a single paragraph.
   - Start immediately with a clear, assertive direct thesis answering what was asked.

2. ACCURATE TECHNICAL DISTINCTION (ML SYSTEMS vs. BI / DASHBOARDS):
   - If asked about "ML systems" or "production data systems":
     - Detail the actual data engineering architecture that feeds the ML lifecycle: feature-readiness pipelines, point-in-time joins, data contracts, validation gates, batch inference ingestion, and gold feature tables powering predictive models (such as patient risk stratification or cost-of-care models).
     - NEVER conflate BI dashboards (e.g. Power BI semantic models, Direct Lake, DAX measures) with Machine Learning systems. Keep BI in its place.

3. REALISTIC & GROUNDED AI USAGE (ZERO HALLUCINATED CAPABILITIES):
   - When asked about using AI (Copilot, LLMs) to improve your work:
     - Ground the answer in what AI tools actually do well: accelerating boilerplate PySpark schema structs, complex regex extractions, repetitive unit test mocks, or SQL window function drafts.
     - NEVER claim AI tools did "performance tuning", "Delta table partitioning", "storage migration", or "architecture design"—hiring managers know AI cannot do that and will instantly flag it as fake.
     - For "what would you change": Describe a realistic engineering edge case (e.g. AI generating outer joins that failed silently on null keys, hallucinating non-existent Spark methods, or missing healthcare-specific code constraints), explaining how it reinforced your rule to always write automated unit tests and never deploy AI code without manual edge-case auditing.
   - NEVER misuse ML terminology: "Data drift" refers to real-world statistical distribution changes in production data over time. NEVER say "data drift" when referring to schema nulls, dirty data, or pre-deployment unit test errors.

4. FOR SHORT FACTUAL / COMPLIANCE QUESTIONS:
   - "Do you have 7+ years...", "Are you authorized to work in the US...", "Do you require sponsorship...":
   - Give an immediate, crisp response followed by 1 factual supporting statement.
   - Example: "Yes. I have 8 years of production data engineering experience designing medallion lakehouses and high-throughput pipelines in PySpark, SQL, and Azure."
   - Example: "Yes, I am legally authorized to work in the United States."
   - Example: "No, I do not require sponsorship now or in the future."

5. FOR "WHY US" / MISSION / CULTURE QUESTIONS:
   - Connect your real technical background directly to {company}'s specific platform and data scale. No sycophantic praise or throat-clearing fluff.

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

    models = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
    raw_response = None
    for model_name in models:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[types.Content(role="user", parts=[types.Part(text=system_prompt + "\n\n" + user_prompt)])],
                config=types.GenerateContentConfig(temperature=0.3, top_p=0.88, max_output_tokens=4096),
            )
            raw_response = response.text
            break
        except Exception as e:
            print(f"[Q&A Copilot] {model_name} error: {e}")
            time.sleep(1)

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
