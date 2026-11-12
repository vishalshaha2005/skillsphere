# SkillSphere Project Guide

This guide explains the current project's architecture, the purpose of its main
files and dependencies, its important workflows, and the engineering practices
used to keep those workflows reliable. It complements the setup and feature
details in [README.md](./README.md).

## 1. What the project does

SkillSphere is a recruitment and career portal for three roles:

- **Candidates** create profiles, upload resumes, find and apply to jobs, take
  assessments, and follow application progress.
- **Recruiters** create jobs, manage job-specific question banks, review
  applicants, send technical assessments, and manage interview stages.
- **Administrators** manage platform accounts and listings and view hiring and
  assessment analytics.

The project is intentionally built as a small monolithic web application:
FastAPI handles the API and serves the frontend; SQLite stores application
data; the frontend is plain HTML, CSS, and JavaScript.

## 2. Project map

| Path | Responsibility |
|---|---|
| `backend/main.py` | FastAPI application, API routes, authorization, SQLite access, database setup/migrations, resume handling, hiring workflow, assessment submission, notifications, analytics, and interview collaboration. |
| `backend/assessment_questions.py` | Built-in technical question sets, topic detection, and selection helpers. Recruiter-managed, job-specific questions are stored in SQLite and take precedence for real job assessments. |
| `backend/email_service.py` | SMTP delivery for assessment invitations and notification emails; development-mode logging when email is not configured. |
| `backend/tests/test_api.py` | API-level automated tests. Each test uses an isolated temporary SQLite data directory. |
| `frontend/index.html` | Main app entry point and static asset loading. |
| `frontend/app.js` | Plain JavaScript UI rendering, navigation, forms, API calls, and interactions for candidate, recruiter, and admin workspaces. |
| `frontend/styles.css` | Main app layout, responsive styling, light/dark glass themes, and motion preferences. |
| `frontend/assessment.html` | Standalone candidate assessment page. |
| `frontend/assessment.js` | Assessment loading, timed questions, answer autosave, submission, and result presentation. |
| `frontend/assessment.css` | Responsive assessment styling and light/dark themes. |
| `frontend/theme.js` | Shared light/dark preference initialization and persistence for both frontend pages. |
| `requirements.txt` | Python runtime and test dependencies. |
| `README.md` | User-facing features, configuration, local setup, and test instructions. |
| `data/` | Runtime SQLite database and private uploaded files. This is application data, not source code; do not commit real candidate data or uploads. |

The frontend has no npm package manifest or JavaScript build step. The browser
loads the source HTML, CSS, and JavaScript files directly.

## 3. Technologies and tools

| Technology/tool | Used for |
|---|---|
| Python 3.10+ | Backend runtime and tests. |
| FastAPI | HTTP API, dependency-based authentication/authorization, WebSocket route, and automatic OpenAPI documentation. |
| Uvicorn | Development/production ASGI server for the FastAPI app. |
| Pydantic | Request-body validation and field constraints on API inputs. |
| SQLite (`sqlite3`) | Relational application storage without a separate database server. SQL is executed by Python's standard library. |
| Plain HTML | Main and standalone assessment page structure. |
| CSS | Responsive layout, glass surfaces, transitions, reduced-motion handling, and theme variants. |
| Browser JavaScript | UI rendering and interaction, API requests, `localStorage` theme persistence, and assessment timer/answer state. |
| `python-multipart` | Multipart file uploads to FastAPI. |
| `pypdf` | Text extraction from text-based PDFs and PDF question-bank parsing support. |
| `pypdfium2`, Pillow, `pytesseract`, Tesseract executable | Optional scanned-PDF/image rendering and OCR. Tesseract itself must be separately installed and available on `PATH`. |
| `email-validator` | Validation for email fields. |
| `httpx` and FastAPI `TestClient` | Automated API tests without launching a separate server. |
| `unittest` | Python test runner used by this repository. |
| SMTP | Optional delivery of assessment links and notification emails. |
| Judge0-compatible service | Optional, separately hosted code runner for interview exercises; not executed inside this app's web process. |

There is no frontend framework, CSS framework, ORM, or JavaScript test/build
tool configured in this repository.

## 4. Request and data flow

1. The browser loads `frontend/index.html`; FastAPI serves the frontend and API
   from the same origin.
2. `frontend/app.js` calls `/api/...` endpoints using `fetch`. After login it
   stores the bearer token in browser storage and sends it with protected
   requests.
3. FastAPI validates request data, resolves the current user, checks role and
   resource ownership, then reads or updates SQLite through
   `backend/main.py`.
4. The backend returns JSON. The frontend renders the result and presents
   explicit errors or success notifications.
5. Uploaded resumes and imported PDFs are stored under the configured data
   directory, not as publicly served frontend assets. Their metadata and
   workflow records are stored in SQLite.

`backend/main.py` is intentionally the main integration point for this
small-project architecture. Keep changes localized to a feature's existing
route/helper and its related UI/tests where possible.

## 5. Main workflows

### Candidate matching and hiring pipeline

- Candidate resumes can be uploaded, parsed, and edited as a profile.
- Applications are compared with job requirements using the project's skill
  matching logic. The application stores a match score and status history.
- A match of at least 70% qualifies a candidate for assessment consideration.
- Recruiters control assessment invitation and later pipeline decisions.

### Technical assessments

- Questions are selected from the relevant job's active question bank, using
  the candidate's resume/profile and job requirements to identify technologies.
- The selected set and answer key are snapshotted for the invitation so later
  question-bank edits do not change a test already sent.
- The candidate receives a private link, starts the assessment timer, and
  submits answers. Answers may be autosaved, but the client does not calculate
  or send a trusted score.
- The backend calculates the score, records Round 1 result and submission
  metadata, updates application history, and creates candidate/recruiter
  notifications. Recruiters review question-level results and choose any next
  pipeline stage.

### Question-bank PDF import

- A recruiter uploads a PDF for a specific job, previews extracted questions,
  corrects or removes entries, and confirms the import.
- Parsing and validation happen on the backend; malformed question blocks are
  reported rather than silently treated as valid questions.
- Text PDFs are extracted directly. Scanned material requires the optional
  OCR dependencies and Tesseract installation.

### Interviews and shared coding

- Recruiters schedule interviews for their applicants.
- The interview code room uses a WebSocket for live updates within the running
  app process.
- Code execution is a separate optional integration with a Judge0-compatible
  service. Do not run candidate code in the FastAPI process.

### Theme preference

- `frontend/theme.js` applies a saved light/dark preference before page styles
  load to avoid an initial theme flash.
- The preference is stored in `localStorage` under `skillsphere_theme`; both
  the main app and assessment page use the same setting.
- Theme controls are icon-only but retain accessible labels and button state.

## 6. Important implementation methodology

### Validate and authorize at the API boundary

- Define request bodies with Pydantic models and explicit field constraints.
- Resolve the authenticated user on the backend and use role checks for
  privileged routes.
- Check ownership at the resource level as well as the role level (for example,
  recruiter access is limited to that recruiter's own jobs and applicants).
- Treat all browser-provided values as untrusted. In particular, calculate
  assessment scores and pass/fail results only from the stored answer key.

### Keep sensitive values out of public responses

- Do not return password hashes or private assessment answer keys to
  candidates.
- Assessment invitation tokens are high-entropy, time-limited, and stored as
  hashes; the link is intended for one attempt.
- Uploaded files are stored outside the static frontend directory, checked
  against size/type constraints, and served only through authorized routes.
- Keep secrets in environment configuration, not source files. Production
  startup requires a deployment-specific signing secret.

### Use transactions and safe schema evolution

- SQLite connections enable foreign-key checks and commit or roll back each
  transaction.
- SQL values should be passed as bound parameters, not concatenated into SQL
  strings.
- Schema initialization includes guarded migrations so existing SQLite
  installations gain newer columns/tables without replacing existing user or
  hiring data.
- For a schema change, update migration/backfill behavior and tests together;
  test against both a fresh database and a representative older schema.

### Make state transitions explicit

- Write pipeline updates to the existing status history instead of replacing
  history.
- Assessment submission and result processing should be idempotent: a repeated
  submission must not duplicate results, notifications, or status-history
  entries.
- Keep email delivery separate from the durable in-app notification record.
  Report email configuration/delivery failures instead of presenting a false
  successful delivery.

### Test observable behavior

- Prefer API tests that exercise complete flows and assert stored state and
  returned response shapes, not just helper implementation details.
- Test boundary conditions, authorization across roles/resources, duplicate
  requests, and migration from earlier database layouts.
- For frontend-only changes, use a browser preview to verify interaction,
  layout, accessibility labels, and narrow-screen behavior.
- Do not add a frontend build tool or dependency unless a feature needs one;
  the current UI is intentionally dependency-free.

## 7. Local development and verification

From the project root in PowerShell:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
```

Open <http://127.0.0.1:8000>. The interactive API reference is available at
<http://127.0.0.1:8000/docs>.

Run the backend API tests:

```powershell
python -m unittest discover -s backend\tests -v
```

The frontend can be served directly by FastAPI during normal development. To
preview just the static frontend, run a simple local HTTP server from the
`frontend` directory; API calls will not work unless the FastAPI server also
handles those API paths.

## 8. Configuration and operational notes

Important settings include:

- `SKILLSPHERE_DATA_DIR`: move SQLite and private upload data away from the
  default `data/` directory.
- `SKILLSPHERE_ENV` and `SKILLSPHERE_SECRET_KEY`: select production behavior
  and set the signed-token secret. A unique secret is required in production.
- `SKILLSPHERE_ROUND1_PASS_PERCENTAGE`: passing threshold for new Round 1
  assessments (defaults to 75%).
- `SKILLSPHERE_ASSESSMENT_TTL_HOURS` and
  `SKILLSPHERE_ASSESSMENT_DURATION_MINUTES`: assessment invitation expiry and
  test duration.
- `SKILLSPHERE_SMTP_*` and `SKILLSPHERE_PUBLIC_BASE_URL`: outbound email
  configuration and externally reachable links.
- `SKILLSPHERE_JUDGE0_URL` and optional `SKILLSPHERE_JUDGE0_TOKEN`: optional
  external code execution service.

See the environment-variable tables in [README.md](./README.md) for all
settings and defaults. Production deployments should additionally plan for
HTTPS, backups, rate limiting, monitored email delivery, secret management,
and an appropriately isolated code runner.
