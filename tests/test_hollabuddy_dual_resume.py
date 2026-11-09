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

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_extracts_controller_action_tailor_resume(self, mock_exec, mock_keys):
        def fake_execute(call_fn):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "I'm starting the resume tailoring pipeline for Snowflake now!\n[[ACTION:tailor_resume|keywords=Snowflake,PySpark,dbt]]"
            mock_response.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_response
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Tailor my resume for this Snowflake role",
            base_resume=self.base_resume,
            pipeline_state={"company": "Snowflake", "role": "Data Engineer"}
        )

        self.assertIsNotNone(res.get("action"))
        self.assertEqual(res["action"]["type"], "tailor_resume")
        self.assertEqual(res["action"]["params"].get("keywords"), "Snowflake,PySpark,dbt")
        # Action tag must be cleanly removed from user reply
        self.assertNotIn("[[ACTION:", res["reply"])
        self.assertIn("I'm starting the resume tailoring pipeline", res["reply"])

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_extracts_controller_action_refine_and_open_editor(self, mock_exec, mock_keys):
        def fake_execute(call_fn):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Applying revisions and opening the Visual Studio Editor for you!\n[[ACTION:refine_resume|instruction=Add 30% latency reduction]]"
            mock_response.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_response
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Make my top bullet emphasize latency reduction",
            base_resume=self.base_resume,
            drafted_resume=self.drafted_resume,
        )

        self.assertIsNotNone(res.get("action"))
        self.assertEqual(res["action"]["type"], "refine_resume")
        self.assertEqual(res["action"]["params"].get("instruction"), "Add 30% latency reduction")
        self.assertNotIn("[[ACTION:", res["reply"])

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_system_prompt_includes_pipeline_state(self, mock_exec, mock_keys):
        captured_system_instruction = None

        def fake_execute(call_fn):
            nonlocal captured_system_instruction
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Understood."
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            def fake_generate_content(model, contents, config):
                nonlocal captured_system_instruction
                captured_system_instruction = config.system_instruction
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        pipeline_state = {
            "company": "Databricks",
            "role": "Solutions Architect",
            "ats_platform": "Workday",
            "score_before": 68,
            "missing_keywords": ["Delta Lake", "Unity Catalog", "MLflow"],
            "has_tailored_resume": False
        }

        chat_with_hollabuddy(
            message="What should I do next?",
            base_resume=self.base_resume,
            pipeline_state=pipeline_state
        )

        self.assertIn("Databricks", captured_system_instruction)
        self.assertIn("Solutions Architect", captured_system_instruction)
        self.assertIn("Delta Lake", captured_system_instruction)
        self.assertIn("Workday", captured_system_instruction)
        self.assertIn("AUTONOMOUS PIPELINE CONTROLLER MANDATE", captured_system_instruction)

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_focus_job_action_parsing(self, mock_exec, mock_keys):
        def fake_execute(call_fn):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "I've loaded your Beehiiv application into working memory! [[ACTION:focus_job|company=Beehiiv]]"
            mock_response.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_response
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="focus on the Beehiiv job in history in your context to chat further",
            base_resume=self.base_resume,
            application_history=[{"company": "Beehiiv", "role": "Senior Engineer"}]
        )

        self.assertIn("action", res)
        self.assertIsNotNone(res["action"])
        self.assertEqual(res["action"]["type"], "focus_job")
        self.assertEqual(res["action"]["params"].get("company"), "Beehiiv")
        # Ensure tag is stripped from user reply
        self.assertNotIn("[[ACTION:", res["reply"])
        self.assertIn("Beehiiv", res["reply"])

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_prompt_differentiates_focus_from_open_editor(self, mock_exec, mock_keys):
        captured_system_instruction = None

        def fake_execute(call_fn):
            nonlocal captured_system_instruction
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "Sure thing!"
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            def fake_generate_content(model, contents, config):
                nonlocal captured_system_instruction
                captured_system_instruction = config.system_instruction
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        chat_with_hollabuddy(
            message="focus on Beehiiv",
            base_resume=self.base_resume,
            application_history=[{"company": "Beehiiv", "role": "Senior Engineer"}]
        )

        self.assertIsNotNone(captured_system_instruction)
        self.assertIn("ACTION:focus_job|company=CompanyName", captured_system_instruction)
        self.assertIn("CRITICAL**: DO NOT output `[[ACTION:open_editor]]` when the candidate just wants to focus", captured_system_instruction)


if __name__ == "__main__":
    unittest.main()

