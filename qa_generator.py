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
    if isinstance(questions_input, str):
        # Split by newlines or numbered lines if multiple questions are pasted
        raw_lines = [q.strip() for q in questions_input.split("\n") if q.strip()]
        # Group multiline questions
        questions = []
        current_q = []
        for line in raw_lines:
            if re.match(r'^(?:\d+[\.\)]|\-|\*|\?)\s*', line) and current_q:
                questions.append(" ".join(current_q))
                current_q = [line]
            else:
                current_q.append(line)
        if current_q:
            questions.append(" ".join(current_q))
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

    system_prompt = f"""You are Dani's Human-Voice Application Q&A Copilot.
Your job is to write compelling, interview-true, and human-sounding answers to custom application questions for {candidate_name} applying for {role} at {company}.

STRICT EDITORIAL RULES (Rules 0–16 from ResumeHQ):
1. ZERO AI FLUFF & THROAT-CLEARING:
   - NEVER start with: "I am excited to answer...", "Throughout my career as a passionate data engineer...", "I believe that...", "In today's fast-paced world...".
   - Start immediately with the direct answer or concrete proof.
2. CANDIDATE TRUTH & INTERVIEW DEFENSIBILITY:
   - Only use facts, metrics, and tools from the Candidate Profile below.
   - For technical or "how many years" questions, state the exact years and where they were applied.
3. DOMAIN & CULTURE QUESTIONS (e.g. Sports, Gaming, Healthcare, Mission):
   - Answer in an authentic, personal, conversational voice. Connect the personal angle with real appreciation for the company's product and engineering scale.
4. BEHAVIORAL / SITUATIONAL QUESTIONS:
   - Use the STAR framework (Situation, Task, Action, Result) concisely in 1-2 tight paragraphs with real metrics.
5. BANNED AI WORDS (Strictly Prohibited):
   {banned_words}, {cliche_openers}, "testament", "pivotal", "transformative", "seamless", "robust", "delve", "tapestry".
6. LENGTH & BREVITY:
   - Keep answers punchy and scannable (typically 60–150 words per answer unless the question requests a long essay).

CANDIDATE PROFILE:
Name: {candidate_name}
Summary: {summary}
Skills: {skills}
Experience:
{experience_snippet}

TARGET JOB & COMPANY CONTEXT:
Company: {company}
Role: {role}
Job Description Excerpt:
{jd_text[:2500]}

OUTPUT JSON FORMAT:
Return strictly a JSON array of objects:
[
  {{
    "question": "Exact question text",
    "answer": "Clean, human-voiced, punchy answer text.",
    "tone_type": "Culture Fit / Behavioral / Technical"
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
