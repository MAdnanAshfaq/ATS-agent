"""
tests/test_gemini_cascade_and_db.py - Tests for Gemini multi-model cascade failover on 503,
and DB pool idle socket handling.
"""
import unittest
import time
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gemini_client
import llm_matcher
import db


class TestGeminiCascadeAndDB(unittest.TestCase):
    def test_default_models_cascade_contains_fallbacks(self):
        """Verify cascade contains robust fallback models (gemini-3.5-flash, gemini-3.6-flash, etc.)."""
        candidates = gemini_client.get_candidate_models()
        self.assertIn("gemini-3.5-flash-lite", candidates)
        self.assertIn("gemini-3.5-flash", candidates)
        self.assertIn("gemini-3.6-flash", candidates)
        self.assertNotIn("gemini-2.5-flash-lite", candidates)  # Shut down model must remain excluded

    @patch("gemini_client.get_all_gemini_keys")
    @patch("gemini_client.get_gemini_client")
    def test_llm_matcher_fails_over_on_503(self, mock_get_client, mock_get_keys):
        """Verify that when a model throws 503, llm_matcher tries subsequent models and succeeds."""
        mock_get_keys.return_value = ["mock_key_1"]

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        call_counts = {"count": 0}

        def mock_generate_content(model, contents, config):
            call_counts["count"] += 1
            if model == "gemini-3.5-flash-lite":
                # Simulate 503 High Demand
                raise Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
            # Second model in cascade succeeds
            resp = MagicMock()
            resp.text = '{"score": 85, "score_scale_10": 8.5, "score_rating": "Great", "matching_keywords": ["Python", "SQL"], "missing_keywords": ["Airflow"]}'
            resp.candidates = [MagicMock()]
            return resp

        mock_client.models.generate_content.side_effect = mock_generate_content

        result = llm_matcher.analyze_jd_and_resume_with_gemini(
            jd_text="Data Engineer at Aya Healthcare. Requirements: Python, SQL, Airflow.",
            base_resume={"name": "Alex", "skills": ["Python", "SQL"]}
        )

        # Score is measured keyword coverage (2 of 3 JD keywords in the resume), not
        # the model's own opinion; the opinion is kept separately as ai_score.
        self.assertEqual(result.get("score"), 67)
        self.assertEqual(result.get("ai_score"), 85)
        self.assertIn("Python", result.get("matching_keywords", []))
        self.assertIn("Airflow", result.get("missing_keywords", []))
        self.assertGreaterEqual(call_counts["count"], 2)

    def test_db_pool_proactive_idle_recycle(self):
        """Verify DB connection idle time is tracked and recycled if older than MAX_IDLE_SECONDS."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = 0
        # Set last used time to 300 seconds ago (older than MAX_IDLE_SECONDS = 240)
        db._conn_last_used[id(mock_conn)] = time.time() - 300.0

        mock_conn_fresh = MagicMock()
        mock_conn_fresh.closed = 0

        # Pool returns old connection first, then fresh connection
        mock_pool.getconn.side_effect = [mock_conn, mock_conn_fresh]

        try:
            with patch("db.get_pool", return_value=mock_pool):
                conn = db.get_conn()
                self.assertEqual(conn, mock_conn_fresh)
                # Verify old conn was returned to pool with close=True
                mock_pool.putconn.assert_any_call(mock_conn, close=True)
                self.assertNotIn(id(mock_conn), db._conn_last_used)
        finally:
            db._conn_last_used.clear()

    def test_db_get_conn_works_with_slotted_connection_objects(self):
        """Real psycopg2 connections reject new attributes; get_conn must not rely on setattr."""
        class _Cursor:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql): pass

        class _SlottedConn:
            __slots__ = ("closed",)
            def __init__(self): self.closed = 0
            def cursor(self): return _Cursor()
            def rollback(self): pass

        real_like = _SlottedConn()
        mock_pool = MagicMock()
        mock_pool.getconn.return_value = real_like
        try:
            with patch("db.get_pool", return_value=mock_pool):
                conn = db.get_conn()
                self.assertIs(conn, real_like)
                db.release_conn(conn)
                mock_pool.putconn.assert_called_with(real_like)
        finally:
            db._conn_last_used.clear()

    def test_standard_genai_config_disables_thinking_for_full_flash(self):
        """Full Flash models must receive thinking_budget=0 to avoid 503/504 spikes; flash-lite must omit it."""
        for m in ("gemini-3.5-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-2.5-flash"):
            for is_json in (True, False):
                cfg = gemini_client.get_standard_genai_config(model_name=m, is_json=is_json)
                self.assertIsNotNone(cfg.thinking_config, f"{m} (is_json={is_json}) missing thinking_config")
                self.assertEqual(cfg.thinking_config.thinking_budget, 0)

        for m in ("gemini-3.5-flash-lite", "gemini-flash-lite-latest"):
            cfg = gemini_client.get_standard_genai_config(model_name=m, is_json=True)
            self.assertIsNone(cfg.thinking_config, f"{m} should omit thinking_config")

    @patch("time.sleep", return_value=None)
    @patch("rewriter.get_all_gemini_keys", return_value=["k1", "k2"])
    @patch("rewriter.rotate_key")
    @patch("rewriter._get_gemini_client")
    def test_rewriter_fails_over_on_503_and_falls_back_gracefully(self, mock_get_client, mock_rotate, mock_keys, mock_sleep):
        """Verify rewriter rotates keys / fails over on 503 and never crashes with RuntimeError if all fail."""
        import rewriter

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def mock_gen_fail_first(model, contents, config):
            if "flash-lite" in model:
                raise Exception("503 UNAVAILABLE. This model is currently experiencing high demand.")
            resp = MagicMock()
            resp.text = '{"summary": "Experienced Engineer.", "skills": ["Python", "SQL", "Airflow"], "experience": [{"title": "Data Engineer", "company": "Acme", "dates": "2022 - Present", "bullets": ["Built Airflow pipelines."]}]}'
            resp.candidates = [MagicMock()]
            return resp

        mock_client.models.generate_content.side_effect = mock_gen_fail_first
        base_res = {"name": "Alex", "skills": ["Python", "SQL"], "experience": [{"title": "Data Engineer", "company": "Acme", "dates": "2022 - Present", "bullets": ["Built pipelines."]}]}
        res = rewriter.rewrite_resume(base_res, "JD needs Airflow", ["Airflow"], "Acme", "Data Engineer")
        self.assertIn("Airflow", res.get("skills", []))
        self.assertTrue(mock_rotate.called)

        # Now verify that even if EVERY model throws 503, rewrite_resume falls back gracefully instead of crashing
        mock_client.models.generate_content.side_effect = Exception("503 UNAVAILABLE. High demand.")
        res_fallback = rewriter.rewrite_resume(base_res, "JD needs Airflow", ["Airflow"], "Acme", "Data Engineer")
        self.assertTrue(any("airflow" in s.lower() for s in res_fallback.get("skills", [])))


if __name__ == "__main__":
    unittest.main()
