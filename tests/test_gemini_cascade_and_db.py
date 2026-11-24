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

        self.assertEqual(result.get("score"), 85)
        self.assertIn("Python", result.get("matching_keywords", []))
        self.assertIn("Airflow", result.get("missing_keywords", []))
        self.assertGreaterEqual(call_counts["count"], 2)

    def test_db_pool_proactive_idle_recycle(self):
        """Verify DB connection idle time is tracked and recycled if older than MAX_IDLE_SECONDS."""
        mock_pool = MagicMock()
        mock_conn = MagicMock()
        mock_conn.closed = 0
        # Set last used time to 300 seconds ago (older than MAX_IDLE_SECONDS = 240)
        mock_conn._ats_last_used = time.time() - 300.0

        mock_conn_fresh = MagicMock()
        mock_conn_fresh.closed = 0
        mock_conn_fresh._ats_last_used = 0

        # Pool returns old connection first, then fresh connection
        mock_pool.getconn.side_effect = [mock_conn, mock_conn_fresh]

        with patch("db.get_pool", return_value=mock_pool):
            conn = db.get_conn()
            self.assertEqual(conn, mock_conn_fresh)
            # Verify old conn was returned to pool with close=True
            mock_pool.putconn.assert_any_call(mock_conn, close=True)


if __name__ == "__main__":
    unittest.main()
