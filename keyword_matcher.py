"""
keyword_matcher.py — Local keyword matching engine.
Calculates before/after resume match scores against a JD without needing Simplify.

Used by agent.py to:
1. Measure baseline score BEFORE rewrite
2. Measure final score AFTER AI detection cleanup
3. Report the delta to show the agent's impact
"""
import json
import re
from typing import Tuple


# Common stop words to exclude from keyword matching
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "this", "that", "these",
    "those", "we", "you", "i", "he", "she", "it", "they", "our", "your",
    "their", "its", "my", "your", "his", "her", "work", "team", "role",
    "join", "looking", "seeking", "strong", "great", "good", "well",
    "experience", "candidate", "position", "job", "opportunity", "company",
    "including", "required", "preferred", "bonus", "etc", "e.g", "i.e",
    "as", "if", "not", "so", "such", "than", "more", "also", "both",
    "each", "while", "about", "like", "per", "across", "within", "who",
}

# Technical keyword patterns to detect in JDs and resumes
TECH_PATTERNS = [
    # Languages
    r'\b(Python|JavaScript|TypeScript|Java|Go|Golang|Rust|Ruby|PHP|Scala|'
    r'Swift|Kotlin|C\+\+|C#|R|Bash|Shell|MATLAB|Perl|Haskell|Elixir)\b',
    # Frontend
    r'\b(React|Vue\.?js|Angular|Next\.?js|Nuxt\.?js|Svelte|Gatsby|'
    r'Redux|MobX|Zustand|Tailwind|Bootstrap|Sass|SCSS|Webpack|Vite|'
    r'Storybook|Figma|Material\s*UI|Ant\s*Design|Chakra\s*UI)\b',
    # Backend
    r'\b(Node\.?js|Express|FastAPI|Django|Flask|Spring|Rails|Laravel|'
    r'NestJS|Fastify|Hono|Gin|Fiber|gRPC|GraphQL|REST|WebSocket|'
    r'OAuth|JWT|SAML|SSO|OpenAPI|Swagger)\b',
    # Databases
    r'\b(PostgreSQL|Postgres|MySQL|MongoDB|SQLite|Redis|Elasticsearch|'
    r'DynamoDB|Cassandra|Neo4j|Supabase|Firebase|CockroachDB|'
    r'Snowflake|BigQuery|Redshift|Pinecone|Weaviate|Chroma)\b',
    # Cloud & DevOps
    r'\b(AWS|GCP|Azure|Docker|Kubernetes|K8s|Terraform|Ansible|Helm|'
    r'CI/CD|GitHub\s*Actions|Jenkins|CircleCI|ArgoCD|Datadog|'
    r'Prometheus|Grafana|Sentry|Vercel|Netlify|Heroku|Cloudflare|'
    r'Lambda|EC2|S3|ECS|EKS|Cloud\s*Run|GKE)\b',
    # Testing
    r'\b(Jest|Pytest|Cypress|Playwright|Selenium|Mocha|Vitest|'
    r'Testing\s*Library|Enzyme|PHPUnit|RSpec)\b',
    # ML/AI
    r'\b(PyTorch|TensorFlow|Keras|scikit-learn|Hugging\s*Face|'
    r'LangChain|LlamaIndex|RAG|LLM|OpenAI|Anthropic|Gemini|'
    r'Vector\s*Database|Embedding|Fine-tuning|RLHF)\b',
    # Data
    r'\b(Kafka|RabbitMQ|Celery|Airflow|Spark|Flink|dbt|Pandas|'
    r'NumPy|Jupyter|Dagster|Prefect|Looker|Tableau|Power\s*BI)\b',
    # Process
    r'\b(Agile|Scrum|Kanban|JIRA|Confluence|Notion|Linear|'
    r'Microservices|Serverless|Event.?driven|Domain.?driven|'
    r'TDD|BDD|DDD|SOLID|Design\s*Patterns|System\s*Design)\b',
]


def extract_keywords_from_text(text: str) -> set:
    """
    Extract all meaningful technical keywords from a block of text.
    Returns a lowercase set of keyword strings.
    """
    keywords = set()

    # 1. Extract known tech keywords using patterns
    for pattern in TECH_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            keywords.add(match.group().strip().lower())

    # 2. Extract multi-word technical phrases (2-3 word combos that look technical)
    phrase_pattern = re.compile(
        r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b'
    )
    for match in phrase_pattern.finditer(text):
        phrase = match.group().strip()
        if (len(phrase) > 5
                and phrase.lower() not in STOP_WORDS
                and not all(w.lower() in STOP_WORDS for w in phrase.split())):
            keywords.add(phrase.lower())

    # 3. Extract standalone technical words (CamelCase or ALL_CAPS or kebab-case)
    word_pattern = re.compile(r'\b([A-Z]{2,}|[A-Z][a-z]+[A-Z][a-z]+\w*|[\w]+-[\w]+)\b')
    for match in word_pattern.finditer(text):
        word = match.group().strip()
        if (3 < len(word) < 40
                and word.lower() not in STOP_WORDS
                and not word.isnumeric()):
            keywords.add(word.lower())

    return keywords


def calculate_match_score(resume: dict, jd_text: str) -> dict:
    """
    Calculate keyword match score between resume and JD.

    Args:
        resume: Resume dict (base or rewritten)
        jd_text: Full job description text

    Returns:
        {
            "score": int (0-100),
            "present_keywords": [str, ...],
            "missing_keywords": [str, ...],
            "total_jd_keywords": int,
        }
    """
    # Extract all text from resume
    resume_text = _flatten_resume_to_text(resume)

    # Get keyword sets
    jd_keywords = extract_keywords_from_text(jd_text)
    resume_keywords = extract_keywords_from_text(resume_text)

    # Filter JD keywords to only meaningful ones (exclude very short/generic)
    jd_keywords = {
        kw for kw in jd_keywords
        if len(kw) > 2 and kw not in STOP_WORDS
    }

    # Calculate matches
    present = sorted(jd_keywords & resume_keywords)
    missing = sorted(jd_keywords - resume_keywords)

    total = len(jd_keywords)
    score = round((len(present) / total * 100) if total > 0 else 0)

    return {
        "score": score,
        "present_keywords": present,
        "missing_keywords": missing,
        "total_jd_keywords": total,
    }


def compare_scores(
    base_resume: dict,
    final_resume: dict,
    jd_text: str,
) -> dict:
    """
    Calculate before/after match scores and return the delta.

    Returns:
    {
        "before_score": int,
        "after_score": int,
        "delta": int,
        "before_present": [str, ...],
        "before_missing": [str, ...],
        "after_present": [str, ...],
        "after_missing": [str, ...],
        "newly_added": [str, ...],      # keywords added by rewrite
        "still_missing": [str, ...],    # keywords still absent after rewrite
    }
    """
    before = calculate_match_score(base_resume, jd_text)
    after = calculate_match_score(final_resume, jd_text)

    newly_added = sorted(set(after["present_keywords"]) - set(before["present_keywords"]))
    still_missing = sorted(set(after["missing_keywords"]))

    return {
        "before_score": before["score"],
        "after_score": after["score"],
        "delta": after["score"] - before["score"],
        "before_present": before["present_keywords"],
        "before_missing": before["missing_keywords"],
        "after_present": after["present_keywords"],
        "after_missing": after["missing_keywords"],
        "newly_added": newly_added,
        "still_missing": still_missing,
        "total_jd_keywords": before["total_jd_keywords"],
    }


def _flatten_resume_to_text(resume: dict) -> str:
    """Flatten all resume fields into a single searchable text string."""
    parts = []

    parts.append(resume.get("summary", ""))
    parts.extend(resume.get("skills", []))

    for exp in resume.get("experience", []):
        parts.append(exp.get("title", ""))
        parts.append(exp.get("company", ""))
        parts.extend(exp.get("bullets", []))

    for proj in resume.get("projects", []):
        parts.append(proj.get("name", ""))
        parts.extend(proj.get("tech_stack", []))
        parts.append(proj.get("description", ""))

    for edu in resume.get("education", []):
        parts.append(edu.get("degree", ""))
        parts.append(edu.get("field", ""))
        parts.append(edu.get("institution", ""))

    parts.extend(resume.get("certifications", []))

    return " ".join(str(p) for p in parts if p)


def format_score_report(comparison: dict) -> str:
    """Format a human-readable before/after score report."""
    lines = [
        "",
        "  KEYWORD MATCH SCORE REPORT",
        f"  Before rewrite : {comparison['before_score']}%",
        f"  After rewrite  : {comparison['after_score']}%",
        f"  Improvement    : +{comparison['delta']}%",
        f"  Total JD keywords : {comparison['total_jd_keywords']}",
    ]

    if comparison["newly_added"]:
        lines.append(f"\n  ✅ Newly added ({len(comparison['newly_added'])}):")
        for kw in comparison["newly_added"][:12]:
            lines.append(f"     • {kw}")
        if len(comparison["newly_added"]) > 12:
            lines.append(f"     ... +{len(comparison['newly_added']) - 12} more")

    if comparison["still_missing"]:
        lines.append(f"\n  ⚠️  Still missing ({len(comparison['still_missing'])}):")
        for kw in comparison["still_missing"][:8]:
            lines.append(f"     • {kw}")
        if len(comparison["still_missing"]) > 8:
            lines.append(f"     ... +{len(comparison['still_missing']) - 8} more")

    return "\n".join(lines)


if __name__ == "__main__":
    """Quick self-test."""
    import sys, json, os

    resume_path = os.path.join(os.path.dirname(__file__), "base_resume.json")
    if not os.path.exists(resume_path):
        print("Run pdf_to_resume.py first to generate base_resume.json")
        sys.exit(1)

    with open(resume_path) as f:
        resume = json.load(f)

    test_jd = """
    Senior Full Stack Engineer. Requirements: React, TypeScript, Node.js, GraphQL,
    PostgreSQL, Redis, Docker, Kubernetes, AWS, CI/CD, GitHub Actions, Jest,
    Agile, system design, microservices, REST APIs, OAuth, JWT.
    """

    result = calculate_match_score(resume, test_jd)
    print(f"Score: {result['score']}%")
    print(f"Present ({len(result['present_keywords'])}): {result['present_keywords']}")
    print(f"Missing ({len(result['missing_keywords'])}): {result['missing_keywords']}")
