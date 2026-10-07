import json
import os
import unittest
from pathlib import Path

from app import app, _build_crafted_master_resume, BASE_DIR


class TestMasterResumeDownload(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.config["TESTING"] = True
        app.config["LOGIN_DISABLED"] = True
        cls.client = app.test_client()

    def test_build_crafted_master_resume_docx_crafted(self):
        user_data_dir = BASE_DIR
        user_resume_path = BASE_DIR / "base_resume.json"
        user_output_dir = BASE_DIR / "output"

        file_path, download_name, mimetype = _build_crafted_master_resume(
            user_data_dir=user_data_dir,
            user_resume_path=user_resume_path,
            user_output_dir=user_output_dir,
            req_format="docx",
            template_mode="crafted",
        )
        self.assertIsNotNone(file_path)
        self.assertTrue(file_path.exists())
        self.assertTrue(download_name.endswith(".docx"))
        self.assertIn("application/vnd.openxmlformats-officedocument.wordprocessingml.document", mimetype)

    def test_build_crafted_master_resume_docx_clean(self):
        user_data_dir = BASE_DIR
        user_resume_path = BASE_DIR / "base_resume.json"
        user_output_dir = BASE_DIR / "output"

        file_path, download_name, mimetype = _build_crafted_master_resume(
            user_data_dir=user_data_dir,
            user_resume_path=user_resume_path,
            user_output_dir=user_output_dir,
            req_format="docx",
            template_mode="clean",
        )
        self.assertIsNotNone(file_path)
        self.assertTrue(file_path.exists())
        self.assertTrue(download_name.endswith(".docx"))
        self.assertIn("ATS", download_name)

    def test_build_crafted_master_resume_pdf(self):
        user_data_dir = BASE_DIR
        user_resume_path = BASE_DIR / "base_resume.json"
        user_output_dir = BASE_DIR / "output"

        file_path, download_name, mimetype = _build_crafted_master_resume(
            user_data_dir=user_data_dir,
            user_resume_path=user_resume_path,
            user_output_dir=user_output_dir,
            req_format="pdf",
            template_mode="crafted",
        )
        self.assertIsNotNone(file_path)
        self.assertTrue(file_path.exists())
        self.assertTrue(download_name.endswith(".pdf"))
        self.assertEqual(mimetype, "application/pdf")

    def test_api_master_resume_download_endpoint_docx(self):
        res = self.client.get("/api/master-resume/download?format=docx&template=crafted")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument", res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        self.assertIn(".docx", res.headers.get("Content-Disposition", ""))

    def test_api_master_resume_download_endpoint_pdf(self):
        res = self.client.get("/api/master-resume/download?format=pdf&template=crafted")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        self.assertIn(".pdf", res.headers.get("Content-Disposition", ""))

    def test_api_master_resume_download_endpoint_clean_ats(self):
        res = self.client.get("/api/master-resume/download?format=docx&template=clean")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument", res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))
        self.assertIn("ATS", res.headers.get("Content-Disposition", ""))

    def test_download_master_resume_route_docx(self):
        res = self.client.get("/api/download/master_resume.docx")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/vnd.openxmlformats-officedocument", res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))

    def test_download_master_resume_route_pdf(self):
        res = self.client.get("/api/download/master_resume.pdf")
        self.assertEqual(res.status_code, 200)
        self.assertIn("application/pdf", res.headers.get("Content-Type", ""))
        self.assertIn("attachment", res.headers.get("Content-Disposition", ""))


if __name__ == "__main__":
    unittest.main()
