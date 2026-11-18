# SkillSphere

SkillSphere is a responsive career and job portal inspired by the supplied screen recording. Its warm, red-accented interface supports job seekers, recruiters, and administrators. The frontend is a dependency-free HTML/CSS/JavaScript client, so it runs without a JavaScript build toolchain; the Python API and SQLite database provide the working application flows.

## Run locally

1. Use Python 3.10 or later.
2. Install the backend requirements:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. For image OCR, install the Tesseract OCR executable and make it available on `PATH`. Text-based PDFs are read directly; scanned PDFs and images are rendered and sent through Tesseract.
4. Start the app from this directory:

   ```powershell
   python -m uvicorn backend.main:app --reload
   ```

5. Open <http://127.0.0.1:8000>.

The API is documented at <http://127.0.0.1:8000/docs>. SQLite data and private resume uploads are stored in `data/`. Set `SKILLSPHERE_DATA_DIR` to move them. Seeded demo accounts and a local-only signing key are enabled in development mode; set `SKILLSPHERE_ENV=production`, a long, unique `SKILLSPHERE_SECRET_KEY`, `SKILLSPHERE_ADMIN_EMAIL`, and `SKILLSPHERE_ADMIN_PASSWORD` before deploying.

### Production security checklist

The app now enforces HTTPS-only cookie settings in production, secure `HttpOnly`/`SameSite=Lax` session cookies, and CSRF validation for cookie-authenticated state-changing requests. Browser clients should use the secure session flow instead of storing bearer tokens in `localStorage`.

Required environment variables for public deployment:

- `SKILLSPHERE_ENV` — set to `production` to enable secure defaults.
- `SKILLSPHERE_SECRET_KEY` — required in production; must be at least 32 characters and unique.
- `SKILLSPHERE_PUBLIC_BASE_URL` — externally reachable public URL used for candidate assessment links and email actions.
- `SKILLSPHERE_ADMIN_EMAIL` and `SKILLSPHERE_ADMIN_PASSWORD` — admin account bootstrap values for production.
- `SKILLSPHERE_SMTP_HOST`, `SKILLSPHERE_SMTP_PORT`, `SKILLSPHERE_SMTP_USERNAME`, `SKILLSPHERE_SMTP_PASSWORD`, and `SKILLSPHERE_SMTP_FROM` — outbound email configuration.
- `SKILLSPHERE_DATA_DIR` — writable private storage location for SQLite and uploaded files.
- `SKILLSPHERE_JUDGE0_URL` and optional `SKILLSPHERE_JUDGE0_TOKEN` — interview code runner configuration.
- `SKILLSPHERE_RATE_LIMIT_*` values may be overridden if scaling beyond the default in-memory limiters; production deployments should use Redis or another shared rate-limit store for multi-instance deployments.

Do not set `SKILLSPHERE_SECRET_KEY` to the development default or any shared demo value. Keep `SKILLSPHERE_ENV` out of `development` in production, and do not seed demo accounts in production mode.

For the architecture, source-file map, dependency/tool roles, workflows, and implementation methodology, see the [Project Guide](./PROJECT_GUIDE.md).

### Demo accounts

| Workspace | Email | Password |
|---|---|---|
| Job seeker | candidate@skillsphere.dev | Demo123! |
| Recruiter | recruiter@skillsphere.dev | Demo123! |
| Admin | admin@skillsphere.dev | Demo123! |

## What works

- Candidate and recruiter registration, sign-in, and role-protected API access.
- Job search by keyword, location, and job type; recruiters can post roles and see their own listings.
- Resume uploads accept PDF, JPG, JPEG, and PNG, enforce a 10 MB limit, validate file signatures, store files outside the public web root, extract text, and retain editable parsed profile fields.
- Resume-to-job comparisons use explicit skill-name matches and missing-skill lists; the score is the matched required skills divided by all required skills.
- Candidates can apply once to a role after uploading a resume, withdraw eligible applications, and review their application history. Applications retain the match percentage and status timeline.
- Candidates matching at least 70% of a job's required skills are shortlisted automatically. Candidates below that threshold are not eligible for an assessment.
- Recruiters manage a separate question bank for each job and can add MCQs manually or import them from a PDF. An automatic assessment selects exactly 20 active questions across technologies shared by the candidate profile and the job requirements; an explicitly selected single-topic assessment needs 20 valid active questions in that topic.
- Shortlisted candidates receive a private, one-use assessment link at their registered email address. Assessments expire, are timed after starting, autosave answers, and are scored server-side. If no relevant technology is detected in a candidate's resume/profile, the recruiter chooses an available job-specific bank.
- Recruiters can review match details and assessment status for their own applicants, resend unused links, access submitted resumes, keep private notes, and move applications through the hiring pipeline. Candidates receive status updates and can review their own application history.
- User-scoped in-app notifications cover application, interview, and assessment events. Selected updates, including Round 1 results, are also emailed when SMTP is configured. Candidates see their score and pass/fail result only after submitting; correct answers remain restricted to authorized recruiter/admin review.
- Recruiters can schedule, reschedule, cancel, and complete applicant interviews using Google Meet, Microsoft Teams, Zoom, or another HTTPS meeting link. Candidates see interview details and a **Join Interview** action in My Applications and on their dashboard; only the candidate on that application and its recruiter can access the invitation.
- The coding room supports Python, JavaScript, Java, and C++; code execution is proxied to a separately configured Judge0 service and is disabled until one is configured.
- Administrators can review users, job listings, applications, question banks, and assessments; disable accounts; and view this-week, last-week, or custom-range hiring and assessment analytics.
- Switch between light and dark glass themes from the sign-in page, workspace header, or candidate assessment page; the choice is saved in the browser and shared across pages.

### Interview code execution

Teams links open in Microsoft Teams; the app does not create meetings or host video itself. The app never executes interview code inside the web server. To enable the **Run code** button, deploy a private Judge0-compatible service with execution time, memory, process, and network limits configured, then set `SKILLSPHERE_JUDGE0_URL` to its base URL. Keep the runner private and configure it to block submission network access. If the runner requires authentication, set `SKILLSPHERE_JUDGE0_TOKEN` as well. Without a configured runner, the live shared editor still works and code execution returns a clear configuration message.

### Interview scheduling and candidate join flow

From **Applicants**, a recruiter opens **Schedule Interview** for a candidate on one of their own jobs. Enter a future date and start time, the time zone, duration, platform, an HTTPS meeting URL, and optional instructions. The application moves to **Interview** and records the pipeline history. The candidate receives an in-app notification and, when SMTP is configured, an email with the meeting details and URL. In local development the in-app notice remains available even without SMTP.

Candidates see the invitation in **My Applications**, with the schedule rendered in their local time zone, duration, platform, and recruiter instructions. The dashboard also shows their nearest upcoming interview. **Join Interview** opens the saved HTTPS URL in a new tab. Recruiters can reschedule, replace the meeting link, cancel, or mark an interview completed; each change notifies the candidate. A cancelled/completed/ended interview has no join action.

Interview details are stored against the application and are returned only to that candidate, the recruiter who owns the job, or an admin. Recruiter authorization is validated by the API, not just by the UI. Candidate invitation views are recorded when they use the Join Interview action. Existing interview records are migrated to the extended SQLite schema at startup.

Manual verification: sign in as a recruiter → open **Applicants** → choose **Schedule Interview** for a candidate on your job → enter a future time, time zone, duration, platform, and HTTPS meeting URL → confirm the candidate receives email/in-app notification → sign in as that candidate → open **My Applications** → verify the interview details and **Join Interview** button → click it and confirm the meeting opens in a new tab. Reschedule the interview and verify a new notification; then cancel it and confirm the join action is hidden and **Interview Cancelled** is shown. Repeat with another recruiter/candidate and confirm they cannot access the invitation.

Live editor updates are broadcast by the running app process. A multi-worker or multi-instance deployment needs shared pub/sub for collaboration across workers.

OCR results are best-effort: files remain available for review if extraction is unsuccessful, and the UI presents the reason instead of inventing missing resume details. The current build stores application data in SQLite; production deployments should add operational controls such as rate limiting, database backups, and a deployment-grade secret manager.

### Candidate technical assessments

#### Round 1: Technical MCQ Test

Every generated 20-question MCQ assessment is named **Round 1: Technical MCQ Test**. The default passing threshold is **75%**: 15/20 correct passes and 14/20 (70%) or fewer fails. Configure the threshold for newly sent assessments with `SKILLSPHERE_ROUND1_PASS_PERCENTAGE` (a number from 0 to 100; defaults to `75`). The threshold is saved on each assessment when it is created, so the result remains consistent if the environment setting changes later.

The test starts its configured timer when the candidate opens it, can be submitted only once, and is scored on the backend using the saved question key. On submission SkillSphere records the question totals, correct and incorrect counts, percentage, result, round, submission/result-processing time, and time taken. The application timeline records Assessment Started, Assessment Completed, and then Round 1 Passed or Round 1 Failed. A pass never automatically advances to an interview; the recruiter chooses whether to move a passed candidate to Interview, Accepted, or Rejected. Recruiters can also reject a failed candidate.

Candidates see the threshold and time limit before starting, then see their score and result after submitting in the test page, Assessment Review, notifications, and application timeline. Recruiters can filter results by pass/fail, score, job, assessment state, pipeline stage, and completion dates, then review each question and answer. Admin weekly analytics include Round 1 completion, pass/fail counts and rate, average score, outcomes by job, and pass/fail distribution. Correct answers are never sent to the candidate before submission.

#### Import a question bank PDF

On the recruiter/admin **Question banks** page, select a job, upload a PDF, review the extracted questions, make any corrections, and confirm the import. The preview does not save questions until confirmation. Malformed questions are listed with reasons and are skipped; duplicate question text for the same technology is not imported twice. Imports are recorded in job-scoped history, and source PDFs are stored privately outside the public web directory.

Use a text-based PDF with one question block per MCQ. Repeat the technology and optional difficulty headers when changing sections:

```text
Technology: SQL
Difficulty: Medium

Question: Which SQL clause filters results after GROUP BY?
A. WHERE
B. HAVING
C. ORDER BY
D. DISTINCT
Answer: B

Technology: Python
Difficulty: Easy

Question: Which keyword is used to define a function in Python?
A. function
B. def
C. func
D. define
Answer: B
```

Each block must provide a technology, question, exactly four labeled options (`A.` through `D.`), and an answer key (`A` through `D`). Difficulty may be Easy, Medium, or Hard; a missing difficulty defaults to Medium. The upload limit is 10 MB and 40 pages. Text extraction uses `pypdf`; scanned PDFs use the existing OCR dependencies. If OCR reports no readable text, install Tesseract and retry, or use a text-based PDF. If question blocks are malformed, check that labels begin on separate lines and use the exact field names and option labels shown above.

#### Automatic question selection and privacy

For candidates at or above the 70% match threshold, SkillSphere checks resume text, parsed resume skills, editable profile skills, and job-required skills. It selects only from that job's active question bank and prefers technologies represented in both the candidate's profile and the job requirements. When multiple relevant technologies have enough questions, the 20-question set is distributed across them according to their presence in the candidate profile and balanced across available Easy/Medium/Hard questions. For example, a set can include SQL, Python, and Tableau questions. If fewer than 20 suitable active questions are available, no partial test is created: the recruiter is notified that the bank needs completion and the candidate sees that their assessment is pending.

The selected questions and answer options are snapshotted, so later bank edits do not change an invitation already sent. Correct answers remain server-side and are never included in the candidate assessment API. Candidates receive the secure assessment link by email and an in-app notification; they must complete the test independently.

#### Camera proctoring and assessment integrity

When proctoring is required, the candidate first sees a clear consent and privacy notice and must grant camera access via `getUserMedia()` before the assessment timer starts or questions are returned. When webcam recording is enabled, candidates are also presented with an explicit webcam recording consent checkbox that must be accepted before starting the test. Assessment questions and the countdown timer remain hidden until camera access is granted and a live video stream is active. A live camera preview stays visible in a fixed corner during the test alongside a "Camera active" badge, a pulsing red "REC" indicator (when recording), and live warning counter. Face-presence detection runs entirely client-side in the candidate's browser (using native `FaceDetector` API when supported, client-side MediaPipe Tasks Vision, or camera frame presence fallback). Video stream and camera monitoring stop immediately upon assessment submission, test expiration, or navigating away.

The browser monitors and reports metadata events for:
- Camera permission granted, denied, unavailable, or revoked mid-test
- Camera stream unexpectedly stopped
- Sustained face-absence (10 seconds or longer by default; brief detection gaps under 10 seconds are not flagged as warnings)
- Face visibility recovery (`face_detected_again` / `face_detected`)
- Tab switched or hidden (`visibilitychange`)
- Window lost focus (`blur`) and regained focus (`focus`)
- Full-screen mode exited (`fullscreenchange`)

Candidates receive an on-screen warning toast upon leaving the window or losing face visibility:
- *“Your face is not visible. Please remain in front of the camera to continue.”*
- *“Warning: You left the assessment window. Please remain on this page until the test is complete.”*

Legitimate candidates are never disqualified or failed based on a single event or temporary glitch. The system uses a configurable warning threshold (default: 3 warnings). Once the threshold is reached, a final warning is shown and the assessment is marked **Flagged for Review**. Candidates may continue unless `SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS=true` is explicitly enabled.

All events are stored securely in the SQLite `assessment_proctoring_events` table and the `assessments` table. Recruiters review integrity summaries and event timelines from **Applicants**, the recruiter **Assessments** table, and the dedicated endpoints (`/api/assessments/{id}/proctoring` and `/api/applications/{application_id}/assessment/proctoring`). Recruiters can access only assessments for their own job listings. Administrators review platform-wide integrity in the **Proctoring** workspace with filters for job, recruiter, candidate, date range, status, and flagged state.

#### Webcam Video Recording and Cloudinary Storage

For comprehensive auditability, SkillSphere captures candidate webcam video via the browser `MediaRecorder` API and uploads it securely:

1. **Client-side Recording:** The browser records video in 10-second chunks using supported codecs (`video/webm` or `video/mp4`). A pulsing red recording indicator remains visible in the camera preview.
2. **Non-blocking Upload:** Upon test submission, timeout, or completion, the video blob is uploaded via `POST /api/assessments/{token}/recording/upload`. Test scoring and result display are non-blocking and never fail if upload is slow or interrupted.
3. **Cloudinary Integration:** Server-side upload to Cloudinary uses authenticated signed uploads tagged by assessment ID and candidate ID. If Cloudinary credentials are not configured, the system falls back gracefully without interrupting tests.
4. **Role Separation & Playback Security:**
   - **Recruiters** see only recording status badges (`Uploaded`, `Pending`, `Failed`) and duration, never video files or playback URLs.
   - **Administrators** can review video playback in the Admin Proctoring dashboard. Playback URLs are generated as short-lived, signed expiring URLs (`/api/admin/recordings/{id}/playback`). Every playback request is audited in `admin_recording_access_logs`.
5. **Retention Policy & Cleanup:** The retention cleaner (`POST /api/admin/recordings/cleanup`) destroys video assets older than `SKILLSPHERE_RECORDING_RETENTION_DAYS` (default 90 days), while automatically preserving recordings for assessments marked **Flagged for Review**.

Supported browsers include current desktop versions of Google Chrome, Microsoft Edge, Mozilla Firefox, and Apple Safari with camera support. The page must be opened over HTTPS or localhost for browser camera permission to be granted.

Configure proctoring and video recording with:

| Variable | Description | Default |
|---|---|---|
| `SKILLSPHERE_PROCTORING_REQUIRED` | Require candidate consent and camera flow for new assessments (`true`/`false`) | `true` |
| `SKILLSPHERE_RECORDING_REQUIRED` | Require candidate webcam video recording (`true`/`false`) | `true` |
| `SKILLSPHERE_FACE_MISSING_WARNING_SECONDS` | Continuous face-absence duration in seconds before a warning is recorded | `10` |
| `SKILLSPHERE_MAX_PROCTORING_WARNINGS` | Warning threshold that flags an assessment for review | `3` |
| `SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS` | Automatically submit assessment when max warnings threshold is reached (`true`/`false`) | `false` |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary account cloud name | `""` |
| `CLOUDINARY_API_KEY` | Cloudinary account API key | `""` |
| `CLOUDINARY_API_SECRET` | Cloudinary account API secret (server-side only, never sent to browser) | `""` |
| `SKILLSPHERE_CLOUDINARY_ENABLED` | Enable Cloudinary upload (`true`/`false`) | `true` |
| `SKILLSPHERE_RECORDING_MAX_UPLOAD_MB` | Maximum video recording upload size in megabytes | `100` |
| `SKILLSPHERE_RECORDING_RETENTION_DAYS` | Days before non-flagged recordings are eligible for cleanup | `90` |

Manual end-to-end verification checklist:
1. Open a secure assessment link (`/assessment.html?token=...`).
2. Review the proctoring consent screen and verify questions and timer are hidden.
3. Check the webcam recording consent checkbox and click **Allow Camera and Start Test**. Grant camera permission when prompted.
4. Verify the live camera preview appears with the "Camera active" badge, the pulsing red "REC" indicator, the 20 questions load, and the countdown timer begins.
5. Switch browser tabs or minimize the window, then return: verify a warning toast is shown and warning count increments.
6. Cover or step away from camera for under 10 seconds: verify no warning is recorded for brief gaps. Step away for >10 seconds: verify face-missing warning toast is shown. Return to camera view: verify recovery is acknowledged.
7. Complete and submit the 20-MCQ assessment: verify camera stream stops immediately, video upload proceeds in background, and results screen displays score.
8. Sign in as the job's recruiter (`recruiter@skillsphere.dev`): navigate to **Applicants** or **Assessments**, verify the proctoring summary badge, recording status, and click **Proctoring timeline** to view the timestamped event audit trail (verify recruiter cannot see video playback).
9. Sign in as another recruiter: verify trying to access this applicant's proctoring timeline returns a 404/access denied.
10. Sign in as an administrator (`admin@skillsphere.dev`): navigate to **Proctoring** to view platform analytics, recording upload metrics, click **Play** or **Watch recording** to review the recorded video alongside the event timeline in the playback modal.

Configure outbound email and the public site URL with these environment variables:

| Variable | Description | Default |
|---|---|---|
| `SKILLSPHERE_PUBLIC_BASE_URL` | Public app URL used to construct candidate links | `http://127.0.0.1:8000` in development |
| `SKILLSPHERE_SMTP_HOST` | SMTP server hostname | unset |
| `SKILLSPHERE_SMTP_PORT` | SMTP port; port 465 uses SSL, other ports use STARTTLS by default | `587` |
| `SKILLSPHERE_SMTP_USERNAME` | SMTP login username | unset |
| `SKILLSPHERE_SMTP_PASSWORD` | SMTP login password | unset |
| `SKILLSPHERE_SMTP_FROM` | Verified sender address | unset |
| `SKILLSPHERE_SMTP_STARTTLS` | Enable STARTTLS for SMTP ports other than 465 | `true` |
| `SKILLSPHERE_ASSESSMENT_TTL_HOURS` | Invitation lifetime before the candidate starts | `48` |
| `SKILLSPHERE_ASSESSMENT_DURATION_MINUTES` | Time limit after starting | `30` |
| `SKILLSPHERE_ROUND1_PASS_PERCENTAGE` | Passing score percentage for newly generated Round 1 assessments (0–100) | `75` |

In development, if SMTP is not configured, the private assessment URL is logged to the backend console for local testing; the recruiter can resend an unused invitation. Production email delivery requires SMTP configuration, and `SKILLSPHERE_PUBLIC_BASE_URL` must be set to the externally reachable app URL. Delivery failures are recorded and reported. Only a hash of each assessment token is stored; reissuing an unused invitation invalidates its previous link. Candidate dashboards do not expose raw links or correct answers.

Manual end-to-end verification: sign in as a recruiter and create a job → add at least 20 valid questions for a technology in its question bank → sign in as a candidate, upload a resume with relevant skills, and apply → confirm a 70%+ match is shortlisted → send the assessment to the candidate's registered email (or use the development console link) → confirm the candidate page identifies **Round 1: Technical MCQ Test**, shows 20 questions, the time limit, and 75% passing score → answer 15 questions correctly and submit to confirm 75% / Passed, then repeat with 14 correct to confirm 70% / Failed → verify result notifications/email, application timeline, and duplicate-submission protection → confirm the recruiter can review question-by-question results and manually move a passed candidate to Interview, Accepted, or Rejected → verify the Admin Dashboard's weekly Round 1 metrics and job breakdown.

The API tests cover the 75% pass boundary, 70% fail boundary, scores above threshold, persisted results, pipeline history, notifications, role-scoped reviews, answer-key privacy, duplicate submissions, and legacy SQLite migration.

On startup, SQLite schema setup applies guarded migrations for application matching, assessment question snapshots, job-specific question banks, notifications, and pipeline history without replacing existing users, jobs, resumes, or applications. If upgrading from the earlier assessment prototype, completed scores are retained; unfinished prototype links are expired because their question snapshots and timing state are incompatible with the timed assessment flow.

## Tests

Run the API test suite with:

```powershell
python -m unittest discover -s backend\tests -v
```
