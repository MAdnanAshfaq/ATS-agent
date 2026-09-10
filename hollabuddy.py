"""
hollabuddy.py — HollaBuddy: Candidate Career Copilot & Interview Wingman.

Available anytime, instant, and fully contextual of the user's master resume.
Does NOT require running the job analyzer first. Answering job application
questions, behavioral scenarios, technical deep dives, or general enquiries.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from gemini_client import get_gemini_client, is_quota_error, rotate_key
from google import genai
from google.genai import types


HOLLABUDDY_SYSTEM_PROMPT = """You are **HollaBuddy**, an ultra-smart, encouraging, and razor-sharp personal career copilot and interview wingman.

You have direct, permanent access to the candidate's authentic master resume profile below. Your mission is to help the candidate land interviews, answer tough job application questions, craft compelling pitches, and prepare for any career conversation.

### CANDIDATE MASTER TRUTH:
{candidate_truth}

### CURRENT JOB / COMPANY CONTEXT (Optional, if mentioned or active):
{job_context}

### YOUR OPERATIONAL PRINCIPLES:
1. **AUTHENTIC GROUNDING (Rule 0)**:
   - Ground every claim, year of experience, tool, and metric in the candidate's actual master resume above.
   - NEVER hallucinate companies, degrees, or years that do not exist in the candidate's profile.
   - If asked about a skill or technology not in the candidate's background, be candid: explain what adjacent experience they have or how they can bridge the gap honestly.

2. **HUMAN-VOICE TONE (Rules 0–16)**:
   - When drafting answers to job application or interview questions:
     - **Front-load value**: Put the concrete result or accomplishment in the very first sentence.
     - **No throat-clearing AI fluff**: Ban openers like "I am thrilled to apply...", "Throughout my career...", "As a seasoned professional...", "In today's fast-paced world...".
     - **Quantified evidence**: Use real numbers, percentages, dollar amounts, and scale metrics from their background whenever relevant.
     - **STAR Structure**: For behavioral questions ("Tell me about a time..."), use concise Situation/Task -> Action -> Measurable Result format (typically 80-150 words).

3. **CONVERSATIONAL PERSONALITY**:
   - As HollaBuddy in chat, you are warm, friendly, supportive, and motivating (use a conversational, upbeat buddy vibe with occasional emojis like 🚀, 💡, 🎯, ✨).
   - BUT when providing a **written application answer** or **drafted bullet**, deliver it cleanly inside a quote or code block so the candidate can 1-click copy it immediately into an employer's application form without editing out chat filler.

4. **AVAILABILITY**:
   - You are available anytime for any question: application prompts, salary negotiation advice, elevator pitches, resume critique, or explaining complex past projects.
"""


def chat_with_hollabuddy(
    message: str,
    history: list[dict[str, str]] | None = None,
    base_resume: dict[str, Any] | None = None,
    job_context: str | dict | None = None,
    user_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Generate an instant response from HollaBuddy using the candidate's master resume.
    
    Args:
        message: User's chat message or question prompt
        history: List of prior turns [{"role": "user"|"assistant", "content": "..."}]
        base_resume: Candidate's master resume JSON (ground truth)
        job_context: Optional active job posting string or dict
        user_settings: Optional user settings for custom API keys
        
    Returns:
        {"reply": str, "suggested_followups": list[str]}
    """
    try:
        if user_settings and user_settings.get("GEMINI_API_KEY"):
            client = genai.Client(api_key=user_settings["GEMINI_API_KEY"])
        else:
            client = get_gemini_client()
    except Exception as e:
        client = None

    if not client:
        return {
            "reply": "I need a Gemini API key to chat! Please open **Settings** (top right) and paste your free Google Gemini API key.",
            "suggested_followups": ["Open Settings"]
        }

    # Format Candidate Truth
    if base_resume:
        cand_str = json.dumps(base_resume, indent=2, ensure_ascii=False)
    else:
        cand_str = "No master resume uploaded yet. The candidate is setting up their profile."

    # Format Job Context
    if isinstance(job_context, dict):
        job_str = (
            f"Target Company: {job_context.get('company', 'Not specified')}\n"
            f"Target Role: {job_context.get('role', 'Not specified')}\n"
            f"Job URL: {job_context.get('url', 'None')}\n"
            f"Job Snippet: {str(job_context.get('jd_text', ''))[:3000]}"
        )
    elif isinstance(job_context, str) and job_context.strip():
        job_str = job_context.strip()[:3000]
    else:
        job_str = "No active job posting loaded. The user is asking standalone or general questions."

    system_content = HOLLABUDDY_SYSTEM_PROMPT.format(
        candidate_truth=cand_str,
        job_context=job_str
    )

    # Build conversation contents
    chat_contents = []
    
    # We prepend system prompt to the first message or instructions
    if history:
        for turn in history[-8:]:  # Keep last 8 turns for token efficiency
            role = "user" if turn.get("role") == "user" else "model"
            content_text = turn.get("content", "")
            if content_text:
                chat_contents.append(types.Content(role=role, parts=[types.Part(text=content_text)]))

    # Add current user message
    user_text = message.strip()
    chat_contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    # Fallback model array
    models = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
    last_err = None

    for model_name in models:
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_content,
                temperature=0.6,
                top_p=0.92,
                max_output_tokens=2048,
            )
            response = client.models.generate_content(
                model=model_name,
                contents=chat_contents,
                config=config,
            )
            reply_text = response.text.strip() if response.text else "I'm right here! How can I help you with your resume or job search?"
            
            # Generate quick contextual suggestions
            followups = _generate_quick_followups(user_text, reply_text)
            
            return {
                "reply": reply_text,
                "suggested_followups": followups,
                "model_used": model_name
            }
        except Exception as e:
            last_err = e
            print(f"[HollaBuddy] Model {model_name} note: {e}")
            time.sleep(0.5)

    return {
        "reply": f"Sorry! I hit a temporary connection hiccup: {last_err}. Please try asking again in a moment!",
        "suggested_followups": ["Try again", "What can you help me with?"]
    }


def _generate_quick_followups(query: str, reply: str) -> list[str]:
    """Provide intelligent 1-click follow-up prompt chips based on query."""
    q_lower = query.lower()
    if any(w in q_lower for w in ("outage", "problem", "conflict", "tell me about", "describe a time")):
        return [
            "Make it shorter (under 100 words)",
            "Emphasize the measurable metrics",
            "What follow-up question will the interviewer ask?"
        ]
    elif any(w in q_lower for w in ("strength", "fit", "skills", "match")):
        return [
            "Give me a 30-second elevator pitch",
            "What might be my biggest interview risk?",
            "Draft an application answer for why I want this role"
        ]
    elif any(w in q_lower for w in ("pitch", "introduce", "about yourself")):
        return [
            "Make it more punchy",
            "Tailor it for a hiring manager vs recruiter",
            "What questions should I ask the interviewer?"
        ]
    else:
        return [
            "Help me answer an application question",
            "What are my strongest skills?",
            "Draft a 30s elevator pitch"
        ]
