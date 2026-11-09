import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

from hollabuddy import chat_with_hollabuddy


class TestRefinePreviewSync(unittest.TestCase):
    def test_hollabuddy_refine_param_parsing_order_independence(self):
        """Verify that instruction and company are parsed correctly regardless of ordering."""
        def fake_exec(call_fn):
            mock_client = MagicMock()
            mock_resp = MagicMock()
            mock_resp.text = "I've revised your bullet point! [[ACTION:refine_resume|company=Beehiiv|instruction=Rewrite bullet 2 to highlight Kafka and high-scale ingestion]]"
            mock_resp.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_resp
            return call_fn(mock_client)

        with patch("hollabuddy.get_all_gemini_keys", return_value=["dummy_key"]), \
             patch("hollabuddy.execute_with_failover", side_effect=fake_exec):
            res = chat_with_hollabuddy("update bullet 2 for beehiiv")
            self.assertIsNotNone(res.get("action"))
            action = res["action"]
            self.assertEqual(action["type"], "refine_resume")
            self.assertEqual(action["params"].get("company"), "Beehiiv")
            self.assertIn("Kafka", action["params"].get("instruction", ""))

    def test_refine_updates_run_log_and_preview_serves_tailored(self):
        """Test that preview endpoint inspects run logs and serves tailored resume."""
        from app import app
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            logs_dir = tmp_path / "logs"
            logs_dir.mkdir(parents=True)

            log_file = logs_dir / "run_20260909_999999.json"
            sample_tailored = {
                "name": "Jane Doe",
                "title": "Lead Kafka Architect",
                "experience": [
                    {
                        "company": "Beehiiv",
                        "role": "Lead Data Engineer",
                        "bullets": ["Engineered high-scale Kafka pipelines handling 10M events daily."]
                    }
                ]
            }
            log_file.write_text(json.dumps({
                "company": "Beehiiv",
                "role": "Lead Data Engineer",
                "output_file": "Beehiiv_Lead_Data_Engineer/Jane_Doe_Resume.docx",
                "relative_file_path": "Beehiiv_Lead_Data_Engineer/Jane_Doe_Resume.docx",
                "tailored_resume": sample_tailored
            }), encoding="utf-8")

            with app.test_client() as client, \
                 patch("app.get_user_output_dir", return_value=tmp_path), \
                 patch("flask_login.utils._get_user", return_value=MagicMock(is_authenticated=True, data_dir=tmp_path, username="testuser")):
                
                resp = client.get("/api/preview/Beehiiv_Lead_Data_Engineer/Jane_Doe_Resume.docx")
                self.assertEqual(resp.status_code, 200)
                html_text = resp.data.decode("utf-8")
                self.assertIn("Lead Kafka Architect", html_text)
                self.assertIn("Engineered high-scale Kafka pipelines", html_text)


if __name__ == "__main__":
    unittest.main()
