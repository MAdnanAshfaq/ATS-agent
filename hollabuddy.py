"""
hollabuddy.py — HollaBuddy: Candidate Career Copilot & Interview Wingman.

Available anytime, instant, and fully contextual of the user's master resume.
Does NOT require running the job analyzer first. Answering job application
questions, behavioral scenarios, technical deep dives, or general enquiries.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Optional

from gemini_client import get_gemini_client, execute_with_failover, is_quota_error, rotate_key, get_all_gemini_keys
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

3. **CLEAN, READABLE FORMATTING MANDATE (CRITICAL)**:
   - When providing a **written application answer** or **drafted bullet**, deliver it cleanly using Markdown blockquotes with `>` syntax (e.g. `> At [Company], I built...`) or standard paragraphs.
   - **NEVER put written prose, cover letter paragraphs, or application answers inside monospace code blocks (` ``` `)**. Code blocks are ONLY for actual programming code (SQL, Python, Bash).
   - **NEVER format text into side-by-side text columns, fixed-width ASCII tables, or narrow vertical word splits.** Never break words or sentences into narrow columns of text.
   - If comparing items, use standard GitHub Markdown tables (`| Col 1 | Col 2 |`).
   - Always write answers in natural, flowing English paragraphs with standard line lengths so the candidate can immediately 1-click copy them into employer application forms.

4. **CONVERSATIONAL PERSONALITY**:
   - As HollaBuddy in chat, you are warm, friendly, supportive, and motivating (use a conversational, upbeat buddy vibe with occasional emojis like 🚀, 💡, 🎯, ✨).
   - Keep conversational remarks brief so the actual drafted answers are immediately prominent and readable.

5. **AVAILABILITY**:
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

    Uses the full multi-key failover pool from gemini_client.py:
      - GEMINI_API_KEY (Primary)
      - GEMINI_API_KEY_2 (Backup — automatically rotated to on quota/429 errors)

    Args:
        message: User's chat message or question prompt
        history: List of prior turns [{"role": "user"|"assistant", "content": "..."}]
        base_resume: Candidate's master resume JSON (ground truth)
        job_context: Optional active job posting string or dict
        user_settings: Optional user settings for custom API keys

    Returns:
        {"reply": str, "suggested_followups": list[str]}
        On quota exhaustion: adds "error_code": "quota_exhausted" so the UI can show a banner.
    """
    # --- Inject user API keys into environment so gemini_client pool sees them ---
    # This ensures GEMINI_API_KEY_2 is always available as a live failover backup.
    if user_settings:
        for env_key in ("GEMINI_API_KEY", "GEMINI_API_KEY_2"):
            val = (user_settings.get(env_key) or "").strip()
            if val:
                os.environ[env_key] = val

    # Verify at least one key is configured
    keys = get_all_gemini_keys()
    if not keys:
        return {
            "reply": "I need a Gemini API key to chat! Please open **Settings** (⚙️ top right) and paste your free Google Gemini API key.",
            "suggested_followups": ["Open Settings"],
            "error_code": "no_api_key",
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
    if history:
        for turn in history[-8:]:  # Keep last 8 turns for token efficiency
            role = "user" if turn.get("role") == "user" else "model"
            content_text = turn.get("content", "")
            if content_text:
                chat_contents.append(types.Content(role=role, parts=[types.Part(text=content_text)]))

    user_text = message.strip()
    chat_contents.append(types.Content(role="user", parts=[types.Part(text=user_text)]))

    # Ordered model fallback list
    models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]
    last_err = None
    all_quota_exhausted = False

    for model_name in models:
        def _call(client, _model=model_name, _contents=chat_contents, _sys=system_content):
            config = types.GenerateContentConfig(
                system_instruction=_sys,
                temperature=0.6,
                top_p=0.92,
                max_output_tokens=8192,  # Raised from 2048 — detailed resume comparisons need room
                automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            )
            return client.models.generate_content(
                model=_model,
                contents=_contents,
                config=config,
            )

        try:
            response = execute_with_failover(_call)
            reply_text = (
                response.text.strip()
                if response.text
                else "I'm right here! How can I help you with your resume or job search?"
            )

            # Detect if Gemini hit the token ceiling mid-answer
            was_truncated = False
            try:
                finish_reason = str(response.candidates[0].finish_reason) if response.candidates else ""
                if "MAX_TOKENS" in finish_reason.upper():
                    was_truncated = True
            except Exception:
                pass

            if was_truncated:
                reply_text += (
                    "\n\n---\n"
                    "✂️ *My answer was cut off here because it got very long. "
                    "Reply **\"Continue\"** and I'll pick up right where I left off!*"
                )

            followups = _generate_quick_followups(user_text, reply_text)
            if was_truncated and "Continue" not in followups:
                followups = ["Continue"] + followups[:2]
            return {
                "reply": reply_text,
                "suggested_followups": followups,
                "model_used": model_name,
                "keys_in_pool": len(keys),
            }
        except Exception as e:
            last_err = e
            print(f"[HollaBuddy] Model {model_name} failed after all key rotations: {e}")
            if is_quota_error(e):
                all_quota_exhausted = True
            time.sleep(0.5)

    # --- Compose a clear, actionable error response ---
    if all_quota_exhausted:
        key_count = len(keys)
        if key_count > 1:
            quota_msg = (
                f"⚠️ **Both your Gemini API keys have hit their quota/rate limit** and I couldn't get a reply right now.\n\n"
                f"**What you can do:**\n"
                f"- Wait a minute and try again (free-tier limits reset quickly).\n"
                f"- Add a third API key in **Settings → API Keys** (`GEMINI_API_KEY_3`).\n"
                f"- Upgrade your Google AI Studio plan for higher limits."
            )
        else:
            quota_msg = (
                f"⚠️ **Your Gemini API key has used up its quota/credits** and I can't respond right now.\n\n"
                f"**What you can do:**\n"
                f"- Wait a minute and try again (free-tier limits reset hourly).\n"
                f"- Add a **second API key** in **Settings → API Keys** (`GEMINI_API_KEY_2`) so I can automatically switch to it.\n"
                f"- Get a free key at [aistudio.google.com](https://aistudio.google.com/apikey)."
            )
        return {
            "reply": quota_msg,
            "suggested_followups": ["Open Settings", "Try again in a moment"],
            "error_code": "quota_exhausted",
            "keys_in_pool": key_count,
        }

    return {
        "reply": f"Sorry! I hit a temporary connection issue. Please try again in a moment! 🔄\n\n*(Technical detail: {last_err})*",
        "suggested_followups": ["Try again", "What can you help me with?"],
        "error_code": "transient_error",
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
