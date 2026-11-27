"""Same job + same resume must give the same score and the same findings.

Covers: the stored keyword list per job, the shared resume report, the cleanup
fixing everything the auditor flags, and HollaBuddy answering audits from the
measured report."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: F401  (keeps tests off the real DB cache and data/ files)
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm_matcher

JD = ("Senior Data Engineer. We need Python, SQL, Apache Airflow, dbt, Snowflake, Kafka and Terraform. "
      "You will build pipelines on AWS with Docker and Kubernetes. ") * 3
RESUME = {
    "name": "Sam",
    "skills": ["Python", "SQL", "Snowflake"],
    "experience": [{"title": "Data Engineer", "company": "Acme", "dates": "2019 – Present",
                    "bullets": ["Built Python ETL jobs into Snowflake for 2M rows daily."]}],
}


def _gemini_payload(keywords):
    import json
    return json.dumps({"score": 70, "matching_keywords": [], "missing_keywords": keywords,
                       "job_title_jd": "Senior Data Engineer", "exp_years_jd": "5+ years exp"})


class TestStableKeywordListPerJob(unittest.TestCase):
    def setUp(self):
        llm_matcher._JD_CACHE_MEM.clear()
        llm_matcher._RESULT_CACHE_MEM.clear()
        if os.path.exists(llm_matcher._JD_CACHE_FILE):
            os.remove(llm_matcher._JD_CACHE_FILE)

    def test_same_job_scores_the_same_even_if_gemini_answers_differently(self):
        answers = iter([
            _gemini_payload(["Python", "SQL", "Apache Airflow", "dbt", "Snowflake", "Kafka"]),
            _gemini_payload(["Python", "Terraform", "Docker", "AWS", "Kubernetes"]),  # a different pick
        ])
        calls = {"n": 0}

        def fake_failover(fn):
            calls["n"] += 1
            resp = MagicMock()
            resp.text = next(answers)
            return resp

        with patch("gemini_client.get_all_gemini_keys", return_value=["k"]), \
             patch("gemini_client.execute_with_failover", side_effect=fake_failover), \
             patch("gemini_client.extract_clean_text", side_effect=lambda r: r.text):
            first = llm_matcher.analyze_jd_and_resume_with_gemini(JD, RESUME, job_url="https://jobs.example.com/123?utm_source=x")
            second = llm_matcher.analyze_jd_and_resume_with_gemini(JD, RESUME, job_url="https://jobs.example.com/123")

        self.assertEqual(calls["n"], 1, "the second check must reuse the stored list, not ask Gemini again")
        self.assertEqual(first["score"], second["score"])
        self.assertEqual(first["matching_keywords"], second["matching_keywords"])
        self.assertEqual(first["missing_keywords"], second["missing_keywords"])
        self.assertEqual(first["score"], 50)  # Python, SQL, Snowflake of 6

    def test_changed_resume_changes_score_against_the_same_list(self):
        llm_matcher._jd_cache_put(llm_matcher._jd_cache_keys(JD), {
            "keywords": ["Python", "SQL", "Apache Airflow", "dbt"], "source": "gemini"})
        before = llm_matcher.analyze_jd_and_resume_with_gemini(JD, RESUME)
        better = dict(RESUME, skills=RESUME["skills"] + ["Apache Airflow", "dbt"])
        after = llm_matcher.analyze_jd_and_resume_with_gemini(JD, better)
        self.assertEqual((before["score"], after["score"]), (50, 100))


class TestSharedReport(unittest.TestCase):
    def test_report_is_deterministic_and_classifies_who_can_fix(self):
        from resume_report import build_resume_report
        master = {"experience": [
            {"title": "Data Engineer", "company": "Acme", "dates": "2023 – 2025", "bullets": ["Built ETL in Python."]},
            {"title": "Analyst", "company": "Beta", "dates": "2015 – 2019", "bullets": ["Wrote SQL reports."]},
        ], "skills": ["Python", "SQL"]}
        tailored = {"summary": "Data engineer building pipelines.", "skills": ["Python", "SQL", "LangChain", "dbt"],
                    "experience": [
                        {"title": "Data Engineer", "company": "Acme", "dates": "2023 – 2025",
                         "bullets": ["Built ETL in Python moving 2M rows daily.", "Modeled 40 tables in dbt for finance."]},
                        {"title": "Analyst", "company": "Beta", "dates": "2015 – 2019",
                         "bullets": ["Wrote SQL reports for 12 teams.", "Prototyped LangChain agents for 3 support flows."]},
                    ]}
        kws = ["Python", "SQL", "LangChain", "dbt"]
        r1 = build_resume_report(tailored, master, kws, "Data Engineer")
        r2 = build_resume_report(tailored, master, kws, "Data Engineer")
        self.assertEqual(r1, r2)
        issues = {f["category"]: f for f in r1["findings"]}
        self.assertEqual(issues["credibility"]["fix"], "pipeline")         # LangChain in a 2015-2019 role
        self.assertEqual(issues["dates"]["fix"], "master")                 # current role lacks "Present"
        self.assertEqual(r1["interview_prep"], ["LangChain", "dbt"])       # added beyond master: prep, not issues
        self.assertFalse(any("dbt" in f["issue"] and f["category"] != "keywords" for f in r1["findings"]))


class TestCleanupFixesEverythingTheAuditorFlags(unittest.TestCase):
    def test_every_cliche_opener_is_replaced(self):
        from danis_engine import deterministic_voice_cleanup
        from human_voice_audit import audit_resume_dict, load_ai_tells
        for opener in load_ai_tells()["cliche_openers"]:
            resume = {"experience": [{"bullets": [f"{opener.title()} the billing pipeline for 3 regions."]}]}
            findings = audit_resume_dict(deterministic_voice_cleanup(resume))["findings"]
            with self.subTest(opener=opener):
                self.assertFalse([f for f in findings if "cliché bullet opener" in f], findings)

    def test_banned_words_in_prose_are_replaced_and_facts_are_not_scanned(self):
        from danis_engine import deterministic_voice_cleanup
        from human_voice_audit import audit_resume_dict
        resume = {"summary": "Builds robust, holistic platforms.", "skills": ["Dynamic Programming", "Robust Statistics"],
                  "experience": [{"company": "Vibrant Labs", "bullets": [
                      "Tuned a dynamic pricing model in Python for 3 regions.",
                      "Moved 40 jobs to Airflow, notably cutting failures 30%."]}]}
        findings = audit_resume_dict(deterministic_voice_cleanup(resume))["findings"]
        self.assertFalse([f for f in findings if "Banned AI tell" in f], findings)

    def test_cleanup_never_creates_a_repeated_opener(self):
        from danis_engine import deterministic_voice_cleanup
        bullets = [f"Collaborated with team {i} on 3 data contracts." for i in range(4)]
        out = deterministic_voice_cleanup({"experience": [{"bullets": bullets}]})
        firsts = [b.split()[0] for b in out["experience"][0]["bullets"]]
        self.assertTrue(all(firsts.count(v) <= 2 for v in firsts), firsts)


class TestHollaBuddyAnswersFromTheReport(unittest.TestCase):
    def test_audit_question_gets_report_and_low_temperature(self):
        import hollabuddy
        seen = {}

        def fake_failover(fn):
            client = MagicMock()

            def gen(model, contents, config):
                seen["system"] = config.system_instruction
                seen["temperature"] = config.temperature
                resp = MagicMock()
                resp.text = "Your resume passes every check."
                resp.candidates = [MagicMock()]
                return resp
            client.models.generate_content.side_effect = gen
            return fn(client)

        report = {"verdict": "ready", "keyword_score": 100, "keywords_total": 4, "score_source": "delivered_docx",
                  "findings": [], "interview_prep": ["dbt"], "keywords_missing": []}
        with patch.object(hollabuddy, "get_all_gemini_keys", return_value=["k"]), \
             patch.object(hollabuddy, "execute_with_failover", side_effect=fake_failover):
            hollabuddy.chat_with_hollabuddy("Audit my resume for ATS issues and interview probability",
                                            base_resume={"name": "Sam"}, drafted_resume={"name": "Sam"},
                                            measured_report=report)
        self.assertIn("MEASURED RESUME REPORT", seen["system"])
        self.assertIn("Findings: none.", seen["system"])
        self.assertIn("NEVER give an interview probability", seen["system"])
        self.assertLessEqual(seen["temperature"], 0.1)


class TestResumeRules(unittest.TestCase):
    JD = """Senior Full Stack Engineer
You will own features end to end and work closely with product managers.
You will mentor junior engineers.
Requirements:
- 5+ years with Python, React and PostgreSQL.
- Experience with AWS and CI/CD.
- Familiarity with Terraform is a plus.
Nice to have:
- Kubernetes
- GraphQL"""

    def test_keyword_tiers(self):
        import resume_rules as rr
        t = rr.split_keyword_tiers(["Python", "React", "PostgreSQL", "AWS", "CI/CD", "Terraform", "Kubernetes", "GraphQL"], self.JD)
        self.assertEqual(t["must_have"], ["Python", "React", "PostgreSQL", "AWS", "CI/CD"])
        self.assertEqual(t["nice_to_have"], ["Terraform", "Kubernetes", "GraphQL"])

    def test_core_themes(self):
        import resume_rules as rr
        themes = rr.extract_core_themes(self.JD)
        for t in ("End-to-end ownership", "Mentoring and technical leadership", "Working with product and cross-functional teams"):
            self.assertIn(t, themes)
        self.assertLessEqual(len(themes), rr.MAX_THEMES)
        resume = {"summary": "Engineer who owned the billing service end to end.",
                  "experience": [{"bullets": ["Mentored 3 engineers.", "Partnered with product managers on the roadmap."]}]}
        self.assertEqual(rr.missing_themes(resume, themes[:3]), [])

    def test_skill_dedupe_keeps_jd_spelling_and_distinct_skills(self):
        import resume_rules as rr
        skills = ["PostgreSQL", "Postgres", "Amazon Web Services", "AWS", "CI/CD", "CI / CD", "PySpark", "Spark", "REST APIs", "REST API"]
        jd = "We use Postgres on AWS with CI/CD and REST APIs."
        self.assertEqual(rr.dedupe_skills(skills, jd), ["Postgres", "AWS", "CI/CD", "PySpark", "Spark", "REST APIs"])
        self.assertEqual(len(rr.duplicate_skills(skills)), 4)

    def test_new_claims_and_stuffing(self):
        import resume_rules as rr
        master = {"experience": [{"company": "Acme", "bullets": ["Cut costs 20% on 2M rows daily in Python."]}]}
        final = {"experience": [{"company": "Acme", "bullets": [
            "Cut costs 20% on 2M rows daily in Python.",
            "Led a team of 6 to ship React, Terraform and Kubernetes deployments for 40 services.",
        ]}]}
        claims = rr.new_claims(master, final)
        self.assertEqual(len(claims), 1)
        self.assertEqual(claims[0]["numbers"], ["6", "40"])
        stuffed = rr.stuffed_bullets(master, final, ["Python", "React", "Terraform", "Kubernetes"])
        self.assertEqual(stuffed[0]["keywords"], ["React", "Terraform", "Kubernetes"])

    def test_trim_caps_roles_and_keeps_only_place_of_a_must_have(self):
        import resume_rules as rr
        master = {"experience": [{"company": "Acme", "bullets": [f"Built report {i} for finance." for i in range(8)]}]}
        final = {"summary": "", "experience": [{"company": "Acme", "bullets":
                 [f"Built report {i} for finance." for i in range(12)] + ["Deployed services on Kubernetes for 4 teams."]}]}
        out, dropped = rr.trim_bullets(final, master, ["Kubernetes"], [], [])
        bullets = out["experience"][0]["bullets"]
        self.assertEqual(len(bullets), rr.role_cap(0, 8))
        self.assertTrue(any("Kubernetes" in b for b in bullets))
        self.assertEqual(len(dropped), 13 - len(bullets))

    def test_report_coverage_vs_believability(self):
        from resume_report import build_resume_report
        master = {"skills": ["Python"], "experience": [{"title": "Engineer", "company": "Acme", "dates": "2020 – Present",
                                                         "bullets": ["Built Python services for 3 teams."]}]}
        resume = {"summary": "Full stack engineer who owned features end to end with product managers and mentored engineers.",
                  "skills": ["Python", "React", "PostgreSQL", "AWS", "CI/CD", "Terraform", "Kubernetes", "GraphQL"],
                  "experience": [{"title": "Engineer", "company": "Acme", "dates": "2020 – Present", "bullets": [
                      "Built Python services and React screens for 3 teams.",
                      "Moved PostgreSQL to AWS with CI/CD checks on every merge."]}]}
        kws = ["Python", "React", "PostgreSQL", "AWS", "CI/CD", "Terraform", "Kubernetes", "GraphQL"]
        r = build_resume_report(resume, master, kws, "Senior Full Stack Engineer", jd_text=self.JD)
        self.assertEqual(r["coverage"]["must_have_in_bullets"], "5/5")
        self.assertEqual(r["coverage"]["nice_to_have_skills_only"], ["Terraform", "Kubernetes", "GraphQL"])
        self.assertFalse([f for f in r["findings"] if f["category"] == "keywords"])  # Skills-only nice-to-have is fine
        self.assertIn("believability", r)
        # A must-have only in Skills is a blocker.
        resume2 = dict(resume, experience=[dict(resume["experience"][0], bullets=["Built Python services for 3 teams."])],
                       summary="Full stack engineer.")
        r2 = build_resume_report(resume2, master, kws, "Senior Full Stack Engineer", jd_text=self.JD)
        self.assertTrue(any(f["category"] == "keywords" and f["severity"] == "blocker" for f in r2["findings"]))


if __name__ == "__main__":
    unittest.main()
