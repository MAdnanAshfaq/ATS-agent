"""
tests/test_editor_save_and_export.py - Verifies visual editor save and PDF export endpoints.
Ensures:
1. No UnboundLocalError for user_output_dir in /api/editor/export-pdf.
2. /api/editor/save does not double-nest directories and updates .docx in target directory.
3. Cache-invalidation operates properly so new edits are reflected.
"""
import unittest
import json
import os
import sys
import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import app as flask_app


class TestEditorSaveAndExport(unittest.TestCase):
    def setUp(self):
        flask_app.app.config["TESTING"] = True
        flask_app.app.config["WTF_CSRF_ENABLED"] = False
        self.client = flask_app.app.test_client()

        # Temporary user directory
        self.test_dir = tempfile.mkdtemp()
        self.user_data_dir = Path(self.test_dir) / "data"
        self.user_output_dir = Path(self.test_dir) / "output"
        self.user_data_dir.mkdir(parents=True)
        self.user_output_dir.mkdir(parents=True)

        self.mock_user = MagicMock()
        self.mock_user.is_authenticated = True
        self.mock_user.username = "test_candidate"
        self.mock_user.data_dir = self.user_data_dir
        self.mock_user.get_id = MagicMock(return_value="test_candidate")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("flask_login.utils._get_user")
    @patch("app.get_user_output_dir")
    @patch("resume_html.generate_pdf_from_html")
    def test_editor_export_pdf_no_unbound_local_error(self, mock_gen_pdf, mock_out_dir, mock_get_user):
        """Verify export-pdf endpoint never throws UnboundLocalError on user_output_dir."""
        def fake_gen_pdf(html_content, output_pdf_path, candidate_name="", role=""):
            Path(output_pdf_path).write_bytes(b"%PDF-1.4 dummy pdf content for testing" + b" " * 1500)
            return True

        mock_gen_pdf.side_effect = fake_gen_pdf
        mock_get_user.return_value = self.mock_user
        mock_out_dir.return_value = self.user_output_dir

        job_folder = self.user_output_dir / "Acme_Data_Engineer"
        job_folder.mkdir(parents=True, exist_ok=True)
        tailored_json = job_folder / "tailored_resume.json"
        resume_data = {
            "name": "Jane Doe",
            "target_company": "Acme",
            "target_role": "Data Engineer",
            "experience": [
                {
                    "company": "Acme",
                    "role": "Data Engineer",
                    "bullets": ["Optimized pipelines by 50% using Spark and Python."]
                }
            ]
        }
        with open(tailored_json, "w", encoding="utf-8") as f:
            json.dump(resume_data, f)

        # Call export-pdf endpoint with force_refresh=True
        resp = self.client.post(
            "/api/editor/export-pdf",
            json={
                "resume_path": "Acme_Data_Engineer/tailored_resume.json",
                "resume": resume_data,
                "force_refresh": True,
                "html": "<p>Test Resume</p>"
            }
        )

        # It should succeed or gracefully fallback without crashing with 500 UnboundLocalError
        self.assertNotEqual(
            resp.status_code, 500,
            f"Export PDF crashed with 500: {resp.get_data(as_text=True)}"
        )
        self.assertNotIn("user_output_dir", resp.get_data(as_text=True))

    @patch("flask_login.utils._get_user")
    @patch("app.get_user_output_dir")
    @patch("resume_html.generate_pdf_from_html")
    def test_editor_save_updates_target_dir_without_nested_folders(self, mock_gen_pdf, mock_out_dir, mock_get_user):
        """Verify editor save writes .docx directly in target_dir without creating target_dir/Acme_Data_Engineer/."""
        mock_gen_pdf.return_value = True
        mock_get_user.return_value = self.mock_user
        mock_out_dir.return_value = self.user_output_dir

        job_folder = self.user_output_dir / "Acme_Data_Engineer"
        job_folder.mkdir(parents=True, exist_ok=True)
        tailored_json = job_folder / "tailored_resume.json"
        old_docx = job_folder / "Jane_Doe_Resume.docx"
        old_docx.write_text("old version")

        updated_resume = {
            "name": "Jane Doe",
            "target_company": "Acme",
            "target_role": "Data Engineer",
            "experience": [
                {
                    "company": "Acme",
                    "role": "Data Engineer",
                    "bullets": ["NEW EDITED BULLET: Deployed LLM agent with 99.9% uptime."]
                }
            ]
        }

        resp = self.client.post(
            "/api/editor/save",
            json={
                "resume_path": "Acme_Data_Engineer/tailored_resume.json",
                "resume": updated_resume,
                "editor_styles": {}
            }
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertTrue(data.get("success"))

        # Verify json was updated
        with open(tailored_json, "r", encoding="utf-8") as f:
            saved_json = json.load(f)
        self.assertIn("NEW EDITED BULLET", saved_json["experience"][0]["bullets"][0])

        # Verify no nested folder job_folder / Acme_Data_Engineer was created
        nested_folder = job_folder / "Acme_Data_Engineer"
        self.assertFalse(nested_folder.exists(), "Double-nested folder was incorrectly created inside target_dir!")

        # Verify Jane_Doe_Resume.docx in job_folder was overwritten and is a valid new file
        self.assertTrue(old_docx.exists())
        self.assertNotEqual(old_docx.read_bytes(), b"old version")


if __name__ == "__main__":
    unittest.main()
