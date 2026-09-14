import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Configure stdout for safe encoding
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# Load .env
env_path = Path('.env')
if env_path.exists():
    with open(env_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ.setdefault(k.strip(), v.strip())

db_url = os.environ.get('DATABASE_URL')
if not db_url:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

import psycopg2

conn = psycopg2.connect(db_url)
cur = conn.cursor()

print("Connected to NeonDB.")

# 1. Load users.json
users_file = Path('data/users.json')
users_data = {}
if users_file.exists():
    with open(users_file, 'r', encoding='utf-8') as f:
        users_data = json.load(f)

print(f"Found {len(users_data)} users in data/users.json: {list(users_data.keys())}")

for username, uinfo in users_data.items():
    email = uinfo.get('email', f'{username}@example.com')
    password_hash = uinfo.get('password_hash', '')
    display_name = uinfo.get('display_name', username)
    created_at_str = uinfo.get('created_at')
    created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.utcnow()

    # Upsert user
    cur.execute(
        """
        INSERT INTO users (username, email, password_hash, display_name, created_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (username) DO UPDATE SET
            email = EXCLUDED.email,
            password_hash = EXCLUDED.password_hash,
            display_name = EXCLUDED.display_name
        """,
        (username, email.lower(), password_hash, display_name, created_at)
    )
    print(f"[OK] User seeded: {username} ({display_name} <{email}>)")

    # 2. User Settings
    settings_file = Path(f'data/users/{username}/settings.json')
    if settings_file.exists():
        with open(settings_file, 'r', encoding='utf-8') as f:
            sdata = json.load(f)
        
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
                sdata.get('GEMINI_API_KEY', ''),
                sdata.get('GEMINI_API_KEY_2', ''),
                sdata.get('SIMPLIFY_EMAIL', ''),
                sdata.get('SIMPLIFY_PASSWORD', ''),
                sdata.get('HF_API_KEY', ''),
                sdata.get('COLAB_DETECTOR_URL', ''),
                datetime.utcnow()
            )
        )
        print(f"[OK] Settings seeded for: {username}")
    else:
        print(f"[INFO] No settings file found for: {username}")

    # 3. User Resume (JSON + DOCX)
    resume_file = Path(f'data/users/{username}/base_resume.json')
    if not resume_file.exists() and username == 'mhaseebhk0':
        resume_file = Path('base_resume.json')
    
    resume_json_str = '{}'
    if resume_file.exists():
        with open(resume_file, 'r', encoding='utf-8') as f:
            resume_json_str = f.read()

    docx_file = Path(f'data/users/{username}/master_resume_original.docx')
    if not docx_file.exists() and username == 'mhaseebhk0':
        docx_file = Path('master_resume_original.docx')
    
    docx_bytes = None
    if docx_file.exists():
        with open(docx_file, 'rb') as f:
            docx_bytes = f.read()

    if resume_json_str != '{}' or docx_bytes:
        cur.execute(
            """
            INSERT INTO user_resumes (username, resume_json, docx_bytes, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (username) DO UPDATE SET
                resume_json = EXCLUDED.resume_json,
                docx_bytes  = COALESCE(EXCLUDED.docx_bytes, user_resumes.docx_bytes),
                updated_at  = EXCLUDED.updated_at
            """,
            (username, resume_json_str, psycopg2.Binary(docx_bytes) if docx_bytes else None, datetime.utcnow())
        )
        print(f"[OK] Resume seeded for {username} (JSON: {len(resume_json_str)} chars, DOCX: {len(docx_bytes) if docx_bytes else 0} bytes)")

    # 4. Job History
    logs_dir = Path(f'data/users/{username}/output/logs')
    run_files = list(logs_dir.glob('run_*.json')) if logs_dir.exists() else []
    if not run_files and username == 'mhaseebhk0':
        root_logs_dir = Path('output/logs')
        if root_logs_dir.exists():
            run_files = list(root_logs_dir.glob('run_*.json'))

    seeded_runs = 0
    for rfile in run_files:
        run_id = rfile.stem
        try:
            with open(rfile, 'r', encoding='utf-8') as f:
                rdata = json.load(f)
            
            created_at = None
            if 'timestamp' in rdata:
                try:
                    created_at = datetime.fromisoformat(rdata['timestamp'])
                except Exception:
                    created_at = datetime.utcnow()
            else:
                created_at = datetime.utcnow()

            cur.execute(
                """
                INSERT INTO job_history (username, run_id, job_title, company, url, status,
                    score_before, score_after, score_delta, run_data, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (run_id) DO UPDATE SET
                    username    = EXCLUDED.username,
                    run_data    = EXCLUDED.run_data,
                    score_after = EXCLUDED.score_after,
                    score_delta = EXCLUDED.score_delta
                """,
                (
                    username,
                    run_id,
                    rdata.get('role', ''),
                    rdata.get('company', ''),
                    rdata.get('url', ''),
                    'complete',
                    rdata.get('score_before'),
                    rdata.get('score_after'),
                    rdata.get('score_delta'),
                    json.dumps(rdata, ensure_ascii=False),
                    created_at
                )
            )
            seeded_runs += 1
        except Exception as e:
            print(f"[WARN] Error reading {rfile}: {e}")

    print(f"[OK] Seeded {seeded_runs} job history runs for: {username}")

conn.commit()
print("\n--- NeonDB Seeding Complete ---")

# Summary check
cur.execute("SELECT username, email, display_name FROM users")
print("Users:", cur.fetchall())

cur.execute("SELECT username, gemini_api_key != '', simplify_email FROM user_settings")
print("Settings:", cur.fetchall())

cur.execute("SELECT username, length(resume_json), length(docx_bytes) FROM user_resumes")
print("Resumes:", cur.fetchall())

cur.execute("SELECT username, count(*) FROM job_history GROUP BY username")
print("Job History Counts:", cur.fetchall())

cur.close()
conn.close()
