import unittest
from unittest.mock import MagicMock, patch
import json

from hollabuddy import chat_with_hollabuddy, _generate_quick_followups


class TestHollaBuddyDualResume(unittest.TestCase):
    def setUp(self):
        self.base_resume = {
            "name": "Jane Doe",
            "title": "Senior Data Engineer",
            "experience": [
                {
                    "company": "Acme Corp",
                    "role": "Data Engineer",
                    "bullets": [
                        "Built ETL pipelines using Python and SQL."
                    ]
                }
            ]
        }
        self.drafted_resume = {
            "name": "Jane Doe",
            "title": "Lead Spark & Snowflake Engineer",
            "experience": [
                {
                    "company": "Acme Corp",
                    "role": "Lead Data Engineer",
                    "bullets": [
                        "Architected scalable PySpark and Snowflake pipelines, improving throughput by 42%."
                    ]
                }
            ]
        }

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_includes_both_master_and_drafted_resume(self, mock_exec, mock_keys):
        captured_system_instruction = None

        def fake_execute(call_fn):
            nonlocal captured_system_instruction
            # Create a mock client that will inspect the config passed
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Here is the comparison between your master and drafted resume."
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            def fake_generate_content(model, contents, config):
                nonlocal captured_system_instruction
                captured_system_instruction = config.system_instruction
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="What is the difference between my master resume and my newly drafted resume?",
            base_resume=self.base_resume,
            drafted_resume=self.drafted_resume,
            job_context={"company": "Snowflake Inc", "role": "Staff Data Platform Engineer"}
        )

        self.assertIsNotNone(captured_system_instruction)
        # Check Master Truth section
        self.assertIn("CANDIDATE MASTER TRUTH", captured_system_instruction)
        self.assertIn("Built ETL pipelines using Python and SQL", captured_system_instruction)

        # Check Drafted Resume section
        self.assertIn("NEW DRAFTED / TAILORED RESUME", captured_system_instruction)
        self.assertIn("Lead Spark & Snowflake Engineer", captured_system_instruction)
        self.assertIn("Architected scalable PySpark and Snowflake pipelines", captured_system_instruction)

        # Check Job Context
        self.assertIn("Snowflake Inc", captured_system_instruction)

        self.assertIn("reply", res)
        self.assertEqual(res["reply"], "Here is the comparison between your master and drafted resume.")

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_without_drafted_resume_uses_placeholder(self, mock_exec, mock_keys):
        captured_system_instruction = None

        def fake_execute(call_fn):
            nonlocal captured_system_instruction
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Loaded your master resume."
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            def fake_generate_content(model, contents, config):
                nonlocal captured_system_instruction
                captured_system_instruction = config.system_instruction
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Help me with interview prep",
            base_resume=self.base_resume,
            drafted_resume=None,
        )

        self.assertIn("No job-specific drafted resume created yet", captured_system_instruction)
        self.assertIn("Jane Doe", captured_system_instruction)

    def test_quick_followups_for_drafted_resume(self):
        followups = _generate_quick_followups("Can you review my new drafted resume?", "Here is the critique")
        self.assertTrue(any("draft" in f.lower() or "keyword" in f.lower() or "bullet" in f.lower() for f in followups))


if __name__ == "__main__":
    unittest.main()
