import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _isolation  # noqa: F401  (keeps tests off the real DB cache and data/ files)
import unittest
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from app import app, _extract_entry_datetime

class TestHistoryMonthAndPurge(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp_dir.name)
        (self.tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_extract_entry_datetime_formats(self):
        # 1. Numeric seconds
        dt1 = _extract_entry_datetime({"timestamp": 1700000000})
        self.assertIsNotNone(dt1)
        self.assertEqual(dt1.tzinfo, timezone.utc)

        # 2. Numeric milliseconds
        dt2 = _extract_entry_datetime({"created_at": 1700000000000})
        self.assertIsNotNone(dt2)

        # 3. ISO string
        dt3 = _extract_entry_datetime({"created_at": "2026-10-15T14:30:00Z"})
        self.assertIsNotNone(dt3)
        self.assertEqual(dt3.year, 2026)
        self.assertEqual(dt3.month, 10)

        # 4. Filename run_YYYYMMDD_HHMMSS
        dt4 = _extract_entry_datetime({"log_file_name": "run_20260920_112233.json"})
        self.assertIsNotNone(dt4)
        self.assertEqual(dt4.year, 2026)
        self.assertEqual(dt4.month, 9)
        self.assertEqual(dt4.day, 20)

    def test_delete_older_than_validation_and_execution(self):
        mock_user = MagicMock(is_authenticated=True, data_dir=self.tmp_path, username="testuser")
        with patch("flask_login.utils._get_user", return_value=mock_user), \
             patch("app.get_user_output_dir", return_value=self.tmp_path):

            # Missing or negative days
            res = self.client.post("/api/history/delete_older_than", 
                                   data=json.dumps({"days": -5}),
                                   content_type="application/json")
            self.assertEqual(res.status_code, 400)

            # Create an old application run log (>45 days ago)
            old_dt = datetime.now(timezone.utc) - timedelta(days=45)
            old_run_name = f"run_{old_dt.strftime('%Y%m%d_%H%M%S')}.json"
            old_log_path = self.tmp_path / "logs" / old_run_name
            
            # Create corresponding target output folder
            target_out_dir = self.tmp_path / "Old_Company_Job_Role"
            target_out_dir.mkdir(parents=True, exist_ok=True)
            dummy_docx = target_out_dir / "Resume.docx"
            dummy_docx.write_text("dummy resume content")

            with open(old_log_path, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": old_dt.timestamp(),
                    "company": "Old Company",
                    "role": "Job Role",
                    "output_file": str(dummy_docx),
                    "relative_file_path": "Old_Company_Job_Role/Resume.docx"
                }, f)

            # Create a recent application (<5 days ago)
            recent_dt = datetime.now(timezone.utc) - timedelta(days=2)
            recent_run_name = f"run_{recent_dt.strftime('%Y%m%d_%H%M%S')}.json"
            recent_log_path = self.tmp_path / "logs" / recent_run_name
            with open(recent_log_path, "w", encoding="utf-8") as f:
                json.dump({
                    "timestamp": recent_dt.timestamp(),
                    "company": "Recent Company",
                    "role": "Recent Role"
                }, f)

            # Purge older than 30 days
            res = self.client.post("/api/history/delete_older_than", 
                                   data=json.dumps({"days": 30}),
                                   content_type="application/json")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("deleted_count"), 1)

            # Verify old log and directory were deleted
            self.assertFalse(old_log_path.exists())
            self.assertFalse(target_out_dir.exists())

            # Verify recent log was preserved
            self.assertTrue(recent_log_path.exists())

    def test_delete_month_execution(self):
        mock_user = MagicMock(is_authenticated=True, data_dir=self.tmp_path, username="testuser")
        with patch("flask_login.utils._get_user", return_value=mock_user), \
             patch("app.get_user_output_dir", return_value=self.tmp_path):

            # Invalid format
            res = self.client.post("/api/history/delete_month",
                                   data=json.dumps({"month": "invalid-month"}),
                                   content_type="application/json")
            self.assertEqual(res.status_code, 400)

            # Create log for 2026-08
            aug_log = self.tmp_path / "logs" / "run_20260815_120000.json"
            aug_dir = self.tmp_path / "August_Company_Role"
            aug_dir.mkdir(parents=True, exist_ok=True)
            with open(aug_log, "w", encoding="utf-8") as f:
                json.dump({
                    "created_at": "2026-08-15T12:00:00Z",
                    "company": "August Company",
                    "output_file": str(aug_dir / "resume.docx")
                }, f)

            # Create log for 2026-09
            sep_log = self.tmp_path / "logs" / "run_20260910_120000.json"
            with open(sep_log, "w", encoding="utf-8") as f:
                json.dump({
                    "created_at": "2026-09-10T12:00:00Z",
                    "company": "September Company"
                }, f)

            # Delete month 2026-08
            res = self.client.post("/api/history/delete_month",
                                   data=json.dumps({"month": "2026-08"}),
                                   content_type="application/json")
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertTrue(data.get("success"))
            self.assertEqual(data.get("deleted_count"), 1)

            # Verify 2026-08 is gone and 2026-09 is untouched
            self.assertFalse(aug_log.exists())
            self.assertFalse(aug_dir.exists())
            self.assertTrue(sep_log.exists())

if __name__ == "__main__":
    unittest.main()
