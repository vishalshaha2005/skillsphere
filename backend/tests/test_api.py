import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from backend import main
from backend.email_service import send_interview_email, send_notification_email


class SkillSphereApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.proctoring_config = patch.dict("os.environ", {"SKILLSPHERE_PROCTORING_REQUIRED": "true"})
        self.proctoring_config.start()
        data_dir = Path(self.temp_dir.name)
        main.DATA_DIR = data_dir
        main.UPLOAD_DIR = data_dir / "uploads"
        main.DB_PATH = data_dir / "test.sqlite3"
        main.initialize_database()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        self.proctoring_config.stop()
        self.temp_dir.cleanup()

    def login(self, email="candidate@skillsphere.dev", password="Demo123!"):
        response = self.client.post("/api/auth/login", json={"email": email, "password": password})
        self.assertEqual(response.status_code, 200, response.text)
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def test_login_sets_secure_cookie_and_requires_csrf_for_cookie_auth(self):
        login = self.client.post("/api/auth/login", json={"email": "candidate@skillsphere.dev", "password": "Demo123!"})
        self.assertEqual(login.status_code, 200, login.text)
        token = login.json()["access_token"]
        cookie_session = self.client.post("/api/auth/session", json={"access_token": token})
        self.assertEqual(cookie_session.status_code, 200, cookie_session.text)
        set_cookie = cookie_session.headers.get("set-cookie", "")
        self.assertIn("skillsphere_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Lax", set_cookie)
        csrf_value = cookie_session.cookies.get("skillsphere_csrf")
        self.assertTrue(csrf_value)

        unauthorized = self.client.post("/api/auth/logout", cookies={"skillsphere_session": cookie_session.cookies["skillsphere_session"]})
        self.assertEqual(unauthorized.status_code, 403)

        authorized = self.client.post(
            "/api/auth/logout",
            cookies={"skillsphere_session": cookie_session.cookies["skillsphere_session"], "skillsphere_csrf": csrf_value},
            headers={"X-CSRF-Token": csrf_value},
        )
        self.assertEqual(authorized.status_code, 200, authorized.text)

    def test_production_environment_requires_strong_secret(self):
        with patch.dict("os.environ", {"SKILLSPHERE_ENV": "production", "SKILLSPHERE_SECRET_KEY": "short"}):
            self.assertRaises(RuntimeError, main.validate_runtime_configuration)

    def create_application(self):
        candidate = self.login()
        job_id = self.client.get("/api/jobs", headers=candidate).json()["items"][0]["id"]
        with main.connect() as db:
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, parsed_profile_json, processing_status, uploaded_at)
                VALUES (1, 'resume.pdf', 'private.pdf', 'application/pdf', '{}', 'completed', '2026-01-01T00:00:00+00:00')"""
            )
        response = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate)
        self.assertEqual(response.status_code, 201, response.text)
        return candidate, response.json()

    def start_assessment(self, token):
        camera = self.client.post(
            f"/api/assessments/{token}/proctoring/start",
            json={"permission_granted": True},
        )
        self.assertEqual(camera.status_code, 200, camera.text)
        return self.client.post(f"/api/assessments/{token}/start")

    def create_assessment_application(
        self,
        required_skills,
        resume_text,
        resume_skills=None,
        seed_question_bank=True,
        seed_question_technologies=None,
    ):
        candidate = self.login()
        recruiter = self.login("recruiter@skillsphere.dev")
        job = self.client.post(
            "/api/jobs",
            headers=recruiter,
            json={
                "title": "Platform Engineer",
                "company": "Northstar",
                "description": "Build reliable services and work closely with product and engineering teams.",
                "location": "Remote",
                "experience": "3–5 years",
                "job_type": "Full-time",
                "salary": "$120k",
                "skills": required_skills,
            },
        )
        self.assertEqual(job.status_code, 201, job.text)
        job_id = job.json()["id"]
        detected_topic = main.detect_assessment_topic(required_skills, resume_text.lower())
        with main.connect() as db:
            candidate_id = db.execute(
                "SELECT id FROM users WHERE email = 'candidate@skillsphere.dev'"
            ).fetchone()["id"]
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, extracted_text,
                parsed_profile_json, processing_status, uploaded_at)
                VALUES (?, 'resume.pdf', 'private.pdf', 'application/pdf', ?, ?, 'completed', ?)""",
                (
                    candidate_id,
                    resume_text,
                    json.dumps({"skills": resume_skills or []}),
                    main.now(),
                ),
            )
            technologies = seed_question_technologies or (
                ([detected_topic] if detected_topic else list(main.QUESTION_BANKS))
                if seed_question_bank else []
            )
            for technology in technologies:
                db.executemany(
                    """INSERT INTO job_questions
                    (job_id, recruiter_id, technology, question, options_json, correct_index,
                    difficulty, active, created_at, updated_at)
                    VALUES (?, 2, ?, ?, ?, ?, ?, 1, ?, ?)""",
                    [
                        (
                            job_id,
                            technology,
                            question,
                            json.dumps(options),
                            correct_index,
                            difficulty,
                            main.now(),
                            main.now(),
                        )
                        for question, options, correct_index, difficulty in main.QUESTION_BANKS[technology]
                    ],
                )
        with patch.dict("os.environ", {
            "SKILLSPHERE_ENV": "development",
            "SKILLSPHERE_PUBLIC_BASE_URL": "http://testserver",
        }):
            with patch("backend.main.send_assessment_email", return_value="development_console") as email:
                application_response = self.client.post(
                    f"/api/jobs/{job_id}/apply", headers=candidate
                )
                application = application_response.json()
                if email.called:
                    application["_test_assessment_link"] = email.call_args.args[1]
        self.assertEqual(application_response.status_code, 201, application_response.text)
        return candidate, recruiter, application

    def make_text_pdf(self, text):
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }))
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        lines = []
        for line in text.splitlines():
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            lines.append(f"({escaped}) Tj T*")
        stream.set_data(("BT /F1 10 Tf 12 TL 50 750 Td " + " ".join(lines) + " ET").encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
        pdf = BytesIO()
        writer.write(pdf)
        return pdf.getvalue()

    def schedule_interview(self, application_id, recruiter=None):
        recruiter = recruiter or self.login("recruiter@skillsphere.dev")
        return self.client.post(
            "/api/interviews",
            headers=recruiter,
            json={
                "application_id": application_id,
                "starts_at": "2027-01-12T15:00:00+00:00",
                "teams_url": "https://teams.microsoft.com/l/meetup-join/example",
            },
        )

    def create_application_interview(self, application_id, recruiter=None, **overrides):
        recruiter = recruiter or self.login("recruiter@skillsphere.dev")
        scheduled_at = main.datetime.now(main.timezone.utc) + main.timedelta(days=3)
        payload = {
            "starts_at": scheduled_at.isoformat(),
            "timezone": "UTC",
            "duration_minutes": 45,
            "meeting_platform": "Google Meet",
            "meeting_url": "https://meet.google.com/abc-defg-hij",
            "recruiter_message": "Please bring your portfolio.",
        }
        payload.update(overrides)
        return self.client.post(
            f"/api/applications/{application_id}/interviews",
            headers=recruiter,
            json=payload,
        )

    def test_interview_schedule_is_visible_only_to_its_participants(self):
        candidate, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        scheduled = self.schedule_interview(application["id"], recruiter)
        self.assertEqual(scheduled.status_code, 201, scheduled.text)
        interview = scheduled.json()
        self.assertEqual(interview["candidate_name"], "Alex Morgan")
        self.assertEqual(interview["recruiter_name"], "Jamie Rivera")
        self.assertEqual(
            self.client.get("/api/applications", headers=candidate).json()["items"][0]["status"],
            "Interview",
        )

        self.assertEqual(len(self.client.get("/api/interviews", headers=candidate).json()["items"]), 1)
        self.assertEqual(len(self.client.get("/api/interviews", headers=recruiter).json()["items"]), 1)
        self.assertEqual(self.client.get(f"/api/interviews/{interview['id']}", headers=candidate).status_code, 200)

        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        self.assertEqual(self.client.get(f"/api/interviews/{interview['id']}", headers=other_headers).status_code, 404)
        self.assertEqual(self.client.get("/api/interviews", headers=self.login("admin@skillsphere.dev")).status_code, 200)

    def test_application_interview_schedule_notifies_candidate_and_updates_pipeline(self):
        candidate, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        meeting_url = "https://zoom.us/j/987654321"
        with patch("backend.main.send_interview_email", return_value="email") as email:
            response = self.create_application_interview(
                application["id"],
                recruiter,
                meeting_platform="Zoom",
                meeting_url=meeting_url,
            )
        self.assertEqual(response.status_code, 201, response.text)
        interview = response.json()
        self.assertEqual(interview["meeting_url"], meeting_url)
        self.assertEqual(interview["status"], "Scheduled")
        self.assertEqual(email.call_args.args[7], meeting_url)
        self.assertEqual(email.call_args.args[5], 45)

        application_response = self.client.get("/api/applications", headers=candidate)
        candidate_application = application_response.json()["items"][0]
        self.assertEqual(candidate_application["status"], "Interview")
        self.assertEqual(candidate_application["interview"]["meeting_url"], meeting_url)
        self.assertEqual(candidate_application["interview"]["meeting_platform"], "Zoom")
        self.assertTrue(any(event["status"] == "Interview" for event in candidate_application["status_history"]))
        notice = self.client.get("/api/notifications", headers=candidate).json()["items"][0]
        self.assertEqual(notice["title"], "Interview scheduled")
        self.assertEqual(notice["email_delivery_status"], "sent")

    def test_application_interview_permissions_and_candidate_link_isolation(self):
        candidate, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        scheduled = self.create_application_interview(application["id"], recruiter)
        self.assertEqual(scheduled.status_code, 201, scheduled.text)
        interview_id = scheduled.json()["id"]

        second_recruiter = self.client.post(
            "/api/auth/register",
            json={"name": "Second Recruiter", "email": "second-recruiter@example.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        unauthorized = {"Authorization": f"Bearer {second_recruiter['access_token']}"}
        self.assertEqual(
            self.create_application_interview(application["id"], unauthorized).status_code,
            404,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/applications/{application['id']}/interviews/{interview_id}",
                headers=unauthorized,
                json={"meeting_url": "https://zoom.us/j/new"},
            ).status_code,
            404,
        )

        other_candidate = self.client.post(
            "/api/auth/register",
            json={"name": "Other Candidate", "email": "other-candidate@example.com", "password": "LongEnough9!", "role": "candidate"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other_candidate['access_token']}"}
        job_id = application["job_id"]
        with main.connect() as db:
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, parsed_profile_json, processing_status, uploaded_at)
                VALUES (?, 'other.pdf', 'private-other.pdf', 'application/pdf', '{}', 'completed', ?)""",
                (other_candidate["user"]["id"], main.now()),
            )
        self.assertEqual(
            self.client.post(f"/api/jobs/{job_id}/apply", headers=other_headers).status_code,
            201,
        )
        other_applications = self.client.get("/api/applications", headers=other_headers).json()["items"]
        self.assertTrue(all(item.get("interview") is None for item in other_applications))
        self.assertEqual(self.client.get(f"/api/interviews/{interview_id}", headers=other_headers).status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/interviews/{interview_id}", headers=candidate).json()["meeting_url"],
            scheduled.json()["meeting_url"],
        )

    def test_reschedule_cancel_and_upcoming_interview_flow(self):
        candidate, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        scheduled = self.create_application_interview(application["id"], recruiter)
        self.assertEqual(scheduled.status_code, 201, scheduled.text)
        interview_id = scheduled.json()["id"]
        next_time = main.datetime.now(main.timezone.utc) + main.timedelta(days=5)
        rescheduled = self.client.patch(
            f"/api/applications/{application['id']}/interviews/{interview_id}",
            headers=recruiter,
            json={
                "starts_at": next_time.isoformat(),
                "duration_minutes": 90,
                "meeting_url": "https://meet.google.com/new-link",
            },
        )
        self.assertEqual(rescheduled.status_code, 200, rescheduled.text)
        self.assertEqual(rescheduled.json()["status"], "Rescheduled")
        self.assertEqual(rescheduled.json()["duration_minutes"], 90)
        self.assertEqual(len(self.client.get("/api/interviews/upcoming", headers=candidate).json()["items"]), 1)
        notifications = self.client.get("/api/notifications", headers=candidate).json()["items"]
        self.assertIn("Interview rescheduled", [notice["title"] for notice in notifications])

        with main.connect() as db:
            db.execute(
                "UPDATE interviews SET starts_at = ? WHERE id = ?",
                ((main.datetime.now(main.timezone.utc) - main.timedelta(days=2)).isoformat(), interview_id),
            )
        self.assertEqual(self.client.get("/api/interviews/upcoming", headers=candidate).json()["items"], [])
        cancelled = self.client.post(
            f"/api/applications/{application['id']}/interviews/{interview_id}/cancel",
            headers=recruiter,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "Cancelled")
        own_application = self.client.get("/api/applications", headers=candidate).json()["items"][0]
        self.assertEqual(own_application["interview"]["status"], "Cancelled")
        self.assertEqual(own_application["interview"]["meeting_url"], "")
        self.assertEqual(
            self.client.get("/api/notifications", headers=candidate).json()["items"][0]["title"],
            "Interview cancelled",
        )

    def test_application_interview_rejects_non_https_and_past_schedule(self):
        _, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        future = (main.datetime.now(main.timezone.utc) + main.timedelta(days=2)).isoformat()
        self.assertEqual(
            self.create_application_interview(application["id"], recruiter, meeting_url="http://zoom.us/j/123").status_code,
            422,
        )
        past = (main.datetime.now(main.timezone.utc) - main.timedelta(days=1)).isoformat()
        self.assertEqual(
            self.create_application_interview(application["id"], recruiter, starts_at=past).status_code,
            422,
        )

    def test_interview_rejects_non_teams_links_and_naive_times(self):
        _, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        payload = {
            "application_id": application["id"],
            "starts_at": "2027-01-12T15:00:00+00:00",
            "teams_url": "https://example.com/meet",
        }
        self.assertEqual(self.client.post("/api/interviews", headers=recruiter, json=payload).status_code, 422)
        payload["teams_url"] = "https://teams.microsoft.com/l/meetup-join/example"
        payload["starts_at"] = "2027-01-12T15:00:00"
        self.assertEqual(self.client.post("/api/interviews", headers=recruiter, json=payload).status_code, 422)

    def test_interview_code_socket_persists_shared_edits(self):
        _, application = self.create_application()
        interview = self.schedule_interview(application["id"]).json()
        recruiter_token = self.login("recruiter@skillsphere.dev")["Authorization"].removeprefix("Bearer ")
        socket_path = f"/api/interviews/{interview['id']}/code"
        with self.client.websocket_connect(socket_path) as interviewer:
            interviewer.send_json({"type": "auth", "token": recruiter_token})
            self.assertEqual(interviewer.receive_json(), {"type": "snapshot", "code": "", "language": "python"})
            interviewer.send_json({"type": "code", "code": "print('hello')"})
            interviewer.send_json({"type": "language", "language": "javascript"})
        candidate_token = self.login()["Authorization"].removeprefix("Bearer ")
        with self.client.websocket_connect(socket_path) as candidate:
            candidate.send_json({"type": "auth", "token": candidate_token})
            self.assertEqual(candidate.receive_json(), {
                "type": "snapshot", "code": "print('hello')", "language": "javascript",
            })
        with main.connect() as db:
            saved = db.execute("SELECT code, language FROM interviews WHERE id = ?", (interview["id"],)).fetchone()
        self.assertEqual((saved["code"], saved["language"]), ("print('hello')", "javascript"))

    def test_code_run_requires_a_configured_isolated_runner(self):
        candidate, application = self.create_application()
        interview = self.schedule_interview(application["id"]).json()
        with patch.dict("os.environ", {"SKILLSPHERE_JUDGE0_URL": ""}):
            response = self.client.post(
                f"/api/interviews/{interview['id']}/run",
                headers=candidate,
                json={"language": "python", "code": "print('hello')"},
            )
        self.assertEqual(response.status_code, 503)

    def test_code_run_uses_the_configured_isolated_runner(self):
        candidate, application = self.create_application()
        interview = self.schedule_interview(application["id"]).json()

        class FakeRunner:
            request = None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_):
                return None

            async def post(self, url, **kwargs):
                self.request = (url, kwargs)
                return httpx.Response(200, json={
                    "stdout": "hello\n",
                    "status": {"description": "Accepted"},
                    "time": "0.01",
                    "memory": 1024,
                })

        runner = FakeRunner()
        with patch.dict("os.environ", {
            "SKILLSPHERE_JUDGE0_URL": "http://judge0.internal",
            "SKILLSPHERE_JUDGE0_TOKEN": "runner-test-token",
        }), patch("httpx.AsyncClient", return_value=runner):
            response = self.client.post(
                f"/api/interviews/{interview['id']}/run",
                headers=candidate,
                json={"language": "python", "code": "print('hello')", "stdin": "input"},
            )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["stdout"], "hello\n")
        self.assertEqual(runner.request[0], "http://judge0.internal/submissions?base64_encoded=false&wait=true")
        self.assertEqual(runner.request[1]["headers"]["X-Auth-Token"], "runner-test-token")
        self.assertEqual(runner.request[1]["json"]["language_id"], main.CODE_LANGUAGES["python"])
        self.assertEqual(runner.request[1]["json"]["stdin"], "input")

    def test_seeded_accounts_authenticate_without_exposing_password_hash(self):
        headers = self.login()
        response = self.client.get("/api/me", headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["role"], "candidate")
        self.assertNotIn("password_hash", response.json())
        self.assertEqual(self.client.get("/api/me").status_code, 401)

    def test_registration_rejects_duplicate_email_and_admin_role(self):
        payload = {"name": "New Member", "email": "new@example.com", "password": "LongEnough9!", "role": "candidate"}
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 409)
        payload["email"] = "other@example.com"
        payload["role"] = "admin"
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 422)

    def test_jobs_can_be_filtered_and_recruiter_can_only_see_own(self):
        candidate = self.login()
        response = self.client.get(
            "/api/jobs?q=designer&location=New%20York&experience=years&skill=Figma",
            headers=candidate,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["items"]), 1)
        self.assertEqual(response.json()["items"][0]["title"], "Product Designer")
        self.assertEqual(self.client.get("/api/jobs?mine=true", headers=candidate).status_code, 403)
        self.assertEqual(self.client.get("/api/jobs?sort_by=salary", headers=candidate).status_code, 422)
        recruiter = self.login("recruiter@skillsphere.dev")
        own_jobs = self.client.get("/api/jobs?mine=true", headers=recruiter)
        self.assertEqual(own_jobs.status_code, 200)
        self.assertTrue(all(job["recruiter_id"] == 2 for job in own_jobs.json()["items"]))

    def test_candidate_cannot_apply_without_resume_or_submit_duplicate(self):
        candidate = self.login()
        job_id = self.client.get("/api/jobs", headers=candidate).json()["items"][0]["id"]
        response = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate)
        self.assertEqual(response.status_code, 409)

        with main.connect() as db:
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, parsed_profile_json, processing_status, uploaded_at)
                VALUES (1, 'resume.pdf', 'private.pdf', 'application/pdf', '{}', 'completed', '2026-01-01T00:00:00+00:00')"""
            )
        self.assertEqual(self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate).status_code, 201)
        duplicate = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate)
        self.assertEqual(duplicate.status_code, 409)

    def test_recruiter_cannot_update_an_application_for_another_team(self):
        candidate = self.login()
        second_recruiter = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        )
        self.assertEqual(second_recruiter.status_code, 201)
        other_headers = {"Authorization": f"Bearer {second_recruiter.json()['access_token']}"}
        posted_job = self.client.post(
            "/api/jobs",
            headers=other_headers,
            json={
                "title": "Community Manager", "company": "Other Team",
                "description": "Help our team build a welcoming community for our customers.",
                "location": "Remote", "experience": "2–4 years", "job_type": "Full-time",
                "salary": "$75k", "skills": ["Communication", "Community"],
            },
        )
        self.assertEqual(posted_job.status_code, 201, posted_job.text)
        job_id = posted_job.json()["id"]
        resume_path = main.UPLOAD_DIR / "candidate-resume.pdf"
        resume_path.write_bytes(b"%PDF-1.7\nsample")
        with main.connect() as db:
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, parsed_profile_json, processing_status, uploaded_at)
                VALUES (1, 'resume.pdf', ?, 'application/pdf', '{}', 'completed', '2026-01-01T00:00:00+00:00')""",
                (str(resume_path),),
            )
        application = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate).json()
        recruiter = self.login("recruiter@skillsphere.dev")
        changed = self.client.patch(
            f"/api/applications/{application['id']}/status",
            headers=recruiter,
            json={"status": "Shortlisted"},
        )
        self.assertEqual(changed.status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/applications/{application['id']}/resume", headers=recruiter).status_code,
            404,
        )
        changed = self.client.patch(
            f"/api/applications/{application['id']}/status",
            headers=other_headers,
            json={"status": "Shortlisted"},
        )
        self.assertEqual(changed.status_code, 409)
        changed = self.client.patch(
            f"/api/applications/{application['id']}/status",
            headers=other_headers,
            json={"status": "Under Review"},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(changed.json()["status"], "Under Review")
        resume_response = self.client.get(f"/api/applications/{application['id']}/resume", headers=other_headers)
        self.assertEqual(resume_response.status_code, 200)
        self.assertEqual(resume_response.content, b"%PDF-1.7\nsample")
        invalid = self.client.patch(
            f"/api/applications/{application['id']}/status",
            headers=other_headers,
            json={"status": "Make offer"},
        )
        self.assertEqual(invalid.status_code, 422)

    def test_exact_70_percent_match_auto_shortlists_and_creates_private_20_question_test(self):
        required = ["Python", "SQL", "FastAPI", "Docker", "AWS", "CSS", "HTML", "JavaScript", "React", "Java"]
        candidate, recruiter, application = self.create_assessment_application(
            required, "Python SQL FastAPI Docker AWS CSS HTML", ["Python", "SQL", "FastAPI"]
        )
        self.assertEqual(application["match_percentage"], 70)
        self.assertEqual(application["status"], "Assessment Sent")
        self.assertEqual(application["assessment_status"], "Sent")
        self.assertEqual(application["assessment_topic"], "Python")
        self.assertNotIn("assessment_url", application)

        with main.connect() as db:
            stored = db.execute(
                "SELECT * FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()
            self.assertEqual(stored["match_percentage"], 70)
            self.assertEqual(stored["status"], "Sent")
            raw_token = application["_test_assessment_link"].split("token=")[1]
            self.assertEqual(stored["token_hash"], hashlib.sha256(raw_token.encode()).hexdigest())
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) FROM assessment_questions WHERE assessment_id = ?", (stored["id"],)
                ).fetchone()[0],
                20,
            )

        token = application["_test_assessment_link"].split("token=")[1]
        self.assertEqual(self.client.get("/assessment").status_code, 200)
        assessment = self.client.get(f"/api/assessments/{token}")
        self.assertEqual(assessment.status_code, 200, assessment.text)
        self.assertEqual(assessment.json()["questions"], [])
        started = self.start_assessment(token)
        self.assertEqual(started.status_code, 200, started.text)
        questions = started.json()["questions"]
        self.assertEqual(len(questions), 20)
        self.assertTrue(all(len(item["options"]) == 4 for item in questions))
        self.assertTrue(all("correct_index" not in item and "answer" not in item for item in questions))
        self.assertTrue(all("topic" not in item and "difficulty" not in item for item in questions))

        with main.connect() as db:
            answer_key = [
                row["correct_index"]
                for row in db.execute(
                    "SELECT correct_index FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order",
                    (stored["id"],),
                )
            ]
        submitted = self.client.post(f"/api/assessments/{token}/submit", json={"answers": answer_key})
        self.assertEqual(submitted.status_code, 200, submitted.text)
        self.assertEqual(submitted.json()["score"], 100)
        self.assertEqual(self.client.post(f"/api/assessments/{token}/submit", json={"answers": answer_key}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/assessments/{token}").status_code, 404)
        recruiter_applications = self.client.get("/api/applications", headers=recruiter).json()["items"]
        recruited = next(item for item in recruiter_applications if item["id"] == application["id"])
        self.assertEqual(recruited["assessment_score"], 100)
        self.assertIsNotNone(recruited["assessment_submitted_at"])
        self.assertNotIn("token_hash", recruited)

    def test_proctoring_gates_start_tracks_warnings_and_scopes_review_data(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"]
        )
        token = application["_test_assessment_link"].split("token=")[1]
        before_start = self.client.get(f"/api/assessments/{token}")
        self.assertEqual(before_start.status_code, 200)
        self.assertEqual(before_start.json()["questions"], [])
        self.assertEqual(
            self.client.post(f"/api/assessments/{token}/start").status_code,
            409,
        )
        denied = self.client.post(
            f"/api/assessments/{token}/proctoring/start",
            json={"permission_granted": False},
        )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(
            self.client.post(
                f"/api/assessments/{'x' * 40}/proctoring/events",
                json={"event_type": "tab_hidden"},
            ).status_code,
            404,
        )

        with patch.dict("os.environ", {
            "SKILLSPHERE_MAX_PROCTORING_WARNINGS": "3",
            "SKILLSPHERE_FACE_MISSING_WARNING_SECONDS": "10",
            "SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS": "false",
        }):
            camera = self.client.post(
                f"/api/assessments/{token}/proctoring/start",
                json={"permission_granted": True},
            )
            self.assertEqual(camera.status_code, 200, camera.text)
            self.assertEqual(camera.json()["max_warnings"], 3)
            started = self.client.post(f"/api/assessments/{token}/start")
            self.assertEqual(started.status_code, 200, started.text)

            short_face_gap = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "face_not_detected", "duration_seconds": 4},
            )
            self.assertEqual(short_face_gap.json()["warning_count"], 0)
            self.assertEqual(short_face_gap.json()["flagged_for_review"], False)
            face_warning = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "face_not_detected", "duration_seconds": 12},
            )
            self.assertEqual(face_warning.status_code, 200, face_warning.text)
            self.assertEqual(face_warning.json()["warning_count"], 1)
            self.assertEqual(
                self.client.post(
                    f"/api/assessments/{token}/proctoring/events",
                    json={"event_type": "face_detected_again", "duration_seconds": 12},
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    f"/api/assessments/{token}/proctoring/events",
                    json={"event_type": "tab_hidden"},
                ).json()["warning_count"],
                2,
            )
            flagged = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "fullscreen_exited"},
            )
            self.assertEqual(flagged.status_code, 200, flagged.text)
            self.assertTrue(flagged.json()["flagged_for_review"])
            self.assertFalse(flagged.json()["auto_submit"])

            status = self.client.get(f"/api/assessments/{token}/proctoring/status")
            self.assertEqual(status.status_code, 200, status.text)
            self.assertEqual(status.json()["warning_count"], 3)
            self.assertTrue(status.json()["flagged_for_review"])
            self.assertNotIn("candidate_id", status.json())
            self.assertNotIn("events", status.json())

        with main.connect() as db:
            assessment_id = db.execute(
                "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()["id"]
        events = self.client.get(
            f"/api/assessments/{assessment_id}/proctoring", headers=recruiter
        )
        self.assertEqual(events.status_code, 200, events.text)
        timeline = events.json()["events"]
        self.assertIn("face_not_detected", [event["event_type"] for event in timeline])
        self.assertIn("face_detected_again", [event["event_type"] for event in timeline])
        short_gap = next(event for event in timeline if event["event_type"] == "face_not_detected" and event["duration_seconds"] == 4)
        self.assertEqual(short_gap["severity"], "Info")
        self.assertTrue(events.json()["summary"]["flagged_for_review"])
        self.assertEqual(
            self.client.get(
                f"/api/assessments/{assessment_id}/proctoring", headers=candidate
            ).status_code,
            403,
        )
        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other-proctor@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        self.assertEqual(
            self.client.get(
                f"/api/assessments/{assessment_id}/proctoring", headers=other_headers
            ).status_code,
            404,
        )
        admin = self.login("admin@skillsphere.dev")
        analytics = self.client.get("/api/admin/proctoring?flagged=true", headers=admin)
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["summary"]["flagged_assessments"], 1)
        self.assertEqual(analytics.json()["summary"]["face_not_visible_warnings"], 1)

    def test_below_threshold_is_not_shortlisted_and_creates_no_assessment(self):
        candidate, _, application = self.create_assessment_application(
            ["Python", "SQL", "FastAPI", "Docker"], "Python SQL"
        )
        self.assertEqual(application["match_percentage"], 50)
        self.assertEqual(application["status"], "Applied")
        self.assertNotIn("assessment_url", application)
        with main.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0], 0)
        self.assertEqual(self.client.get("/api/applications", headers=candidate).status_code, 200)

    def test_manual_topic_required_and_selected_by_recruiter(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Docker", "AWS", "HTML", "CSS"], "Docker AWS HTML CSS"
        )
        self.assertEqual(application["match_percentage"], 100)
        self.assertEqual(application["status"], "Shortlisted")
        self.assertEqual(application["assessment_status"], "Manual Topic Required")
        self.assertNotIn("assessment_url", application)
        with patch.dict("os.environ", {"SKILLSPHERE_PUBLIC_BASE_URL": "http://testserver"}):
            with patch("backend.main.send_assessment_email", return_value="development_console") as email:
                sent = self.client.post(
                    f"/api/applications/{application['id']}/assessment/send",
                    headers=recruiter,
                    json={"technology": "React"},
                )
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertEqual(sent.json()["technology"], "React")
        self.assertNotIn("development_url", sent.json())
        token = email.call_args.args[1].split("token=")[1]
        self.assertEqual(len(self.start_assessment(token).json()["questions"]), 20)

    def test_job_question_banks_are_owner_scoped_and_validate_four_options(self):
        recruiter = self.login("recruiter@skillsphere.dev")
        job_id = self.client.get("/api/jobs?mine=true", headers=recruiter).json()["items"][0]["id"]
        question = {
            "technology": "Python",
            "question": "Which type is immutable?",
            "options": ["tuple", "list", "dict", "set"],
            "correct_index": 0,
            "difficulty": "Easy",
        }
        added = self.client.post(f"/api/jobs/{job_id}/questions", headers=recruiter, json=question)
        self.assertEqual(added.status_code, 201, added.text)
        summary = self.client.get(
            f"/api/jobs/{job_id}/question-bank-summary", headers=recruiter
        ).json()
        self.assertEqual(summary["technologies"][0]["valid_active_questions"], 1)
        self.assertEqual(summary["technologies"][0]["needed"], 19)
        self.assertFalse(summary["technologies"][0]["ready"])

        invalid = dict(question, options=["only", "three", "options"])
        self.assertEqual(
            self.client.post(f"/api/jobs/{job_id}/questions", headers=recruiter, json=invalid).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}/questions", headers=self.login()).status_code,
            403,
        )
        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}/questions", headers=other_headers).status_code,
            404,
        )

        changed = self.client.patch(
            f"/api/jobs/{job_id}/questions/{added.json()['id']}",
            headers=recruiter,
            json={"active": False},
        )
        self.assertEqual(changed.status_code, 200)
        self.assertFalse(changed.json()["active"])
        self.assertEqual(
            self.client.delete(
                f"/api/jobs/{job_id}/questions/{added.json()['id']}", headers=recruiter
            ).status_code,
            200,
        )

    def test_pdf_question_bank_import_preview_confirmation_and_ownership(self):
        recruiter = self.login("recruiter@skillsphere.dev")
        job_id = self.client.get("/api/jobs?mine=true", headers=recruiter).json()["items"][0]["id"]
        pdf_text = """Technology: SQL
Difficulty: Hard
Question: Which clause filters grouped rows?
A. WHERE
B. HAVING
C. ORDER BY
D. DISTINCT
Answer: B

Technology: Python
Question: Which keyword defines a function?
A. function
B. def
C. func
D. define
Answer: B

Technology: Excel
Difficulty: Easy
Question: Which formula adds values?
A. SUM
B. COUNT
D. MAX
Answer: A

Technology: SQL
Difficulty: Hard
Question: Which clause filters grouped rows?
A. WHERE
B. HAVING
C. ORDER BY
D. DISTINCT
Answer: B
"""
        pdf = self.make_text_pdf(pdf_text)
        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        unauthorized = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports",
            headers=other_headers,
            files={"file": ("bank.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(unauthorized.status_code, 404)
        candidate = self.login()
        self.assertEqual(
            self.client.post(
                f"/api/jobs/{job_id}/question-bank/imports",
                headers=candidate,
                files={"file": ("bank.pdf", pdf, "application/pdf")},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(
                f"/api/jobs/{job_id}/question-bank/imports", headers=candidate
            ).status_code,
            403,
        )

        uploaded = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports",
            headers=recruiter,
            files={"file": ("Data_Analyst_Question_Bank.pdf", pdf, "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        preview = uploaded.json()
        self.assertEqual(preview["valid_question_count"], 2)
        self.assertEqual(preview["invalid_question_count"], 2)
        self.assertEqual(preview["technology_counts"], {"SQL": 1, "Python": 1})
        self.assertEqual(preview["difficulty_counts"], {"Hard": 1, "Medium": 1})
        invalid_reasons = " ".join(
            reason for item in preview["invalid_questions"] for reason in item["reasons"]
        )
        self.assertIn("Question 3 is missing option C.", invalid_reasons)
        self.assertIn("duplicates an earlier question in this PDF", invalid_reasons)
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}/questions", headers=recruiter).json()["items"],
            [],
        )
        with main.connect() as db:
            imported = db.execute(
                "SELECT storage_path, status FROM question_bank_imports WHERE id = ?",
                (preview["import_id"],),
            ).fetchone()
        self.assertEqual(imported["status"], "pending_review")
        self.assertTrue(Path(imported["storage_path"]).is_relative_to(main.QUESTION_BANK_IMPORT_DIR))
        self.assertNotIn("storage_path", preview)

        manual = self.client.post(
            f"/api/jobs/{job_id}/questions",
            headers=recruiter,
            json=preview["valid_questions"][0] | {"active": True},
        )
        self.assertEqual(manual.status_code, 201, manual.text)
        confirmed = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports/{preview['import_id']}/confirm",
            headers=recruiter,
            json={"questions": preview["valid_questions"]},
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["imported_count"], 1)
        self.assertEqual(confirmed.json()["skipped_duplicate_count"], 1)
        rows = self.client.get(f"/api/jobs/{job_id}/questions", headers=recruiter).json()["items"]
        self.assertEqual({row["source_type"] for row in rows}, {"manual", "pdf_import"})
        self.assertEqual({row["technology"] for row in rows}, {"SQL", "Python"})
        summary = self.client.get(
            f"/api/jobs/{job_id}/question-bank-summary", headers=recruiter
        ).json()
        self.assertEqual(summary["total_valid_active_questions"], 2)
        self.assertEqual(summary["difficulty_counts"]["Hard"], 1)
        self.assertEqual(
            self.client.get(f"/api/jobs/{job_id}/question-bank/imports", headers=other_headers).status_code,
            404,
        )
        history = self.client.get(f"/api/jobs/{job_id}/question-bank/imports", headers=recruiter).json()["items"]
        self.assertEqual(history[0]["status"], "confirmed")
        self.assertNotIn("storage_path", history[0])

    def test_question_bank_pdf_rejects_non_pdf_and_oversized_upload(self):
        recruiter = self.login("recruiter@skillsphere.dev")
        job_id = self.client.get("/api/jobs?mine=true", headers=recruiter).json()["items"][0]["id"]
        invalid_type = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports",
            headers=recruiter,
            files={"file": ("bank.txt", b"Question: not a PDF", "text/plain")},
        )
        self.assertEqual(invalid_type.status_code, 415)
        invalid_signature = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports",
            headers=recruiter,
            files={"file": ("bank.pdf", b"not a pdf", "application/pdf")},
        )
        self.assertEqual(invalid_signature.status_code, 415)
        too_large = self.client.post(
            f"/api/jobs/{job_id}/question-bank/imports",
            headers=recruiter,
            files={"file": ("bank.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
        )
        self.assertEqual(too_large.status_code, 413)

    def test_multi_technology_assessment_selects_exactly_twenty_relevant_questions(self):
        candidate, _, application = self.create_assessment_application(
            ["Python", "SQL", "JavaScript"],
            "Python SQL JavaScript",
            ["Python", "SQL", "JavaScript"],
            seed_question_technologies=["Python", "SQL", "JavaScript"],
        )
        self.assertEqual(application["assessment_status"], "Sent")
        self.assertEqual(application["assessment_topic"], "Python, SQL, JavaScript")
        token = application["_test_assessment_link"].split("token=")[1]
        questions = self.start_assessment(token).json()["questions"]
        self.assertEqual(len(questions), 20)
        topics = {}
        with main.connect() as db:
            assessment_id = db.execute(
                "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()["id"]
            snapshot_topics = db.execute(
                "SELECT topic FROM assessment_questions WHERE assessment_id = ?", (assessment_id,)
            ).fetchall()
        for question in snapshot_topics:
            topics[question["topic"]] = topics.get(question["topic"], 0) + 1
        self.assertEqual(set(topics), {"Python", "SQL", "JavaScript"})
        self.assertEqual(sum(topics.values()), 20)
        self.assertLessEqual(max(topics.values()) - min(topics.values()), 1)
        self.assertEqual(self.client.get("/api/assessments", headers=candidate).status_code, 200)

    def test_shortlisting_does_not_create_assessment_until_job_bank_has_twenty_valid_questions(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"], seed_question_bank=False
        )
        self.assertEqual(application["match_percentage"], 100)
        self.assertEqual(application["status"], "Shortlisted")
        self.assertEqual(application["assessment_status"], "Question Bank Incomplete")
        self.assertNotIn("assessment_url", application)
        candidate_applications = self.client.get("/api/applications", headers=candidate).json()["items"]
        self.assertEqual(candidate_applications[0]["assessment_status"], "Question Bank Incomplete")
        candidate_notifications = self.client.get("/api/notifications", headers=candidate).json()["items"]
        self.assertTrue(any(item["type"] == "assessment_pending" for item in candidate_notifications))
        recruiter_notifications = self.client.get("/api/notifications", headers=recruiter).json()["items"]
        self.assertTrue(any(item["type"] == "question_bank_incomplete" for item in recruiter_notifications))
        with main.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM assessments").fetchone()[0], 0)

        for index in range(19):
            question = {
                "technology": "Python",
                "question": f"Python job question number {index}",
                "options": ["first", "second", "third", "fourth"],
                "correct_index": index % 4,
                "difficulty": ("Easy", "Medium", "Hard")[index % 3],
            }
            response = self.client.post(
                f"/api/jobs/{application['job_id']}/questions",
                headers=recruiter,
                json=question,
            )
            self.assertEqual(response.status_code, 201, response.text)

        insufficient = self.client.post(
            f"/api/applications/{application['id']}/assessment/send",
            headers=recruiter,
            json={"technology": "Python"},
        )
        self.assertEqual(insufficient.status_code, 409)
        self.assertIn("add 1 more", insufficient.json()["detail"])
        self.assertEqual(
            self.client.get("/api/assessments", headers=candidate).json()["items"],
            [],
        )

        question["question"] = "Python job question number nineteen"
        self.assertEqual(
            self.client.post(
                f"/api/jobs/{application['job_id']}/questions",
                headers=recruiter,
                json=question,
            ).status_code,
            201,
        )
        with patch("backend.main.send_assessment_email", return_value="development_console") as email:
            sent = self.client.post(
                f"/api/applications/{application['id']}/assessment/send",
                headers=recruiter,
                json={"technology": "Python"},
            )
        self.assertEqual(sent.status_code, 201, sent.text)
        self.assertNotIn("development_url", sent.json())
        with main.connect() as db:
            assessment_id = db.execute(
                "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()["id"]
            snapshot = db.execute(
                "SELECT COUNT(*) FROM assessment_questions WHERE assessment_id = ?",
                (assessment_id,),
            ).fetchone()[0]
        self.assertEqual(snapshot, 20)
        self.assertNotIn(email.call_args.args[1], json.dumps(sent.json()))

    def test_application_pipeline_history_notes_and_notifications_are_private(self):
        candidate, application = self.create_application()
        recruiter = self.login("recruiter@skillsphere.dev")
        changed = self.client.patch(
            f"/api/applications/{application['id']}/status",
            headers=recruiter,
            json={"status": "Under Review"},
        )
        self.assertEqual(changed.status_code, 200)
        note = self.client.patch(
            f"/api/applications/{application['id']}/notes",
            headers=recruiter,
            json={"note": "Recruiter-only screening note"},
        )
        self.assertEqual(note.status_code, 200)
        candidate_app = self.client.get("/api/applications", headers=candidate).json()["items"][0]
        self.assertEqual(candidate_app["status"], "Under Review")
        self.assertNotIn("internal_notes", candidate_app)
        self.assertNotIn("recruiter_note", json.dumps(candidate_app["status_history"]))

        notification_data = self.client.get("/api/notifications", headers=candidate).json()
        submitted = next(
            item for item in notification_data["items"] if item["type"] == "application_submitted"
        )
        recruiter_notifications = self.client.get("/api/notifications", headers=recruiter).json()
        new_application = next(
            item for item in recruiter_notifications["items"] if item["type"] == "new_application"
        )
        self.assertEqual(
            self.client.patch(
                f"/api/notifications/{new_application['id']}/read", headers=candidate
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/notifications/unread-count", headers=candidate).json()["unread_count"],
            2,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/notifications/{submitted['id']}/read", headers=candidate
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch("/api/notifications/read-all", headers=candidate).json()["updated"],
            1,
        )
        self.assertEqual(
            self.client.patch(
                f"/api/applications/{application['id']}/status",
                headers=recruiter,
                json={"status": "Applied"},
            ).status_code,
            409,
        )

    def test_assessment_review_is_role_scoped_and_candidate_results_are_visible_after_submission(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"]
        )
        token = application["_test_assessment_link"].split("token=")[1]
        candidate_assessments = self.client.get("/api/assessments", headers=candidate)
        self.assertEqual(candidate_assessments.status_code, 200)
        item = candidate_assessments.json()["items"][0]
        self.assertIsNone(item["score"])
        self.assertNotIn("token_hash", item)

        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        self.assertEqual(
            self.client.get(f"/api/assessments/{item['id']}/review", headers=other_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(f"/api/assessments/{item['id']}/review", headers=recruiter).status_code,
            409,
        )
        started = self.start_assessment(token)
        self.assertEqual(started.status_code, 200)
        with main.connect() as db:
            keys = [
                row["correct_index"] for row in db.execute(
                    "SELECT correct_index FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order",
                    (item["id"],),
                )
            ]
        submitted = self.client.post(f"/api/assessments/{token}/submit", json={"answers": keys})
        self.assertEqual(submitted.status_code, 200)
        self.assertEqual(submitted.json()["score"], 100)
        self.assertEqual(submitted.json()["result"], "Passed")
        candidate_after = self.client.get("/api/assessments", headers=candidate).json()["items"][0]
        self.assertEqual(candidate_after["score"], 100)
        review = self.client.get(f"/api/assessments/{item['id']}/review", headers=recruiter)
        self.assertEqual(review.status_code, 200)
        self.assertEqual(review.json()["score"], 100)
        self.assertEqual(len(review.json()["questions"]), 20)
        self.assertEqual(
            self.client.get(f"/api/assessments/{item['id']}/review", headers=other_headers).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/api/assessments/{item['id']}/review", headers=candidate
            ).status_code,
            403,
        )

    def test_round1_scoring_pipeline_notifications_and_admin_analytics(self):
        cases = [(15, 75, "Passed"), (14, 70, "Failed"), (16, 80, "Passed")]
        first_passed_application = None
        for correct_count, expected_score, expected_result in cases:
            with self.subTest(correct_count=correct_count):
                with main.connect() as db:
                    candidate_id = db.execute(
                        "SELECT id FROM users WHERE email = 'candidate@skillsphere.dev'"
                    ).fetchone()["id"]
                    db.execute("DELETE FROM resumes WHERE candidate_id = ?", (candidate_id,))
                candidate, recruiter, application = self.create_assessment_application(
                    ["Python"], "Python", ["Python"]
                )
                self.assertIn("Authorization", candidate)
                self.assertIn("Authorization", recruiter)
                with main.connect() as db:
                    assessment_id = db.execute(
                        "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
                    ).fetchone()["id"]
                token = application["_test_assessment_link"].split("token=")[1]
                with main.connect() as db:
                    stored = db.execute(
                        "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
                    ).fetchone()
                    self.assertEqual(stored["assessment_name"], "Round 1: Technical MCQ Test")
                    self.assertEqual(stored["assessment_round"], "Round 1")
                    self.assertEqual(stored["pass_percentage"], 75)
                self.assertEqual(self.client.get(f"/api/assessments/{token}").json()["assessment_name"], "Round 1: Technical MCQ Test")
                started = self.start_assessment(token)
                self.assertEqual(started.status_code, 200, started.text)
                self.assertTrue(all("correct_index" not in question for question in started.json()["questions"]))
                with main.connect() as db:
                    keys = [
                        row["correct_index"] for row in db.execute(
                            "SELECT correct_index FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order",
                            (assessment_id,),
                        )
                    ]
                answers = [
                    key if index < correct_count else (key + 1) % 4
                    for index, key in enumerate(keys)
                ]
                with patch.dict("os.environ", {"SKILLSPHERE_ENV": "development"}):
                    submitted = self.client.post(
                        f"/api/assessments/{token}/submit", json={"answers": answers}
                    )
                self.assertEqual(submitted.status_code, 200, submitted.text)
                result = submitted.json()
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(result["correct_answer_count"], correct_count)
                self.assertEqual(result["incorrect_answer_count"], 20 - correct_count)
                self.assertEqual(result["result"], expected_result)
                self.assertIsNotNone(result["time_taken_seconds"])
                self.assertEqual(
                    self.client.post(f"/api/assessments/{token}/submit", json={"answers": answers}).status_code,
                    404,
                )
                with main.connect() as db:
                    stored = db.execute(
                        "SELECT * FROM assessments WHERE id = ?", (assessment_id,)
                    ).fetchone()
                    statuses = [
                        row["status"] for row in db.execute(
                            "SELECT status FROM application_status_history WHERE application_id = ? ORDER BY id",
                            (application["id"],),
                        )
                    ]
                    self.assertEqual(stored["correct_answer_count"], correct_count)
                    self.assertEqual(stored["incorrect_answer_count"], 20 - correct_count)
                    self.assertEqual(stored["score_percentage"], expected_score)
                    self.assertEqual(stored["result"], expected_result)
                    self.assertIsNotNone(stored["result_processed_at"])
                    self.assertEqual(stored["time_taken_seconds"], result["time_taken_seconds"])
                    self.assertEqual(statuses.count("Assessment Completed"), 1)
                    self.assertEqual(statuses.count(f"Round 1 {expected_result}"), 1)
                    self.assertEqual(
                        db.execute(
                            "SELECT status FROM applications WHERE id = ?", (application["id"],)
                        ).fetchone()["status"],
                        f"Round 1 {expected_result}",
                    )
                    if expected_result == "Passed" and first_passed_application is None:
                        first_passed_application = application["id"]
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM notifications WHERE related_assessment_id = ? AND type = 'round1_result'",
                            (assessment_id,),
                        ).fetchone()[0],
                        3,
                    )
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) FROM notifications WHERE related_assessment_id = ? AND type = 'round1_result' AND title = ?",
                            (assessment_id, "You passed Round 1" if expected_result == "Passed" else "Round 1 result"),
                        ).fetchone()[0],
                        1,
                    )
                    candidate_notice = db.execute(
                        """SELECT title, message, email_delivery_status FROM notifications
                        WHERE user_id = ? AND related_assessment_id = ? AND type = 'round1_result'""",
                        (stored["candidate_id"], assessment_id),
                    ).fetchone()
                    recruiter_id = db.execute(
                        "SELECT recruiter_id FROM jobs WHERE id = ?", (stored["job_id"],)
                    ).fetchone()["recruiter_id"]
                    recruiter_notice = db.execute(
                        """SELECT title, message FROM notifications
                        WHERE user_id = ? AND related_assessment_id = ? AND type = 'round1_result'""",
                        (recruiter_id, assessment_id),
                    ).fetchone()
                    self.assertEqual(
                        candidate_notice["title"],
                        "You passed Round 1" if expected_result == "Passed" else "Round 1 result",
                    )
                    self.assertIn("Platform Engineer", candidate_notice["message"])
                    self.assertIn(f"{expected_score}%", candidate_notice["message"])
                    self.assertEqual(candidate_notice["email_delivery_status"], "development_console")
                    if expected_result == "Failed":
                        self.assertIn("did not reach the required passing score", candidate_notice["message"])
                    self.assertEqual(recruiter_notice["title"], "Candidate completed Round 1")
                    self.assertIn("Alex Morgan", recruiter_notice["message"])
                    self.assertIn(expected_result, recruiter_notice["message"])
                    admin_id = db.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()["id"]
                    admin_notice = db.execute(
                        """SELECT title, message FROM notifications
                        WHERE user_id = ? AND type = 'round1_result' AND related_application_id = ?""",
                        (admin_id, application["id"]),
                    ).fetchone()
                    self.assertEqual(admin_notice["title"], "Round 1 assessment completed")
                    self.assertIn(expected_result, admin_notice["message"])
        self.assertIsNotNone(first_passed_application)
        with main.connect() as db:
            self.assertEqual(
                db.execute(
                    "SELECT status FROM applications WHERE id = ?", (first_passed_application,)
                ).fetchone()["status"],
                "Round 1 Passed",
            )
        moved = self.client.patch(
            f"/api/applications/{first_passed_application}/status",
            headers=recruiter,
            json={"status": "Interview"},
        )
        self.assertEqual(moved.status_code, 200, moved.text)
        self.assertEqual(moved.json()["status"], "Interview")
        with patch.dict("os.environ", {"SKILLSPHERE_ROUND1_PASS_PERCENTAGE": "80"}):
            with main.connect() as db:
                candidate_id = db.execute(
                    "SELECT id FROM users WHERE email = 'candidate@skillsphere.dev'"
                ).fetchone()["id"]
                db.execute("DELETE FROM resumes WHERE candidate_id = ?", (candidate_id,))
            candidate, _, application = self.create_assessment_application(
                ["Python"], "Python", ["Python"]
            )
            token = application["_test_assessment_link"].split("token=")[1]
            self.start_assessment(token)
            with main.connect() as db:
                assessment_id = db.execute(
                    "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
                ).fetchone()["id"]
                keys = [
                    row["correct_index"] for row in db.execute(
                        "SELECT correct_index FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order",
                        (assessment_id,),
                    )
                ]
            result = self.client.post(
                f"/api/assessments/{token}/submit",
                json={"answers": [key if index < 15 else (key + 1) % 4 for index, key in enumerate(keys)]},
            ).json()
            self.assertEqual(result["pass_percentage"], 80)
            self.assertEqual(result["result"], "Failed")
        admin = self.login("admin@skillsphere.dev")
        analytics = self.client.get("/api/admin/analytics?range=this_week", headers=admin)
        self.assertEqual(analytics.status_code, 200, analytics.text)
        self.assertEqual(analytics.json()["round1_assessments_completed"], 4)
        self.assertEqual(analytics.json()["round1_passed"], 2)
        self.assertEqual(analytics.json()["round1_failed"], 2)
        self.assertEqual(analytics.json()["round1_pass_rate"], 50)
        self.assertEqual(
            sum(row["count"] for row in analytics.json()["round1_score_distribution"]),
            4,
        )

    def test_recruiter_cannot_send_assessment_for_another_recruiters_job(self):
        _, _, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"]
        )
        other = self.client.post(
            "/api/auth/register",
            json={"name": "Other Recruiter", "email": "other@company.com", "password": "LongEnough9!", "role": "recruiter"},
        ).json()
        response = self.client.post(
            f"/api/applications/{application['id']}/assessment/send",
            headers={"Authorization": f"Bearer {other['access_token']}"},
            json={},
        )
        self.assertEqual(response.status_code, 404)

    def test_reissuing_assessment_invalidates_old_link_and_expiry_is_persisted(self):
        _, recruiter, application = self.create_assessment_application(["Java"], "Java", ["Java"])
        old_token = application["_test_assessment_link"].split("token=")[1]
        with patch.dict("os.environ", {"SKILLSPHERE_PUBLIC_BASE_URL": "http://testserver"}):
            with patch("backend.main.send_assessment_email", return_value="development_console") as email:
                reissued = self.client.post(
                    f"/api/applications/{application['id']}/assessment/reissue",
                    headers=recruiter,
                )
        self.assertEqual(reissued.status_code, 201, reissued.text)
        self.assertNotIn("development_url", reissued.json())
        new_token = email.call_args.args[1].split("token=")[1]
        self.assertNotEqual(old_token, new_token)
        self.assertEqual(self.client.get(f"/api/assessments/{old_token}").status_code, 404)
        with main.connect() as db:
            db.execute(
                "UPDATE assessments SET expires_at = ? WHERE application_id = ?",
                ("2000-01-01T00:00:00+00:00", application["id"]),
            )
        expired = self.client.get(f"/api/assessments/{new_token}")
        self.assertEqual(expired.status_code, 410)
        with main.connect() as db:
            self.assertEqual(
                db.execute("SELECT status FROM assessments WHERE application_id = ?", (application["id"],)).fetchone()["status"],
                "Expired",
            )

    def test_timed_out_assessment_submits_last_server_saved_answers(self):
        _, _, application = self.create_assessment_application(["SQL"], "SQL", ["SQL"])
        token = application["_test_assessment_link"].split("token=")[1]
        self.assertEqual(self.start_assessment(token).status_code, 200)
        with main.connect() as db:
            assessment_id = db.execute(
                "SELECT id FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()["id"]
            answer_key = [
                row["correct_index"]
                for row in db.execute(
                    "SELECT correct_index FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order",
                    (assessment_id,),
                )
            ]
        saved = self.client.put(
            f"/api/assessments/{token}/answers", json={"answers": answer_key}
        )
        self.assertEqual(saved.status_code, 200, saved.text)
        with main.connect() as db:
            db.execute(
                "UPDATE assessments SET expires_at = ? WHERE id = ?",
                ("2000-01-01T00:00:00+00:00", assessment_id),
            )
        timed_out = self.client.post(
            f"/api/assessments/{token}/submit", json={"answers": [0] * 20}
        )
        self.assertEqual(timed_out.status_code, 200, timed_out.text)
        self.assertTrue(timed_out.json()["timed_out"])
        self.assertEqual(timed_out.json()["score"], 100)
        self.assertEqual(timed_out.json()["result"], "Passed")
        with main.connect() as db:
            result = db.execute("SELECT status, score FROM assessments WHERE id = ?", (assessment_id,)).fetchone()
        self.assertEqual((result["status"], result["score"]), ("Completed", 100))

    def test_production_email_failure_does_not_log_or_return_a_development_link(self):
        _, recruiter, application = self.create_assessment_application(["Python"], "Python", ["Python"])
        with patch.dict("os.environ", {
            "SKILLSPHERE_ENV": "production",
            "SKILLSPHERE_PUBLIC_BASE_URL": "https://skillsphere.example",
        }):
            with self.assertNoLogs("backend.email_service", level="WARNING"):
                failed = self.client.post(
                    f"/api/applications/{application['id']}/assessment/reissue",
                    headers=recruiter,
                )
        self.assertEqual(failed.status_code, 502)
        self.assertNotIn("development_url", failed.json())
        with main.connect() as db:
            saved = db.execute(
                "SELECT status FROM assessments WHERE application_id = ?", (application["id"],)
            ).fetchone()
        self.assertEqual(saved["status"], "Not Sent")

    def test_notification_email_uses_absolute_public_app_url(self):
        with patch.dict("os.environ", {
            "SKILLSPHERE_ENV": "development",
            "SKILLSPHERE_SMTP_HOST": "smtp.example.test",
            "SKILLSPHERE_SMTP_FROM": "noreply@example.test",
            "SKILLSPHERE_SMTP_PORT": "587",
            "SKILLSPHERE_SMTP_STARTTLS": "false",
            "SKILLSPHERE_PUBLIC_BASE_URL": "https://skillsphere.example/",
        }):
            with patch("backend.email_service.smtplib.SMTP") as smtp:
                send_notification_email(
                    "candidate@example.test",
                    "Assessment completed",
                    "Your assessment was submitted.",
                    "/",
                )
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertIn("Open SkillSphere:\nhttps://skillsphere.example/", message.get_content())

    def test_interview_email_contains_schedule_instructions_and_secure_meeting_link(self):
        with patch.dict("os.environ", {
            "SKILLSPHERE_ENV": "development",
            "SKILLSPHERE_SMTP_HOST": "smtp.example.test",
            "SKILLSPHERE_SMTP_FROM": "noreply@example.test",
            "SKILLSPHERE_SMTP_PORT": "587",
            "SKILLSPHERE_SMTP_STARTTLS": "false",
        }):
            with patch("backend.email_service.smtplib.SMTP") as smtp:
                delivery = send_interview_email(
                    "candidate@example.test",
                    "Data Analyst",
                    "ABC Company",
                    "20 November 2026, 10:00 AM",
                    "Asia/Kolkata",
                    45,
                    "Google Meet",
                    "https://meet.google.com/abc-defg-hij",
                    "Please bring your portfolio.",
                )
        self.assertEqual(delivery, "email")
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        content = message.get_content()
        self.assertIn("Data Analyst at ABC Company", content)
        self.assertIn("Asia/Kolkata", content)
        self.assertIn("45 minutes", content)
        self.assertIn("Google Meet", content)
        self.assertIn("Please bring your portfolio.", content)
        self.assertIn("https://meet.google.com/abc-defg-hij", content)

    def test_withdrawing_application_revokes_assessment_link(self):
        candidate, _, application = self.create_assessment_application(["React"], "React", ["React"])
        token = application["_test_assessment_link"].split("token=")[1]
        withdrawn = self.client.patch(
            f"/api/applications/{application['id']}/withdraw", headers=candidate
        )
        self.assertEqual(withdrawn.status_code, 200)
        self.assertEqual(self.client.get(f"/api/assessments/{token}").status_code, 404)

    def test_question_banks_are_seeded_with_20_four_option_questions_and_schema_migrates(self):
        with main.connect() as db:
            for technology in ("Python", "Java", "JavaScript", "React", "SQL"):
                questions = db.execute(
                    "SELECT options_json, correct_index, difficulty FROM technical_questions WHERE technology = ?",
                    (technology,),
                ).fetchall()
                self.assertEqual(len(questions), 20)
                self.assertTrue(all(len(json.loads(row["options_json"])) == 4 for row in questions))
                self.assertTrue(all(row["difficulty"] in {"Easy", "Medium", "Hard"} for row in questions))
            db.execute("ALTER TABLE applications DROP COLUMN match_percentage")
        main.initialize_database()
        with main.connect() as db:
            columns = {row["name"] for row in db.execute("PRAGMA table_info(applications)")}
        self.assertIn("match_percentage", columns)

    def test_legacy_assessment_schema_migrates_and_revokes_pending_links(self):
        created_at = main.now()
        expires_at = "2099-01-01T00:00:00+00:00"
        with main.connect() as db:
            db.execute("PRAGMA foreign_keys = OFF")
            db.execute("DROP TABLE assessment_questions")
            db.execute("DROP TABLE assessments")
            application_ids = []
            for job_id in (1, 2):
                cursor = db.execute(
                    """INSERT INTO applications (candidate_id, job_id, status, match_percentage, applied_at)
                    VALUES (1, ?, 'Applied', 80, ?)""",
                    (job_id, created_at),
                )
                application_ids.append(cursor.lastrowid)
            db.execute(
                """CREATE TABLE assessments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
                    token_hash TEXT NOT NULL UNIQUE,
                    technology TEXT NOT NULL,
                    questions_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending' CHECK(status IN ('Pending', 'Completed', 'Expired')),
                    score INTEGER,
                    created_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    completed_at TEXT
                )"""
            )
            db.execute(
                """CREATE TABLE assessment_questions (
                    assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                    question_id INTEGER,
                    question_order INTEGER NOT NULL,
                    question_text TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_index INTEGER NOT NULL,
                    difficulty TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    selected_answer INTEGER,
                    is_correct INTEGER,
                    answered_at TEXT,
                    PRIMARY KEY(assessment_id, question_order)
                )"""
            )
            db.executemany(
                """INSERT INTO assessments
                (application_id, token_hash, technology, questions_json, status, score, created_at, expires_at, completed_at)
                VALUES (?, ?, 'Python', '[]', ?, ?, ?, ?, ?)""",
                [
                    (application_ids[0], "pending-hash", "Pending", None, created_at, expires_at, None),
                    (application_ids[1], "completed-hash", "Completed", 85, created_at, expires_at, created_at),
                ],
            )
        main.initialize_database()
        with main.connect() as db:
            migrated = db.execute(
                """SELECT application_id, candidate_id, job_id, status, token_hash, score, submitted_at,
                assessment_name, assessment_round, pass_percentage, score_percentage,
                correct_answer_count, incorrect_answer_count, result, result_processed_at
                FROM assessments ORDER BY id"""
            ).fetchall()
        self.assertEqual(migrated[0]["status"], "Expired")
        self.assertIsNone(migrated[0]["token_hash"])
        self.assertEqual(migrated[1]["status"], "Completed")
        self.assertIsNone(migrated[1]["token_hash"])
        self.assertEqual(migrated[1]["score"], 85)
        self.assertEqual(migrated[1]["submitted_at"], created_at)
        self.assertEqual(migrated[1]["assessment_name"], "Round 1: Technical MCQ Test")
        self.assertEqual(migrated[1]["assessment_round"], "Round 1")
        self.assertEqual(migrated[1]["pass_percentage"], 75)
        self.assertEqual(migrated[1]["score_percentage"], 85)
        self.assertEqual(migrated[1]["correct_answer_count"], 17)
        self.assertEqual(migrated[1]["incorrect_answer_count"], 3)
        self.assertEqual(migrated[1]["result"], "Passed")
        self.assertEqual(migrated[1]["result_processed_at"], created_at)

    def test_resume_upload_rejects_unsupported_and_corrupt_file_signatures(self):
        candidate = self.login()
        unsupported = self.client.post(
            "/api/resume/upload", headers=candidate,
            files={"file": ("resume.txt", b"not a resume", "text/plain")},
        )
        self.assertEqual(unsupported.status_code, 415)
        corrupt_pdf = self.client.post(
            "/api/resume/upload", headers=candidate,
            files={"file": ("resume.pdf", b"%PDF-1.7\ninvalid", "application/pdf")},
        )
        self.assertEqual(corrupt_pdf.status_code, 422)
        corrupt_image = self.client.post(
            "/api/resume/upload", headers=candidate,
            files={"file": ("resume.png", b"\x89PNG\r\n\x1a\nnot an image", "image/png")},
        )
        self.assertEqual(corrupt_image.status_code, 422)
        too_large = self.client.post(
            "/api/resume/upload", headers=candidate,
            files={"file": ("resume.pdf", b"%PDF-" + b"x" * (10 * 1024 * 1024 + 1), "application/pdf")},
        )
        self.assertEqual(too_large.status_code, 413)
        no_resume = self.client.get("/api/resume", headers=candidate)
        self.assertEqual(no_resume.status_code, 200)
        self.assertIsNone(no_resume.json())

    def test_text_pdf_is_parsed_and_match_score_explains_skill_gaps(self):
        candidate = self.login()
        writer = PdfWriter()
        page = writer.add_blank_page(width=612, height=792)
        font = writer._add_object(DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }))
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 14 Tf 50 700 Td (Alex Morgan alex@example.com Figma UX research) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        pdf = BytesIO()
        writer.write(pdf)

        uploaded = self.client.post(
            "/api/resume/upload", headers=candidate,
            files={"file": ("resume.pdf", pdf.getvalue(), "application/pdf")},
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        self.assertEqual(uploaded.json()["processing_status"], "completed")
        self.assertEqual(uploaded.json()["parsed_profile"]["email"], "alex@example.com")
        self.assertNotIn("storage_path", uploaded.json())
        self.assertNotIn("extracted_text", uploaded.json())
        job = self.client.get("/api/jobs?q=Product%20Designer", headers=candidate).json()["items"][0]
        match = self.client.get(f"/api/matches/{job['id']}", headers=candidate)
        self.assertEqual(match.status_code, 200)
        self.assertEqual(match.json()["matched_skills"], ["Figma", "UX research"])
        self.assertEqual(match.json()["missing_skills"], ["Prototyping", "Design systems"])
        self.assertEqual(match.json()["match_percentage"], 50)

    def test_roles_are_enforced_on_admin_analytics(self):
        candidate = self.login()
        self.assertEqual(self.client.get("/api/admin/analytics", headers=candidate).status_code, 403)
        admin = self.login("admin@skillsphere.dev")
        report = self.client.get("/api/admin/analytics", headers=admin)
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["users"], 3)

    def test_admin_custom_analytics_uses_stored_timestamps_and_lists_recent_users(self):
        self.create_application()
        admin = self.login("admin@skillsphere.dev")
        today = main.datetime.now(main.timezone.utc).date().isoformat()
        report = self.client.get(
            f"/api/admin/analytics?range=custom&start_date={today}&end_date={today}",
            headers=admin,
        )
        self.assertEqual(report.status_code, 200, report.text)
        data = report.json()
        self.assertEqual(data["applications_received"], 1)
        self.assertEqual(sum(item["applications"] for item in data["weekly_trend"]), 1)
        self.assertEqual(data["new_candidates"], 1)
        self.assertEqual(self.client.get("/api/admin/analytics?range=this_week", headers=admin).status_code, 200)
        self.assertTrue(any(item["type"] == "weekly_report" for item in self.client.get(
            "/api/notifications", headers=admin
        ).json()["items"]))
        users = self.client.get("/api/admin/users", headers=admin)
        self.assertEqual(users.status_code, 200)
        self.assertEqual(len(users.json()["items"]), 3)
        self.assertIn("last_activity", users.json()["items"][0])
        self.assertEqual(self.client.get("/api/admin/users", headers=self.login()).status_code, 403)

    def test_admin_can_disable_accounts_and_close_job_listings(self):
        admin = self.login("admin@skillsphere.dev")
        candidate = self.login()
        self.assertEqual(
            self.client.patch("/api/admin/users/3/status", headers=admin, json={"active": False}).status_code,
            409,
        )
        disabled = self.client.patch("/api/admin/users/1/status", headers=admin, json={"active": False})
        self.assertEqual(disabled.status_code, 200)
        self.assertEqual(
            self.client.post("/api/auth/login", json={"email": "candidate@skillsphere.dev", "password": "Demo123!"}).status_code,
            401,
        )
        self.assertEqual(self.client.get("/api/jobs", headers=candidate).status_code, 401)
        self.assertEqual(self.client.patch("/api/admin/users/1/status", headers=admin, json={"active": True}).status_code, 200)

        job = self.client.get("/api/jobs", headers=admin).json()["items"][0]
        closed = self.client.patch(f"/api/admin/jobs/{job['id']}/status", headers=admin, json={"status": "Closed"})
        self.assertEqual(closed.status_code, 200)
        self.assertEqual(closed.json()["status"], "Closed")
        self.assertEqual(self.client.get(f"/api/jobs/{job['id']}", headers=admin).status_code, 404)

    def test_candidate_can_withdraw_and_reapply_but_not_after_interview(self):
        candidate = self.login()
        job_id = self.client.get("/api/jobs", headers=candidate).json()["items"][0]["id"]
        with main.connect() as db:
            db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, parsed_profile_json, processing_status, uploaded_at)
                VALUES (1, 'resume.pdf', 'private.pdf', 'application/pdf', '{}', 'completed', '2026-01-01T00:00:00+00:00')"""
            )
        application = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate).json()
        withdrawn = self.client.patch(f"/api/applications/{application['id']}/withdraw", headers=candidate)
        self.assertEqual(withdrawn.status_code, 200)
        self.assertEqual(withdrawn.json()["status"], "Withdrawn")
        reapplied = self.client.post(f"/api/jobs/{job_id}/apply", headers=candidate)
        self.assertEqual(reapplied.status_code, 201)
        recruiter = self.login("recruiter@skillsphere.dev")
        self.assertEqual(
            self.client.patch(
                f"/api/applications/{application['id']}/status",
                headers=recruiter,
                json={"status": "Interview"},
            ).status_code,
            200,
        )
        blocked = self.client.patch(f"/api/applications/{application['id']}/withdraw", headers=candidate)
        self.assertEqual(blocked.status_code, 409)

    def test_application_assessment_proctoring_route_and_role_permissions(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"]
        )
        token = application["_test_assessment_link"].split("token=")[1]
        self.start_assessment(token)

        # Record a proctoring event
        self.client.post(
            f"/api/assessments/{token}/proctoring/events",
            json={"event_type": "tab_hidden"},
        )

        # Recruiter can review via application-scoped endpoint
        app_proctoring = self.client.get(
            f"/api/applications/{application['id']}/assessment/proctoring",
            headers=recruiter,
        )
        self.assertEqual(app_proctoring.status_code, 200, app_proctoring.text)
        data = app_proctoring.json()
        self.assertEqual(data["summary"]["tab_switch_count"], 1)
        self.assertTrue(any(ev["event_type"] == "tab_hidden" for ev in data["events"]))

        # Candidate is forbidden (403)
        self.assertEqual(
            self.client.get(
                f"/api/applications/{application['id']}/assessment/proctoring",
                headers=candidate,
            ).status_code,
            403,
        )

        # Other recruiter gets 404
        other = self.client.post(
            "/api/auth/register",
            json={"name": "Different Recruiter", "email": "diff-recruiter@example.com", "password": "Password123!", "role": "recruiter"},
        ).json()
        other_headers = {"Authorization": f"Bearer {other['access_token']}"}
        self.assertEqual(
            self.client.get(
                f"/api/applications/{application['id']}/assessment/proctoring",
                headers=other_headers,
            ).status_code,
            404,
        )

        # Admin gets 200
        admin = self.login("admin@skillsphere.dev")
        admin_resp = self.client.get(
            f"/api/applications/{application['id']}/assessment/proctoring",
            headers=admin,
        )
        self.assertEqual(admin_resp.status_code, 200)

    def test_proctoring_auto_submit_policy_and_post_submission_event_rejection(self):
        candidate, recruiter, application = self.create_assessment_application(
            ["Python"], "Python", ["Python"]
        )
        token = application["_test_assessment_link"].split("token=")[1]

        with patch.dict("os.environ", {
            "SKILLSPHERE_MAX_PROCTORING_WARNINGS": "2",
            "SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS": "true",
        }):
            self.start_assessment(token)

            # Warning 1: tab hidden
            w1 = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "tab_hidden"},
            )
            self.assertEqual(w1.status_code, 200)
            self.assertEqual(w1.json()["warning_count"], 1)
            self.assertFalse(w1.json()["auto_submit"])

            # Warning 2: fullscreen exited -> hits max warnings (2) -> auto_submit=True
            w2 = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "fullscreen_exited"},
            )
            self.assertEqual(w2.status_code, 200)
            self.assertEqual(w2.json()["warning_count"], 2)
            self.assertTrue(w2.json()["flagged_for_review"])
            self.assertTrue(w2.json()["auto_submit"])

            # Submit the assessment
            submitted = self.client.post(
                f"/api/assessments/{token}/submit",
                json={"answers": [0] * 20},
            )
            self.assertEqual(submitted.status_code, 200)

            # Once submitted/completed, link is invalidated and further proctoring events are rejected (404)
            post_submit_event = self.client.post(
                f"/api/assessments/{token}/proctoring/events",
                json={"event_type": "tab_hidden"},
            )
            self.assertEqual(post_submit_event.status_code, 404)

    def test_proctoring_disabled_switch_allows_start_without_camera(self):
        with patch.dict("os.environ", {"SKILLSPHERE_PROCTORING_REQUIRED": "false"}):
            candidate, recruiter, application = self.create_assessment_application(
                ["Python"], "Python", ["Python"]
            )
            token = application["_test_assessment_link"].split("token=")[1]

            # Before start, check proctoring status
            status = self.client.get(f"/api/assessments/{token}/proctoring/status")
            self.assertEqual(status.status_code, 200)
            self.assertFalse(status.json()["proctoring_required"])

            # Assessment can start immediately without calling /proctoring/start
            started = self.client.post(f"/api/assessments/{token}/start")
            self.assertEqual(started.status_code, 200)
            self.assertEqual(len(started.json()["questions"]), 20)

    def test_proctoring_token_isolation_and_face_detected_recovery(self):
        candidate, recruiter, app1 = self.create_assessment_application(["Python"], "Python", ["Python"])
        token1 = app1["_test_assessment_link"].split("token=")[1]
        self.start_assessment(token1)

        # Create a second job and assessment
        job2 = self.client.post(
            "/api/jobs",
            headers=recruiter,
            json={
                "title": "Backend Lead",
                "company": "Northstar",
                "description": "Lead backend services.",
                "location": "Remote",
                "experience": "5+ years",
                "job_type": "Full-time",
                "salary": "$140k",
                "skills": ["Python"],
            },
        ).json()
        with main.connect() as db:
            db.executemany(
                """INSERT INTO job_questions
                (job_id, recruiter_id, technology, question, options_json, correct_index,
                difficulty, active, created_at, updated_at)
                VALUES (?, 2, 'Python', ?, ?, ?, ?, 1, ?, ?)""",
                [
                    (job2["id"], q, json.dumps(opts), c_idx, diff, main.now(), main.now())
                    for q, opts, c_idx, diff in main.QUESTION_BANKS["Python"]
                ],
            )
        with patch("backend.main.send_assessment_email", return_value="development_console") as email:
            app2 = self.client.post(f"/api/jobs/{job2['id']}/apply", headers=candidate).json()
            token2 = email.call_args.args[1].split("token=")[1]
        self.start_assessment(token2)

        # Trigger warning on assessment 1
        self.client.post(
            f"/api/assessments/{token1}/proctoring/events",
            json={"event_type": "tab_hidden"},
        )

        status1 = self.client.get(f"/api/assessments/{token1}/proctoring/status").json()
        status2 = self.client.get(f"/api/assessments/{token2}/proctoring/status").json()

        # Token 1 has 1 warning, token 2 has 0 warnings (isolated)
        self.assertEqual(status1["warning_count"], 1)
        self.assertEqual(status2["warning_count"], 0)

        # Test face_detected event on token 1
        face_ev = self.client.post(
            f"/api/assessments/{token1}/proctoring/events",
            json={"event_type": "face_detected"},
        )
        self.assertEqual(face_ev.status_code, 200)
        self.assertEqual(face_ev.json()["accepted"], True)
        self.assertEqual(face_ev.json()["warning_count"], 1)  # Does not increment warning count


if __name__ == "__main__":
    unittest.main()
