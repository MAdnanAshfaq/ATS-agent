"""Regression tests: measured (not invented) ATS scores, per-user cache isolation,
and the engine's keyword-coverage guarantee."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: F401  (keeps tests off the real DB cache and data/ files)
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ats_scoring
from ats_scoring import keyword_present, score_text, score_docx, docx_parse_findings, keywords_added_beyond


class TestKeywordMatching(unittest.TestCase):
    def test_literal_matching_edge_cases(self):
        cases = [
            ("C++", "Wrote C++ services", True),
            ("C", "Wrote C++ services", False),
            ("C#", "Built C# APIs", True),
            (".NET", "Migrated to .NET 6", True),
            ("Node.js", "Node.js backend", True),
            ("CI/CD", "built CI / CD pipelines", True),
            ("Go", "a good team player", False),
            ("Go", "services in Go and Python", True),
            ("R", "led R&D work", False),
            ("Spark", "sparkling water", False),
            ("ETL Pipelines", "owned the ETL pipeline", True),
            ("REST API", "designed REST APIs", True),
            ("Kubernetes", "K8s clusters", False),
        ]
        for kw, text, expected in cases:
            with self.subTest(kw=kw, text=text):
                self.assertEqual(keyword_present(kw, text), expected)

    def test_alias_counts_only_as_evidence(self):
        self.assertFalse(keyword_present("Kubernetes", "ran K8s clusters"))
        self.assertTrue(keyword_present("Kubernetes", "ran K8s clusters", allow_aliases=True))

    def test_score_is_plain_coverage(self):
        res = score_text("Python and SQL on Snowflake", ["Python", "SQL", "Airflow", "dbt"])
        self.assertEqual(res["score"], 50)
        self.assertEqual(res["missing"], ["Airflow", "dbt"])
        self.assertIsNone(score_text("anything", [])["score"])

    def test_added_beyond_master_lists_only_new_claims(self):
        master = {"skills": ["Python", "K8s"], "experience": [{"bullets": ["Built ETL in Python"]}]}
        final = "Python ETL on Kubernetes with Airflow"
        added = keywords_added_beyond(master, final, ["Python", "Kubernetes", "Airflow", "dbt"])
        # Kubernetes is backed by the K8s alias; dbt is not in the final text.
        self.assertEqual(added, ["Airflow"])


class TestDeliveredFileScoring(unittest.TestCase):
    def _docx(self, build):
        from docx import Document
        doc = Document()
        build(doc)
        fd, path = tempfile.mkstemp(suffix=".docx")
        os.close(fd)
        doc.save(path)
        self.addCleanup(os.remove, path)
        return path

    def test_scores_body_and_tables_but_not_text_boxes(self):
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        def build(doc):
            doc.add_paragraph("Experience")
            doc.add_paragraph("Built pipelines in Python and Airflow.")
            doc.add_paragraph("Education")
            doc.add_paragraph("Skills")
            t = doc.add_table(rows=1, cols=1)
            t.cell(0, 0).text = "Snowflake"
            p = doc.add_paragraph()
            p._p.append(parse_xml(
                f'<w:r {nsdecls("w")}><w:txbxContent><w:p><w:r><w:t>Kubernetes dbt</w:t></w:r></w:p>'
                f'</w:txbxContent></w:r>'))

        path = self._docx(build)
        res = score_docx(path, ["Python", "Airflow", "Snowflake", "Kubernetes"])
        self.assertEqual(res["matched"], ["Python", "Airflow", "Snowflake"])
        self.assertEqual(res["missing"], ["Kubernetes"])  # only inside a text box
        issues = " ".join(f["issue"] for f in res["parse_findings"])
        self.assertIn("text box", issues)
        self.assertIn("table", issues)

    def test_clean_single_column_file_has_no_findings(self):
        def build(doc):
            for line in ("Jane Doe", "jane@example.com", "Experience", "Built APIs.",
                         "Education", "BSc", "Skills", "Python"):
                doc.add_paragraph(line)

        self.assertEqual(docx_parse_findings(self._docx(build)), [])


class TestAnalysisCacheIsolation(unittest.TestCase):
    def setUp(self):
        import app as app_module
        self.app = app_module
        self.app._ANALYSIS_CACHE_BY_USER.clear()

    def tearDown(self):
        self.app._ANALYSIS_CACHE_BY_USER.clear()

    def test_users_never_see_each_others_entries(self):
        self.app._user_analysis_cache("alice")["https://jobs.example.com/1"] = {
            "jd_text": "A" * 80, "missing_keywords": ["Airflow"]}
        self.assertIsNone(self.app.get_cached_analysis_entry("https://jobs.example.com/1", "", "bob"))
        self.assertIsNotNone(self.app.get_cached_analysis_entry("https://jobs.example.com/1", "", "alice"))

    def test_real_url_never_falls_back_to_another_job(self):
        self.app._user_analysis_cache("alice")["https://jobs.example.com/1"] = {"jd_text": "A" * 80}
        self.assertIsNone(self.app.get_cached_analysis_entry("https://jobs.example.com/2", "", "alice"))
        # With no URL at all, the user's own most recent analysis is reused.
        self.assertIsNotNone(self.app.get_cached_analysis_entry("", "", "alice"))


class TestEngineKeywordCoverage(unittest.TestCase):
    BASE = {
        "name": "Sam",
        "skills": ["Python", "SQL"],
        "experience": [
            {"title": "Data Engineer", "company": "Acme", "dates": "2019 – Present",
             "bullets": ["Built batch ETL jobs in Python moving 2M rows daily into the warehouse.",
                         "Wrote SQL models that cut dashboard load time by 30 percent."]},
            {"title": "Analyst", "company": "Beta", "dates": "2015 – 2019",
             "bullets": ["Maintained SQL reports for the finance team every month."]},
        ],
        "education": [{"degree": "BSc"}],
    }

    def _writer_draft(self, **kwargs):
        draft = {k: v for k, v in self.BASE.items()}
        draft["experience"] = [dict(e) for e in self.BASE["experience"]]
        draft["experience"][0] = dict(draft["experience"][0], company="Acme Corp (renamed)", title="Staff Engineer")
        return draft

    def _weave(self, prompt, **kwargs):
        import json
        exp = json.loads(prompt.split("EXPERIENCE (JSON):", 1)[1])
        exp[0]["bullets"] = exp[0]["bullets"] + ["Orchestrated nightly loads with Apache Airflow across 40 DAGs."]
        return exp

    def test_missing_keywords_end_up_in_bullets_and_skills(self):
        import danis_engine
        with patch.object(danis_engine, "get_gemini_client", return_value=None), \
             patch.object(danis_engine, "run_writer_phase", side_effect=self._writer_draft), \
             patch.object(danis_engine, "_call_json_llm", side_effect=self._weave), \
             patch.object(danis_engine, "run_editor_phase", side_effect=lambda d, *a, **k: d):
            out = danis_engine.execute_danis_engine_pipeline(
                base_resume=self.BASE, jd_text="Python SQL Apache Airflow", missing_keywords=["Apache Airflow"],
                company="Target", role="Data Engineer", target_keywords=["Python", "SQL", "Apache Airflow"])

        bullets = " ".join(out["experience"][0]["bullets"])
        self.assertIn("Apache Airflow", bullets)
        self.assertIn("Apache Airflow", out["skills"])
        self.assertEqual(out["_keyword_coverage"]["skills_only"], [])
        # Fixed facts are forced back from the master resume.
        self.assertEqual(out["experience"][0]["company"], "Acme")
        self.assertEqual(out["experience"][0]["title"], "Data Engineer")
        self.assertEqual(out["experience"][0]["dates"], "2019 – Present")
        # The audit attached to the result was run on this final resume.
        self.assertIn("findings", out["_voice_audit"])
        self.assertIn("findings", out["_ats_audit"])


class TestVoiceCleanupIsSafe(unittest.TestCase):
    def test_technical_terms_survive(self):
        from danis_engine import deterministic_voice_cleanup
        out = deterministic_voice_cleanup({"experience": [{"bullets": [
            "Spearheaded a dynamic programming solver for routing.",
            "Ensured idempotency of Airflow DAGs using seamless retries.",
        ]}]})
        b = out["experience"][0]["bullets"]
        self.assertEqual(b[0], "Led a dynamic programming solver for routing.")
        # "Ensured" is on the auditor's cliche-opener list, so it must be swapped (or the
        # audit would flag it on every run); the technical term itself is untouched.
        self.assertEqual(b[1], "Maintained idempotency of Airflow DAGs using smooth retries.")


class TestSecretsNeverSentToBrowser(unittest.TestCase):
    def test_mask_and_round_trip(self):
        import app as app_module
        key = "AIzaSyD-example-key-1234567890abcd"
        masked = app_module._mask_secret(key)
        self.assertNotIn(key[4:-4], masked)
        self.assertTrue(masked.startswith(key[:4]) and masked.endswith(key[-4:]))
        # A masked value posted back resolves to the stored key...
        self.assertEqual(app_module._unmask_secret(masked, [key]), key)
        # ...a newly pasted key is saved as typed...
        self.assertEqual(app_module._unmask_secret("AIzaNEWKEY0000000000", [key]), "AIzaNEWKEY0000000000")
        # ...and mask text that matches nothing is dropped, never saved as a key.
        self.assertEqual(app_module._unmask_secret("AIza••••zzzz", [key]), "")
        self.assertEqual(app_module._mask_secret(""), "")


if __name__ == "__main__":
    unittest.main()
