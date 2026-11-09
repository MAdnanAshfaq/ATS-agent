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


HOLLABUDDY_SYSTEM_PROMPT = """You are **HollaBuddy**, an ultra-smart, encouraging, and razor-sharp personal career copilot, interview wingman, and **AUTONOMOUS PIPELINE CONTROLLER**.

You have direct access to the candidate's authentic master resume profile, their newly drafted/tailored resume (when customized for a specific target role), their full application history across all past jobs, and the live ATS pipeline state. Your mission is to help the candidate land interviews, answer tough job application questions, craft compelling pitches, review drafted bullets, explain changes, cross-reference past applications, and **actively control the ATS tailoring pipeline**.

### CANDIDATE MASTER TRUTH (Ground Truth Profile):
{candidate_truth}

### NEW DRAFTED / TAILORED RESUME (Job-Specific Draft):
{drafted_resume}

### CURRENT JOB / COMPANY CONTEXT (Optional, if mentioned or active):
{job_context}

### CANDIDATE APPLICATION HISTORY (Past Applications, Tailored Resumes & Cover Letters):
{application_history}

### LIVE PIPELINE STATUS & KEYWORD MATCH CONTEXT:
{pipeline_status}

### YOUR OPERATIONAL PRINCIPLES:
1. **AUTHENTIC GROUNDING & DUAL-RESUME AWARENESS (Rule 0)**:
   - Ground every claim, year of experience, tool, and metric in the candidate's actual master resume above.
   - You have full visibility into BOTH the **Master Resume** (base ground truth) and the **New Drafted / Tailored Resume** (generated specifically for the active job posting).
   - When asked what changed, what was tailored, or how their bullets were adapted for the role: compare the drafted resume against the master resume, pointing out specific keyword inclusions, metric front-loading, and role-tailored bullet points.
   - When reviewing or refining resume bullets, work directly from the drafted resume bullets, enhancing them while keeping them 100% authentic to the candidate's real master background.
   - NEVER hallucinate companies, degrees, or years that do not exist in the candidate's profile.
   - If asked about a skill or technology not in the candidate's background, be candid: explain what adjacent experience they have or how they can bridge the gap honestly.

2. **DEEP APPLICATION HISTORY REFERENCING & MEMORY FOCUS**:
   - You have full, searchable access to the candidate's past applications from their application history above (including company names, roles, scores, tailored bullets, and past cover letters).
   - When the candidate asks you to focus on, load into memory, switch to, or chat about a specific past job (e.g. "focus on the Beehiiv job in history to chat further", "let's look at Snowflake", "bring in my Amazon application", "load Beehiiv in memory to work on"):
     * Identify the matching application from their history.
     * Output `[[ACTION:focus_job|company=CompanyName]]` so the system loads that job's resume, bullets, and context into HollaBuddy's active memory!
     * **CRITICAL**: DO NOT output `[[ACTION:open_editor]]` when the candidate just wants to focus, load in memory, or chat about a job! Only output `open_editor` if they explicitly ask to open the visual studio editor modal.
     * Analyze and cite specific accomplishments, scale metrics, or phrasing from that past application in your chat response.
     * If requested, adapt and integrate those past bullets/metrics into the current resume (`[[ACTION:refine_resume|instruction=...]]`) or cover letter (`[[ACTION:generate_cover_letter|instruction=...]]`).

3. **AUTONOMOUS PIPELINE CONTROLLER MANDATE (TRUE AUTONOMY & OPINION EXECUTION)**:
   - You are the active, autonomous controller for the whole ATS pipeline! When the candidate gives you their opinion, preferences, critique, or directions on how they want the resume crafted or modified:
     * DO NOT just say "Sure, here's what you can do" or list advice in text.
     * TAKE IMMEDIATE AUTONOMOUS ACTION by executing the pipeline, refiner, or context loader!
     * If they ask to focus on or work on a job from history in memory: trigger `[[ACTION:focus_job|company=CompanyName]]`.
     * If they ask to tailor, rebuild, or adjust keywords: trigger `[[ACTION:tailor_resume|keywords=kw1,kw2]]`.
     * If they give instructions or opinions on how bullets/summary should be written or improved (e.g. "focus on distributed systems", "highlight Kafka and Spark", "cut out generic buzzwords"): trigger `[[ACTION:refine_resume|instruction=...]]` with their exact instructions synthesized into concrete, high-impact edits.
     * **OPENING THE VISUAL EDITOR (Strict Rule)**:
       - ONLY trigger `[[ACTION:open_editor|company=CompanyName]]` or `[[ACTION:open_editor]]` when the user EXPLICITLY and CLEARLY asks to "open the visual editor", "launch the editor", "open editor", or "edit in visual editor".
       - NEVER trigger `open_editor` when the user merely wants to focus, chat, discuss, or work on a job inside HollaBuddy!
     * Action Tags Reference:
       * `[[ACTION:focus_job|company=CompanyName]]`: Loads a specific past application from history into HollaBuddy's active memory context so you can chat, review, and refine without opening external modals.
       * `[[ACTION:open_editor]]` or `[[ACTION:open_editor|company=CompanyName]]`: Opens the visual PDF studio editor (ONLY when explicitly requested).
       * `[[ACTION:refine_resume|instruction=...]]` or `[[ACTION:refine_resume|instruction=...|company=CompanyName]]`: Surgically modifies bullets/sections in the tailored resume and rebuilds documents in ~2s. Add `|open_editor=true` ONLY if the candidate explicitly wants the editor opened afterwards.
       * `[[ACTION:tailor_resume]]` or `[[ACTION:tailor_resume|keywords=kw1,kw2]]`: Starts the resume tailoring pipeline to embed missing keywords.
       * `[[ACTION:generate_cover_letter]]` or `[[ACTION:generate_cover_letter|instruction=...]]`: Generates a job-tailored cover letter with prioritized custom instructions.
       * `[[ACTION:open_preview]]`: Opens the live in-browser document preview modal.
       * `[[ACTION:answer_questions|questions=...]]`: Runs the Q&A Copilot to draft authentic STAR answers.
       * `[[ACTION:audit_ats|platform=...]]`: Runs a deep ATS compliance audit (Workday/Greenhouse/Taleo/Safe Mode).
       * `[[ACTION:download_resume|format=pdf]]` or `[[ACTION:download_resume|format=docx]]`: Triggers instant download of the tailored resume.
   - When the user asks you to execute an action or shares how they want the resume made, explain what you are doing in your warm, friendly voice and include the exact `[[ACTION:...]]` tag at the bottom of your message.

4. **DANI'S HUMAN-VOICE & ANTI-AI MANDATE (Rules 0–16)**:
   - **STRICTLY BANNED AI BUZZWORDS**: NEVER use these statistical-average AI filler words:
     `delve`, `tapestry`, `robust`, `seamless`, `seamlessly`, `multifaceted`, `holistic`, `synergy`, `pivotal`, `testament`, `transformative`, `groundbreaking`, `cutting-edge`, `game-changer`, `beacon`, `cornerstone`, `linchpin`, `vibrant`, `dynamic`, `paramount`, `relentless`, `unwavering`, `moreover`, `furthermore`, `additionally`, `in conclusion`, `fast-paced environment`, `deep dive`.
   - **STRICTLY BANNED CLICHÉ OPENERS**: NEVER open sentences or bullets with overused AI verbs:
     `spearheaded`, `leveraged`, `utilized`, `facilitated`, `championed`, `fostered`, `orchestrated`, `pioneered`, `empowered`, `elevated`, `unlocked`.
     -> Use crisp, authentic human verbs instead: `built`, `led`, `shipped`, `designed`, `wrote`, `cut`, `grew`, `automated`, `reduced`, `managed`.
   - **BANNED FORMULAIC OPENERS**: NEVER start answers with fluff:
     `results-driven`, `seasoned professional`, `proven track record`, `passionate and dedicated`, `I am thrilled to apply...`, `Throughout my career...`, `As a...`.
   - **HIGH BURSTINESS & NATURAL RHYTHM**: Vary sentence lengths intentionally like a real human. Alternate between punchy short sentences (4–8 words) and longer compound sentences (18–25 words). Avoid robotic, uniform paragraph blocks.
   - **FRONT-LOAD VALUE**: Put the concrete result, metric, or accomplishment in the very first sentence.
   - **QUANTIFIED EVIDENCE**: Use real numbers, percentages, dollar amounts, and scale metrics from their background.
   - **STAR STRUCTURE**: For behavioral questions ("Tell me about a time..."), use concise Situation/Task -> Action -> Measurable Result format (typically 80-150 words).

4. **CLEAN, READABLE FORMATTING MANDATE (CRITICAL)**:
   - When providing a **written application answer** or **drafted bullet**, deliver it cleanly using Markdown blockquotes with `>` syntax (e.g. `> At [Company], I built...`) or standard paragraphs.
   - **NEVER put written prose, cover letter paragraphs, or application answers inside monospace code blocks (` ``` `)**. Code blocks are ONLY for actual programming code (SQL, Python, Bash).
   - **NEVER format text into side-by-side text columns, fixed-width ASCII tables, or narrow vertical word splits.** Never break words or sentences into narrow columns of text.
   - If comparing items, use standard GitHub Markdown tables (`| Col 1 | Col 2 |`).
   - Always write answers in natural, flowing English paragraphs with standard line lengths so the candidate can immediately 1-click copy them into employer application forms.

5. **CONVERSATIONAL PERSONALITY**:
   - As HollaBuddy in chat, you are warm, friendly, supportive, and motivating (use a conversational, upbeat buddy vibe with occasional emojis like 🚀, 💡, 🎯, ✨).
   - Keep conversational remarks brief so the actual drafted answers are immediately prominent and readable.

6. **AVAILABILITY**:
   - You are available anytime for any question: application prompts, salary negotiation advice, elevator pitches, resume critique, or explaining complex past projects.
"""


def chat_with_hollabuddy(
    message: str,
    history: list[dict[str, str]] | None = None,
    base_resume: dict[str, Any] | None = None,
    drafted_resume: dict[str, Any] | None = None,
    job_context: str | dict | None = None,
    pipeline_state: dict[str, Any] | None = None,
    user_settings: dict[str, Any] | None = None,
    application_history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Generate an instant response from HollaBuddy using the candidate's master resume,
    optional new drafted/tailored resume, application history, and live pipeline status.
    Acts as the AUTONOMOUS PIPELINE CONTROLLER after URL job analysis.

    Uses the full multi-key failover pool from gemini_client.py:
      - GEMINI_API_KEY (Primary)
      - GEMINI_API_KEY_2 (Backup — automatically rotated to on quota/429 errors)

    Args:
        message: User's chat message or question prompt
        history: List of prior turns [{"role": "user"|"assistant", "content": "..."}]
        base_resume: Candidate's master resume JSON (ground truth)
        drafted_resume: Candidate's newly tailored/drafted resume JSON (for active job)
        job_context: Optional active job posting string or dict
        pipeline_state: Optional live pipeline status and keyword match details
        user_settings: Optional user settings for custom API keys
        application_history: List of past job applications, scores, bullets, and cover letters

    Returns:
        {"reply": str, "action": dict|None, "suggested_followups": list[str]}
        On quota exhaustion: adds "error_code": "quota_exhausted" so the UI can show a banner.
    """
    # --- Inject all user API keys into thread-local pool so gemini_client sees them ---
    keys_arr = []
    if user_settings:
        raw_arr = user_settings.get("GEMINI_API_KEYS") or []
        for itm in raw_arr:
            k = (itm.get("key") or "").strip() if isinstance(itm, dict) else str(itm).strip()
            if k and k not in keys_arr:
                keys_arr.append(k)
        for env_key in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
            val = (user_settings.get(env_key) or "").strip()
            if val and val not in keys_arr:
                keys_arr.append(val)
    if keys_arr:
        from gemini_client import set_thread_gemini_keys
        set_thread_gemini_keys(keys_arr)

    # Verify at least one key is configured
    keys = get_all_gemini_keys()
    if not keys:
        return {
            "reply": "I need a Gemini API key to chat! Please open **Settings** (⚙️ top right) and paste your free Google Gemini API key.",
            "suggested_followups": ["Open Settings"],
            "error_code": "no_api_key",
        }

    # Format Candidate Truth (Master Resume)
    if base_resume:
        cand_str = json.dumps(base_resume, indent=2, ensure_ascii=False)
    else:
        cand_str = "No master resume uploaded yet. The candidate is setting up their profile."

    # Format Drafted / Tailored Resume
    if drafted_resume:
        draft_str = json.dumps(drafted_resume, indent=2, ensure_ascii=False)
    else:
        draft_str = "No job-specific drafted resume created yet. The candidate is currently referencing their master resume."

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

    # Format Application History
    app_hist_str = ""
    if application_history:
        lines = []
        for i, a in enumerate(application_history[:10], 1):
            co = a.get("company", "Unknown")
            ro = a.get("role", "Unknown")
            dt = a.get("timestamp") or a.get("date") or ""
            sc = a.get("score_after") or a.get("score") or ""
            kw = ", ".join(a.get("matched_keywords", [])[:8])
            cl_snip = a.get("cover_letter_snippet") or ""
            exp_high = a.get("experience_highlights") or []
            exp_str = ""
            if exp_high:
                exp_items = [f"    - {e.get('title')} at {e.get('company')}: {'; '.join(e.get('bullets', [])[:2])}" for e in exp_high if isinstance(e, dict)]
                exp_str = "\n" + "\n".join(exp_items)
            cl_part = f"\n   * Cover Letter Excerpt: \"{cl_snip[:160]}...\"" if cl_snip else ""
            lines.append(f"{i}. **{co}** — {ro} (Date: {dt}, Score: {sc}%)\n   * Matched Skills: {kw}{exp_str}{cl_part}")
        app_hist_str = "\n\n".join(lines)
    else:
        app_hist_str = "No past application history on file yet. Candidate is currently working on their first application or master profile."

    # Format Live Pipeline Status
    if pipeline_state and isinstance(pipeline_state, dict):
        p_lines = []
        p_lines.append(f"- Active Company: {pipeline_state.get('company') or 'Not specified'}")
        p_lines.append(f"- Active Role: {pipeline_state.get('role') or 'Not specified'}")
        p_lines.append(f"- ATS Target Platform: {pipeline_state.get('ats_platform') or 'Safe Mode'}")
        if pipeline_state.get('score_before') is not None:
            p_lines.append(f"- Initial ATS Match Score: {pipeline_state.get('score_before')}%")
        if pipeline_state.get('score_after') is not None:
            p_lines.append(f"- Tailored ATS Match Score: {pipeline_state.get('score_after')}%")
        missing_kw = pipeline_state.get('missing_keywords') or []
        if missing_kw:
            p_lines.append(f"- Missing Keywords to inject ({len(missing_kw)}): {', '.join(missing_kw[:20])}")
        matched_kw = pipeline_state.get('matched_keywords') or []
        if matched_kw:
            p_lines.append(f"- Matched Keywords ({len(matched_kw)}): {', '.join(matched_kw[:20])}")
        p_lines.append(f"- Resume Tailored/Generated: {'Yes' if pipeline_state.get('has_tailored_resume') else 'No'}")
        p_lines.append(f"- Cover Letter Generated: {'Yes' if pipeline_state.get('has_cover_letter') else 'No'}")
        pipeline_status_str = "\n".join(p_lines)
    else:
        pipeline_status_str = "No active pipeline state provided. Candidate may be on master profile or fresh session."

    system_content = HOLLABUDDY_SYSTEM_PROMPT.format(
        candidate_truth=cand_str,
        drafted_resume=draft_str,
        job_context=job_str,
        application_history=app_hist_str,
        pipeline_status=pipeline_status_str,
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

    from gemini_client import (
        get_candidate_models, extract_clean_text, get_standard_genai_config,
        record_model_failure, record_model_success, clear_thread_gemini_keys
    )
    last_err = None
    all_quota_exhausted = False
    used_model = None

    def _call(client):
        nonlocal used_model, last_err
        call_err = None
        for m in get_candidate_models():
            try:
                cfg = get_standard_genai_config(model_name=m, max_output_tokens=4096, temperature=0.55, top_p=0.92)
                cfg.system_instruction = system_content
                cfg.automatic_function_calling = types.AutomaticFunctionCallingConfig(disable=True)
                resp = client.models.generate_content(
                    model=m,
                    contents=chat_contents,
                    config=cfg,
                )
                txt = extract_clean_text(resp)
                if txt:
                    record_model_success(m)
                    used_model = m
                    return resp
            except Exception as me:
                record_model_failure(m, me)
                call_err = me
                continue
        if call_err:
            raise call_err
        raise RuntimeError("All candidate models failed")

    try:
        response = execute_with_failover(_call)
        clean_reply = extract_clean_text(response)
        reply_text = (
            clean_reply
            if clean_reply
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

        # Extract and parse action controller tag if present
        action_data = None
        action_match = re.search(r'\[\[ACTION:([a-zA-Z0-9_]+)(?:\|([^\]]+))?\]\]', reply_text)
        if action_match:
            action_type = action_match.group(1).strip()
            raw_params = (action_match.group(2) or "").strip()
            params = {}
            if raw_params:
                if action_type in ("refine_resume", "generate_cover_letter") and raw_params.startswith("instruction="):
                    params["instruction"] = raw_params.split("instruction=", 1)[1].strip()
                else:
                    for chunk in raw_params.split("|"):
                        if "=" in chunk:
                            k, v = chunk.split("=", 1)
                            params[k.strip()] = v.strip()
                        else:
                            params[chunk.strip()] = True
            action_data = {
                "type": action_type,
                "params": params
            }
            # Strip tag from the reply shown to user
            reply_text = re.sub(r'\[\[ACTION:[^\]]+\]\]', '', reply_text).strip()

        followups = _generate_quick_followups(user_text, reply_text, pipeline_state=pipeline_state)
        if was_truncated and "Continue" not in followups:
            followups = ["Continue"] + followups[:2]
        return {
            "reply": reply_text,
            "action": action_data,
            "suggested_followups": followups,
            "model_used": used_model or "gemini",
            "keys_in_pool": len(keys),
        }
    except Exception as e:
        last_err = e
        print(f"[HollaBuddy] Chat failed after all key rotations: {e}")
        if is_quota_error(e):
            all_quota_exhausted = True
    finally:
        clear_thread_gemini_keys()


    # --- Compose a clear, actionable error response ---
    if all_quota_exhausted:
        key_count = len(keys)
        if key_count > 1:
            quota_msg = (
                f"⚠️ **All {key_count} of your Gemini API keys have hit Google's quota/rate limit** and cannot respond right now.\n\n"
                f"**What you can do:**\n"
                f"- Add another API key in **Settings → API Keys** so the pool can switch to it.\n"
                f"- Wait for Google's quota window to reset (free-tier requests reset hourly/daily).\n"
                f"- Upgrade your Google AI Studio plan for higher limits."
            )
        else:
            quota_msg = (
                f"⚠️ **Your Gemini API key has hit Google's quota/rate limit**.\n\n"
                f"**What you can do:**\n"
                f"- Add more API keys in **Settings → API Keys** so the system can automatically switch between them.\n"
                f"- Wait a moment for Google's quota window to reset."
            )
        return {
            "reply": quota_msg,
            "action": None,
            "suggested_followups": ["Open Settings", "Try again in a moment"],
            "error_code": "quota_exhausted",
            "keys_in_pool": key_count,
        }

    return {
        "reply": f"Sorry! I hit a temporary connection issue. Please try again in a moment! 🔄\n\n*(Technical detail: {last_err})*",
        "action": None,
        "suggested_followups": ["Try again", "What can you help me with?"],
        "error_code": "transient_error",
    }


def _generate_quick_followups(query: str, reply: str, pipeline_state: dict[str, Any] | None = None) -> list[str]:
    """Provide intelligent 1-click follow-up prompt chips based on query and pipeline state."""
    q_lower = query.lower()

    # Prioritize pipeline controller followups when user is in active job context
    has_analyzed = False
    has_tailored = False
    if pipeline_state and isinstance(pipeline_state, dict):
        has_analyzed = bool(pipeline_state.get("company") or pipeline_state.get("role"))
        has_tailored = bool(pipeline_state.get("has_tailored_resume"))

    if any(w in q_lower for w in ("tailor", "generate", "pipeline", "run")):
        return [
            "Open the Visual Editor",
            "Generate a cover letter for this role",
            "What keywords were added?",
            "Audit ATS compatibility"
        ]
    elif any(w in q_lower for w in ("draft", "new resume", "change", "diff", "bullet", "refine")):
        return [
            "Open the Visual Editor",
            "Refine top bullet for measurable impact",
            "Generate a tailored cover letter",
            "Download tailored resume (PDF)"
        ]
    elif any(w in q_lower for w in ("editor", "edit")):
        return [
            "Which missing keywords should I add in the editor?",
            "Make my summary punchier",
            "Audit ATS compatibility"
        ]
    elif any(w in q_lower for w in ("cover letter", "cover_letter")):
        return [
            "Tailor cover letter for a hiring manager",
            "Download tailored resume (PDF)",
            "Open the Visual Editor"
        ]
    elif any(w in q_lower for w in ("outage", "problem", "conflict", "tell me about", "describe a time")):
        return [
            "Make it shorter (under 100 words)",
            "Emphasize the measurable metrics",
            "What follow-up question will the interviewer ask?"
        ]
    elif any(w in q_lower for w in ("strength", "fit", "skills", "match")):
        return [
            "Tailor my resume for this job",
            "Give me a 30-second elevator pitch",
            "What might be my biggest interview risk?"
        ]
    else:
        if has_analyzed and not has_tailored:
            return [
                "Tailor my resume for this role",
                "What are my missing keywords?",
                "Open the Visual Editor",
                "Draft a 30s elevator pitch"
            ]
        elif has_tailored:
            return [
                "Open the Visual Editor",
                "Generate a tailored cover letter",
                "What changed in my drafted resume?",
                "Download tailored resume (PDF)"
            ]
        return [
            "Help me answer an application question",
            "Open the Visual Editor",
            "Draft a 30s elevator pitch"
        ]
