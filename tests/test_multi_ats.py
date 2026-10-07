import unittest
import os
import sys
import json

# Ensure parent directory is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from platform_rules import (
    AtsProfile,
    get_profile,
    get_safe_mode_profile,
    get_all_platforms,
    _load_registry,
)
from ats_profiles import (
    ATSProfile,
    get_all_profiles,
    get_platform_options,
)
from ats_detector import (
    detect_ats_from_url,
    detect_ats_from_text,
    detect_ats,
)
import ats_learning
from human_voice_audit import audit_ats_compliance
from cover_letter_generator import generate_cover_letter
from app import app


class TestATSProfiles(unittest.TestCase):
    def test_all_expected_profiles_exist(self):
        registry = _load_registry()
        expected = [
            "workday", "greenhouse", "lever", "icims", "taleo",
            "successfactors", "ashby", "smartrecruiters", "workable",
            "bamboohr", "jobvite", "unknown"
        ]
        for key in expected:
            self.assertIn(key, registry, f"Missing platform profile: {key}")

    def test_profile_aliases_and_options(self):
        all_profs = get_all_profiles()
        self.assertIsInstance(all_profs, dict)
        opts = get_platform_options()
        self.assertIsInstance(opts, list)
        self.assertGreaterEqual(len(opts), 10)
        self.assertIs(ATSProfile, AtsProfile)

    def test_taleo_and_workday_strictness(self):
        taleo = get_profile("taleo")
        workday = get_profile("workday")
        self.assertEqual(taleo.format_tolerance, "strict")
        self.assertEqual(workday.format_tolerance, "strict")
        self.assertFalse(taleo.allows_tables)
        self.assertFalse(workday.allows_tables)
        self.assertEqual(taleo.keyword_density_ceiling, 0.015)
        self.assertEqual(workday.keyword_density_ceiling, 0.015)

    def test_greenhouse_and_ashby_matching_style(self):
        gh = get_profile("greenhouse")
        ashby = get_profile("ashby")
        self.assertEqual(gh.matching_style, "semantic")
        self.assertEqual(ashby.matching_style, "semantic")
        self.assertEqual(gh.format_tolerance, "moderate")
        self.assertEqual(ashby.format_tolerance, "lenient")

    def test_safe_mode_fallback_profile(self):
        safe = get_safe_mode_profile()
        self.assertEqual(safe.platform_id, "unknown")
        self.assertEqual(safe.format_tolerance, "strict")
        self.assertFalse(safe.allows_tables)
        self.assertEqual(safe.keyword_density_ceiling, 0.015)

    def test_profile_to_dict_and_from_dict(self):
        p = get_profile("workday")
        d = p.to_dict()
        self.assertEqual(d["platform_id"], "workday")
        recreated = AtsProfile.from_dict(d)
        self.assertEqual(recreated.platform_id, p.platform_id)
        self.assertEqual(recreated.display_name, p.display_name)


class TestATSDetector(unittest.TestCase):
    def test_detect_workday_url(self):
        url = "https://nvidia.wd5.myworkdayjobs.com/en-US/careers/job/12345"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "workday")
        self.assertGreaterEqual(conf, 0.95)

    def test_detect_greenhouse_url(self):
        url = "https://boards.greenhouse.io/airbnb/jobs/4012345"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "greenhouse")
        self.assertGreaterEqual(conf, 0.95)

    def test_detect_lever_url(self):
        url = "https://jobs.lever.co/stripe/abc-123"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "lever")
        self.assertGreaterEqual(conf, 0.95)

    def test_detect_taleo_url(self):
        url = "https://oracle.taleo.net/careersection/jobdetail.ftl?job=998877"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "taleo")
        self.assertGreaterEqual(conf, 0.95)

    def test_detect_icims_url(self):
        url = "https://careers-company.icims.com/jobs/1001/software-developer/job"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "icims")
        self.assertGreaterEqual(conf, 0.95)

    def test_detect_from_html_content(self):
        html = "<html><body>Apply online. <div id='lever-jobs-container'></div></body></html>"
        profile, conf, src, detected = detect_ats_from_url("https://company.com/careers", html_content=html)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "lever")
        self.assertEqual(src, "html_fingerprint")

    def test_detect_from_text_heuristics(self):
        sample_text = "Apply via Workday careers portal. System powered by Workday application system."
        profile, conf, src, detected = detect_ats_from_text(sample_text)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "workday")

    def test_detect_ats_helper_dict(self):
        res = detect_ats("https://jobs.ashbyhq.com/figma/12345")
        self.assertTrue(res["detected"])
        self.assertEqual(res["platform_id"], "ashby")
        self.assertIn("profile", res)
        self.assertIn("all_platforms", res)

    def test_detect_fallback_generic(self):
        url = "https://randomcompany1234567.com/about-us"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertFalse(detected)
        self.assertEqual(profile.platform_id, "unknown")
        self.assertEqual(src, "safe_mode_fallback")


class TestATSLearning(unittest.TestCase):
    def test_record_feedback_and_retrieval(self):
        test_domain = "custom-portal-enterprise-suite.org"
        ok = ats_learning.record_domain_ats(test_domain, "greenhouse", source="user_override", confidence=1.0)
        self.assertTrue(ok)

        entry = ats_learning.get_domain_ats(test_domain)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["platform_id"], "greenhouse")
        self.assertEqual(entry["source"], "user_override")

    def test_stats_retrieval(self):
        stats = ats_learning.get_learning_stats()
        self.assertIn("total_learned_domains", stats)
        self.assertIn("metrics", stats)


class TestATSComplianceAuditing(unittest.TestCase):
    def setUp(self):
        self.base_resume = {
            "name": "Jane Doe",
            "email": "jane.doe@example.com",
            "phone": "555-0199",
            "summary": "Software engineer with background in distributed backend systems.",
            "skills": ["Python", "FastAPI", "Docker", "PostgreSQL", "Kafka"],
            "experience": [
                {
                    "title": "Senior Software Engineer",
                    "company": "CloudTech",
                    "dates": "March 2021 – Present",
                    "bullets": [
                        "Architected scalable backend microservices using Python and FastAPI for high traffic APIs.",
                        "Optimized PostgreSQL query latency reducing database execution time across key services.",
                        "Containerized applications using Docker and deployed automated CI/CD pipelines.",
                        "Streamlined messaging topology using Kafka clusters handling asynchronous message delivery.",
                        "Maintained test suites with rigorous automated verification to ensure zero regression."
                    ]
                }
            ],
            "education": [
                {
                    "degree": "B.S. in Computer Science",
                    "school": "University of Technology",
                    "year": "2020"
                }
            ]
        }

    def test_compliant_resume_passes_audit(self):
        profile = get_profile("workday")
        res = audit_ats_compliance(
            self.base_resume,
            ats_profile=profile,
            jd_keywords=["Python", "FastAPI", "Docker"],
            jd_title="Senior Software Engineer"
        )
        self.assertTrue(res["passed"])
        self.assertGreaterEqual(res["score"], 80.0)
        self.assertEqual(res["platform"], "workday")

    def test_keyword_stuffing_violates_density_ceiling(self):
        stuffed_resume = dict(self.base_resume)
        stuffed_resume["experience"] = [
            {
                "title": "Senior Python Engineer",
                "company": "Tech Corp",
                "dates": "January 2021 - Present",
                "bullets": [
                    "Python Python Python Python Python Python Python Python.",
                    "Python Python Python Python Python Python Python Python.",
                    "Python Python Python Python Python Python Python Python."
                ]
            }
        ]
        profile = get_profile("taleo")  # 1.5% ceiling
        res = audit_ats_compliance(
            stuffed_resume,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Senior Python Engineer"
        )
        self.assertFalse(res["passed"])
        self.assertFalse(res["gate_results"]["gate_1_density"]["passed"])
        self.assertIn("exceeds Taleo (Oracle)'s ceiling", res["findings"][0])

    def test_tables_flagged_on_strict_platforms(self):
        resume_with_table = dict(self.base_resume)
        resume_with_table["_has_tables"] = True
        profile = get_profile("taleo")
        res = audit_ats_compliance(
            resume_with_table,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Senior Software Engineer"
        )
        self.assertFalse(res["passed"])
        self.assertFalse(res["gate_results"]["gate_2_parse_safety"]["passed"])
        self.assertTrue(any("Tables detected" in f for f in res["findings"]))

    def test_date_formatting_check_for_taleo(self):
        # Taleo requires full month names (e.g. 'March 2021', not '03/2021')
        resume_short_dates = dict(self.base_resume)
        resume_short_dates["experience"] = [
            {
                "title": "Senior Software Engineer",
                "company": "CloudTech",
                "dates": "03/2021 – 11/2023",
                "bullets": ["Developed APIs using Python."]
            }
        ]
        profile = get_profile("taleo")
        res = audit_ats_compliance(
            resume_short_dates,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Senior Software Engineer"
        )
        self.assertFalse(res["gate_results"]["gate_4_platform_quirks"]["passed"])
        self.assertTrue(any("numeric MM/YYYY" in f for f in res["findings"]))


class TestAppEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_get_profiles_endpoint(self):
        resp = self.client.get("/api/ats-profiles")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertGreaterEqual(len(data["profiles"]), 10)

    def test_detect_endpoint(self):
        resp = self.client.post("/api/ats/detect", json={"url": "https://boards.greenhouse.io/datadog/jobs/123"})
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertTrue(data["detected"])
        self.assertEqual(data["profile"]["platform_id"], "greenhouse")

    def test_audit_endpoint(self):
        resp = self.client.post("/api/ats/audit", json={
            "resume": {
                "name": "Alex Smith",
                "skills": ["Python", "FastAPI"],
                "experience": [{
                    "title": "Backend Engineer",
                    "company": "SaaS Co",
                    "dates": "2021 – Present",
                    "bullets": ["Engineered high performance backend systems in Python."]
                }]
            },
            "platform_id": "greenhouse",
            "jd_keywords": ["Python"],
            "jd_title": "Backend Engineer"
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertIn("score", data["audit"])

    def test_feedback_endpoint(self):
        resp = self.client.post("/api/ats/feedback", json={
            "url": "https://newco-suite.careers/job/5",
            "platform_id": "workday",
            "confirmed": True
        })
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])

    def test_stats_endpoint(self):
        resp = self.client.get("/api/ats-stats")
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.data)
        self.assertTrue(data["success"])
        self.assertIn("stats", data)


class TestSection7AcceptanceCriteria(unittest.TestCase):
    """
    Direct coverage for all 6 non-negotiable acceptance criteria from
    'Multi-ATS Detection & Platform-Aware Resume Engine — Spec.md' §7.
    """

    def setUp(self):
        self.clean_resume = {
            "name": "Jordan Taylor",
            "email": "jordan.taylor@example.com",
            "phone": "555-0188",
            "summary": "Distributed systems engineer specialized in high-throughput data processing and microservice architecture.",
            "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Kafka", "Redis"],
            "experience": [
                {
                    "title": "Senior Backend Engineer",
                    "company": "DataStream Inc",
                    "dates": "January 2021 – Present",
                    "bullets": [
                        "Architected event-driven microservices using Python and FastAPI handling 15,000 requests per second.",
                        "Optimized PostgreSQL query plans and connection pooling reducing API latency by 42%.",
                        "Designed Dockerized staging and production pipelines with continuous deployment.",
                        "Integrated Kafka message brokers for reliable asynchronous stream processing.",
                        "Mentored junior engineers and conducted peer code reviews maintaining 95% test coverage."
                    ]
                }
            ],
            "education": [
                {
                    "degree": "B.S. in Computer Science",
                    "school": "State University",
                    "year": "2020"
                }
            ]
        }

    def test_criterion_1_workday_title_mismatch(self):
        """
        Criterion 1: Given a Workday URL and a resume where the candidate's actual title
        doesn't match the JD title with no equivalence noted → Auditor flags title mismatch.
        """
        url = "https://acme.myworkdayjobs.com/en-US/careers/job/staff-cloud-architect"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "workday")
        self.assertEqual(profile.title_weight, "high")

        # Resume has 'Senior Backend Engineer', target role is 'Staff Cloud Architect'
        res_mismatch = audit_ats_compliance(
            self.clean_resume,
            ats_profile=profile,
            jd_keywords=["Python", "Cloud"],
            jd_title="Staff Cloud Architect"
        )
        self.assertFalse(res_mismatch["passed"])
        self.assertFalse(res_mismatch["gate_results"]["gate_3_title_match"]["passed"])
        self.assertTrue(any("does not match target role 'Staff Cloud Architect' on Workday" in f for f in res_mismatch["findings"]))

        # Truthful parenthetical equivalence noted → passes Gate 3
        equiv_resume = dict(self.clean_resume)
        equiv_resume["experience"] = [
            {
                "title": "Senior Backend Engineer (Staff Cloud Architect equivalent)",
                "company": "DataStream Inc",
                "dates": "January 2021 – Present",
                "bullets": ["Architected distributed cloud systems using Python and FastAPI."]
            }
        ]
        res_equiv = audit_ats_compliance(
            equiv_resume,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Staff Cloud Architect"
        )
        self.assertTrue(res_equiv["gate_results"]["gate_3_title_match"]["passed"])

    def test_criterion_2_taleo_table_refusal_and_loud_parse_fail(self):
        """
        Criterion 2: Given a Taleo URL and a resume containing a table → Editor refuses
        to export until the table is removed; Auditor's parse-safety check fails loudly, not silently.
        """
        url = "https://oracle.taleo.net/careersection/jobdetail.ftl?job=99001"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "taleo")
        self.assertFalse(profile.allows_tables)

        resume_with_table = dict(self.clean_resume)
        resume_with_table["_has_tables"] = True

        # Part A: Auditor parse-safety check fails loudly
        audit_res = audit_ats_compliance(
            resume_with_table,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Senior Backend Engineer"
        )
        self.assertFalse(audit_res["passed"])
        self.assertFalse(audit_res["gate_results"]["gate_2_parse_safety"]["passed"])
        self.assertTrue(any("Tables detected in resume structure" in f for f in audit_res["findings"]))

        # Part B: Editor refuses export when allows_tables is false
        from docx_patcher import patch_docx_with_rewritten_resume
        original_master = os.path.join(os.path.dirname(__file__), "..", "master_resume_original.docx")
        if os.path.exists(original_master):
            with self.assertRaises(ValueError) as ctx:
                patch_docx_with_rewritten_resume(
                    original_docx_path=original_master,
                    rewritten_resume=resume_with_table,
                    company="OracleTaleoCorp",
                    role="SoftwareEngineer",
                    output_dir=os.path.join(os.path.dirname(__file__), "..", "output"),
                    ats_profile=profile,
                )
            self.assertIn("Tables are strictly prohibited", str(ctx.exception))

    def test_criterion_3_greenhouse_cover_letter_generated(self):
        """
        Criterion 3: Given a Greenhouse application with no cover letter → Writer generates
        one before the Auditor runs (since Greenhouse scores it).
        """
        url = "https://boards.greenhouse.io/stripe/jobs/12345"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertTrue(detected)
        self.assertEqual(profile.platform_id, "greenhouse")
        self.assertTrue(profile.cover_letter_scored)

        # Generate cover letter using cover_letter_generator with Greenhouse profile
        from unittest.mock import patch
        from cover_letter_generator import generate_cover_letter
        mock_cl_text = (
            "Dear Stripe Hiring Team,\n\n"
            "I am applying for the Infrastructure Engineer role at Stripe. With proven experience "
            "scaling distributed systems using Python and event-driven architecture, my background directly "
            "addresses Stripe's high-reliability infrastructure needs.\n\nSincerely,\nJordan Taylor"
        )
        with patch("cover_letter_generator.execute_with_failover", return_value=mock_cl_text):
            cl_res = generate_cover_letter(
                base_resume=self.clean_resume,
                jd_text="Seeking an Infrastructure Engineer with strong Python and distributed systems experience at Stripe.",
                company="Stripe",
                role="Infrastructure Engineer",
                missing_keywords=["Python", "Distributed Systems"],
                ats_profile=profile
            )
            self.assertIn("text", cl_res)
            self.assertGreater(len(cl_res["text"]), 50)
            self.assertIn("Stripe", cl_res["text"])

    def test_criterion_4_unrecognized_custom_domain_safe_mode(self):
        """
        Criterion 4: Given an unrecognized custom domain → ats_profile.detected == false,
        Safe Mode values applied, and the resume still exports successfully with the 1.5% density ceiling enforced.
        """
        url = "https://whitelabel-custom-career-portal.internal.net/job/442"
        profile, conf, src, detected = detect_ats_from_url(url)
        self.assertFalse(detected)
        self.assertEqual(profile.platform_id, "unknown")
        self.assertEqual(src, "safe_mode_fallback")
        self.assertEqual(profile.keyword_density_ceiling, 0.015)
        self.assertFalse(profile.allows_tables)

        # Compliant resume under 1.5% ceiling passes audit and Gate 1 density check
        audit_res = audit_ats_compliance(
            self.clean_resume,
            ats_profile=profile,
            jd_keywords=["Python"],
            jd_title="Senior Backend Engineer"
        )
        self.assertTrue(audit_res["passed"])
        self.assertTrue(audit_res["gate_results"]["gate_1_density"]["passed"])

        from docx_patcher import patch_docx_with_rewritten_resume
        original_master = os.path.join(os.path.dirname(__file__), "..", "master_resume_original.docx")
        if os.path.exists(original_master):
            out_file = patch_docx_with_rewritten_resume(
                original_docx_path=original_master,
                rewritten_resume=self.clean_resume,
                company="UnknownCo",
                role="Engineer",
                output_dir=os.path.join(os.path.dirname(__file__), "..", "output"),
                ats_profile=profile
            )
            self.assertTrue(os.path.exists(out_file))

    def test_criterion_5_keyword_density_revised_down(self):
        """
        Criterion 5: Given a JD keyword count that would push density to 5% if inserted
        at the Writer's default rate → Auditor catches it pre-export and the Writer's output
        is revised down, not just flagged after the fact.
        """
        profile = get_profile("workday")  # 1.5% density ceiling
        # Stuffed resume with 10 mentions of Kafka in ~160 words -> ~6.25% density (> 5%)
        stuffed_resume = dict(self.clean_resume)
        stuffed_resume["summary"] = (
            "Senior Backend and Distributed Systems Engineer with eight years of experience building, deploying, "
            "and scaling event-driven microservices, high-volume transactional databases, and resilient data processing pipelines."
        )
        stuffed_resume["experience"] = [
            {
                "title": "Senior Backend Engineer",
                "company": "DataStream Inc",
                "dates": "January 2021 – Present",
                "bullets": [
                    "Architected high-throughput message streaming systems using Kafka Kafka Kafka stream processing with Kafka clusters.",
                    "Deployed and configured distributed Kafka consumer groups and configured reliable Kafka brokers for zero message drop.",
                    "Maintained fault-tolerant Kafka topologies with Kafka mirrors across active Kafka partitions and clusters.",
                    "Optimized PostgreSQL database performance, reducing execution latency across production query workloads by 35%.",
                    "Containerized internal microservices using Docker and orchestrated end-to-end integration test suites across CI/CD.",
                    "Collaborated with security teams to implement robust role-based access control and TLS transport encryption."
                ]
            }
        ]

        # Auditor catches it
        pre_audit = audit_ats_compliance(
            stuffed_resume,
            ats_profile=profile,
            jd_keywords=["Kafka"],
            jd_title="Senior Backend Engineer"
        )
        self.assertFalse(pre_audit["passed"])
        self.assertFalse(pre_audit["gate_results"]["gate_1_density"]["passed"])
        self.assertGreater(pre_audit["max_density_found"], 0.05)

        # Editor revises output down below ceiling
        from danis_engine import reduce_keyword_density_to_ceiling, run_editor_phase
        revised = reduce_keyword_density_to_ceiling(stuffed_resume, ats_profile=profile, jd_keywords=["Kafka"])
        post_audit = audit_ats_compliance(
            revised,
            ats_profile=profile,
            jd_keywords=["Kafka"],
            jd_title="Senior Backend Engineer"
        )
        self.assertTrue(post_audit["gate_results"]["gate_1_density"]["passed"])
        self.assertLessEqual(post_audit["max_density_found"], profile.keyword_density_ceiling)

    def test_criterion_6_taleo_screening_question_score_risk(self):
        """
        Criterion 6: Given a Taleo screening question answered 'weak but not disqualifying'
        → system logs this as a score risk (not just a pass), distinct from how a
        Newton-style binary knockout is logged.
        """
        from human_voice_audit import audit_knockout_screening_questions

        taleo_profile = get_profile("taleo")
        newton_profile = get_profile("greenhouse")

        screening_questions = [
            {
                "question": "Are you legally authorized to work in the United States?",
                "answer": "Yes",
                "required_answer": "Yes",
                "is_knockout": True,
            },
            {
                "question": "How many years of enterprise Oracle DB experience do you have?",
                "answer": "1 year",
                "required_answer": "3+ years preferred",
                "is_knockout": False,
                "is_weak": True,
                "answer_quality": "weak_but_not_disqualifying",
            }
        ]

        # On Taleo: weak answer is logged as score_risk
        taleo_res = audit_knockout_screening_questions(screening_questions, ats_profile=taleo_profile)
        self.assertFalse(taleo_res["disqualified"])  # NOT a binary knockout
        self.assertTrue(taleo_res["has_score_risks"])
        self.assertEqual(len(taleo_res["score_risks"]), 1)
        self.assertEqual(taleo_res["score_risks"][0]["status"], "score_risk")
        self.assertIn("composite ranking risk", taleo_res["score_risks"][0]["message"])

        # Compare with a binary knockout disqualification
        knockout_questions = [
            {
                "question": "Do you hold an active Top Secret clearance?",
                "answer": "No",
                "required_answer": "Yes",
                "is_knockout": True,
            }
        ]
        ko_res = audit_knockout_screening_questions(knockout_questions, ats_profile=newton_profile)
        self.assertTrue(ko_res["disqualified"])
        self.assertEqual(ko_res["results"][0]["status"], "knockout_disqualification")

    def test_workday_and_ashby_detection_urls_and_prose(self):
        from ats_detector import detect_ats, detect_ats_from_url, detect_ats_from_text

        # 1. Workday URLs
        wd1 = detect_ats("https://target.myworkdayjobs.com/en-US/careers/job/Engineer_123")
        self.assertTrue(wd1["detected"])
        self.assertEqual(wd1["platform_id"], "workday")

        wd2 = detect_ats("https://nvidia.wd5.myworkdayjobs.com/job/123")
        self.assertTrue(wd2["detected"])
        self.assertEqual(wd2["platform_id"], "workday")

        # 2. Ashby URLs
        ash1 = detect_ats("https://jobs.ashbyhq.com/openai/1234-abcd")
        self.assertTrue(ash1["detected"])
        self.assertEqual(ash1["platform_id"], "ashby")

        ash2 = detect_ats("https://ashbyhq.com/acme/job/789")
        self.assertTrue(ash2["detected"])
        self.assertEqual(ash2["platform_id"], "ashby")

        # 3. Pasted prose text with ATS mentions
        wd_text = detect_ats("We are looking for a Senior Engineer. Powered by Workday. Apply online.")
        self.assertTrue(wd_text["detected"])
        self.assertEqual(wd_text["platform_id"], "workday")

        ash_text = detect_ats("Join our hypergrowth AI team. Submit your application via Ashby portal today.")
        self.assertTrue(ash_text["detected"])
        self.assertEqual(ash_text["platform_id"], "ashby")

        # 4. HTTP API endpoint /api/ats-detect
        client = app.test_client()
        r_wd = client.post("/api/ats-detect", json={"url": "https://company.myworkdayjobs.com/job/1"})
        self.assertEqual(r_wd.status_code, 200)
        self.assertEqual(r_wd.get_json()["platform_id"], "workday")

        r_ash = client.post("/api/ats-detect", json={"url": "https://jobs.ashbyhq.com/company/1"})
        self.assertEqual(r_ash.status_code, 200)
        self.assertEqual(r_ash.get_json()["platform_id"], "ashby")


if __name__ == "__main__":
    unittest.main()


