"""
llm_matcher.py — Gemini LLM-based Keyword Extraction Engine.

Replaces rigid static regex patterns with Gemini LLM intelligence:
- Extracts high-value hard technical skills (languages, frameworks, tools, platforms)
- Extracts exact job titles (e.g., Senior Full Stack Engineer, Product Engineer)
- Filters out generic action verbs, soft skills, and filler words.
"""

import json
import os
import re
from google import genai
from google.genai import types


def extract_keywords_with_gemini(jd_text: str) -> list[str]:
    """
    Uses Gemini to analyze the Job Description and extract only
    real, high-value hard technical skills and job titles.
    """
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        print("[LLM Matcher] Warning: GEMINI_API_KEY missing — fallback to regex matcher")
        from keyword_matcher import extract_keywords_from_text
        return list(extract_keywords_from_text(jd_text))

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""You are an expert ATS (Applicant Tracking System) parser. Analyze the following Job Description.

YOUR TASK:
Extract a clean list of ONLY high-value keywords that a tech recruiter would search for.

CRITICAL FILTERS:
1. Extract HARD SKILLS ONLY (e.g., Python, React, AWS, Docker, PostgreSQL, CI/CD, GraphQL, Redis, Microservices).
2. Extract EXACT JOB TITLES (e.g., Senior Product Engineer, Full Stack Developer, Backend Lead).
3. STRICTLY IGNORE generic action verbs, soft skills, and filler words (e.g., responsiveness, knowledge, leading, work, code, ensure, optimize, integrating, current, design, dynamic, using, team player, communication).

JOB DESCRIPTION:
{jd_text[:6000]}

OUTPUT FORMAT:
Return ONLY a raw JSON list of strings. Do not include markdown formatting or backticks.
Example: ["Python", "React", "AWS Lambda", "Senior Product Engineer"]"""

        models = ["gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-3.6-flash", "gemini-2.5-flash"]
        response = None
        for m in models:
            try:
                response = client.models.generate_content(
                    model=m,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        response_mime_type="application/json",
                    ),
                )
                if response and response.text:
                    break
            except Exception as model_err:
                print(f"[LLM Matcher] Note for model {m}: {model_err}")
                continue

        if not response or not response.text:
            raise RuntimeError("All Gemini models exhausted")

        raw_text = response.text or ""
        cleaned_text = raw_text.replace("```json", "").replace("```", "").strip()
        keywords = json.loads(cleaned_text)

        if isinstance(keywords, list):
            clean_list = [str(kw).strip() for kw in keywords if str(kw).strip()]
            print(f"[LLM Matcher] Gemini extracted {len(clean_list)} high-value keywords: {clean_list[:8]}")
            return clean_list

    except Exception as e:
        print(f"[LLM Matcher] Error calling Gemini: {e}. Falling back to regex matcher.")

    # Fallback to local regex matcher if LLM fails
    try:
        from keyword_matcher import extract_keywords_from_text
        return list(extract_keywords_from_text(jd_text))
    except Exception:
        return []


if __name__ == "__main__":
    sample_jd = """
    Senior Full Stack Engineer — Ashby / Infinity Constellation.
    Building web application infrastructure with React, Next.js, TypeScript, Node.js, GraphQL, PostgreSQL, Docker, AWS Lambda.
    Requires strong knowledge of system design, microservices, CI/CD automation tools, and Zapier integrations.
    """
    kws = extract_keywords_with_gemini(sample_jd)
    print("\n--- EXTRACTED LLM KEYWORDS ---")
    print(json.dumps(kws, indent=2))
