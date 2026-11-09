import unittest
from unittest.mock import MagicMock, patch
import json

from hollabuddy import chat_with_hollabuddy
from cover_letter_generator import generate_cover_letter


class TestHistoryAndCoverLetterCustom(unittest.TestCase):
    def setUp(self):
        self.base_resume = {
            "name": "Alex Mercer",
            "title": "Principal Data Engineer",
            "contact": {
                "email": "alex@example.com",
                "phone": "555-0199",
                "location": "San Francisco, CA"
            },
            "summary": "Data engineer specializing in large-scale streaming systems.",
            "skills": ["Python", "Spark", "Kafka", "Snowflake", "Databricks"],
            "experience": [
                {
                    "company": "Amazon",
                    "title": "Senior Data Engineer",
                    "bullets": [
                        "Scaled DynamoDB and Spark pipelines, reducing latency by 45% for 10M daily events."
                    ]
                }
            ]
        }

        self.application_history = [
            {
                "run_id": "run_snowflake_001",
                "company": "Snowflake",
                "role": "Staff Platform Engineer",
                "score_after": 88,
                "timestamp": "2026-10-15 14:30:00",
                "matched_keywords": ["Snowflake", "SQL", "Data Warehousing", "Python"],
                "cover_letter_snippet": "At Amazon, I built low-latency processing systems...",
                "experience_highlights": [
                    {
                        "title": "Senior Data Engineer",
                        "company": "Amazon",
                        "bullets": ["Scaled DynamoDB and Spark pipelines, reducing latency by 45%."]
                    }
                ]
            },
            {
                "run_id": "run_databricks_002",
                "company": "Databricks",
                "role": "Solutions Architect",
                "score_after": 92,
                "timestamp": "2026-10-28 11:20:00",
                "matched_keywords": ["Spark", "Delta Lake", "PySpark"],
                "cover_letter_snippet": "My background in distributed Lakehouse architecture...",
                "experience_highlights": []
            }
        ]

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_embeds_application_history_in_prompt(self, mock_exec, mock_keys):
        captured_system_instruction = None

        def fake_execute(call_fn):
            nonlocal captured_system_instruction
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = "I've reviewed your Snowflake application from history!"
            mock_response.candidates = [MagicMock(finish_reason="STOP")]

            def fake_generate_content(model, contents, config):
                nonlocal captured_system_instruction
                captured_system_instruction = config.system_instruction
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Compare my current role to what we did for Snowflake last month.",
            base_resume=self.base_resume,
            application_history=self.application_history,
            job_context={"company": "Stripe", "role": "Data Infrastructure Engineer"}
        )

        self.assertIsNotNone(captured_system_instruction)
        # Verify application history is present in system instructions
        self.assertIn("CANDIDATE APPLICATION HISTORY", captured_system_instruction)
        self.assertIn("Snowflake", captured_system_instruction)
        self.assertIn("Staff Platform Engineer", captured_system_instruction)
        self.assertIn("Databricks", captured_system_instruction)
        self.assertIn("Solutions Architect", captured_system_instruction)
        self.assertIn("Scaled DynamoDB and Spark pipelines", captured_system_instruction)
        self.assertIn("I've reviewed your Snowflake application", res["reply"])

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_action_cover_letter_with_custom_instruction(self, mock_exec, mock_keys):
        def fake_execute(call_fn):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = (
                "I will draft your cover letter highlighting distributed streaming wins and cost reduction!\n\n"
                "[[ACTION:generate_cover_letter|instruction=Focus on distributed streaming and cut cloud costs by 30%]]"
            )
            mock_response.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_response
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Make a cover letter focusing on distributed streaming and cloud cost cuts.",
            base_resume=self.base_resume,
            job_context={"company": "Netflix", "role": "Senior Distributed Systems Engineer"}
        )

        self.assertIsNotNone(res.get("action"))
        self.assertEqual(res["action"]["type"], "generate_cover_letter")
        self.assertEqual(
            res["action"]["params"].get("instruction"),
            "Focus on distributed streaming and cut cloud costs by 30%"
        )
        self.assertNotIn("[[ACTION:", res["reply"])

    @patch("cover_letter_generator.execute_with_failover")
    def test_cover_letter_generator_prioritizes_custom_instruction(self, mock_exec):
        captured_prompt = None

        def fake_execute(call_fn):
            nonlocal captured_prompt
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = (
                "Dear Netflix Hiring Team,\n\n"
                "I built massive streaming architectures handling 10M daily events at Amazon. "
                "My experience with Kafka and AWS scaling directly addresses Netflix's real-time streaming needs.\n\n"
                "Sincerely,\nAlex Mercer"
            )

            def fake_generate_content(model, contents, config):
                nonlocal captured_prompt
                # inspect contents parts
                captured_prompt = contents[0].parts[0].text
                return mock_response

            mock_client.models.generate_content.side_effect = fake_generate_content
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        custom_cmd = "Keep intro to one sentence, emphasize Kafka scaling and AWS cost reduction."
        res = generate_cover_letter(
            base_resume=self.base_resume,
            jd_text="Netflix seeks Senior Distributed Systems Engineer to scale Kafka clusters.",
            company="Netflix",
            role="Senior Distributed Systems Engineer",
            custom_instruction=custom_cmd
        )

        self.assertIsNotNone(captured_prompt)
        self.assertIn("USER'S DIRECT COVER LETTER COMMAND (HIGHEST PRIORITY)", captured_prompt)
        self.assertIn(custom_cmd, captured_prompt)
        self.assertIn("Dear Netflix Hiring Team", res["cover_letter_text"])

    @patch("hollabuddy.get_all_gemini_keys", return_value=["test_gemini_key_123"])
    @patch("hollabuddy.execute_with_failover")
    def test_hollabuddy_open_editor_with_company_param(self, mock_exec, mock_keys):
        def fake_execute(call_fn):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = (
                "Opening the visual editor for your Beehiiv application right away! "
                "You can review and edit all your tailored bullets directly in the canvas.\n\n"
                "[[ACTION:open_editor|company=Beehiiv]]"
            )
            mock_response.candidates = [MagicMock(finish_reason="STOP")]
            mock_client.models.generate_content.return_value = mock_response
            return call_fn(mock_client)

        mock_exec.side_effect = fake_execute

        res = chat_with_hollabuddy(
            message="Open the visual editor for the job Beehiiv in history tab, i need to edit things in that resume.",
            base_resume=self.base_resume,
            application_history=[
                {"company": "Beehiiv", "role": "Senior Fullstack Engineer", "score_after": 89}
            ]
        )

        self.assertIsNotNone(res.get("action"))
        self.assertEqual(res["action"]["type"], "open_editor")
        self.assertEqual(res["action"]["params"].get("company"), "Beehiiv")
        self.assertNotIn("[[ACTION:", res["reply"])

    def test_target_role_cleans_placeholder_string(self):
        from resume_html import resume_json_to_html
        test_resume = {
            "name": "Alex Mercer",
            "target_role": "Target Role / Professional Title",
            "title": "Principal Data Engineer",
            "contact": {"email": "alex@example.com"},
            "summary": "Data engineer specializing in large-scale streaming systems.",
            "skills": ["Python", "Spark"],
            "experience": [
                {
                    "company": "Amazon",
                    "title": "Principal Data Engineer",
                    "bullets": ["Scaled systems."]
                }
            ]
        }
        rendered_html = resume_json_to_html(test_resume)
        # Verify that literal placeholder text is NOT rendered
        self.assertNotIn("Target Role / Professional Title", rendered_html)
        self.assertIn("Principal Data Engineer", rendered_html)


if __name__ == "__main__":
    unittest.main()
