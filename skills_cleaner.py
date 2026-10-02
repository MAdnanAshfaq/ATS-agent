"""
skills_cleaner.py — High-precision technical skills cleaner, deduplicator,
and ecosystem integrity guardian for ATS Resume Optimization.

Solves:
1. Vendor/ecosystem cross-contamination (e.g. Databricks OneLake, Azure Direct Lake).
2. Errant comma splits of compound multi-word tech (e.g. "Unity, Catalog" -> "Unity Catalog").
3. Garbage word fragments (e.g. "Direct", "Lake", "Data", "Factory", "HR", "governance").
4. Duplicate/subsumed entries (e.g. "Microsoft Azure" + "Azure", "Azure Data Factory" + "Data Factory").
5. Core Job Description keywords omission (e.g. Palantir Foundry, PySpark, AWS/GCP, GIS, Governance).
"""

import re
import json
from typing import List, Union

# Known Frankenstein vendor mashups to detect and cleanly separate into authentic components
FRANKENSTEIN_REPAIRS = [
    (r'\bDatabricks\s+OneLake\b', ['Databricks (Unity Catalog)', 'Microsoft Fabric (OneLake)']),
    (r'\bAzure\s*\(\s*Direct\s+Lake\s*\)', ['Microsoft Azure', 'Power BI (Direct Lake)']),
    (r'\bAzure\s+Direct\s+Lake\b', ['Microsoft Azure', 'Power BI (Direct Lake)']),
    (r'\bAWS\s+BigQuery\b', ['AWS', 'Google Cloud BigQuery']),
    (r'\bSnowflake\s+Unity\s+Catalog\b', ['Snowflake', 'Databricks Unity Catalog']),
    (r'\bGoogle\s+Redshift\b', ['Google Cloud (GCP)', 'Amazon Redshift']),
]

# Compound multi-word terms that should never be split by commas, spaces, or parser heuristics
COMPOUND_PHRASES = [
    "Unity Catalog", "Data Factory", "Azure Data Factory", "Direct Lake", "Delta Lake",
    "Delta Live Tables", "Microsoft Fabric", "Palantir Foundry", "Power BI",
    "Azure Synapse", "Azure DevOps", "ADLS Gen2", "Google Cloud Platform", "Cloud Storage",
    "Google BigQuery", "Amazon Web Services", "AWS Glue", "AWS Lambda", "AWS EMR", "AWS Athena",
    "Amazon Redshift", "Amazon S3", "Amazon Kinesis", "DynamoDB", "Repository Governance",
    "Dataset Versioning", "Audit Readiness", "Data Governance", "Data Modeling", "Data Lineage",
    "GIS Platforms", "Geospatial Data", "Spatial Analysis", "Apache Spark", "Apache Airflow",
    "Apache Kafka", "PySpark", "CI/CD", "GitHub Actions", "GitLab CI", "Docker Compose",
    "Machine Learning", "Deep Learning", "Generative AI", "Large Language Models",
    "Prompt Engineering", "Object Oriented Programming", "Software Development Lifecycle",
    "Test Driven Development", "Continuous Integration", "Continuous Deployment",
    "Business Intelligence", "Relational Database", "NoSQL Database", "Distributed Systems",
    "Microservices Architecture", "Event Driven Architecture", "Rest API", "Rest APIs"
]

# Meaningless standalone fragment words that are almost always broken remnants of split phrases
FRAGMENT_WORDS = {
    'direct', 'lake', 'data', 'factory', 'catalog', 'governance', 'hr',
    'readiness', 'versioning', 'platform', 'platforms', 'tool', 'tools',
    'service', 'services', 'cloud', 'system', 'systems', 'management',
    'architecture', 'engineering', 'development', 'solutions', 'framework',
    'frameworks', 'library', 'libraries', 'mode', 'storage'
}

# Synonyms and canonical forms: map variants to canonical representation
SYNONYM_MAP = {
    'azure': 'Microsoft Azure',
    'ms azure': 'Microsoft Azure',
    'microsoft azure': 'Microsoft Azure',
    'aws': 'AWS',
    'amazon web services': 'AWS',
    'gcp': 'Google Cloud (GCP)',
    'google cloud': 'Google Cloud (GCP)',
    'google cloud platform': 'Google Cloud (GCP)',
    'powerbi': 'Power BI',
    'power bi': 'Power BI',
    'k8s': 'Kubernetes',
    'postgres': 'PostgreSQL',
    'postgresql': 'PostgreSQL',
    'fabric': 'Microsoft Fabric',
    'microsoft fabric': 'Microsoft Fabric',
    'onelake': 'Microsoft Fabric (OneLake)',
    'fabric onelake': 'Microsoft Fabric (OneLake)',
    'palantir': 'Palantir Foundry',
    'palantir foundry': 'Palantir Foundry',
    'dbt': 'dbt',
    'airflow': 'Apache Airflow',
    'kafka': 'Apache Kafka',
    'spark': 'Apache Spark',
    'pyspark': 'PySpark',
}


def clean_technical_skills_list(skills: Union[List[str], str], jd_text: str = "") -> List[str]:
    """
    Cleans, deduplicates, repairs ecosystem mashups, stitches split compounds,
    removes meaningless fragment orphans, and preserves core JD requirements.
    """
    if not skills:
        return []

    # Flatten and stringify
    raw_list = []
    if isinstance(skills, str):
        raw_list = [skills]
    elif isinstance(skills, (list, tuple, set)):
        for item in skills:
            if isinstance(item, list):
                raw_list.extend(str(x) for x in item if x)
            elif item:
                raw_list.append(str(item))

    # Pre-step 1: Repair raw text strings before splitting
    pre_repaired = []
    for s in raw_list:
        text = str(s).strip()
        # Fix errant comma splits inside compound terms: "Unity, Catalog" -> "Unity Catalog"
        text = re.sub(r'\bUnity\s*,\s*Catalog\b', 'Unity Catalog', text, flags=re.I)
        text = re.sub(r'\bData\s*,\s*Factory\b', 'Data Factory', text, flags=re.I)
        text = re.sub(r'\bDirect\s*,\s*Lake\b', 'Direct Lake', text, flags=re.I)
        text = re.sub(r'\bDelta\s*,\s*Lake\b', 'Delta Lake', text, flags=re.I)
        text = re.sub(r'\bPower\s*,\s*BI\b', 'Power BI', text, flags=re.I)
        text = re.sub(r'\bPalantir\s*,\s*Foundry\b', 'Palantir Foundry', text, flags=re.I)
        text = re.sub(r'\bMicrosoft\s*,\s*Fabric\b', 'Microsoft Fabric', text, flags=re.I)
        text = re.sub(r'\bAudit\s*,\s*Readiness\b', 'Audit Readiness', text, flags=re.I)
        text = re.sub(r'\bRepository\s*,\s*Governance\b', 'Repository Governance', text, flags=re.I)
        text = re.sub(r'\bDataset\s*,\s*Versioning\b', 'Dataset Versioning', text, flags=re.I)

        # Check for Frankenstein repairs
        repaired = False
        for pat, replacements in FRANKENSTEIN_REPAIRS:
            if re.search(pat, text, flags=re.I):
                pre_repaired.extend(replacements)
                repaired = True
                break
        if not repaired:
            pre_repaired.append(text)

    # Step 2: Separate items if a string has multiple comma-separated items
    # (preserve single multi-word items like "Microsoft Fabric OneLake")
    split_items = []
    for item in pre_repaired:
        if ',' in item:
            parts = [p.strip() for p in re.split(r',+', item) if p.strip()]
            split_items.extend(parts)
        else:
            split_items.append(item.strip())

    # Step 3: Stitch together adjacent split words in the list if present
    # e.g. ['Unity', 'Catalog'] -> 'Unity Catalog'
    stitched_items = []
    i = 0
    while i < len(split_items):
        curr = split_items[i].strip(' "\'`;:[]{}•·▪-*')
        nxt = split_items[i+1].strip(' "\'`;:[]{}•·▪-*') if i + 1 < len(split_items) else ""
        pair = f"{curr} {nxt}".lower()

        matched_compound = None
        for cp in COMPOUND_PHRASES:
            if cp.lower() == pair:
                matched_compound = cp
                break

        if matched_compound:
            stitched_items.append(matched_compound)
            i += 2
        else:
            if curr:
                stitched_items.append(curr)
            i += 1

    # Step 4: Normalize, Canonicalize, and Filter Fragments
    cleaned_result = []
    seen_canonical = set()

    for item in stitched_items:
        clean = item.strip(' "\'`;:[]{}•·▪-*')
        # If parens are unbalanced (e.g. "(" without ")"), repair them
        if clean.count('(') > clean.count(')'):
            clean += ')'
        elif clean.count(')') > clean.count('('):
            clean = clean.replace(')', '')

        if not clean or len(clean) < 2:
            continue

        c_lower = clean.lower()

        # Check if it's a standalone fragment word
        if c_lower in FRAGMENT_WORDS:
            continue

        # Canonicalize if in synonym map
        canonical = SYNONYM_MAP.get(c_lower, clean)
        canon_lower = canonical.lower()

        if canon_lower not in seen_canonical:
            seen_canonical.add(canon_lower)
            cleaned_result.append(canonical)

    # Step 5: Subsumption deduplication
    final_skills = []
    all_lower = {s.lower() for s in cleaned_result}

    for skill in cleaned_result:
        sk_lower = skill.lower()
        if sk_lower == "data factory" and ("azure data factory" in all_lower):
            continue
        if sk_lower == "azure" and ("microsoft azure" in all_lower):
            continue
        if sk_lower == "unity catalog" and ("databricks (unity catalog)" in all_lower or "databricks unity catalog" in all_lower):
            continue
        if sk_lower == "direct lake" and any("direct lake" in x for x in all_lower if x != "direct lake"):
            continue
        if sk_lower == "microsoft fabric" and ("microsoft fabric (onelake)" in all_lower):
            continue
        if sk_lower == "onelake" and any("onelake" in x for x in all_lower if x != "onelake"):
            continue
        final_skills.append(skill)

    # Step 6: If Job Description is provided, check for critical missing tech keywords
    if jd_text:
        jd_lower = jd_text.lower()
        priority_checks = [
            ("palantir foundry", "Palantir Foundry"),
            ("pyspark", "PySpark"),
            ("unity catalog", "Databricks (Unity Catalog)"),
            ("delta lake", "Delta Lake"),
            ("microsoft fabric", "Microsoft Fabric (OneLake)"),
            ("data factory", "Azure Data Factory"),
            ("geospatial", "GIS / Geospatial Data"),
            ("dataset versioning", "Dataset Versioning"),
            ("repository governance", "Repository Governance"),
            ("audit readiness", "Audit Readiness"),
            ("snowflake", "Snowflake"),
            ("aws", "AWS"),
            ("gcp", "Google Cloud (GCP)"),
            ("dbt", "dbt"),
            ("airflow", "Apache Airflow"),
            ("kafka", "Apache Kafka"),
        ]
        curr_lower = {s.lower() for s in final_skills}
        for trigger, full_name in priority_checks:
            if trigger in jd_lower and not any(trigger in x for x in curr_lower):
                final_skills.append(full_name)
                curr_lower.add(full_name.lower())

    return final_skills
