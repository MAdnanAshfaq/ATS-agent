"""
db.py — NeonDB PostgreSQL database layer for ATS Agent.

Replaces all local JSON file storage with PostgreSQL (NeonDB).
- Users registry  (was: data/users.json)
- User settings   (was: data/users/{username}/settings.json)
- Resume JSON     (was: data/users/{username}/base_resume.json)
- Resume DOCX     (was: data/users/{username}/master_resume_original.docx)
- Job history     (was: data/users/{username}/output/logs/run_*.json)

Set DATABASE_URL env var to enable. Falls back to local file mode if not set.
"""

import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Connection pool ────────────────────────────────────────────────────────────

_pool = None


def get_pool():
    """Return a psycopg2 connection pool (created once per process)."""
    global _pool
    if _pool is not None:
        return _pool

    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        return None  # No DB configured — caller falls back to file mode

    try:
        from psycopg2 import pool as pg_pool
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=db_url,
        )
        logger.info("[DB] Connected to NeonDB PostgreSQL")
    except Exception as e:
        logger.error(f"[DB] Failed to connect to NeonDB: {e}")
        _pool = None

    return _pool


def get_conn():
    """Get a connection from the pool."""
    p = get_pool()
    if p is None:
        return None
    return p.getconn()


def release_conn(conn):
    """Return connection to pool."""
    p = get_pool()
    if p and conn:
        try:
            p.putconn(conn)
        except Exception:
            pass


def is_db_available() -> bool:
    """True if NeonDB connection is configured and reachable."""
    return get_pool() is not None


# ── Schema Init ────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    username        VARCHAR(50) PRIMARY KEY,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    display_name    VARCHAR(100),
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_settings (
    username            VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
    gemini_api_key      TEXT DEFAULT '',
    gemini_api_key_2    TEXT DEFAULT '',
    simplify_email      TEXT DEFAULT '',
    simplify_password   TEXT DEFAULT '',
    hf_api_key          TEXT DEFAULT '',
    colab_url           TEXT DEFAULT '',
    updated_at          TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS user_resumes (
    username        VARCHAR(50) PRIMARY KEY REFERENCES users(username) ON DELETE CASCADE,
    resume_json     TEXT NOT NULL DEFAULT '{}',
    docx_bytes      BYTEA,
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_history (
    id              SERIAL PRIMARY KEY,
    username        VARCHAR(50) REFERENCES users(username) ON DELETE CASCADE,
    run_id          VARCHAR(120) UNIQUE,
    job_title       TEXT,
    company         TEXT,
    url             TEXT,
    status          VARCHAR(50) DEFAULT 'complete',
    score_before    FLOAT,
    score_after     FLOAT,
    score_delta     FLOAT,
    run_data        TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_job_history_username ON job_history(username);
CREATE INDEX IF NOT EXISTS idx_job_history_created ON job_history(created_at DESC);
"""


def init_schema():
    """Create all tables if they don't exist. Call once on startup."""
    conn = get_conn()
    if conn is None:
        logger.warning("[DB] No DB connection — skipping schema init (file mode)")
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
        logger.info("[DB] Schema initialized (tables verified)")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] Schema init error: {e}")
        return False
    finally:
        release_conn(conn)


# ── Users ──────────────────────────────────────────────────────────────────────

def db_create_user(username: str, email: str, password_hash: str, display_name: str) -> bool:
    """Insert a new user row. Returns True on success."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, display_name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (username, email.lower(), password_hash, display_name, datetime.utcnow())
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] create_user error: {e}")
        return False
    finally:
        release_conn(conn)


def db_get_user_by_username(username: str) -> Optional[dict]:
    """Return user row dict or None."""
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, email, password_hash, display_name, created_at FROM users WHERE username = %s",
                (username,)
            )
            row = cur.fetchone()
            if row:
                return {
                    "username": row[0], "email": row[1], "password_hash": row[2],
                    "display_name": row[3], "created_at": row[4].isoformat() if row[4] else ""
                }
    except Exception as e:
        logger.error(f"[DB] get_user_by_username error: {e}")
    finally:
        release_conn(conn)
    return None


def db_get_user_by_email(email: str) -> Optional[dict]:
    """Return user row dict or None."""
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT username, email, password_hash, display_name, created_at FROM users WHERE LOWER(email) = %s",
                (email.strip().lower(),)
            )
            row = cur.fetchone()
            if row:
                return {
                    "username": row[0], "email": row[1], "password_hash": row[2],
                    "display_name": row[3], "created_at": row[4].isoformat() if row[4] else ""
                }
    except Exception as e:
        logger.error(f"[DB] get_user_by_email error: {e}")
    finally:
        release_conn(conn)
    return None


def db_update_password(username: str, new_hash: str) -> bool:
    """Update user's password hash."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE username = %s", (new_hash, username))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] update_password error: {e}")
        return False
    finally:
        release_conn(conn)


def db_count_users() -> int:
    """Return total number of registered users."""
    conn = get_conn()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM users")
            row = cur.fetchone()
            return row[0] if row else 0
    except Exception as e:
        logger.error(f"[DB] count_users error: {e}")
        return 0
    finally:
        release_conn(conn)


def db_get_all_users() -> list:
    """Return list of all user summary dicts."""
    conn = get_conn()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT username, email, display_name, created_at FROM users ORDER BY created_at")
            rows = cur.fetchall()
            return [
                {"username": r[0], "email": r[1], "display_name": r[2],
                 "created_at": r[3].isoformat() if r[3] else ""}
                for r in rows
            ]
    except Exception as e:
        logger.error(f"[DB] get_all_users error: {e}")
        return []
    finally:
        release_conn(conn)


# ── User Settings ──────────────────────────────────────────────────────────────

def db_get_settings(username: str) -> dict:
    """Return user settings dict (API keys etc)."""
    defaults = {
        "GEMINI_API_KEY": "", "GEMINI_API_KEY_2": "",
        "SIMPLIFY_EMAIL": "", "SIMPLIFY_PASSWORD": "",
        "HF_API_KEY": "", "COLAB_DETECTOR_URL": "",
    }
    conn = get_conn()
    if not conn:
        return defaults
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT gemini_api_key, gemini_api_key_2, simplify_email, simplify_password, hf_api_key, colab_url FROM user_settings WHERE username = %s",
                (username,)
            )
            row = cur.fetchone()
            if row:
                defaults["GEMINI_API_KEY"] = row[0] or ""
                defaults["GEMINI_API_KEY_2"] = row[1] or ""
                defaults["SIMPLIFY_EMAIL"] = row[2] or ""
                defaults["SIMPLIFY_PASSWORD"] = row[3] or ""
                defaults["HF_API_KEY"] = row[4] or ""
                defaults["COLAB_DETECTOR_URL"] = row[5] or ""
    except Exception as e:
        logger.error(f"[DB] get_settings error: {e}")
    finally:
        release_conn(conn)
    return defaults


def db_save_settings(username: str, settings: dict) -> bool:
    """Upsert user settings."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_settings (username, gemini_api_key, gemini_api_key_2, simplify_email, simplify_password, hf_api_key, colab_url, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    gemini_api_key   = EXCLUDED.gemini_api_key,
                    gemini_api_key_2 = EXCLUDED.gemini_api_key_2,
                    simplify_email   = EXCLUDED.simplify_email,
                    simplify_password= EXCLUDED.simplify_password,
                    hf_api_key       = EXCLUDED.hf_api_key,
                    colab_url        = EXCLUDED.colab_url,
                    updated_at       = EXCLUDED.updated_at
                """,
                (
                    username,
                    settings.get("GEMINI_API_KEY", ""),
                    settings.get("GEMINI_API_KEY_2", ""),
                    settings.get("SIMPLIFY_EMAIL", ""),
                    settings.get("SIMPLIFY_PASSWORD", ""),
                    settings.get("HF_API_KEY", ""),
                    settings.get("COLAB_DETECTOR_URL", ""),
                    datetime.utcnow(),
                )
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] save_settings error: {e}")
        return False
    finally:
        release_conn(conn)


# ── Resumes ────────────────────────────────────────────────────────────────────

def db_get_resume(username: str) -> Optional[dict]:
    """Return parsed resume dict or None."""
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT resume_json FROM user_resumes WHERE username = %s", (username,))
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        logger.error(f"[DB] get_resume error: {e}")
    finally:
        release_conn(conn)
    return None


def db_save_resume(username: str, resume_dict: dict) -> bool:
    """Upsert resume JSON for user."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_resumes (username, resume_json, updated_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    resume_json = EXCLUDED.resume_json,
                    updated_at  = EXCLUDED.updated_at
                """,
                (username, json.dumps(resume_dict, ensure_ascii=False), datetime.utcnow())
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] save_resume error: {e}")
        return False
    finally:
        release_conn(conn)


def db_save_resume_docx(username: str, docx_bytes: bytes) -> bool:
    """Store raw DOCX bytes in DB (upsert)."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_resumes (username, resume_json, docx_bytes, updated_at)
                VALUES (%s, '{}', %s, %s)
                ON CONFLICT (username) DO UPDATE SET
                    docx_bytes = EXCLUDED.docx_bytes,
                    updated_at = EXCLUDED.updated_at
                """,
                (username, docx_bytes, datetime.utcnow())
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] save_resume_docx error: {e}")
        return False
    finally:
        release_conn(conn)


def db_get_resume_docx(username: str) -> Optional[bytes]:
    """Return DOCX bytes or None."""
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT docx_bytes FROM user_resumes WHERE username = %s", (username,))
            row = cur.fetchone()
            if row and row[0]:
                return bytes(row[0])
    except Exception as e:
        logger.error(f"[DB] get_resume_docx error: {e}")
    finally:
        release_conn(conn)
    return None


def db_delete_resume(username: str) -> bool:
    """Clear resume data for user."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE user_resumes SET resume_json = %s, docx_bytes = NULL, updated_at = %s WHERE username = %s",
                (json.dumps({"_empty": True}), datetime.utcnow(), username)
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] delete_resume error: {e}")
        return False
    finally:
        release_conn(conn)


def db_has_resume(username: str) -> bool:
    """Return True if user has a non-empty resume."""
    data = db_get_resume(username)
    if not data:
        return False
    return not data.get("_empty", False) and bool(data.get("name", "").strip())


# ── Job History ────────────────────────────────────────────────────────────────

def db_save_run_log(username: str, run_id: str, log_data: dict) -> bool:
    """Insert a job history run log row."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_history (username, run_id, job_title, company, url, status,
                    score_before, score_after, score_delta, run_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    run_data   = EXCLUDED.run_data,
                    score_after = EXCLUDED.score_after,
                    score_delta = EXCLUDED.score_delta
                """,
                (
                    username,
                    run_id,
                    log_data.get("role", ""),
                    log_data.get("company", ""),
                    log_data.get("url", ""),
                    "complete",
                    log_data.get("score_before"),
                    log_data.get("score_after"),
                    log_data.get("score_delta"),
                    json.dumps(log_data, ensure_ascii=False),
                    datetime.utcnow(),
                )
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] save_run_log error: {e}")
        return False
    finally:
        release_conn(conn)


def db_get_history(username: str) -> list:
    """Return list of job history dicts for a user, newest first."""
    conn = get_conn()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT run_id, run_data, created_at FROM job_history WHERE username = %s ORDER BY created_at DESC LIMIT 200",
                (username,)
            )
            rows = cur.fetchall()
            results = []
            for row in rows:
                run_id, run_data_str, created_at = row
                try:
                    entry = json.loads(run_data_str) if run_data_str else {}
                except Exception:
                    entry = {}
                entry["log_file_name"] = f"{run_id}.json"
                entry["_db_run_id"] = run_id
                results.append(entry)
            return results
    except Exception as e:
        logger.error(f"[DB] get_history error: {e}")
        return []
    finally:
        release_conn(conn)


def db_get_history_item(run_id: str) -> Optional[dict]:
    """Get a single history item by run_id."""
    conn = get_conn()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT run_data FROM job_history WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            if row and row[0]:
                return json.loads(row[0])
    except Exception as e:
        logger.error(f"[DB] get_history_item error: {e}")
    finally:
        release_conn(conn)
    return None


def db_update_history_item(run_id: str, company: str = None, role: str = None, url: str = None) -> bool:
    """Update mutable fields on a history row."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            # Fetch existing run_data
            cur.execute("SELECT run_data FROM job_history WHERE run_id = %s", (run_id,))
            row = cur.fetchone()
            if not row:
                return False
            data = json.loads(row[0]) if row[0] else {}
            if company:
                data["company"] = company
            if role:
                data["role"] = role
            if url is not None:
                data["url"] = url

            cur.execute(
                "UPDATE job_history SET run_data = %s, company = COALESCE(%s, company), job_title = COALESCE(%s, job_title), url = COALESCE(%s, url) WHERE run_id = %s",
                (json.dumps(data), company, role, url, run_id)
            )
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] update_history_item error: {e}")
        return False
    finally:
        release_conn(conn)


def db_delete_history_item(run_id: str) -> bool:
    """Hard delete a single history row by run_id."""
    conn = get_conn()
    if not conn:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_history WHERE run_id = %s", (run_id,))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] delete_history_item error: {e}")
        return False
    finally:
        release_conn(conn)


def db_delete_all_history(username: str) -> int:
    """Delete all history rows for a user. Returns deleted count."""
    conn = get_conn()
    if not conn:
        return 0
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM job_history WHERE username = %s", (username,))
            count = cur.rowcount
        conn.commit()
        return count
    except Exception as e:
        conn.rollback()
        logger.error(f"[DB] delete_all_history error: {e}")
        return 0
    finally:
        release_conn(conn)
