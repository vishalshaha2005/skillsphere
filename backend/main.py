from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.assessment_questions import QUESTION_BANKS, detect_assessment_topic, get_questions
from backend.email_service import (
    EmailDeliveryError,
    send_assessment_email,
    send_interview_email,
    send_notification_email,
)
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field, HttpUrl
from starlette.concurrency import run_in_threadpool

ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIR = ROOT / "frontend"
DATA_DIR = Path(os.environ.get("SKILLSPHERE_DATA_DIR", ROOT / "data")).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
QUESTION_BANK_IMPORT_DIR = DATA_DIR / "question_bank_imports"
DB_PATH = DATA_DIR / "skillsphere.sqlite3"
MAX_RESUME_BYTES = 10 * 1024 * 1024
MAX_QUESTION_BANK_PDF_BYTES = 10 * 1024 * 1024
MAX_QUESTION_BANK_PDF_PAGES = 40
APP_ENV = os.environ.get("SKILLSPHERE_ENV", "development").lower()
IS_PRODUCTION = APP_ENV == "production"
AUTH_COOKIE_NAME = "skillsphere_session"
CSRF_COOKIE_NAME = "skillsphere_csrf"
COOKIE_PATH = "/"
DEFAULT_SECRET = "local-development-only-change-before-deploying"

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL", "").strip()
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN", "").strip()

try:
    import libsql_experimental as libsql
    HAS_LIBSQL = True
except ImportError:
    libsql = None
    HAS_LIBSQL = False


def turso_configured() -> bool:
    return bool(HAS_LIBSQL and TURSO_DATABASE_URL and TURSO_AUTH_TOKEN)


def current_is_production() -> bool:
    return os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production"


def runtime_secret() -> str:
    secret = (os.environ.get("SKILLSPHERE_SECRET_KEY") or "").strip()
    if secret and len(secret) >= 32 and secret not in {DEFAULT_SECRET, "change-me", "development-secret"}:
        return secret
    if current_is_production():
        generated = secrets.token_urlsafe(32)
        os.environ["SKILLSPHERE_SECRET_KEY"] = generated
        return generated
    return secret or DEFAULT_SECRET


TOKEN_SECRET = runtime_secret()
TOKEN_TTL_SECONDS = 60 * 60 * 12

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get(
        "SKILLSPHERE_ALLOWED_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="SkillSphere API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1|.*\.onrender\.com|.*\.koyeb\.app)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    if request.method in {"GET", "HEAD", "OPTIONS"} or request.url.path.startswith("/api/assessments/") or request.url.path in {"/api/auth/login", "/api/auth/register", "/api/auth/csrf"}:
        response = await call_next(request)
    else:
        auth_header = request.headers.get("authorization")
        has_cookie_auth = AUTH_COOKIE_NAME in request.cookies
        csrf_header = request.headers.get("x-csrf-token") or request.headers.get("x-xsrf-token")
        csrf_cookie = request.cookies.get(CSRF_COOKIE_NAME)
        if has_cookie_auth and not auth_header and (not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header)):
            return JSONResponse({"detail": "CSRF token is required for cookie-authenticated requests."}, status_code=403)
        response = await call_next(request)

    response.headers.setdefault("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; img-src 'self' data: https://res.cloudinary.com; font-src 'self' data: https://fonts.gstatic.com; media-src 'self' blob: data: https://res.cloudinary.com; connect-src 'self' https://cdn.jsdelivr.net https://storage.googleapis.com https://res.cloudinary.com https://api.cloudinary.com; worker-src 'self' blob:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=(), interest-cohort=()")
    if current_is_production():
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response




def validate_runtime_configuration() -> None:
    if not current_is_production():
        return
    secret = (os.environ.get("SKILLSPHERE_SECRET_KEY") or "").strip()
    if not secret or len(secret) < 32 or secret in {DEFAULT_SECRET, "change-me", "development-secret"}:
        os.environ["SKILLSPHERE_SECRET_KEY"] = secrets.token_urlsafe(32)


logger = logging.getLogger(__name__)
interview_connections: dict[int, set[WebSocket]] = {}
interview_connection_lock = asyncio.Lock()
CODE_LANGUAGES = {"python": 71, "javascript": 93, "java": 91, "cpp": 105}
MAX_INTERVIEW_CODE_LENGTH = 30_000
MAX_INTERVIEW_INPUT_LENGTH = 4_000
ASSESSMENT_MATCH_THRESHOLD = 70
ROUND1_ASSESSMENT_NAME = "Round 1: Technical MCQ Test"
PROCTORING_EVENT_TYPES = {
    "camera_permission_granted",
    "camera_permission_denied",
    "camera_unavailable",
    "camera_stream_stopped",
    "face_detected",
    "face_not_detected",
    "face_detected_again",
    "tab_hidden",
    "tab_visible_again",
    "window_blur",
    "window_focus",
    "fullscreen_exited",
    "warning_shown",
    "assessment_flagged",
}


def proctoring_required() -> bool:
    value = os.environ.get("SKILLSPHERE_PROCTORING_REQUIRED", "true").strip().lower()
    if value not in {"true", "false"}:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_PROCTORING_REQUIRED must be true or false.")
    return value == "true"


def proctoring_face_missing_seconds() -> int:
    try:
        value = int(os.environ.get("SKILLSPHERE_FACE_MISSING_WARNING_SECONDS", "10"))
    except ValueError as error:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_FACE_MISSING_WARNING_SECONDS must be a positive integer.") from error
    if value < 1:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_FACE_MISSING_WARNING_SECONDS must be a positive integer.")
    return value


def max_proctoring_warnings() -> int:
    try:
        value = int(os.environ.get("SKILLSPHERE_MAX_PROCTORING_WARNINGS", "3"))
    except ValueError as error:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_MAX_PROCTORING_WARNINGS must be a positive integer.") from error
    if value < 1:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_MAX_PROCTORING_WARNINGS must be a positive integer.")
    return value


def auto_submit_on_max_proctoring_warnings() -> bool:
    value = os.environ.get("SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS", "false").strip().lower()
    if value not in {"true", "false"}:
        raise HTTPException(status_code=503, detail="SKILLSPHERE_AUTO_SUBMIT_ON_MAX_WARNINGS must be true or false.")
    return value == "true"


def recording_required() -> bool:
    if not proctoring_required():
        return False
    value = os.environ.get("SKILLSPHERE_RECORDING_REQUIRED", "true").strip().lower()
    return value == "true"


def recording_max_upload_bytes() -> int:
    try:
        mb = int(os.environ.get("SKILLSPHERE_RECORDING_MAX_UPLOAD_MB", "100"))
    except ValueError:
        mb = 100
    return max(1, mb) * 1024 * 1024


def recording_retention_days() -> int:
    try:
        days = int(os.environ.get("SKILLSPHERE_RECORDING_RETENTION_DAYS", "90"))
    except ValueError:
        days = 90
    return max(1, days)


def cloudinary_configured() -> bool:
    enabled = os.environ.get("SKILLSPHERE_CLOUDINARY_ENABLED", "true").strip().lower() == "true"
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip()
    api_key = os.environ.get("CLOUDINARY_API_KEY", "").strip()
    api_secret = os.environ.get("CLOUDINARY_API_SECRET", "").strip()
    return bool(enabled and cloud_name and api_key and api_secret)


def get_cloudinary_config() -> dict[str, str]:
    return {
        "cloud_name": os.environ.get("CLOUDINARY_CLOUD_NAME", "").strip(),
        "api_key": os.environ.get("CLOUDINARY_API_KEY", "").strip(),
        "api_secret": os.environ.get("CLOUDINARY_API_SECRET", "").strip(),
        "folder": os.environ.get("CLOUDINARY_UPLOAD_FOLDER", "skillsphere/assessment-recordings").strip(),
    }


def upload_video_to_cloudinary(
    content: bytes,
    public_id: str,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    if not cloudinary_configured():
        raise RuntimeError("Cloudinary is not configured or disabled.")
    import cloudinary
    import cloudinary.uploader

    config = get_cloudinary_config()
    cloudinary.config(
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        secure=True,
    )
    folder = config["folder"]
    full_public_id = f"{folder}/{public_id}".strip("/")
    return cloudinary.uploader.upload(
        content,
        resource_type="video",
        public_id=full_public_id,
        tags=tags or ["skillsphere", "proctoring"],
        type="authenticated",
        overwrite=True,
    )


def generate_signed_playback_url(
    public_id: str,
    resource_type: str = "video",
    format: str | None = None,
    expires_in_seconds: int = 3600,
) -> str:
    if not cloudinary_configured():
        return f"https://res.cloudinary.com/demo/video/upload/{public_id}.mp4"
    import cloudinary
    import cloudinary.utils

    config = get_cloudinary_config()
    cloudinary.config(
        cloud_name=config["cloud_name"],
        api_key=config["api_key"],
        api_secret=config["api_secret"],
        secure=True,
    )
    expires_at = int(time.time()) + expires_in_seconds
    url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        resource_type=resource_type,
        type="authenticated",
        format=format,
        sign_url=True,
        expires_at=expires_at,
        secure=True,
    )
    return url


def round1_pass_percentage() -> float:
    try:
        percentage = float(os.environ.get("SKILLSPHERE_ROUND1_PASS_PERCENTAGE", "75"))
    except ValueError as error:
        raise HTTPException(
            status_code=503,
            detail="SKILLSPHERE_ROUND1_PASS_PERCENTAGE must be a number between 0 and 100.",
        ) from error
    if not 0 <= percentage <= 100:
        raise HTTPException(
            status_code=503,
            detail="SKILLSPHERE_ROUND1_PASS_PERCENTAGE must be between 0 and 100.",
        )
    return percentage


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if turso_configured():
        try:
            # Embedded replica mode: ultra-fast local SQLite synced with Turso cloud
            connection = libsql.connect(
                str(DB_PATH),
                sync_url=TURSO_DATABASE_URL,
                auth_token=TURSO_AUTH_TOKEN,
            )
            try:
                connection.sync()
            except Exception as sync_err:
                logger.warning("Turso pre-sync notice: %s", sync_err)
            connection.row_factory = sqlite3.Row
            try:
                yield connection
                connection.commit()
                try:
                    connection.sync()
                except Exception as sync_err:
                    logger.warning("Turso post-sync notice: %s", sync_err)
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
            return
        except Exception as err:
            logger.error("Turso connection failed, falling back to local SQLite: %s", err)

    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    result = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 180_000)
    return f"{salt.hex()}:{result.hex()}"


def check_password(password: str, encoded: str) -> bool:
    try:
        salt, expected = encoded.split(":", 1)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 180_000)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def auth_cookie_settings() -> dict[str, Any]:
    return {
        "httponly": True,
        "secure": current_is_production(),
        "samesite": "Lax",
        "path": COOKIE_PATH,
        "max_age": TOKEN_TTL_SECONDS,
    }


def csrf_cookie_settings() -> dict[str, Any]:
    return {
        "httponly": False,
        "secure": current_is_production(),
        "samesite": "Lax",
        "path": COOKIE_PATH,
        "max_age": TOKEN_TTL_SECONDS,
    }


def encode_token(user: sqlite3.Row | dict[str, Any]) -> str:
    import base64

    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = {
        "sub": user["id"],
        "role": user["role"],
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=").decode()
    signature = hmac.new(TOKEN_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    signed = base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return f"{header}.{body}.{signed}"


def decode_token(token: str) -> dict[str, Any]:
    import base64

    try:
        header, body, signature = token.split(".")
        expected = hmac.new(TOKEN_SECRET.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("Invalid signature")
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        if payload.get("exp", 0) <= time.time():
            raise ValueError("Expired token")
        return payload
    except (ValueError, TypeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=401, detail="Invalid or expired authentication token") from error


RATE_LIMIT_BUCKETS: dict[str, list[float]] = {}
LAST_RATE_LIMIT_CLEANUP: float = 0.0
TRUSTED_PROXIES = {
    ip.strip()
    for ip in os.environ.get("SKILLSPHERE_TRUSTED_PROXIES", "127.0.0.1,::1,testclient").split(",")
    if ip.strip()
}


def client_ip(request: Request) -> str:
    peer_host = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and (peer_host in TRUSTED_PROXIES or not current_is_production()):
        candidate = forwarded.split(",", 1)[0].strip()
        if candidate:
            return candidate
    return peer_host


def enforce_rate_limit(scope: str, identifier: str, limit: int, window_seconds: int) -> None:
    global LAST_RATE_LIMIT_CLEANUP
    key = f"{scope}:{identifier}"
    now = time.monotonic()
    if now - LAST_RATE_LIMIT_CLEANUP > 60:
        LAST_RATE_LIMIT_CLEANUP = now
        stale_keys = [
            k for k, timestamps in RATE_LIMIT_BUCKETS.items()
            if not timestamps or (now - timestamps[-1] >= window_seconds)
        ]
        for k in stale_keys:
            RATE_LIMIT_BUCKETS.pop(k, None)
    bucket = RATE_LIMIT_BUCKETS.setdefault(key, [])
    bucket[:] = [timestamp for timestamp in bucket if now - timestamp < window_seconds]
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="Too many attempts. Please wait a moment and try again.")
    bucket.append(now)


def public_user(row: sqlite3.Row) -> dict[str, Any]:
    user = dict(row)
    user.pop("password_hash", None)
    user["profile"] = json.loads(user.pop("profile_json") or "{}")
    return user


def get_current_user(authorization: str | None = None, token: str | None = None) -> dict[str, Any]:
    provided = token or authorization
    if not provided:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    if provided.startswith("Bearer "):
        provided = provided[7:]
    payload = decode_token(provided)
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE id = ?", (payload.get("sub"),)).fetchone()
    if not row or not row["active"]:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return public_user(row)


async def current_user(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    token = authorization
    if not token:
        token = request.cookies.get(AUTH_COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return get_current_user(token=token)


def require_role(*roles: str):
    def dependency(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="This action is not available for your account")
        return user

    return dependency


class RegisterBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = "candidate"


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class AuthSessionBody(BaseModel):
    access_token: str


class JobBody(BaseModel):
    title: str = Field(min_length=2, max_length=120)
    company: str = Field(min_length=2, max_length=100)
    description: str = Field(min_length=20, max_length=10_000)
    location: str = Field(min_length=2, max_length=100)
    experience: str = Field(min_length=2, max_length=80)
    job_type: str = Field(default="Full-time", max_length=30)
    salary: str = Field(default="", max_length=80)
    skills: list[str] = Field(min_length=1, max_length=30)


class StatusBody(BaseModel):
    status: str
    note: str | None = Field(default=None, max_length=2_000)


class InternalNoteBody(BaseModel):
    note: str = Field(max_length=8_000)


class ProfileBody(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    profile: dict[str, Any] = Field(default_factory=dict)


class UserStatusBody(BaseModel):
    active: bool


class JobStatusBody(BaseModel):
    status: str


class JobUpdateBody(JobBody):
    pass


class QuestionBody(BaseModel):
    technology: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=5, max_length=2_000)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_index: int = Field(ge=0, le=3)
    difficulty: str = "Medium"
    active: bool = True


class QuestionUpdateBody(BaseModel):
    technology: str | None = Field(default=None, min_length=1, max_length=40)
    question: str | None = Field(default=None, min_length=5, max_length=2_000)
    options: list[str] | None = Field(default=None, min_length=4, max_length=4)
    correct_index: int | None = Field(default=None, ge=0, le=3)
    difficulty: str | None = None
    active: bool | None = None


class ImportQuestionBody(QuestionBody):
    pass


class ConfirmQuestionBankImportBody(BaseModel):
    questions: list[ImportQuestionBody] = Field(max_length=500)


class MatchBody(BaseModel):
    job_id: int


class AssessmentSendBody(BaseModel):
    technology: str | None = Field(default=None, max_length=40)


class AssessmentSubmissionBody(BaseModel):
    answers: list[int] = Field(min_length=20, max_length=20)


class InterviewBody(BaseModel):
    application_id: int
    starts_at: datetime
    teams_url: HttpUrl


class InterviewScheduleBody(BaseModel):
    starts_at: datetime
    timezone: str = Field(min_length=1, max_length=100)
    duration_minutes: int = Field(default=60, ge=15, le=480)
    meeting_platform: str = Field(default="Other", min_length=1, max_length=40)
    meeting_url: str = Field(default="", max_length=2048)
    recruiter_message: str = Field(default="", max_length=2000)


class InterviewUpdateBody(BaseModel):
    starts_at: datetime | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=100)
    duration_minutes: int | None = Field(default=None, ge=15, le=480)
    meeting_platform: str | None = Field(default=None, min_length=1, max_length=40)
    meeting_url: str | None = Field(default=None, max_length=2048)
    recruiter_message: str | None = Field(default=None, max_length=2000)


class CodeRunBody(BaseModel):
    language: str
    code: str = Field(max_length=MAX_INTERVIEW_CODE_LENGTH)
    stdin: str = Field(default="", max_length=MAX_INTERVIEW_INPUT_LENGTH)


class ProctoringStartBody(BaseModel):
    permission_granted: bool


class ProctoringEventBody(BaseModel):
    event_type: str = Field(min_length=1, max_length=50)
    duration_seconds: int | None = Field(default=None, ge=0, le=3600)


class RecordingStartBody(BaseModel):
    consent_given: bool
    consent_version: str = Field(default="1.0", max_length=20)


class RecordingCompleteBody(BaseModel):
    duration_seconds: int | None = Field(default=None, ge=0)
    status: str = Field(default="Uploaded", max_length=30)


def initialize_database() -> None:
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    QUESTION_BANK_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        migrate_legacy_assessments(db)
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('candidate', 'recruiter', 'admin')),
                profile_json TEXT NOT NULL DEFAULT '{}',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recruiter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                description TEXT NOT NULL,
                location TEXT NOT NULL,
                experience TEXT NOT NULL,
                job_type TEXT NOT NULL,
                salary TEXT NOT NULL DEFAULT '',
                skills_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open', 'Closed')),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS resumes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                content_type TEXT NOT NULL,
                extracted_text TEXT NOT NULL DEFAULT '',
                parsed_profile_json TEXT NOT NULL DEFAULT '{}',
                processing_status TEXT NOT NULL,
                processing_error TEXT NOT NULL DEFAULT '',
                uploaded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS question_bank_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                recruiter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                storage_path TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending_review'
                    CHECK(status IN ('pending_review', 'confirmed', 'cancelled', 'failed')),
                total_questions INTEGER NOT NULL DEFAULT 0,
                valid_question_count INTEGER NOT NULL DEFAULT 0,
                invalid_question_count INTEGER NOT NULL DEFAULT 0,
                preview_json TEXT NOT NULL DEFAULT '{}',
                error_summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                resume_id INTEGER REFERENCES resumes(id) ON DELETE SET NULL,
                status TEXT NOT NULL DEFAULT 'Applied',
                match_percentage INTEGER NOT NULL DEFAULT 0,
                matched_skills_json TEXT NOT NULL DEFAULT '[]',
                missing_skills_json TEXT NOT NULL DEFAULT '[]',
                internal_notes TEXT NOT NULL DEFAULT '',
                applied_at TEXT NOT NULL,
                UNIQUE(candidate_id, job_id)
            );
            CREATE TABLE IF NOT EXISTS job_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                recruiter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                technology TEXT NOT NULL,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
                difficulty TEXT NOT NULL CHECK(difficulty IN ('Easy', 'Medium', 'Hard')),
                active INTEGER NOT NULL DEFAULT 1,
                source_type TEXT NOT NULL DEFAULT 'manual' CHECK(source_type IN ('manual', 'pdf_import')),
                source_import_id INTEGER REFERENCES question_bank_imports(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS job_questions_job_idx
                ON job_questions(job_id, technology, active);
            CREATE TABLE IF NOT EXISTS application_status_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                status TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                actor_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                recruiter_note TEXT
            );
            CREATE INDEX IF NOT EXISTS application_status_history_app_idx
                ON application_status_history(application_id, updated_at);
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                related_application_id INTEGER REFERENCES applications(id) ON DELETE CASCADE,
                related_assessment_id INTEGER REFERENCES assessments(id) ON DELETE CASCADE,
                action_url TEXT,
                is_read INTEGER NOT NULL DEFAULT 0,
                email_delivery_status TEXT NOT NULL DEFAULT 'not_requested',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS notifications_user_idx
                ON notifications(user_id, is_read, created_at);
            CREATE TABLE IF NOT EXISTS technical_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                technology TEXT NOT NULL,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
                difficulty TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                UNIQUE(technology, question)
            );
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
                candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                technology TEXT,
                token_hash TEXT UNIQUE,
                status TEXT NOT NULL DEFAULT 'Not Sent'
                    CHECK(status IN ('Not Sent', 'Sent', 'Started', 'Completed', 'Expired', 'Manual Topic Required')),
                match_percentage INTEGER NOT NULL,
                starts_at TEXT,
                expires_at TEXT,
                submitted_at TEXT,
                expired_at TEXT,
                score INTEGER,
                total_questions INTEGER NOT NULL DEFAULT 20,
                assessment_name TEXT NOT NULL DEFAULT 'Round 1: Technical MCQ Test',
                assessment_round TEXT NOT NULL DEFAULT 'Round 1',
                pass_percentage REAL NOT NULL DEFAULT 75,
                score_percentage REAL,
                correct_answer_count INTEGER,
                incorrect_answer_count INTEGER,
                result TEXT CHECK(result IN ('Passed', 'Failed')),
                result_processed_at TEXT,
                time_taken_seconds INTEGER,
                duration_minutes INTEGER NOT NULL DEFAULT 30,
                email_sent_at TEXT,
                expiry_warning_sent_at TEXT,
                selection_reasoning TEXT NOT NULL DEFAULT '',
                proctoring_required INTEGER NOT NULL DEFAULT 1,
                proctoring_status TEXT NOT NULL DEFAULT 'Not Started',
                warning_count INTEGER NOT NULL DEFAULT 0,
                flagged_for_review INTEGER NOT NULL DEFAULT 0,
                flagged_at TEXT,
                camera_permission_granted_at TEXT,
                last_face_detected_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assessment_questions (
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                question_id INTEGER REFERENCES technical_questions(id) ON DELETE SET NULL,
                question_order INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
                difficulty TEXT NOT NULL,
                topic TEXT NOT NULL,
                job_question_id INTEGER REFERENCES job_questions(id) ON DELETE SET NULL,
                selected_answer INTEGER,
                is_correct INTEGER,
                answered_at TEXT,
                PRIMARY KEY(assessment_id, question_order)
            );
            CREATE TABLE IF NOT EXISTS assessment_proctoring_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                event_type TEXT NOT NULL,
                severity TEXT NOT NULL CHECK(severity IN ('Info', 'Warning', 'High')),
                message TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                duration_seconds INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assessment_proctoring_events_assessment_idx
                ON assessment_proctoring_events(assessment_id, occurred_at, id);
            CREATE INDEX IF NOT EXISTS assessment_proctoring_events_type_idx
                ON assessment_proctoring_events(event_type, occurred_at);
            CREATE INDEX IF NOT EXISTS assessments_candidate_idx ON assessments(candidate_id, status);
            CREATE INDEX IF NOT EXISTS assessments_job_idx ON assessments(job_id, status);
            CREATE TABLE IF NOT EXISTS assessment_recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                assessment_id INTEGER NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                cloudinary_public_id TEXT,
                cloudinary_asset_id TEXT,
                cloudinary_resource_type TEXT NOT NULL DEFAULT 'video',
                secure_url TEXT,
                duration_seconds INTEGER,
                file_size_bytes INTEGER,
                format TEXT,
                recording_status TEXT NOT NULL DEFAULT 'Pending'
                    CHECK(recording_status IN ('Pending', 'Uploading', 'Uploaded', 'Failed', 'Partial', 'Expired')),
                upload_error TEXT,
                started_at TEXT,
                ended_at TEXT,
                uploaded_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS assessment_recordings_assessment_idx ON assessment_recordings(assessment_id);
            CREATE INDEX IF NOT EXISTS assessment_recordings_candidate_idx ON assessment_recordings(candidate_id, created_at);
            CREATE TABLE IF NOT EXISTS admin_recording_access_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recording_id INTEGER NOT NULL REFERENCES assessment_recordings(id) ON DELETE CASCADE,
                admin_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                accessed_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS interviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                recruiter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                starts_at TEXT NOT NULL,
                teams_url TEXT NOT NULL DEFAULT '',
                meeting_platform TEXT NOT NULL DEFAULT 'Microsoft Teams',
                meeting_url TEXT NOT NULL DEFAULT '',
                duration_minutes INTEGER NOT NULL DEFAULT 60,
                timezone TEXT NOT NULL DEFAULT 'UTC',
                recruiter_message TEXT NOT NULL DEFAULT '',
                code TEXT NOT NULL DEFAULT '',
                language TEXT NOT NULL DEFAULT 'python',
                status TEXT NOT NULL DEFAULT 'Scheduled'
                    CHECK(status IN ('Scheduled', 'Rescheduled', 'Completed', 'Cancelled')),
                invitation_sent_at TEXT,
                candidate_viewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS interviews_recruiter_id_idx ON interviews(recruiter_id, starts_at);
            CREATE INDEX IF NOT EXISTS interviews_candidate_id_idx ON interviews(candidate_id, starts_at);
            """
        )
        interview_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'interviews'"
        ).fetchone()["sql"]
        if "Rescheduled" not in interview_sql:
            db.execute("ALTER TABLE interviews RENAME TO interviews_legacy")
            db.execute(
                """CREATE TABLE interviews (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
                    recruiter_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    starts_at TEXT NOT NULL,
                    teams_url TEXT NOT NULL DEFAULT '',
                    meeting_platform TEXT NOT NULL DEFAULT 'Microsoft Teams',
                    meeting_url TEXT NOT NULL DEFAULT '',
                    duration_minutes INTEGER NOT NULL DEFAULT 60,
                    timezone TEXT NOT NULL DEFAULT 'UTC',
                    recruiter_message TEXT NOT NULL DEFAULT '',
                    code TEXT NOT NULL DEFAULT '',
                    language TEXT NOT NULL DEFAULT 'python',
                    status TEXT NOT NULL DEFAULT 'Scheduled'
                        CHECK(status IN ('Scheduled', 'Rescheduled', 'Completed', 'Cancelled')),
                    invitation_sent_at TEXT,
                    candidate_viewed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            legacy_columns = {row["name"] for row in db.execute("PRAGMA table_info(interviews_legacy)")}
            code_column = "code" if "code" in legacy_columns else "''"
            language_column = "language" if "language" in legacy_columns else "'python'"
            db.execute(
                f"""INSERT INTO interviews
                (id, application_id, recruiter_id, candidate_id, starts_at, teams_url,
                meeting_platform, meeting_url, duration_minutes, timezone, recruiter_message,
                code, language, status, invitation_sent_at, candidate_viewed_at, created_at, updated_at)
                SELECT id, application_id, recruiter_id, candidate_id, starts_at, teams_url,
                'Microsoft Teams', teams_url, 60, 'UTC', '', {code_column}, {language_column},
                status, NULL, NULL, created_at, created_at FROM interviews_legacy"""
            )
            db.execute("DROP TABLE interviews_legacy")
        else:
            interview_columns = {row["name"] for row in db.execute("PRAGMA table_info(interviews)")}
            for column, definition in (
                ("meeting_platform", "TEXT NOT NULL DEFAULT 'Microsoft Teams'"),
                ("meeting_url", "TEXT NOT NULL DEFAULT ''"),
                ("duration_minutes", "INTEGER NOT NULL DEFAULT 60"),
                ("timezone", "TEXT NOT NULL DEFAULT 'UTC'"),
                ("recruiter_message", "TEXT NOT NULL DEFAULT ''"),
                ("invitation_sent_at", "TEXT"),
                ("candidate_viewed_at", "TEXT"),
                ("updated_at", "TEXT NOT NULL DEFAULT ''"),
            ):
                if column not in interview_columns:
                    db.execute(f"ALTER TABLE interviews ADD COLUMN {column} {definition}")
            db.execute("UPDATE interviews SET meeting_url = teams_url WHERE meeting_url = ''")
            db.execute("UPDATE interviews SET updated_at = created_at WHERE updated_at = ''")
        db.execute("CREATE INDEX IF NOT EXISTS interviews_application_idx ON interviews(application_id, created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS interviews_candidate_schedule_idx ON interviews(candidate_id, status, starts_at)")
        db.execute("CREATE INDEX IF NOT EXISTS interviews_recruiter_id_idx ON interviews(recruiter_id, starts_at)")
        db.execute("CREATE INDEX IF NOT EXISTS interviews_candidate_id_idx ON interviews(candidate_id, starts_at)")
        user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
        if "active" not in user_columns:
            db.execute("ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1")
        application_columns = {row["name"] for row in db.execute("PRAGMA table_info(applications)")}
        if "match_percentage" not in application_columns:
            db.execute("ALTER TABLE applications ADD COLUMN match_percentage INTEGER NOT NULL DEFAULT 0")
        for column, definition in (
            ("matched_skills_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("missing_skills_json", "TEXT NOT NULL DEFAULT '[]'"),
            ("internal_notes", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in application_columns:
                db.execute(f"ALTER TABLE applications ADD COLUMN {column} {definition}")
        assessment_columns = {row["name"] for row in db.execute("PRAGMA table_info(assessments)")}
        for column, definition in (
            ("expiry_warning_sent_at", "TEXT"),
            ("expired_at", "TEXT"),
            ("selection_reasoning", "TEXT NOT NULL DEFAULT ''"),
            ("assessment_name", "TEXT NOT NULL DEFAULT 'Round 1: Technical MCQ Test'"),
            ("assessment_round", "TEXT NOT NULL DEFAULT 'Round 1'"),
            ("pass_percentage", "REAL NOT NULL DEFAULT 75"),
            ("score_percentage", "REAL"),
            ("correct_answer_count", "INTEGER"),
            ("incorrect_answer_count", "INTEGER"),
            ("result", "TEXT CHECK(result IN ('Passed', 'Failed'))"),
            ("result_processed_at", "TEXT"),
            ("time_taken_seconds", "INTEGER"),
            ("proctoring_required", "INTEGER NOT NULL DEFAULT 1"),
            ("proctoring_status", "TEXT NOT NULL DEFAULT 'Not Started'"),
            ("warning_count", "INTEGER NOT NULL DEFAULT 0"),
            ("flagged_for_review", "INTEGER NOT NULL DEFAULT 0"),
            ("flagged_at", "TEXT"),
            ("camera_permission_granted_at", "TEXT"),
            ("last_face_detected_at", "TEXT"),
            ("recording_required", "INTEGER NOT NULL DEFAULT 1"),
            ("recording_consent_given_at", "TEXT"),
            ("recording_consent_version", "TEXT DEFAULT '1.0'"),
            ("recording_status", "TEXT NOT NULL DEFAULT 'Pending'"),
            ("recording_failure_reason", "TEXT"),
            ("recording_available_at", "TEXT"),
        ):
            if column not in assessment_columns:
                db.execute(f"ALTER TABLE assessments ADD COLUMN {column} {definition}")
        job_question_columns = {row["name"] for row in db.execute("PRAGMA table_info(job_questions)")}
        if "source_type" not in job_question_columns:
            db.execute("ALTER TABLE job_questions ADD COLUMN source_type TEXT NOT NULL DEFAULT 'manual'")
        if "source_import_id" not in job_question_columns:
            db.execute(
                "ALTER TABLE job_questions ADD COLUMN source_import_id INTEGER REFERENCES question_bank_imports(id) ON DELETE SET NULL"
            )
        db.execute(
            "CREATE INDEX IF NOT EXISTS question_bank_imports_job_idx ON question_bank_imports(job_id, created_at)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS applications_job_status_idx ON applications(job_id, status)"
        )
        db.execute(
            "CREATE INDEX IF NOT EXISTS jobs_recruiter_status_idx ON jobs(recruiter_id, status)"
        )
        assessment_question_columns = {
            row["name"] for row in db.execute("PRAGMA table_info(assessment_questions)")
        }
        if "job_question_id" not in assessment_question_columns:
            db.execute(
                "ALTER TABLE assessment_questions ADD COLUMN job_question_id INTEGER REFERENCES job_questions(id) ON DELETE SET NULL"
            )
        db.execute(
            """UPDATE assessments SET assessment_name = ?, assessment_round = 'Round 1'
            WHERE assessment_name = '' OR assessment_round = ''""",
            (ROUND1_ASSESSMENT_NAME,),
        )
        db.execute(
            """UPDATE assessments SET
            score_percentage = COALESCE(score_percentage, score),
            correct_answer_count = COALESCE(correct_answer_count, CASE
                WHEN (SELECT COUNT(*) FROM assessment_questions question
                    WHERE question.assessment_id = assessments.id AND question.is_correct IS NOT NULL) > 0
                THEN (SELECT COUNT(*) FROM assessment_questions question
                    WHERE question.assessment_id = assessments.id AND question.is_correct = 1)
                ELSE CAST(ROUND(COALESCE(score, 0) * total_questions / 100.0) AS INTEGER)
            END),
            incorrect_answer_count = COALESCE(incorrect_answer_count, total_questions - (
                CASE
                    WHEN (SELECT COUNT(*) FROM assessment_questions question
                        WHERE question.assessment_id = assessments.id AND question.is_correct IS NOT NULL) > 0
                    THEN (SELECT COUNT(*) FROM assessment_questions question
                        WHERE question.assessment_id = assessments.id AND question.is_correct = 1)
                    ELSE CAST(ROUND(COALESCE(score, 0) * total_questions / 100.0) AS INTEGER)
                END
            )),
            result = COALESCE(result, CASE WHEN COALESCE(score, 0) >= pass_percentage THEN 'Passed' ELSE 'Failed' END),
            result_processed_at = COALESCE(result_processed_at, submitted_at)
            WHERE status = 'Completed'"""
        )
        db.execute("UPDATE applications SET status = 'Accepted' WHERE status = 'Selected'")
        db.execute(
            """INSERT INTO application_status_history (application_id, status, updated_at)
            SELECT application.id, application.status, application.applied_at
            FROM applications application
            WHERE NOT EXISTS (
                SELECT 1 FROM application_status_history history
                WHERE history.application_id = application.id
            )"""
        )
        db.execute(
            """UPDATE applications SET status = (
                SELECT 'Round 1 ' || assessment.result FROM assessments assessment
                WHERE assessment.application_id = applications.id
                AND assessment.status = 'Completed' AND assessment.result IN ('Passed', 'Failed')
            )
            WHERE status IN ('Applied', 'Under Review', 'Shortlisted', 'Assessment Sent',
                'Assessment Started', 'Assessment Completed')
            AND EXISTS (
                SELECT 1 FROM assessments assessment
                WHERE assessment.application_id = applications.id
                AND assessment.status = 'Completed' AND assessment.result IN ('Passed', 'Failed')
            )"""
        )
        db.execute(
            """INSERT INTO application_status_history (application_id, status, updated_at)
            SELECT application.id, 'Round 1 ' || assessment.result,
                COALESCE(assessment.result_processed_at, assessment.submitted_at, :now)
            FROM applications application JOIN assessments assessment
                ON assessment.application_id = application.id
            WHERE assessment.status = 'Completed' AND assessment.result IN ('Passed', 'Failed')
            AND NOT EXISTS (
                SELECT 1 FROM application_status_history history
                WHERE history.application_id = application.id
                AND history.status = 'Round 1 ' || assessment.result
            )""",
            {"now": now()},
        )
        for technology, questions in QUESTION_BANKS.items():
            db.executemany(
                """INSERT OR IGNORE INTO technical_questions
                (technology, question, options_json, correct_index, difficulty, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    (technology, question, json.dumps(options), correct_index, difficulty, now())
                    for question, options, correct_index, difficulty in questions
                ],
            )
        if IS_PRODUCTION:
            admin_email = os.environ.get("SKILLSPHERE_ADMIN_EMAIL")
            admin_password = os.environ.get("SKILLSPHERE_ADMIN_PASSWORD")
            if admin_email and admin_password and not db.execute(
                "SELECT 1 FROM users WHERE email = ?", (admin_email,)
            ).fetchone():
                db.execute(
                    "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
                    ("SkillSphere Admin", admin_email, password_hash(admin_password), now()),
                )
            return
        if db.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
            return
        users = [
            ("Alex Morgan", "candidate@skillsphere.dev", password_hash("Demo123!"), "candidate", '{"location":"Brooklyn, NY"}', now()),
            ("Jamie Rivera", "recruiter@skillsphere.dev", password_hash("Demo123!"), "recruiter", '{"company":"Northstar"}', now()),
            ("Avery Chen", "admin@skillsphere.dev", password_hash("Demo123!"), "admin", "{}", now()),
        ]
        if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production":
            admin_email = os.environ.get("SKILLSPHERE_ADMIN_EMAIL")
            admin_password = os.environ.get("SKILLSPHERE_ADMIN_PASSWORD")
            if admin_email and admin_password:
                db.execute(
                    "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, 'admin', ?)",
                    ("SkillSphere Admin", admin_email, password_hash(admin_password), now()),
                )
            return
        db.executemany(
            "INSERT INTO users (name, email, password_hash, role, profile_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            users,
        )
        recruiter_id = db.execute("SELECT id FROM users WHERE email = ?", ("recruiter@skillsphere.dev",)).fetchone()["id"]
        jobs = [
            ("Product Designer", "Northstar", "Shape clear, human-centered product experiences from early discovery through thoughtful delivery. Partner with product and engineering to make complex workflows feel effortless.", "New York, NY", "2–4 years", "Full-time", "$95k – $125k", ["Figma", "UX research", "Prototyping", "Design systems"]),
            ("Frontend Engineer", "Layer", "Help us make useful tools feel delightful. Build accessible, polished interfaces with a product-minded team that cares about performance, collaboration, and the details.", "Remote · US", "3–5 years", "Remote", "$110k – $145k", ["React", "TypeScript", "CSS", "Accessibility"]),
            ("Data Analyst", "Goodkind", "Turn questions into insights that help our teams and customers make better decisions. Work across product analytics, experimentation, and clear data storytelling.", "Austin, TX", "1–3 years", "Full-time", "$82k – $105k", ["SQL", "Python", "Tableau", "Analytics"]),
            ("People Operations Partner", "Fieldwork", "Create warm, thoughtful experiences across the employee journey. Help build scalable people programs in a growing, remote-friendly company.", "Remote · US", "3–6 years", "Remote", "$88k – $118k", ["People ops", "HR", "Communication", "Operations"]),
            ("Marketing Associate", "Sunday Studio", "Bring a curious, creative perspective to campaigns that help more people discover our work. You'll collaborate across content, community, and growth.", "Brooklyn, NY", "1–2 years", "Full-time", "$65k – $82k", ["Content", "Social media", "Writing", "Marketing"]),
            ("Backend Engineer", "Northstar", "Build dependable APIs and thoughtfully designed services for a growing product. We value ownership, clear communication, and pragmatic engineering.", "New York, NY", "4–6 years", "Contract", "$125k – $160k", ["Python", "FastAPI", "PostgreSQL", "APIs"]),
        ]
        seeded_at = now()
        db.executemany(
            """INSERT INTO jobs
            (recruiter_id, title, company, description, location, experience, job_type, salary, skills_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [(recruiter_id, *job[:7], json.dumps(job[7]), seeded_at) for job in jobs],
        )


def public_job(row: sqlite3.Row) -> dict[str, Any]:
    job = dict(row)
    job["skills"] = json.loads(job.pop("skills_json"))
    return job


def public_resume(row: sqlite3.Row) -> dict[str, Any]:
    resume = dict(row)
    resume.pop("storage_path", None)
    resume.pop("extracted_text", None)
    resume["parsed_profile"] = json.loads(resume.pop("parsed_profile_json") or "{}")
    return resume


def public_application(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def insert_notification(
    db: sqlite3.Connection,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    application_id: int | None = None,
    assessment_id: int | None = None,
    action_url: str | None = None,
    email_delivery_status: str = "not_requested",
) -> int:
    cursor = db.execute(
        """INSERT INTO notifications
        (user_id, type, title, message, related_application_id, related_assessment_id,
        action_url, email_delivery_status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            notification_type,
            title,
            message,
            application_id,
            assessment_id,
            action_url,
            email_delivery_status,
            now(),
        ),
    )
    return cursor.lastrowid


def notify_user(
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    application_id: int | None = None,
    assessment_id: int | None = None,
    action_url: str | None = None,
    send_email: bool = False,
    email_delivery_status: str = "not_requested",
) -> int:
    with connect() as db:
        user = db.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user:
            raise RuntimeError(f"Cannot create notification for missing user {user_id}.")
        notification_id = insert_notification(
            db,
            user_id,
            notification_type,
            title,
            message,
            application_id,
            assessment_id,
            action_url,
            "pending" if send_email else email_delivery_status,
        )
    if send_email:
        try:
            delivery = send_notification_email(user["email"], title, message, action_url)
            status = "sent" if delivery == "email" else "development_console"
        except EmailDeliveryError as error:
            logger.error("Notification email delivery failed for user %s: %s", user_id, error)
            status = "failed"
        with connect() as db:
            db.execute(
                "UPDATE notifications SET email_delivery_status = ? WHERE id = ?",
                (status, notification_id),
            )
    return notification_id


def notify_admins(
    notification_type: str,
    title: str,
    message: str,
    action_url: str | None = None,
    send_email: bool = False,
    application_id: int | None = None,
    assessment_id: int | None = None,
) -> None:
    with connect() as db:
        admin_ids = [
            row["id"] for row in db.execute(
                "SELECT id FROM users WHERE role = 'admin' AND active = 1"
            ).fetchall()
        ]
    for admin_id in admin_ids:
        notify_user(
            admin_id,
            notification_type,
            title,
            message,
            application_id=application_id,
            assessment_id=assessment_id,
            action_url=action_url,
            send_email=send_email,
        )


def application_history(db: sqlite3.Connection, application_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT history.status, history.updated_at, history.recruiter_note,
        actor.name AS actor_name
        FROM application_status_history history
        LEFT JOIN users actor ON actor.id = history.actor_user_id
        WHERE history.application_id = ? ORDER BY history.updated_at, history.id""",
        (application_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def application_transition_allowed(
    current_status: str,
    next_status: str,
    match_percentage: int,
) -> bool:
    current_status = "Accepted" if current_status == "Selected" else current_status
    next_status = "Accepted" if next_status == "Selected" else next_status
    allowed = {
        "Applied": {"Under Review", "Shortlisted", "Interview", "Rejected"},
        "Under Review": {"Shortlisted", "Interview", "Rejected"},
        "Shortlisted": {"Assessment Sent", "Assessment Started", "Assessment Completed", "Interview", "Rejected"},
        "Assessment Sent": {"Assessment Started", "Assessment Completed", "Interview", "Rejected"},
        "Assessment Started": {"Assessment Completed", "Rejected"},
        "Assessment Completed": {"Round 1 Passed", "Round 1 Failed", "Rejected"},
        "Round 1 Passed": {"Interview", "Accepted", "Rejected"},
        "Round 1 Failed": {"Rejected"},
        "Interview": {"Accepted", "Rejected"},
        "Accepted": set(),
        "Rejected": set(),
        "Withdrawn": set(),
    }
    if next_status == current_status:
        return True
    if next_status == "Shortlisted" and match_percentage < ASSESSMENT_MATCH_THRESHOLD:
        return False
    return next_status in allowed.get(current_status, set())


def record_application_status(
    db: sqlite3.Connection,
    application_id: int,
    status: str,
    actor_user_id: int | None,
    note: str | None = None,
) -> None:
    db.execute("UPDATE applications SET status = ? WHERE id = ?", (status, application_id))
    if note:
        db.execute(
            """UPDATE applications SET internal_notes =
            CASE WHEN internal_notes = '' THEN ? ELSE internal_notes || char(10) || ? END
            WHERE id = ?""",
            (note.strip(), note.strip(), application_id),
        )
    db.execute(
        """INSERT INTO application_status_history
        (application_id, status, updated_at, actor_user_id, recruiter_note)
        VALUES (?, ?, ?, ?, ?)""",
        (application_id, status, now(), actor_user_id, note),
    )


def skill_matches(skill: str, text: str) -> bool:
    clean = skill.strip()
    if not clean:
        return False
    pattern = rf"(?<!\w){re.escape(clean)}(?!\w)"
    return bool(re.search(pattern, text, re.IGNORECASE))


def calculate_match(
    required_skills: list[str],
    extracted_text: str,
    parsed_profile_json: str,
    saved_profile_json: str,
) -> dict[str, Any]:
    parsed_profile = json.loads(parsed_profile_json or "{}")
    saved_profile = json.loads(saved_profile_json or "{}")
    extracted_skills = parsed_profile.get("skills", [])
    saved_skills = saved_profile.get("skills", [])
    if not isinstance(extracted_skills, list) or not all(isinstance(skill, str) for skill in extracted_skills):
        raise HTTPException(status_code=500, detail="The saved resume profile is invalid")
    if not isinstance(saved_skills, list) or not all(isinstance(skill, str) for skill in saved_skills):
        raise HTTPException(status_code=422, detail="Profile skills must be a list of text values")
    candidate_text = f"{extracted_text} {' '.join([*extracted_skills, *saved_skills])}".lower()
    matched = [skill for skill in required_skills if skill_matches(skill, candidate_text)]
    missing = [skill for skill in required_skills if not skill_matches(skill, candidate_text)]
    percentage = round(len(matched) / len(required_skills) * 100) if required_skills else 0
    return {
        "match_percentage": percentage,
        "matched_skills": matched,
        "missing_skills": missing,
        "candidate_text": candidate_text,
    }


def assessment_public_url() -> str:
    base_url = (
        os.environ.get("SKILLSPHERE_PUBLIC_BASE_URL")
        or os.environ.get("SKILLSPHERE_PUBLIC_URL")
        or "http://127.0.0.1:8000"
    ).strip().rstrip("/")
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=503, detail="Set SKILLSPHERE_PUBLIC_BASE_URL to a valid public app URL.")
    if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production" and not (
        os.environ.get("SKILLSPHERE_PUBLIC_BASE_URL") or os.environ.get("SKILLSPHERE_PUBLIC_URL")
    ):
        raise HTTPException(status_code=503, detail="SKILLSPHERE_PUBLIC_BASE_URL is required to send assessment links.")
    return base_url


def assessment_settings() -> tuple[int, int]:
    try:
        ttl_hours = int(os.environ.get("SKILLSPHERE_ASSESSMENT_TTL_HOURS", "48"))
        duration_minutes = int(os.environ.get("SKILLSPHERE_ASSESSMENT_DURATION_MINUTES", "30"))
    except ValueError as error:
        raise HTTPException(status_code=503, detail="Assessment expiry and duration settings must be valid integers.") from error
    if ttl_hours < 1 or duration_minutes < 1:
        raise HTTPException(status_code=503, detail="Assessment expiry and duration settings must be positive.")
    return ttl_hours, duration_minutes


def assessment_candidate_data(db: sqlite3.Connection, application_id: int) -> sqlite3.Row:
    row = db.execute(
        """SELECT a.id, a.candidate_id, a.job_id, a.status AS application_status,
        j.recruiter_id, j.title, j.company, j.skills_json, candidate.email,
        candidate.profile_json, resume.extracted_text, resume.parsed_profile_json
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        JOIN users candidate ON candidate.id = a.candidate_id
        LEFT JOIN resumes resume ON resume.id = a.resume_id
        WHERE a.id = ?""",
        (application_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Application not found")
    return row


def interview_public_payload(row: sqlite3.Row, user: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    if user["role"] == "candidate":
        end_time = datetime.fromisoformat(row["starts_at"]) + timedelta(
            minutes=row["duration_minutes"]
        )
        ended = end_time <= datetime.now(timezone.utc)
        if row["status"] in {"Cancelled", "Completed"} or ended:
            result["meeting_url"] = ""
            result["teams_url"] = ""
    return result


def match_application(row: sqlite3.Row) -> dict[str, Any]:
    return calculate_match(
        json.loads(row["skills_json"]),
        row["extracted_text"] or "",
        row["parsed_profile_json"] or "{}",
        row["profile_json"] or "{}",
    )


def assessment_questions_for_client(db: sqlite3.Connection, assessment_id: int) -> list[dict[str, Any]]:
    rows = db.execute(
        """SELECT question_order, question_text, options_json, selected_answer
        FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order""",
        (assessment_id,),
    ).fetchall()
    return [
        {
            "number": row["question_order"],
            "question": row["question_text"],
            "options": json.loads(row["options_json"]),
            "selected_answer": row["selected_answer"],
        }
        for row in rows
    ]


def valid_question_is_valid(row: sqlite3.Row) -> bool:
    try:
        options = json.loads(row["options_json"])
        return (
            isinstance(options, list)
            and len(options) == 4
            and all(isinstance(option, str) and option.strip() for option in options)
            and 0 <= int(row["correct_index"]) <= 3
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return False


def question_fingerprint(technology: str, question: str) -> tuple[str, str]:
    normalize = lambda value: re.sub(
        r"\s+", " ", re.sub(r"[^\w]+", " ", value.casefold(), flags=re.UNICODE)
    ).strip()
    return normalize(technology), normalize(question)


def parse_question_bank_text(text: str) -> dict[str, Any]:
    valid: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    technology_context = ""
    difficulty_context = "Medium"
    current: dict[str, Any] | None = None

    def finish() -> None:
        nonlocal current
        if current is None:
            return
        question_number = len(blocks) + 1
        question_text = " ".join(current["question_parts"]).strip()
        options = [current["options"].get(letter, "").strip() for letter in "ABCD"]
        reasons: list[str] = []
        reasons.extend(current["parse_errors"])
        if not current["technology"]:
            reasons.append(f"Question {question_number} is missing Technology.")
        if not question_text:
            reasons.append(f"Question {question_number} is missing question text.")
        elif len(question_text) < 5:
            reasons.append(f"Question {question_number} is too short to be a valid question.")
        for letter in "ABCD":
            if letter not in current["options"] or not current["options"][letter].strip():
                reasons.append(f"Question {question_number} is missing option {letter}.")
        if current["extra_options"]:
            reasons.append(f"Question {question_number} must have exactly options A, B, C, and D.")
        if len(current["options"]) != 4:
            exact_options = False
        else:
            exact_options = set(current["options"]) == set("ABCD")
        answer = current["answer"]
        if not isinstance(answer, str) or answer.strip().upper() not in set("ABCD"):
            reasons.append(f"Question {question_number} has no valid Answer field.")
        if current["difficulty"] not in {"Easy", "Medium", "Hard"}:
            reasons.append(f"Question {question_number} has an invalid Difficulty.")
        if len(current["technology"]) > 40 or len(question_text) > 2_000 or any(len(option) > 1_000 for option in options):
            reasons.append(f"Question {question_number} exceeds the supported field length.")
        record = {
            "question_number": question_number,
            "technology": current["technology"].strip(),
            "difficulty": current["difficulty"],
            "question": question_text,
            "options": options,
            "correct_index": "ABCD".find(answer.strip().upper()) if isinstance(answer, str) else -1,
        }
        if not exact_options and not any("exactly options" in reason for reason in reasons):
            reasons.append(f"Question {question_number} must have exactly options A, B, C, and D.")
        blocks.append(record)
        if reasons:
            invalid.append({
                "question_number": question_number,
                "question": question_text,
                "reasons": list(dict.fromkeys(reasons)),
            })
        else:
            valid.append(record)
        current = None

    for raw_line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        field = re.match(r"^(Technology|Difficulty)\s*:\s*(.*)$", line, re.I)
        if field:
            if current is not None:
                finish()
            key, value = field.group(1).lower(), field.group(2).strip()
            if key == "technology":
                technology_context = value
                difficulty_context = "Medium"
            else:
                difficulty_context = value.title() if value else "Medium"
            continue
        question = re.match(r"^Question\s*:\s*(.*)$", line, re.I)
        if question:
            finish()
            current = {
                "technology": technology_context,
                "difficulty": difficulty_context or "Medium",
                "question_parts": [question.group(1).strip()] if question.group(1).strip() else [],
                "options": {},
                "extra_options": [],
                "answer": None,
                "parse_errors": [],
            }
            continue
        if current is None:
            continue
        answer_match = re.match(r"^Answer\s*:\s*(.*)$", line, re.I)
        if answer_match:
            if current["answer"] is not None:
                current["parse_errors"].append("The question contains more than one Answer field.")
            current["answer"] = answer_match.group(1).strip()
            continue
        option_match = re.match(r"^([A-Z])\s*[.):]\s*(.*)$", line)
        if option_match:
            letter, value = option_match.group(1), option_match.group(2).strip()
            if letter in "ABCD":
                if letter in current["options"]:
                    current["extra_options"].append(letter)
                current["options"][letter] = value
            else:
                current["extra_options"].append(letter)
            continue
        if current["options"]:
            last_letter = next(reversed(current["options"]))
            current["options"][last_letter] = f"{current['options'][last_letter]} {line}".strip()
        else:
            current["question_parts"].append(line)
    finish()

    seen: set[tuple[str, str]] = set()
    unique_valid: list[dict[str, Any]] = []
    for record in valid:
        fingerprint = question_fingerprint(record["technology"], record["question"])
        if fingerprint in seen:
            invalid.append({
                "question_number": record["question_number"],
                "question": record["question"],
                "reasons": [f"Question {record['question_number']} duplicates an earlier question in this PDF."],
            })
        else:
            seen.add(fingerprint)
            unique_valid.append(record)
    if not blocks:
        invalid.append({
            "question_number": None,
            "question": "",
            "reasons": ["No supported MCQ blocks were found. Please use the provided template."],
        })

    technology_counts: dict[str, int] = {}
    difficulty_counts: dict[str, int] = {}
    for question in unique_valid:
        technology_counts[question["technology"]] = technology_counts.get(question["technology"], 0) + 1
        difficulty_counts[question["difficulty"]] = difficulty_counts.get(question["difficulty"], 0) + 1
    return {
        "total_questions": len(blocks),
        "valid_questions": unique_valid,
        "invalid_questions": invalid,
        "technology_counts": technology_counts,
        "difficulty_counts": difficulty_counts,
    }


def extract_question_bank_pdf_text(content: bytes) -> str:
    import io
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as error:
        raise HTTPException(status_code=422, detail="This PDF is unreadable or corrupted.") from error
    if len(reader.pages) > MAX_QUESTION_BANK_PDF_PAGES:
        raise HTTPException(
            status_code=422,
            detail=f"This PDF has too many pages. Upload a document with {MAX_QUESTION_BANK_PDF_PAGES} pages or fewer.",
        )
    try:
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except Exception as error:
        raise HTTPException(status_code=422, detail="Text could not be extracted from this PDF.") from error
    if text:
        return text

    try:
        import pypdfium2 as pdfium
        import pytesseract

        document = pdfium.PdfDocument(content)
        pages = [
            pytesseract.image_to_string(document[index].render(scale=1.5).to_pil())
            for index in range(len(document))
        ]
    except Exception as error:
        if error.__class__.__name__ == "TesseractNotFoundError":
            raise HTTPException(
                status_code=422,
                detail="No readable text was found in this PDF. Install Tesseract OCR to import scanned PDFs.",
            ) from error
        raise HTTPException(
            status_code=422,
            detail="No readable text was found in this PDF. Check that OCR is installed for scanned PDFs.",
        ) from error
    text = "\n".join(pages).strip()
    if not text:
        raise HTTPException(status_code=422, detail="No readable text was found in this PDF.")
    return text


def question_bank_count(db: sqlite3.Connection, job_id: int) -> tuple[int, dict[str, int]]:
    rows = db.execute(
        """SELECT technology, difficulty, options_json, correct_index
        FROM job_questions WHERE job_id = ? AND active = 1""",
        (job_id,),
    ).fetchall()
    by_technology: dict[str, int] = {}
    total = 0
    for row in rows:
        if valid_question_is_valid(row):
            total += 1
            by_technology[row["technology"]] = by_technology.get(row["technology"], 0) + 1
    return total, by_technology


def select_job_assessment_questions(
    rows: list[sqlite3.Row],
    candidate_text: str = "",
    required_skills: list[str] | None = None,
    required_count: int = 20,
    selected_topic: str | None = None,
) -> list[sqlite3.Row]:
    valid_rows = [row for row in rows if valid_question_is_valid(row)]
    required_skills = required_skills or []
    lowered_candidate = candidate_text.casefold()

    def contains_term(text: str, term: str) -> bool:
        escaped = re.escape(term.strip())
        escaped = re.sub(r"\\\s+", r"\\s+", escaped)
        return bool(re.search(rf"(?<!\w){escaped}(?!\w)", text, re.I))

    required_topics = {skill.strip().casefold() for skill in required_skills if skill.strip()}
    relevant_topics = {
        row["technology"] for row in valid_rows
        if (
            row["technology"].casefold() in required_topics
            and contains_term(lowered_candidate, row["technology"])
            and (not selected_topic or row["technology"].casefold() == selected_topic.casefold())
        )
    }
    if selected_topic and not relevant_topics:
        relevant_topics = {
            row["technology"] for row in valid_rows
            if row["technology"].casefold() == selected_topic.casefold()
        }
    eligible = [row for row in valid_rows if row["technology"] in relevant_topics]
    chooser = secrets.SystemRandom()
    required_order = {skill.strip().casefold(): index for index, skill in enumerate(required_skills)}
    technologies = sorted(
        relevant_topics,
        key=lambda technology: (
            required_order.get(technology.casefold(), len(required_order)),
            technology.casefold(),
        ),
    )
    topic_weights = {
        technology: min(
            5,
            max(
                1,
                len(re.findall(
                    r"(?<!\w)" + re.sub(r"\\\s+", r"\\s+", re.escape(technology.strip())) + r"(?!\w)",
                    lowered_candidate,
                    re.I,
                )),
            ),
        )
        for technology in technologies
    }
    buckets: dict[str, dict[str, list[sqlite3.Row]]] = {}
    for technology in technologies:
        buckets[technology] = {"Easy": [], "Medium": [], "Hard": []}
    for row in eligible:
        difficulty = row["difficulty"] if row["difficulty"] in {"Easy", "Medium", "Hard"} else "Medium"
        buckets[row["technology"]][difficulty].append(row)
    for difficulty_buckets in buckets.values():
        for bucket in difficulty_buckets.values():
            chooser.shuffle(bucket)
    selected: list[sqlite3.Row] = []
    selected_by_topic = {technology: 0 for technology in technologies}
    selected_by_difficulty = {
        technology: {"Easy": 0, "Medium": 0, "Hard": 0}
        for technology in technologies
    }
    while len(selected) < required_count and any(any(items for items in topic.values()) for topic in buckets.values()):
        available = [
            technology for technology in technologies
            if any(buckets[technology][difficulty] for difficulty in ("Easy", "Medium", "Hard"))
        ]
        if not available:
            break
        technology = max(
            available,
            key=lambda item: (
                topic_weights[item] / (selected_by_topic[item] + 1),
                -technologies.index(item),
            ),
        )
        topic_buckets = buckets[technology]
        available_difficulties = [
            difficulty for difficulty in ("Easy", "Medium", "Hard")
            if topic_buckets[difficulty]
        ]
        difficulty = min(
            available_difficulties,
            key=lambda item: (selected_by_difficulty[technology][item], ("Easy", "Medium", "Hard").index(item)),
        )
        selected.append(topic_buckets[difficulty].pop())
        selected_by_topic[technology] += 1
        selected_by_difficulty[technology][difficulty] += 1
    return selected


def send_assessment_invitation(application_id: int, selected_topic: str | None = None) -> dict[str, Any]:
    ttl_hours, duration_minutes = assessment_settings()
    pass_percentage = round1_pass_percentage()
    requires_proctoring = proctoring_required()
    token = secrets.token_urlsafe(32)
    with connect() as db:
        candidate = assessment_candidate_data(db, application_id)
        match = match_application(candidate)
        db.execute(
            "UPDATE applications SET match_percentage = ? WHERE id = ?",
            (match["match_percentage"], application_id),
        )
        if match["match_percentage"] < ASSESSMENT_MATCH_THRESHOLD:
            raise HTTPException(
                status_code=409,
                detail=f"Candidate match is {match['match_percentage']}%; at least {ASSESSMENT_MATCH_THRESHOLD}% is required.",
            )
        if candidate["application_status"] in {"Rejected", "Withdrawn", "Selected", "Accepted", "Interview"}:
            raise HTTPException(status_code=409, detail="This application is no longer eligible for an assessment.")
        recommended_topic = detect_assessment_topic(json.loads(candidate["skills_json"]), match["candidate_text"])
        question_rows = db.execute(
            """SELECT id, technology, question, options_json, correct_index, difficulty
            FROM job_questions
            WHERE job_id = ? AND active = 1""",
            (candidate["job_id"],),
        ).fetchall()
        required_skills = json.loads(candidate["skills_json"])
        questions = select_job_assessment_questions(
            question_rows,
            match["candidate_text"],
            required_skills,
            selected_topic=selected_topic,
        )
        if not selected_topic and not recommended_topic and not questions:
            raise HTTPException(
                status_code=422,
                detail="Select an assessment topic manually; no relevant job-bank technology could be detected.",
            )
        if len(questions) < 20:
            valid_count = len(questions)
            question_topics = sorted({question["technology"] for question in questions})
            raise HTTPException(
                status_code=409,
                detail=f"The relevant question bank for this job has {valid_count} valid active questions; add {20 - valid_count} more before sending an assessment.",
            )
        selected_topics = list(dict.fromkeys(question["technology"] for question in questions))
        technology = selected_topic or ", ".join(selected_topics)
        reasoning = (
            "Selected active questions only from this job's bank. Topics were chosen where the technology "
            "appears in both the candidate profile/resume and the job's required skills; questions were "
            "distributed across available relevant topics and Easy/Medium/Hard difficulty."
        )
        existing = db.execute(
            "SELECT id, status, starts_at FROM assessments WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if existing and existing["status"] == "Completed":
            raise HTTPException(status_code=409, detail="The candidate has already completed this assessment.")
        if existing and existing["status"] == "Started":
            raise HTTPException(status_code=409, detail="The candidate has already started this assessment.")
        if existing and existing["starts_at"] is not None:
            raise HTTPException(status_code=409, detail="An assessment attempt has already started and cannot be reissued.")
        created_at = now()
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=ttl_hours)).isoformat()
        if existing:
            assessment_id = existing["id"]
            db.execute(
                """UPDATE assessments SET technology = ?, token_hash = ?, status = 'Not Sent',
                match_percentage = ?, starts_at = NULL, expires_at = ?, submitted_at = NULL,
                expired_at = NULL, expiry_warning_sent_at = NULL,
                score = NULL, total_questions = 20, assessment_name = ?, assessment_round = 'Round 1',
                pass_percentage = ?, score_percentage = NULL, correct_answer_count = NULL,
                incorrect_answer_count = NULL, result = NULL, result_processed_at = NULL,
                time_taken_seconds = NULL, duration_minutes = ?, email_sent_at = NULL,
                selection_reasoning = ?, proctoring_required = ?,
                proctoring_status = 'Not Started', warning_count = 0,
                flagged_for_review = 0, flagged_at = NULL,
                camera_permission_granted_at = NULL, last_face_detected_at = NULL,
                created_at = ? WHERE id = ?""",
                (
                    technology, hashlib.sha256(token.encode()).hexdigest(), match["match_percentage"],
                    expires_at, ROUND1_ASSESSMENT_NAME, pass_percentage, duration_minutes,
                    reasoning, int(requires_proctoring), created_at, assessment_id,
                ),
            )
            db.execute("DELETE FROM assessment_questions WHERE assessment_id = ?", (assessment_id,))
        else:
            cursor = db.execute(
                """INSERT INTO assessments
                (application_id, candidate_id, job_id, technology, token_hash, status,
                match_percentage, expires_at, total_questions, assessment_name, assessment_round,
                pass_percentage, duration_minutes, selection_reasoning, proctoring_required, recording_required, created_at)
                VALUES (?, ?, ?, ?, ?, 'Not Sent', ?, ?, 20, ?, 'Round 1', ?, ?, ?, ?, ?, ?)""",
                (
                    application_id, candidate["candidate_id"], candidate["job_id"], technology,
                    hashlib.sha256(token.encode()).hexdigest(), match["match_percentage"],
                    expires_at, ROUND1_ASSESSMENT_NAME, pass_percentage, duration_minutes,
                    reasoning, int(requires_proctoring), int(recording_required()), created_at,
                ),
            )
            assessment_id = cursor.lastrowid
        db.executemany(
            """INSERT INTO assessment_questions
            (assessment_id, job_question_id, question_order, question_text, options_json, correct_index, difficulty, topic)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (assessment_id, question["id"], order, question["question"], question["options_json"],
                 question["correct_index"], question["difficulty"], question["technology"])
                for order, question in enumerate(questions, start=1)
            ],
        )
        email = candidate["email"]
        job_title = candidate["title"]
        company = candidate["company"]
        recruiter_id = candidate["recruiter_id"]

    url = f"{assessment_public_url()}/assessment?token={token}"
    try:
        delivery = send_assessment_email(
            email, url, technology, job_title, company, duration_minutes, expires_at,
            ROUND1_ASSESSMENT_NAME, pass_percentage,
        )
    except EmailDeliveryError as error:
        logger.error("Assessment invitation delivery failed for application %s: %s", application_id, error)
        with connect() as db:
            assessment_row = db.execute(
                "SELECT id FROM assessments WHERE application_id = ?", (application_id,)
            ).fetchone()
        notify_user(
            recruiter_id,
            "email_delivery_failed",
            "Assessment invitation could not be delivered",
            f"The assessment email for {job_title} at {company} failed. Reissue it after checking SMTP configuration.",
            application_id=application_id,
            assessment_id=assessment_row["id"],
            action_url="/",
            send_email=True,
        )
        notify_admins(
            "email_delivery_failed",
            "Assessment email delivery failed",
            f"An assessment invitation for {job_title} at {company} could not be delivered.",
            "/",
        )
        return {
            "application_id": application_id,
            "status": "Shortlisted",
            "assessment_status": "Not Sent",
            "technology": technology,
            "match_percentage": match["match_percentage"],
            "delivery_error": str(error),
        }
    with connect() as db:
        assessment_row = db.execute(
            "SELECT id FROM assessments WHERE application_id = ?", (application_id,)
        ).fetchone()
        db.execute(
            "UPDATE assessments SET status = 'Sent', email_sent_at = ? WHERE id = ? AND status = 'Not Sent'",
            (now(), assessment_id),
        )
        application = db.execute(
            "SELECT status, match_percentage FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if application["status"] in {"Shortlisted", "Under Review", "Applied"}:
            record_application_status(db, application_id, "Assessment Sent", None)
    notify_user(
        candidate["candidate_id"],
        "assessment_sent",
        "Your assessment link is ready",
        f"Your {technology} assessment for {job_title} at {company} has been sent to your registered email address.",
        application_id=application_id,
        assessment_id=assessment_row["id"],
        action_url="/",
        email_delivery_status="sent" if delivery == "email" else "development_console",
    )
    notify_user(
        recruiter_id,
        "assessment_sent",
        "Assessment invitation sent",
        f"A {technology} assessment invitation was sent for {job_title} at {company}.",
        application_id=application_id,
        assessment_id=assessment_row["id"],
        action_url="/",
    )
    notify_admins(
        "assessment_sent",
        "Assessment invitation sent",
        f"A {technology} assessment was sent for {job_title} at {company}.",
        "/",
    )
    result = {
        "application_id": application_id,
        "status": "Assessment Sent",
        "assessment_status": "Sent",
        "technology": technology,
        "match_percentage": match["match_percentage"],
        "email_sent_at": now(),
        "delivery": delivery,
    }
    return result


def save_manual_topic_required(application_id: int, match_percentage: int) -> None:
    with connect() as db:
        candidate = assessment_candidate_data(db, application_id)
        existing = db.execute(
            "SELECT id, status FROM assessments WHERE application_id = ?", (application_id,)
        ).fetchone()
        if existing and existing["status"] in {"Completed", "Started"}:
            return
        if existing:
            db.execute(
                """UPDATE assessments SET technology = NULL, token_hash = NULL,
                status = 'Manual Topic Required', match_percentage = ?, starts_at = NULL,
                expires_at = NULL, submitted_at = NULL, score = NULL,
                score_percentage = NULL, correct_answer_count = NULL, incorrect_answer_count = NULL,
                result = NULL, result_processed_at = NULL, time_taken_seconds = NULL,
                email_sent_at = NULL
                WHERE id = ?""",
                (match_percentage, existing["id"]),
            )
            db.execute("DELETE FROM assessment_questions WHERE assessment_id = ?", (existing["id"],))
        else:
            db.execute(
                """INSERT INTO assessments
                (application_id, candidate_id, job_id, status, match_percentage, created_at)
                VALUES (?, ?, ?, 'Manual Topic Required', ?, ?)""",
                (application_id, candidate["candidate_id"], candidate["job_id"], match_percentage, now()),
            )


def expire_assessment(assessment_id: int) -> bool:
    with connect() as db:
        row = db.execute(
            """SELECT assessment.status, assessment.application_id, assessment.candidate_id,
            assessment.job_id, job.recruiter_id, job.title, job.company
            FROM assessments assessment JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.id = ?""",
            (assessment_id,),
        ).fetchone()
        if not row or row["status"] not in {"Sent", "Started"}:
            return False
        db.execute(
            "UPDATE assessments SET status = 'Expired', token_hash = NULL, expired_at = ? WHERE id = ?",
            (now(), assessment_id),
        )
    message = f"The assessment for {row['title']} at {row['company']} expired."
    notify_user(
        row["candidate_id"], "assessment_expired", "Assessment expired", message,
        application_id=row["application_id"], assessment_id=assessment_id, action_url="/",
    )
    notify_user(
        row["recruiter_id"], "assessment_expired", "Candidate assessment expired", message,
        application_id=row["application_id"], assessment_id=assessment_id, action_url="/",
    )
    notify_admins("assessment_expired", "Assessment expired", message, "/")
    return True


def notify_expiring_assessments(user: dict[str, Any]) -> None:
    current_time = datetime.now(timezone.utc)
    warning_limit = (current_time + timedelta(hours=24)).isoformat()
    scope_sql = ""
    scope_values: list[Any] = []
    if user["role"] == "candidate":
        scope_sql = "AND assessment.candidate_id = ?"
        scope_values.append(user["id"])
    elif user["role"] == "recruiter":
        scope_sql = "AND job.recruiter_id = ?"
        scope_values.append(user["id"])
    with connect() as db:
        rows = db.execute(
            """SELECT assessment.id, assessment.application_id, assessment.candidate_id,
            job.title, job.company
            FROM assessments assessment JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.status = 'Sent' AND assessment.starts_at IS NULL
            AND assessment.expiry_warning_sent_at IS NULL
            AND assessment.expires_at > ? AND assessment.expires_at <= ? """ + scope_sql,
            (current_time.isoformat(), warning_limit, *scope_values),
        ).fetchall()
    for row in rows:
        with connect() as db:
            updated = db.execute(
                """UPDATE assessments SET expiry_warning_sent_at = ?
                WHERE id = ? AND expiry_warning_sent_at IS NULL AND status = 'Sent'""",
                (now(), row["id"]),
            )
        if updated.rowcount:
            notify_user(
                row["candidate_id"],
                "assessment_reminder",
                "Assessment link expires soon",
                f"Your assessment for {row['title']} at {row['company']} expires within 24 hours. Open your registered email for the secure link.",
                application_id=row["application_id"],
                assessment_id=row["id"],
                action_url="/",
                send_email=True,
            )


def detect_profile(text: str) -> dict[str, Any]:
    email = re.search(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", text, re.I)
    phone = re.search(r"(?<!\w)(?:\+?\d[\d\s().-]{7,}\d)(?!\w)", text)
    name = None
    for line in (line.strip() for line in text.splitlines()):
        if line and len(line) < 70 and not re.search(r"[@\d]", line) and len(line.split()) <= 5:
            name = line
            break
    known_skills = (
        "python", "javascript", "typescript", "react", "fastapi", "sql", "postgresql",
        "figma", "ux research", "product design", "project management", "excel",
        "tableau", "data analysis", "html", "css", "node.js", "communication",
        "leadership", "machine learning", "java", "aws", "docker",
    )
    lower = text.lower()
    skills = [skill.title() for skill in known_skills if skill_matches(skill, lower)]
    return {
        "name": name or "",
        "email": email.group(0) if email else "",
        "phone": phone.group(0).strip() if phone else "",
        "skills": skills,
        "summary": "",
    }


def migrate_legacy_assessments(db: sqlite3.Connection) -> None:
    columns = {row["name"] for row in db.execute("PRAGMA table_info(assessments)")}
    if not columns or {"candidate_id", "job_id", "match_percentage", "duration_minutes"}.issubset(columns):
        return
    application_columns = {row["name"] for row in db.execute("PRAGMA table_info(applications)")}
    match_expression = "COALESCE(application.match_percentage, 0)" if "match_percentage" in application_columns else "0"
    legacy_question_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(assessment_questions)")
    }
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute(
        """CREATE TABLE assessments_migration (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id) ON DELETE CASCADE,
            candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            technology TEXT,
            token_hash TEXT UNIQUE,
            status TEXT NOT NULL DEFAULT 'Not Sent'
                CHECK(status IN ('Not Sent', 'Sent', 'Started', 'Completed', 'Expired', 'Manual Topic Required')),
            match_percentage INTEGER NOT NULL,
            starts_at TEXT,
            expires_at TEXT,
            submitted_at TEXT,
            score INTEGER,
            total_questions INTEGER NOT NULL DEFAULT 20,
            duration_minutes INTEGER NOT NULL DEFAULT 30,
            email_sent_at TEXT,
            created_at TEXT NOT NULL
        )"""
    )
    db.execute(
        """CREATE TABLE assessment_questions_migration (
            assessment_id INTEGER NOT NULL REFERENCES assessments_migration(id) ON DELETE CASCADE,
            question_id INTEGER REFERENCES technical_questions(id) ON DELETE SET NULL,
            question_order INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            options_json TEXT NOT NULL,
            correct_index INTEGER NOT NULL CHECK(correct_index BETWEEN 0 AND 3),
            difficulty TEXT NOT NULL,
            topic TEXT NOT NULL,
            selected_answer INTEGER,
            is_correct INTEGER,
            answered_at TEXT,
            PRIMARY KEY(assessment_id, question_order)
        )"""
    )
    db.execute(
        """INSERT INTO assessments_migration
        (id, application_id, candidate_id, job_id, technology, token_hash, status,
        match_percentage, expires_at, submitted_at, score, total_questions, duration_minutes, created_at)
        SELECT old.id, old.application_id, application.candidate_id, application.job_id,
        old.technology, NULL,
        CASE WHEN old.status = 'Completed' THEN 'Completed' ELSE 'Expired' END,
        {match_expression}, old.expires_at,
        CASE WHEN old.status = 'Completed' THEN old.completed_at ELSE NULL END,
        old.score, 20, 30, old.created_at
        FROM assessments old
        JOIN applications application ON application.id = old.application_id""".format(
            match_expression=match_expression
        )
    )
    required_question_columns = {
        "assessment_id", "question_id", "question_order", "question_text", "options_json",
        "correct_index", "difficulty", "topic", "selected_answer", "is_correct", "answered_at",
    }
    if required_question_columns.issubset(legacy_question_columns):
        db.execute(
            """INSERT INTO assessment_questions_migration
            SELECT assessment_id, question_id, question_order, question_text, options_json,
            correct_index, difficulty, topic, selected_answer, is_correct, answered_at
            FROM assessment_questions"""
        )
    if "assessment_questions" in {
        row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }:
        db.execute("DROP TABLE assessment_questions")
    db.execute("DROP TABLE assessments")
    db.execute("ALTER TABLE assessments_migration RENAME TO assessments")
    db.execute("ALTER TABLE assessment_questions_migration RENAME TO assessment_questions")
    db.commit()
    db.execute("PRAGMA foreign_keys = ON")


def extract_resume_text(content: bytes, content_type: str) -> str:
    if content_type == "application/pdf":
        from pypdf import PdfReader
        import io

        try:
            reader = PdfReader(io.BytesIO(content))
        except Exception as error:
            raise HTTPException(status_code=422, detail="This PDF is unreadable or corrupted. Please check the file and try again.") from error
        if len(reader.pages) > 40:
            raise HTTPException(status_code=422, detail="This PDF has too many pages. Please upload a document with 40 pages or fewer.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if text:
            return text
        import pypdfium2 as pdfium
        import pytesseract

        document = pdfium.PdfDocument(content)
        try:
            pages = []
            max_ocr_pages = min(len(document), 10)
            for index in range(max_ocr_pages):
                image = document[index].render(scale=1.5).to_pil()
                try:
                    pages.append(pytesseract.image_to_string(image))
                finally:
                    if hasattr(image, "close"):
                        image.close()
            return "\n".join(pages).strip()
        finally:
            document.close()
    from PIL import Image
    import io
    import pytesseract

    try:
        with Image.open(io.BytesIO(content)) as raw_image:
            raw_image.verify()
        with Image.open(io.BytesIO(content)).convert("RGB") as image:
            return pytesseract.image_to_string(image).strip()
    except Exception as error:
        raise HTTPException(status_code=422, detail="This image is unreadable or corrupted. Please check the file and try again.") from error
    return pytesseract.image_to_string(image).strip()


@app.on_event("startup")
def startup() -> None:
    validate_runtime_configuration()
    initialize_database()


@app.get("/")
def home() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/csrf")
def csrf() -> dict[str, str]:
    token = generate_csrf_token()
    response = JSONResponse({"csrf_token": token})
    response.set_cookie(CSRF_COOKIE_NAME, token, **csrf_cookie_settings())
    return response


@app.post("/api/auth/session")
def auth_session(body: AuthSessionBody) -> dict[str, Any]:
    payload = decode_token(body.access_token)
    user = get_current_user(token=body.access_token)
    csrf_token = generate_csrf_token()
    response = JSONResponse({"status": "ok", "csrf_token": csrf_token, "user": user})
    response.set_cookie(AUTH_COOKIE_NAME, body.access_token, **auth_cookie_settings())
    response.set_cookie(CSRF_COOKIE_NAME, csrf_token, **csrf_cookie_settings())
    return response


@app.post("/api/auth/register", status_code=201)
def register(request: Request, body: RegisterBody) -> dict[str, Any]:
    role = body.role.lower()
    if role not in {"candidate", "recruiter"}:
        raise HTTPException(status_code=422, detail="Choose a job seeker or recruiter account")
    enforce_rate_limit("register-ip", client_ip(request), limit=200, window_seconds=60)
    try:
        with connect() as db:
            cursor = db.execute(
                "INSERT INTO users (name, email, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (body.name.strip(), body.email.lower(), password_hash(body.password), role, now()),
            )
            row = db.execute("SELECT * FROM users WHERE id = ?", (cursor.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="An account with this email already exists") from error
    user = public_user(row)
    if role in {"candidate", "recruiter"}:
        notify_admins(
            "registration",
            "New account registered",
            f"{user['name']} registered as a {role}.",
            "/",
        )
    token = encode_token(row)
    return {"access_token": token, "token_type": "bearer", "user": user}


@app.post("/api/auth/login")
def login(request: Request, body: LoginBody) -> dict[str, Any]:
    email = body.email.lower().strip()
    enforce_rate_limit("login-ip", client_ip(request), limit=200, window_seconds=60)
    enforce_rate_limit("login-email", email, limit=200, window_seconds=60)
    with connect() as db:
        row = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row or not row["active"] or not check_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect")
    token = encode_token(row)
    return {"access_token": token, "token_type": "bearer", "user": public_user(row)}


@app.post("/api/auth/logout")
def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(AUTH_COOKIE_NAME, path=COOKIE_PATH, samesite="Lax", secure=current_is_production())
    response.delete_cookie(CSRF_COOKIE_NAME, path=COOKIE_PATH, samesite="Lax", secure=current_is_production())
    return {"status": "ok"}


@app.get("/api/me")
def me(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    return user


@app.get("/api/jobs")
def list_jobs(
    q: str = "",
    location: str = "",
    job_type: str = "",
    experience: str = "",
    skill: str = "",
    mine: bool = False,
    sort_by: str = "newest",
    page: int = 1,
    page_size: int = 50,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="Page must be positive and page size must be between 1 and 100")
    clauses = [] if mine and user["role"] == "recruiter" else ["j.status = 'Open'"]
    values: list[Any] = []
    if mine:
        if user["role"] != "recruiter":
            raise HTTPException(status_code=403, detail="Only recruiters can view their own job listings")
        clauses.append("j.recruiter_id = ?")
        values.append(user["id"])
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append("(j.title LIKE ? OR j.company LIKE ? OR j.description LIKE ? OR j.skills_json LIKE ?)")
        values.extend([like, like, like, like])
    if location.strip():
        clauses.append("j.location LIKE ?")
        values.append(f"%{location.strip()}%")
    if job_type.strip():
        clauses.append("j.job_type = ?")
        values.append(job_type.strip())
    if experience.strip():
        clauses.append("j.experience LIKE ?")
        values.append(f"%{experience.strip()}%")
    if skill.strip():
        clauses.append("j.skills_json LIKE ?")
        values.append(f"%{skill.strip()}%")
    sort_options = {
        "newest": "j.created_at DESC",
        "company": "j.company COLLATE NOCASE ASC",
        "title": "j.title COLLATE NOCASE ASC",
    }
    if sort_by not in sort_options:
        raise HTTPException(status_code=422, detail="Choose a valid job sort order")
    where = " AND ".join(clauses)
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM jobs j WHERE {where}", values).fetchone()[0]
        rows = db.execute(
            f"SELECT j.* FROM jobs j WHERE {where} ORDER BY {sort_options[sort_by]}, j.id ASC LIMIT ? OFFSET ?",
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"items": [public_job(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    del user
    with connect() as db:
        row = db.execute("SELECT * FROM jobs WHERE id = ? AND status = 'Open'", (job_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="This role is no longer available")
    return public_job(row)


@app.post("/api/jobs", status_code=201)
def create_job(body: JobBody, user: dict[str, Any] = Depends(require_role("recruiter"))) -> dict[str, Any]:
    skills = list(dict.fromkeys(skill.strip() for skill in body.skills if skill.strip()))
    if not skills:
        raise HTTPException(status_code=422, detail="Add at least one required skill")
    with connect() as db:
        cursor = db.execute(
            """INSERT INTO jobs (recruiter_id, title, company, description, location, experience, job_type, salary, skills_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], body.title.strip(), body.company.strip(), body.description.strip(), body.location.strip(),
             body.experience.strip(), body.job_type.strip(), body.salary.strip(), json.dumps(skills), now()),
        )
        row = db.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()
    notify_admins(
        "job_posted",
        "New job posted",
        f"{row['title']} at {row['company']} was posted.",
        "/",
    )
    notify_user(
        user["id"],
        "question_bank_incomplete",
        "Set up this job's question bank",
        f"{row['title']} does not have any active job-specific assessment questions yet. Add 20 valid questions for each assessment technology.",
        action_url="/",
    )
    return public_job(row)


def managed_job(db: sqlite3.Connection, job_id: int, user: dict[str, Any]) -> sqlite3.Row:
    row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row or (user["role"] != "admin" and row["recruiter_id"] != user["id"]):
        raise HTTPException(status_code=404, detail="Job listing not found for your account")
    return row


def public_job_question(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["options"] = json.loads(result.pop("options_json"))
    result["active"] = bool(result["active"])
    return result


def normalized_question(body: QuestionBody | QuestionUpdateBody, partial: bool = False) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=partial)
    if any(value is None for value in values.values()):
        raise HTTPException(status_code=422, detail="Question values cannot be null")
    if "difficulty" in values and values["difficulty"] not in {"Easy", "Medium", "Hard"}:
        raise HTTPException(status_code=422, detail="Choose Easy, Medium, or Hard difficulty")
    if "options" in values:
        options = [option.strip() for option in values["options"]]
        if len(options) != 4 or any(not option for option in options):
            raise HTTPException(status_code=422, detail="Provide exactly four non-empty answer options")
        values["options_json"] = json.dumps(options)
        values.pop("options")
    if "question" in values:
        values["question"] = values["question"].strip()
    if "technology" in values:
        values["technology"] = values["technology"].strip()
    return values


@app.patch("/api/jobs/{job_id}")
def update_job(
    job_id: int,
    body: JobUpdateBody,
    user: dict[str, Any] = Depends(require_role("recruiter")),
) -> dict[str, Any]:
    skills = list(dict.fromkeys(skill.strip() for skill in body.skills if skill.strip()))
    if not skills:
        raise HTTPException(status_code=422, detail="Add at least one required skill")
    with connect() as db:
        managed_job(db, job_id, user)
        db.execute(
            """UPDATE jobs SET title = ?, company = ?, description = ?, location = ?,
            experience = ?, job_type = ?, salary = ?, skills_json = ? WHERE id = ?""",
            (
                body.title.strip(), body.company.strip(), body.description.strip(), body.location.strip(),
                body.experience.strip(), body.job_type.strip(), body.salary.strip(),
                json.dumps(skills), job_id,
            ),
        )
        updated = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return public_job(updated)


@app.patch("/api/jobs/{job_id}/status")
def recruiter_update_job_status(
    job_id: int,
    body: JobStatusBody,
    user: dict[str, Any] = Depends(require_role("recruiter")),
) -> dict[str, Any]:
    if body.status not in {"Open", "Closed"}:
        raise HTTPException(status_code=422, detail="Choose Open or Closed")
    with connect() as db:
        managed_job(db, job_id, user)
        db.execute("UPDATE jobs SET status = ? WHERE id = ?", (body.status, job_id))
    return {"id": job_id, "status": body.status}


@app.get("/api/jobs/{job_id}/questions")
def list_job_questions(
    job_id: int,
    technology: str | None = None,
    difficulty: str | None = None,
    active: bool | None = None,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    clauses = ["job_id = ?"]
    values: list[Any] = [job_id]
    with connect() as db:
        managed_job(db, job_id, user)
        if technology:
            clauses.append("technology = ?")
            values.append(technology)
        if difficulty:
            if difficulty not in {"Easy", "Medium", "Hard"}:
                raise HTTPException(status_code=422, detail="Choose Easy, Medium, or Hard difficulty")
            clauses.append("difficulty = ?")
            values.append(difficulty)
        if active is not None:
            clauses.append("active = ?")
            values.append(int(active))
        rows = db.execute(
            f"SELECT * FROM job_questions WHERE {' AND '.join(clauses)} ORDER BY technology, difficulty, id",
            values,
        ).fetchall()
    return {"items": [public_job_question(row) for row in rows]}


@app.post("/api/jobs/{job_id}/questions", status_code=201)
def create_job_question(
    job_id: int,
    body: QuestionBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    values = normalized_question(body)
    with connect() as db:
        job = managed_job(db, job_id, user)
        duplicate = db.execute(
            "SELECT id, technology, question FROM job_questions WHERE job_id = ?",
            (job_id,),
        ).fetchall()
        if any(
            question_fingerprint(row["technology"], row["question"])
            == question_fingerprint(values["technology"], values["question"])
            for row in duplicate
        ):
            raise HTTPException(status_code=409, detail="This question already exists in this job's question bank.")
        cursor = db.execute(
            """INSERT INTO job_questions
            (job_id, recruiter_id, technology, question, options_json, correct_index,
            difficulty, active, source_type, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?)""",
            (
                job_id, job["recruiter_id"], values["technology"], values["question"],
                values["options_json"], values["correct_index"], values["difficulty"],
                int(values["active"]), now(), now(),
            ),
        )
        row = db.execute("SELECT * FROM job_questions WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return public_job_question(row)


@app.patch("/api/jobs/{job_id}/questions/{question_id}")
def update_job_question(
    job_id: int,
    question_id: int,
    body: QuestionUpdateBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    values = normalized_question(body, partial=True)
    if not values:
        raise HTTPException(status_code=422, detail="Provide at least one question field to update")
    with connect() as db:
        managed_job(db, job_id, user)
        row = db.execute(
            "SELECT id, technology, question FROM job_questions WHERE id = ? AND job_id = ?",
            (question_id, job_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Question not found for this job")
        next_technology = values.get("technology", row["technology"])
        next_question = values.get("question", row["question"])
        duplicate = db.execute(
            "SELECT technology, question FROM job_questions WHERE job_id = ? AND id != ?",
            (job_id, question_id),
        ).fetchall()
        if any(
            question_fingerprint(existing["technology"], existing["question"])
            == question_fingerprint(next_technology, next_question)
            for existing in duplicate
        ):
            raise HTTPException(status_code=409, detail="This question already exists in this job's question bank.")
        assignments = [f"{column} = ?" for column in values]
        params = list(values.values())
        assignments.append("updated_at = ?")
        params.extend([now(), question_id, job_id])
        db.execute(
            f"UPDATE job_questions SET {', '.join(assignments)} WHERE id = ? AND job_id = ?",
            params,
        )
        updated = db.execute("SELECT * FROM job_questions WHERE id = ?", (question_id,)).fetchone()
    return public_job_question(updated)


@app.delete("/api/jobs/{job_id}/questions/{question_id}")
def delete_job_question(
    job_id: int,
    question_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, int]:
    with connect() as db:
        managed_job(db, job_id, user)
        result = db.execute(
            "DELETE FROM job_questions WHERE id = ? AND job_id = ?", (question_id, job_id)
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Question not found for this job")
    return {"id": question_id}


@app.get("/api/jobs/{job_id}/question-bank-summary")
def job_question_bank_summary(
    job_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        managed_job(db, job_id, user)
        rows = db.execute(
            """SELECT technology, difficulty, options_json, correct_index FROM job_questions
            WHERE job_id = ? AND active = 1""",
            (job_id,),
        ).fetchall()
    counts: dict[str, int] = {}
    difficulty_counts = {"Easy": 0, "Medium": 0, "Hard": 0}
    grouped_counts: dict[str, dict[str, int]] = {}
    for row in rows:
        if valid_question_is_valid(row):
            counts[row["technology"]] = counts.get(row["technology"], 0) + 1
            difficulty_counts[row["difficulty"]] = difficulty_counts.get(row["difficulty"], 0) + 1
            grouped_counts.setdefault(row["technology"], {}).setdefault(row["difficulty"], 0)
            grouped_counts[row["technology"]][row["difficulty"]] += 1
    return {
        "job_id": job_id,
        "technologies": [
            {"technology": technology, "valid_active_questions": count, "ready": count >= 20, "needed": max(0, 20 - count)}
            for technology, count in sorted(counts.items())
        ],
        "total_valid_active_questions": sum(counts.values()),
        "difficulty_counts": difficulty_counts,
        "technology_difficulty_counts": grouped_counts,
    }


@app.post("/api/jobs/{job_id}/question-bank/imports", status_code=201)
async def upload_question_bank_pdf(
    job_id: int,
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        job = managed_job(db, job_id, user)
    filename = Path(file.filename or "question-bank.pdf").name
    if Path(filename).suffix.lower() != ".pdf":
        raise HTTPException(status_code=415, detail="Upload a PDF question bank.")
    content = await file.read(MAX_QUESTION_BANK_PDF_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="This PDF is empty.")
    if len(content) > MAX_QUESTION_BANK_PDF_BYTES:
        raise HTTPException(status_code=413, detail="Question-bank PDF must be 10 MB or smaller.")
    if not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="This file does not contain a valid PDF.")
    text = await run_in_threadpool(extract_question_bank_pdf_text, content)
    preview = await run_in_threadpool(parse_question_bank_text, text)
    storage_path = QUESTION_BANK_IMPORT_DIR / f"{uuid.uuid4().hex}.pdf"
    storage_path.write_bytes(content)
    try:
        with connect() as db:
            cursor = db.execute(
                """INSERT INTO question_bank_imports
                (job_id, recruiter_id, filename, storage_path, status, total_questions,
                valid_question_count, invalid_question_count, preview_json, error_summary, created_at)
                VALUES (?, ?, ?, ?, 'pending_review', ?, ?, ?, ?, ?, ?)""",
                (
                    job_id,
                    job["recruiter_id"],
                    filename,
                    str(storage_path),
                    preview["total_questions"],
                    len(preview["valid_questions"]),
                    len(preview["invalid_questions"]),
                    json.dumps(preview),
                    "; ".join(
                        reason
                        for item in preview["invalid_questions"]
                        for reason in item["reasons"]
                    )[:4_000],
                    now(),
                ),
            )
            import_id = cursor.lastrowid
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    notify_user(
        job["recruiter_id"],
        "question_bank_import_ready",
        "Question-bank PDF ready for review",
        f"{filename} was parsed for {job['title']}: {len(preview['valid_questions'])} valid and {len(preview['invalid_questions'])} invalid or skipped question(s). Review the preview before importing.",
        action_url="/",
    )
    if preview["invalid_questions"]:
        notify_user(
            job["recruiter_id"],
            "question_bank_import_invalid",
            "Some PDF questions need correction",
            f"{filename} contains {len(preview['invalid_questions'])} malformed, duplicate, or skipped question(s). They were not saved.",
            action_url="/",
        )
    return {
        "import_id": import_id,
        "job_id": job_id,
        "job_title": job["title"],
        "filename": filename,
        "status": "pending_review",
        **preview,
        "valid_question_count": len(preview["valid_questions"]),
        "invalid_question_count": len(preview["invalid_questions"]),
    }


@app.get("/api/jobs/{job_id}/question-bank/imports")
def list_question_bank_imports(
    job_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        managed_job(db, job_id, user)
        rows = db.execute(
            """SELECT id, filename, status, total_questions, valid_question_count,
            invalid_question_count, error_summary, created_at, confirmed_at
            FROM question_bank_imports WHERE job_id = ? ORDER BY created_at DESC, id DESC
            LIMIT 50""",
            (job_id,),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.delete("/api/jobs/{job_id}/question-bank/imports/{import_id}")
def cancel_question_bank_import(
    job_id: int,
    import_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        managed_job(db, job_id, user)
        result = db.execute(
            """UPDATE question_bank_imports SET status = 'cancelled'
            WHERE id = ? AND job_id = ? AND status = 'pending_review'""",
            (import_id, job_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Pending question-bank import not found.")
    return {"id": import_id, "status": "cancelled"}


@app.post("/api/jobs/{job_id}/question-bank/imports/{import_id}/confirm")
def confirm_question_bank_import(
    job_id: int,
    import_id: int,
    body: ConfirmQuestionBankImportBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    if not body.questions:
        raise HTTPException(status_code=422, detail="Select at least one valid question to import.")
    inserted = 0
    skipped_duplicates = 0
    with connect() as db:
        job = managed_job(db, job_id, user)
        imported = db.execute(
            """SELECT * FROM question_bank_imports
            WHERE id = ? AND job_id = ? AND status = 'pending_review'""",
            (import_id, job_id),
        ).fetchone()
        if not imported:
            raise HTTPException(status_code=404, detail="Pending question-bank import not found.")
        fingerprints = {
            question_fingerprint(row["technology"], row["question"])
            for row in db.execute(
                "SELECT technology, question FROM job_questions WHERE job_id = ?",
                (job_id,),
            ).fetchall()
        }
        added_in_request: set[tuple[str, str]] = set()
        for question in body.questions:
            values = normalized_question(question)
            fingerprint = question_fingerprint(values["technology"], values["question"])
            if fingerprint in fingerprints or fingerprint in added_in_request:
                skipped_duplicates += 1
                continue
            db.execute(
                """INSERT INTO job_questions
                (job_id, recruiter_id, technology, question, options_json, correct_index,
                difficulty, active, source_type, source_import_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pdf_import', ?, ?, ?)""",
                (
                    job_id,
                    job["recruiter_id"],
                    values["technology"],
                    values["question"],
                    values["options_json"],
                    values["correct_index"],
                    values["difficulty"],
                    int(values["active"]),
                    import_id,
                    now(),
                    now(),
                ),
            )
            added_in_request.add(fingerprint)
            inserted += 1
        if inserted == 0:
            raise HTTPException(status_code=409, detail="All approved questions already exist in this job's question bank.")
        db.execute(
            """UPDATE question_bank_imports SET status = 'confirmed', confirmed_at = ?
            WHERE id = ?""",
            (now(), import_id),
        )
        total, by_technology = question_bank_count(db, job_id)
    notify_user(
        job["recruiter_id"],
        "question_bank_import_completed",
        "Question-bank import completed",
        f"Imported {inserted} question(s) for {job['title']}; {skipped_duplicates} duplicate(s) were skipped.",
        action_url="/",
    )
    incomplete = {technology: max(0, 20 - count) for technology, count in by_technology.items() if count < 20}
    if incomplete:
        shortage = ", ".join(f"{technology}: {needed} more" for technology, needed in sorted(incomplete.items()))
        notify_user(
            job["recruiter_id"],
            "question_bank_incomplete",
            "Job question bank needs more questions",
            f"{job['title']} still needs at least 20 valid active questions per assessment technology ({shortage}).",
            action_url="/",
            send_email=True,
        )
    return {
        "import_id": import_id,
        "status": "confirmed",
        "imported_count": inserted,
        "skipped_duplicate_count": skipped_duplicates,
        "total_valid_active_questions": total,
        "technology_counts": by_technology,
    }


@app.post("/api/jobs/{job_id}/apply", status_code=201)
def apply(job_id: int, user: dict[str, Any] = Depends(require_role("candidate"))) -> dict[str, Any]:
    with connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ? AND status = 'Open'", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="This role is no longer available")
        resume = db.execute(
            "SELECT id, extracted_text, parsed_profile_json FROM resumes WHERE candidate_id = ?",
            (user["id"],),
        ).fetchone()
        if not resume:
            raise HTTPException(status_code=409, detail="Upload a resume before applying")
        saved_profile = db.execute("SELECT profile_json FROM users WHERE id = ?", (user["id"],)).fetchone()
        match = calculate_match(
            json.loads(job["skills_json"]),
            resume["extracted_text"],
            resume["parsed_profile_json"],
            saved_profile["profile_json"],
        )
        application_status = (
            "Shortlisted" if match["match_percentage"] >= ASSESSMENT_MATCH_THRESHOLD else "Applied"
        )
        existing = db.execute(
            "SELECT id, status FROM applications WHERE candidate_id = ? AND job_id = ?",
            (user["id"], job_id),
        ).fetchone()
        if existing and existing["status"] != "Withdrawn":
            raise HTTPException(status_code=409, detail="You have already applied for this role")
        if existing:
            db.execute(
                """UPDATE applications SET resume_id = ?, status = ?, match_percentage = ?,
                matched_skills_json = ?, missing_skills_json = ?, applied_at = ?
                WHERE id = ?""",
                (
                    resume["id"], application_status, match["match_percentage"],
                    json.dumps(match["matched_skills"]), json.dumps(match["missing_skills"]),
                    now(), existing["id"],
                ),
            )
            application_id = existing["id"]
        else:
            cursor = db.execute(
                """INSERT INTO applications
                (candidate_id, job_id, resume_id, status, match_percentage,
                matched_skills_json, missing_skills_json, applied_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user["id"], job_id, resume["id"], application_status, match["match_percentage"],
                    json.dumps(match["matched_skills"]), json.dumps(match["missing_skills"]), now(),
                ),
            )
            application_id = cursor.lastrowid
        db.execute(
            """INSERT INTO application_status_history
            (application_id, status, updated_at, actor_user_id)
            VALUES (?, ?, ?, ?)""",
            (application_id, "Applied", now(), user["id"]),
        )
        if application_status == "Shortlisted":
            db.execute(
                """INSERT INTO application_status_history
                (application_id, status, updated_at, actor_user_id)
                VALUES (?, 'Shortlisted', ?, NULL)""",
                (application_id, now()),
            )
        row = db.execute(
            """SELECT a.id, a.candidate_id, a.job_id, a.status, a.match_percentage, a.applied_at, j.title, j.company
            FROM applications a JOIN jobs j ON j.id = a.job_id WHERE a.id = ?""",
            (application_id,),
        ).fetchone()
        recruiter_id = job["recruiter_id"]
        question_rows = db.execute(
            """SELECT id, technology, question, options_json, correct_index, difficulty
            FROM job_questions WHERE job_id = ? AND active = 1 ORDER BY technology, id""",
            (job_id,),
        ).fetchall()
        existing_assessment = db.execute(
            "SELECT technology, status FROM assessments WHERE application_id = ?",
            (application_id,),
        ).fetchone()
    result = public_application(row)
    result.update({
        "matched_skills": match["matched_skills"],
        "missing_skills": match["missing_skills"],
        "assessment_status": existing_assessment["status"] if existing_assessment else "Not Sent",
    })
    notify_user(
        user["id"],
        "application_submitted",
        "Application submitted",
        f"Your application for {row['title']} at {row['company']} was submitted.",
        application_id=application_id,
        action_url="/",
    )
    notify_user(
        recruiter_id,
        "new_application",
        "New candidate application",
        f"{user['name']} applied for {row['title']}.",
        application_id=application_id,
        action_url="/",
    )
    if match["match_percentage"] < ASSESSMENT_MATCH_THRESHOLD:
        return result
    notify_user(
        user["id"],
        "candidate_shortlisted",
        "You have been shortlisted",
        f"You matched {match['match_percentage']}% of the requirements for {row['title']} at {row['company']}.",
        application_id=application_id,
        action_url="/",
        send_email=True,
    )
    notify_user(
        recruiter_id,
        "candidate_shortlisted",
        "Candidate automatically shortlisted",
        f"{user['name']} matched {match['match_percentage']}% of the requirements for {row['title']}.",
        application_id=application_id,
        action_url="/",
    )
    if existing_assessment and existing_assessment["status"] == "Completed":
        result.update({
            "assessment_status": "Completed",
            "assessment_topic": existing_assessment["technology"],
        })
        return result
    job_skills = json.loads(job["skills_json"])
    relevant_questions = select_job_assessment_questions(
        list(question_rows),
        match["candidate_text"],
        job_skills,
    )
    topic = ", ".join(dict.fromkeys(question["technology"] for question in relevant_questions))
    detected_topic = detect_assessment_topic(job_skills, match["candidate_text"])
    if len(relevant_questions) < 20:
        pending_status = (
            "Question Bank Incomplete"
            if relevant_questions or detected_topic
            else "Manual Topic Required"
        )
        result.update({
            "assessment_status": pending_status,
            "assessment_topic": topic or detected_topic,
        })
        missing_count = max(0, 20 - len(relevant_questions))
        notify_user(
            recruiter_id,
            "question_bank_incomplete",
            "Job question bank needs attention",
            f"{row['title']} needs {missing_count} more relevant valid active question(s) before an assessment can be sent.",
            application_id=application_id,
            action_url="/",
            send_email=True,
        )
        notify_user(
            user["id"],
            "assessment_pending",
            "Your assessment is pending",
            "You are shortlisted. The hiring team is preparing your technical assessment and will email you when it is ready.",
            application_id=application_id,
            action_url="/",
        )
        return result
    try:
        invitation = send_assessment_invitation(application_id)
        result.update({
            "status": invitation["status"],
            "assessment_status": invitation["assessment_status"],
            "assessment_topic": invitation.get("technology"),
            "assessment_delivery": invitation.get("delivery"),
            "assessment_delivery_error": invitation.get("delivery_error"),
        })
    except HTTPException as error:
        logger.error("Assessment invitation is pending for application %s: %s", application_id, error.detail)
        result.update({"assessment_status": "Not Sent", "assessment_delivery_error": error.detail})
    return result


@app.get("/api/applications")
def list_applications(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    with connect() as db:
        if user["role"] == "candidate":
            rows = db.execute(
                """SELECT a.id, a.candidate_id, a.job_id, a.status, a.applied_at,
                a.match_percentage, a.matched_skills_json, a.missing_skills_json, j.title, j.company
                FROM applications a JOIN jobs j ON j.id = a.job_id
                WHERE a.candidate_id = ? ORDER BY a.applied_at DESC""",
                (user["id"],),
            ).fetchall()
        elif user["role"] == "recruiter":
            rows = db.execute(
                """SELECT a.id, a.candidate_id, a.job_id, a.status, a.applied_at,
                a.match_percentage, a.matched_skills_json, a.missing_skills_json, a.internal_notes,
                j.title, j.company, j.recruiter_id, u.name AS candidate_name, u.email AS candidate_email
                FROM applications a JOIN jobs j ON j.id = a.job_id JOIN users u ON u.id = a.candidate_id
                WHERE j.recruiter_id = ? ORDER BY a.applied_at DESC""",
                (user["id"],),
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT a.id, a.candidate_id, a.job_id, a.status, a.applied_at,
                a.match_percentage, a.matched_skills_json, a.missing_skills_json, a.internal_notes,
                j.title, j.company, j.recruiter_id, u.name AS candidate_name, u.email AS candidate_email,
                recruiter.name AS recruiter_name
                FROM applications a JOIN jobs j ON j.id = a.job_id
                JOIN users u ON u.id = a.candidate_id
                JOIN users recruiter ON recruiter.id = j.recruiter_id
                ORDER BY a.applied_at DESC LIMIT 500"""
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["matched_skills"] = json.loads(item.pop("matched_skills_json") or "[]")
            item["missing_skills"] = json.loads(item.pop("missing_skills_json") or "[]")
            if user["role"] == "candidate":
                item.pop("internal_notes", None)
            question_topics = [
                topic["technology"] for topic in db.execute(
                    """SELECT DISTINCT technology FROM job_questions
                    WHERE job_id = ? AND active = 1 ORDER BY technology""",
                    (row["job_id"],),
                ).fetchall()
            ]
            item["job_question_technologies"] = question_topics if user["role"] != "candidate" else []
            assessment = db.execute(
                """SELECT id, technology, status, score, score_percentage, starts_at, submitted_at,
                email_sent_at, expires_at, duration_minutes, assessment_name, assessment_round,
                correct_answer_count, incorrect_answer_count, pass_percentage, result, result_processed_at,
                proctoring_required, proctoring_status, warning_count, flagged_for_review, flagged_at,
                camera_permission_granted_at
                FROM assessments WHERE application_id = ?""",
                (row["id"],),
            ).fetchone()
            answered_count = 0
            if assessment:
                answered_count = db.execute(
                    """SELECT COUNT(*) FROM assessment_questions
                    WHERE assessment_id = ? AND selected_answer IS NOT NULL""",
                    (assessment["id"],),
                ).fetchone()[0]
            elif row["match_percentage"] >= ASSESSMENT_MATCH_THRESHOLD:
                details = assessment_candidate_data(db, row["id"])
                match = match_application(details)
                required_skills = json.loads(details["skills_json"])
                available_questions = db.execute(
                    """SELECT technology, question, options_json, correct_index, difficulty
                    FROM job_questions WHERE job_id = ? AND active = 1""",
                    (row["job_id"],),
                ).fetchall()
                relevant_questions = select_job_assessment_questions(
                    list(available_questions),
                    match["candidate_text"],
                    required_skills,
                )
                topic = ", ".join(dict.fromkeys(question["technology"] for question in relevant_questions))
                if len(relevant_questions) >= 20:
                    item["assessment_status"] = "Not Sent"
                elif relevant_questions or detect_assessment_topic(required_skills, match["candidate_text"]):
                    item["assessment_status"] = "Question Bank Incomplete"
                else:
                    item["assessment_status"] = "Manual Topic Required"
                item["assessment_topic"] = topic or detect_assessment_topic(
                    required_skills, match["candidate_text"]
                )
            item.update({
                "assessment_id": assessment["id"] if assessment else None,
                "assessment_status": assessment["status"] if assessment else item.get("assessment_status", "Not Sent"),
                "assessment_topic": assessment["technology"] if assessment else item.get("assessment_topic"),
                "assessment_score": (
                    assessment["score_percentage"] if assessment and assessment["status"] == "Completed" else None
                ),
                "assessment_name": assessment["assessment_name"] if assessment else None,
                "assessment_round": assessment["assessment_round"] if assessment else None,
                "assessment_correct_answer_count": assessment["correct_answer_count"] if assessment else None,
                "assessment_incorrect_answer_count": assessment["incorrect_answer_count"] if assessment else None,
                "assessment_result": assessment["result"] if assessment else None,
                "assessment_pass_percentage": assessment["pass_percentage"] if assessment else None,
                "assessment_result_processed_at": assessment["result_processed_at"] if assessment else None,
                "assessment_started_at": assessment["starts_at"] if assessment else None,
                "assessment_submitted_at": assessment["submitted_at"] if assessment else None,
                "assessment_email_sent_at": assessment["email_sent_at"] if assessment else None,
                "assessment_expires_at": assessment["expires_at"] if assessment else None,
                "assessment_answered_count": answered_count,
                "status_history": application_history(db, row["id"]),
            })
            if assessment and user["role"] != "candidate":
                item["assessment_proctoring"] = proctoring_summary(db, assessment["id"])
            interview = db.execute(
                """SELECT id, status, starts_at, duration_minutes, timezone, meeting_platform,
                meeting_url, recruiter_message, candidate_viewed_at
                FROM interviews WHERE application_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1""",
                (row["id"],),
            ).fetchone()
            item["interview"] = (
                dict(interview) if interview else None
            )
            if item["interview"] and user["role"] == "candidate":
                interview_ended = (
                    datetime.fromisoformat(item["interview"]["starts_at"])
                    + timedelta(minutes=item["interview"]["duration_minutes"])
                ) <= datetime.now(timezone.utc)
                if item["interview"]["status"] in {"Cancelled", "Completed"} or interview_ended:
                    item["interview"]["meeting_url"] = ""
            if assessment and assessment["starts_at"] and assessment["submitted_at"]:
                item["assessment_time_taken_seconds"] = max(
                    0,
                    int((
                        datetime.fromisoformat(assessment["submitted_at"])
                        - datetime.fromisoformat(assessment["starts_at"])
                    ).total_seconds()),
                )
            else:
                item["assessment_time_taken_seconds"] = None
            if user["role"] == "candidate":
                for history in item["status_history"]:
                    history.pop("recruiter_note", None)
                    history.pop("actor_name", None)
            items.append(item)
    return {"items": items}


@app.get("/api/notifications")
def list_notifications(
    unread_only: bool = False,
    page: int = 1,
    page_size: int = 50,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    if page < 1 or page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="Page must be positive and page size must be between 1 and 100")
    clauses = ["user_id = ?"]
    values: list[Any] = [user["id"]]
    if unread_only:
        clauses.append("is_read = 0")
    where = " AND ".join(clauses)
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM notifications WHERE {where}", values).fetchone()[0]
        rows = db.execute(
            f"""SELECT id, type, title, message, related_application_id, related_assessment_id,
            action_url, is_read, email_delivery_status, created_at
            FROM notifications WHERE {where} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?""",
            [*values, page_size, (page - 1) * page_size],
        ).fetchall()
    return {"items": [dict(row) for row in rows], "total": total, "page": page, "page_size": page_size}


@app.get("/api/notifications/unread-count")
def unread_notification_count(user: dict[str, Any] = Depends(current_user)) -> dict[str, int]:
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND is_read = 0",
            (user["id"],),
        ).fetchone()[0]
    return {"unread_count": count}


@app.patch("/api/notifications/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    with connect() as db:
        result = db.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (notification_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": notification_id, "is_read": True}


@app.patch("/api/notifications/read-all")
def mark_all_notifications_read(user: dict[str, Any] = Depends(current_user)) -> dict[str, int]:
    with connect() as db:
        result = db.execute(
            "UPDATE notifications SET is_read = 1 WHERE user_id = ? AND is_read = 0",
            (user["id"],),
        )
    return {"updated": result.rowcount}


@app.patch("/api/applications/{application_id}/withdraw")
def withdraw_application(
    application_id: int,
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    withdrawable = {"Applied", "Under Review", "Shortlisted", "Assessment Sent"}
    with connect() as db:
        row = db.execute(
            "SELECT id, status FROM applications WHERE id = ? AND candidate_id = ?",
            (application_id, user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found")
        if row["status"] not in withdrawable:
            raise HTTPException(status_code=409, detail="This application can no longer be withdrawn")
        record_application_status(db, application_id, "Withdrawn", user["id"])
        recruiter = db.execute(
            """SELECT j.recruiter_id, j.title, candidate.name AS candidate_name
            FROM applications a JOIN jobs j ON j.id = a.job_id
            JOIN users candidate ON candidate.id = a.candidate_id
            WHERE a.id = ?""",
            (application_id,),
        ).fetchone()
        db.execute(
            """UPDATE assessments SET status = 'Expired', token_hash = NULL
            WHERE application_id = ? AND status IN ('Not Sent', 'Sent', 'Started', 'Manual Topic Required')""",
            (application_id,),
        )
    notify_user(
        recruiter["recruiter_id"],
        "application_withdrawn",
        "Candidate withdrew an application",
        f"{recruiter['candidate_name']} withdrew from {recruiter['title']}.",
        application_id=application_id,
        action_url="/",
    )
    return {"id": application_id, "status": "Withdrawn"}


@app.put("/api/applications/{application_id}/status")
@app.patch("/api/applications/{application_id}/status", include_in_schema=False)
def update_application_status(
    application_id: int,
    body: StatusBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    valid_statuses = {
        "Applied", "Under Review", "Shortlisted", "Assessment Sent", "Assessment Started",
        "Assessment Completed", "Round 1 Passed", "Round 1 Failed",
        "Interview", "Accepted", "Selected", "Rejected",
    }
    if body.status not in valid_statuses:
        raise HTTPException(status_code=422, detail="Choose a valid hiring-pipeline status")
    next_status = "Accepted" if body.status == "Selected" else body.status
    with connect() as db:
        row = db.execute(
            """SELECT a.id, a.status, a.match_percentage, a.candidate_id, j.title, j.company,
            j.recruiter_id, candidate.name AS candidate_name
            FROM applications a JOIN jobs j ON j.id = a.job_id
            JOIN users candidate ON candidate.id = a.candidate_id
            WHERE a.id = ? AND (? = 'admin' OR j.recruiter_id = ?)""",
            (application_id, user["role"], user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found for your job listings")
        current_status = "Accepted" if row["status"] == "Selected" else row["status"]
        if next_status == "Shortlisted" and row["match_percentage"] < ASSESSMENT_MATCH_THRESHOLD:
            raise HTTPException(status_code=409, detail="Candidates need at least a 70% match to be shortlisted.")
        if next_status in {"Assessment Sent", "Assessment Started", "Assessment Completed"}:
            expected_assessment_status = {
                "Assessment Sent": {"Sent"},
                "Assessment Started": {"Started"},
                "Assessment Completed": {"Completed"},
            }[next_status]
            with connect() as status_db:
                assessment = status_db.execute(
                    "SELECT status FROM assessments WHERE application_id = ?", (application_id,)
                ).fetchone()
            if not assessment or assessment["status"] not in expected_assessment_status:
                raise HTTPException(status_code=409, detail="Assessment pipeline stages are updated by the assessment workflow.")
        if next_status in {"Round 1 Passed", "Round 1 Failed"}:
            with connect() as status_db:
                assessment = status_db.execute(
                    "SELECT status, result FROM assessments WHERE application_id = ?", (application_id,)
                ).fetchone()
            if not assessment or assessment["status"] != "Completed" or assessment["result"] != next_status.removeprefix("Round 1 "):
                raise HTTPException(status_code=409, detail="Round 1 results are updated by the assessment workflow.")
        if not application_transition_allowed(current_status, next_status, row["match_percentage"]):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot move an application from {current_status} to {next_status}.",
            )
        status_changed = current_status != next_status
        if status_changed:
            record_application_status(db, application_id, next_status, user["id"], body.note)
        elif body.note:
            db.execute(
                """UPDATE applications SET internal_notes =
                CASE WHEN internal_notes = '' THEN ? ELSE internal_notes || char(10) || ? END
                WHERE id = ?""",
                (body.note.strip(), body.note.strip(), application_id),
            )
            db.execute(
                """INSERT INTO application_status_history
                (application_id, status, updated_at, actor_user_id, recruiter_note)
                VALUES (?, ?, ?, ?, ?)""",
                (application_id, next_status, now(), user["id"], body.note.strip()),
            )
        if next_status in {"Rejected", "Accepted"}:
            db.execute(
                """UPDATE assessments SET status = 'Expired', token_hash = NULL
                WHERE application_id = ? AND status IN ('Not Sent', 'Sent', 'Started', 'Manual Topic Required')""",
                (application_id,),
            )
    if status_changed:
        notify_user(
            row["candidate_id"],
            "application_status",
            f"Application status: {next_status}",
            f"Your application for {row['title']} at {row['company']} is now {next_status}.",
            application_id=application_id,
            action_url="/",
            send_email=True,
        )
    return {"id": row["id"], "status": next_status}


@app.patch("/api/applications/{application_id}/notes")
def update_application_internal_notes(
    application_id: int,
    body: InternalNoteBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, int]:
    with connect() as db:
        row = db.execute(
            """SELECT application.id, application.status FROM applications application
            JOIN jobs job ON job.id = application.job_id
            WHERE application.id = ? AND (? = 'admin' OR job.recruiter_id = ?)""",
            (application_id, user["role"], user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Application not found for your job listings")
        db.execute(
            "UPDATE applications SET internal_notes = ? WHERE id = ?",
            (body.note.strip(), application_id),
        )
        if body.note.strip():
            db.execute(
                """INSERT INTO application_status_history
                (application_id, status, updated_at, actor_user_id, recruiter_note)
                VALUES (?, ?, ?, ?, ?)""",
                (application_id, row["status"], now(), user["id"], body.note.strip()),
            )
    return {"id": application_id}


@app.post("/api/applications/{application_id}/assessment/send", status_code=201)
@app.post("/api/applications/{application_id}/assessment/reissue", status_code=201, include_in_schema=False)
def recruiter_send_assessment(
    application_id: int,
    body: AssessmentSendBody | None = None,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        candidate = assessment_candidate_data(db, application_id)
        if user["role"] != "admin" and candidate["recruiter_id"] != user["id"]:
            raise HTTPException(status_code=404, detail="Application not found for your job listings")
    result = send_assessment_invitation(application_id, body.technology if body else None)
    if result.get("delivery_error"):
        raise HTTPException(status_code=502, detail=result["delivery_error"])
    return result


@app.post("/api/assessments/{assessment_id}/resend-link", status_code=201)
def candidate_resend_assessment_link(
    assessment_id: int,
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            """SELECT application_id, candidate_id, status, starts_at
            FROM assessments WHERE id = ? AND candidate_id = ?""",
            (assessment_id, user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Assessment not found")
    if row["starts_at"] is not None or row["status"] not in {"Sent", "Expired", "Not Sent"}:
        raise HTTPException(status_code=409, detail="Only unused assessment links can be reissued.")
    result = send_assessment_invitation(row["application_id"])
    if result.get("delivery_error"):
        raise HTTPException(status_code=502, detail=result["delivery_error"])
    return {
        "assessment_status": result["assessment_status"],
        "technology": result.get("technology"),
        "delivery": result.get("delivery"),
    }


@app.get("/api/assessments")
def list_assessment_reviews(
    job_id: int | None = None,
    status: str | None = None,
    application_stage: str | None = None,
    technology: str | None = None,
    candidate: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    score_min: int | None = None,
    score_max: int | None = None,
    result: str | None = None,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    notify_expiring_assessments(user)
    scope_sql = ""
    scope_values: list[Any] = []
    if user["role"] == "candidate":
        scope_sql = "AND candidate_id = ?"
        scope_values.append(user["id"])
    elif user["role"] == "recruiter":
        scope_sql = "AND job_id IN (SELECT id FROM jobs WHERE recruiter_id = ?)"
        scope_values.append(user["id"])
    with connect() as db:
        expired_ids = [
            row["id"] for row in db.execute(
                """SELECT id FROM assessments WHERE status IN ('Sent', 'Started')
                AND expires_at IS NOT NULL AND expires_at <= ? """ + scope_sql,
                (now(), *scope_values),
            ).fetchall()
        ]
    for assessment_id in expired_ids:
        expire_assessment(assessment_id)

    clauses: list[str] = []
    values: list[Any] = []
    if user["role"] == "candidate":
        clauses.append("assessment.candidate_id = ?")
        values.append(user["id"])
    elif user["role"] == "recruiter":
        clauses.append("job.recruiter_id = ?")
        values.append(user["id"])
    if job_id is not None:
        clauses.append("assessment.job_id = ?")
        values.append(job_id)
    if status:
        clauses.append("assessment.status = ?")
        values.append(status)
    if technology:
        clauses.append("assessment.technology = ?")
        values.append(technology)
    if candidate:
        clauses.append("(candidate.name LIKE ? OR candidate.email LIKE ?)")
        values.extend([f"%{candidate.strip()}%", f"%{candidate.strip()}%"])
    if start_date:
        try:
            parsed_start_date = datetime.fromisoformat(start_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="start_date must be an ISO date or datetime") from error
        clauses.append("assessment.submitted_at >= ?")
        values.append(parsed_start_date.isoformat())
    if end_date:
        try:
            parsed_end_date = datetime.fromisoformat(end_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="end_date must be an ISO date or datetime") from error
        if len(end_date) == 10:
            clauses.append("assessment.submitted_at < ?")
            values.append((parsed_end_date + timedelta(days=1)).isoformat())
        else:
            clauses.append("assessment.submitted_at <= ?")
            values.append(parsed_end_date.isoformat())
    if score_min is not None:
        if not 0 <= score_min <= 100:
            raise HTTPException(status_code=422, detail="score_min must be between 0 and 100")
        clauses.append("assessment.score_percentage >= ?")
        values.append(score_min)
    if score_max is not None:
        if not 0 <= score_max <= 100:
            raise HTTPException(status_code=422, detail="score_max must be between 0 and 100")
        clauses.append("assessment.score_percentage <= ?")
        values.append(score_max)
    if result:
        if result not in {"Passed", "Failed"}:
            raise HTTPException(status_code=422, detail="result must be Passed or Failed")
        clauses.append("assessment.result = ?")
        values.append(result)
    if application_stage:
        clauses.append("application.status = ?")
        values.append(application_stage)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with connect() as db:
        rows = db.execute(
            f"""SELECT assessment.id, assessment.application_id, assessment.candidate_id,
            assessment.job_id, assessment.technology, assessment.status, assessment.match_percentage,
            assessment.starts_at, assessment.submitted_at, assessment.expires_at,
            assessment.email_sent_at, assessment.created_at, assessment.duration_minutes,
            assessment.assessment_name, assessment.assessment_round, assessment.pass_percentage,
            assessment.score, assessment.score_percentage, assessment.correct_answer_count,
            assessment.incorrect_answer_count, assessment.result, assessment.result_processed_at,
            assessment.time_taken_seconds, assessment.total_questions,
            candidate.name AS candidate_name, candidate.email AS candidate_email,
            job.title AS job_title, job.company, job.recruiter_id, application.status AS application_status,
            (SELECT COUNT(*) FROM assessment_questions q
                WHERE q.assessment_id = assessment.id AND q.selected_answer IS NOT NULL) AS answered_count
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            {where}
            ORDER BY assessment.created_at DESC, assessment.id DESC""",
            values,
        ).fetchall()
    items = []
    for row in rows:
        item = dict(row)
        started = datetime.fromisoformat(row["starts_at"]) if row["starts_at"] else None
        submitted = datetime.fromisoformat(row["submitted_at"]) if row["submitted_at"] else None
        item["time_taken_seconds"] = row["time_taken_seconds"]
        if item["time_taken_seconds"] is None:
            item["time_taken_seconds"] = max(0, int((submitted - started).total_seconds())) if started and submitted else None
        if user["role"] == "candidate":
            item.pop("recruiter_id", None)
            item.pop("candidate_id", None)
            item.pop("candidate_email", None)
        else:
            item["proctoring"] = proctoring_summary(db, row["id"])
        items.append(item)
    return {"items": items}


@app.get("/api/assessments/{assessment_id}/review")
def review_assessment(
    assessment_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            """SELECT assessment.*, candidate.name AS candidate_name,
            candidate.email AS candidate_email, job.title AS job_title,
            job.company, job.recruiter_id, application.status AS application_status
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.id = ?""",
            (assessment_id,),
        ).fetchone()
        if not row or (user["role"] == "recruiter" and row["recruiter_id"] != user["id"]):
            raise HTTPException(status_code=404, detail="Assessment not found for your job listings")
        if row["status"] != "Completed":
            raise HTTPException(status_code=409, detail="Assessment answers are available only after submission.")
        questions = db.execute(
            """SELECT question_order, question_text, options_json, correct_index,
            selected_answer, is_correct, difficulty, topic
            FROM assessment_questions WHERE assessment_id = ? ORDER BY question_order""",
            (assessment_id,),
        ).fetchall()
        proctoring = proctoring_summary(db, assessment_id)
    time_taken = row["time_taken_seconds"]
    if time_taken is None and row["starts_at"] and row["submitted_at"]:
        time_taken = max(
            0,
            int((datetime.fromisoformat(row["submitted_at"]) - datetime.fromisoformat(row["starts_at"])).total_seconds()),
        )
    return {
        "id": row["id"],
        "candidate_name": row["candidate_name"],
        "candidate_email": row["candidate_email"],
        "job_title": row["job_title"],
        "company": row["company"],
        "technology": row["technology"],
        "assessment_name": row["assessment_name"],
        "assessment_round": row["assessment_round"],
        "status": row["status"],
        "match_percentage": row["match_percentage"],
        "score": row["score_percentage"],
        "score_percentage": row["score_percentage"],
        "total_questions": row["total_questions"],
        "correct_answer_count": row["correct_answer_count"],
        "incorrect_answer_count": row["incorrect_answer_count"],
        "pass_percentage": row["pass_percentage"],
        "result": row["result"],
        "result_processed_at": row["result_processed_at"],
        "application_status": row["application_status"],
        "started_at": row["starts_at"],
        "submitted_at": row["submitted_at"],
        "time_taken_seconds": time_taken,
        "selection_reasoning": row["selection_reasoning"],
        "proctoring": proctoring,
        "selected_topics": list(dict.fromkeys(question["topic"] for question in questions)),
        "answered_count": sum(question["selected_answer"] is not None for question in questions),
        "questions": [
            {
                "number": question["question_order"],
                "question": question["question_text"],
                "options": json.loads(question["options_json"]),
                "selected_answer": question["selected_answer"],
                "correct_answer": question["correct_index"],
                "is_correct": bool(question["is_correct"]) if question["is_correct"] is not None else None,
                "difficulty": question["difficulty"],
                "technology": question["topic"],
            }
            for question in questions
        ],
    }


@app.get("/api/assessments/{assessment_id}/proctoring")
def review_assessment_proctoring(
    assessment_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        assessment = db.execute(
            """SELECT assessment.id, job.recruiter_id
            FROM assessments assessment JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.id = ?""",
            (assessment_id,),
        ).fetchone()
        if not assessment or (user["role"] == "recruiter" and assessment["recruiter_id"] != user["id"]):
            raise HTTPException(status_code=404, detail="Assessment not found for your job listings.")
        summary = proctoring_summary(db, assessment_id)
        events = db.execute(
            """SELECT event_type, severity, message, occurred_at, duration_seconds, metadata_json
            FROM assessment_proctoring_events WHERE assessment_id = ?
            ORDER BY occurred_at, id""",
            (assessment_id,),
        ).fetchall()
        recording_row = db.execute(
            """SELECT id, recording_status, duration_seconds, file_size_bytes, format,
                      started_at, ended_at, uploaded_at, upload_error
            FROM assessment_recordings WHERE assessment_id = ? ORDER BY id DESC LIMIT 1""",
            (assessment_id,),
        ).fetchone()
    return {
        "assessment_id": assessment_id,
        "summary": summary,
        "recording": {
            "id": recording_row["id"],
            "recording_status": recording_row["recording_status"],
            "duration_seconds": recording_row["duration_seconds"],
            "file_size_bytes": recording_row["file_size_bytes"],
            "format": recording_row["format"],
            "started_at": recording_row["started_at"],
            "ended_at": recording_row["ended_at"],
            "uploaded_at": recording_row["uploaded_at"],
            "has_recording": bool(recording_row["recording_status"] == "Uploaded"),
        } if recording_row else None,
        "events": [
            {
                "event_type": row["event_type"],
                "severity": row["severity"],
                "message": row["message"],
                "occurred_at": row["occurred_at"],
                "duration_seconds": row["duration_seconds"],
                "warning_number": json.loads(row["metadata_json"] or "{}").get("warning_number"),
            }
            for row in events
        ],
    }


@app.get("/api/applications/{application_id}/assessment/proctoring")
def review_application_assessment_proctoring(
    application_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            """SELECT assessment.id, job.recruiter_id
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN jobs job ON job.id = application.job_id
            WHERE application.id = ?""",
            (application_id,),
        ).fetchone()
        if not row or (user["role"] == "recruiter" and row["recruiter_id"] != user["id"]):
            raise HTTPException(status_code=404, detail="Assessment not found for this application.")
    return review_assessment_proctoring(row["id"], user)


@app.get("/api/admin/proctoring")
def admin_proctoring(
    job_id: int | None = None,
    recruiter_id: int | None = None,
    candidate: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    assessment_status: str | None = None,
    flagged: bool | None = None,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    del user
    clauses = ["assessment.proctoring_required = 1"]
    values: list[Any] = []
    if job_id is not None:
        clauses.append("assessment.job_id = ?")
        values.append(job_id)
    if recruiter_id is not None:
        clauses.append("job.recruiter_id = ?")
        values.append(recruiter_id)
    if candidate:
        clauses.append("(candidate.name LIKE ? OR candidate.email LIKE ?)")
        values.extend([f"%{candidate.strip()}%", f"%{candidate.strip()}%"])
    if assessment_status:
        clauses.append("assessment.status = ?")
        values.append(assessment_status)
    if flagged is not None:
        clauses.append("assessment.flagged_for_review = ?")
        values.append(int(flagged))
    for field, value, operator in (
        ("start_date", start_date, ">="),
        ("end_date", end_date, "<="),
    ):
        if value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError as error:
                raise HTTPException(status_code=422, detail=f"{field} must be an ISO date or datetime.") from error
            if field == "end_date" and len(value) == 10:
                parsed += timedelta(days=1)
                operator = "<"
            clauses.append(f"COALESCE(assessment.submitted_at, assessment.starts_at, assessment.created_at) {operator} ?")
            values.append(parsed.isoformat())
    where = "WHERE " + " AND ".join(clauses)
    with connect() as db:
        assessments = db.execute(
            f"""SELECT assessment.id, assessment.application_id, assessment.candidate_id,
            assessment.job_id, assessment.status, assessment.warning_count,
            assessment.flagged_for_review, assessment.flagged_at,
            assessment.camera_permission_granted_at, assessment.submitted_at,
            assessment.created_at, candidate.name AS candidate_name, candidate.email AS candidate_email,
            job.title AS job_title, job.recruiter_id, recruiter.name AS recruiter_name,
            assessment.recording_required, assessment.recording_status,
            recording.id AS recording_id, recording.duration_seconds AS recording_duration,
            recording.file_size_bytes AS recording_file_size, recording.format AS recording_format
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            JOIN users recruiter ON recruiter.id = job.recruiter_id
            LEFT JOIN assessment_recordings recording ON recording.assessment_id = assessment.id
            {where}
            ORDER BY assessment.flagged_for_review DESC, assessment.created_at DESC
            LIMIT 200""",
            values,
        ).fetchall()
        summary = db.execute(
            f"""SELECT COUNT(DISTINCT assessment.id) AS proctored_assessments,
            COUNT(DISTINCT CASE WHEN assessment.flagged_for_review = 1 THEN assessment.id END) AS flagged_assessments,
            COUNT(DISTINCT CASE WHEN event.event_type = 'camera_permission_denied' THEN assessment.id END) AS camera_denied,
            COUNT(DISTINCT CASE WHEN event.event_type = 'tab_hidden' THEN event.id END) AS tab_switches,
            COUNT(DISTINCT CASE WHEN event.event_type = 'face_not_detected' AND event.severity = 'Warning' THEN event.id END) AS face_warnings
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            LEFT JOIN assessment_proctoring_events event ON event.assessment_id = assessment.id
            {where}""",
            values,
        ).fetchone()
        top_candidates = db.execute(
            f"""SELECT assessment.candidate_id, candidate.name AS candidate_name,
            candidate.email AS candidate_email, MAX(assessment.warning_count) AS warning_count,
            COUNT(DISTINCT assessment.id) AS assessment_count
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            {where}
            GROUP BY assessment.candidate_id ORDER BY warning_count DESC LIMIT 10""",
            values,
        ).fetchall()
        event_rows = db.execute(
            f"""SELECT event.assessment_id, event.event_type, event.severity,
            event.message, event.occurred_at, event.duration_seconds, event.metadata_json,
            candidate.name AS candidate_name, job.title AS job_title
            FROM assessment_proctoring_events event
            JOIN assessments assessment ON assessment.id = event.assessment_id
            JOIN applications application ON application.id = assessment.application_id
            JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            {where}
            ORDER BY event.occurred_at DESC, event.id DESC LIMIT 50""",
            values,
        ).fetchall()
        recent_events = [
            {
                "assessment_id": row["assessment_id"],
                "event_type": row["event_type"],
                "severity": row["severity"],
                "message": row["message"],
                "occurred_at": row["occurred_at"],
                "duration_seconds": row["duration_seconds"],
                "warning_number": json.loads(row["metadata_json"] or "{}").get("warning_number"),
                "candidate_name": row["candidate_name"],
                "job_title": row["job_title"],
            }
            for row in event_rows
        ]
        job_filters = db.execute("SELECT id, title FROM jobs ORDER BY title").fetchall()
        recruiter_filters = db.execute(
            "SELECT id, name FROM users WHERE role = 'recruiter' ORDER BY name"
        ).fetchall()
        recording_stats = db.execute(
            """SELECT
            COUNT(CASE WHEN recording_status = 'Uploaded' THEN 1 END) AS total_recordings,
            COUNT(CASE WHEN recording_status = 'Failed' THEN 1 END) AS upload_failures,
            COUNT(CASE WHEN recording_status = 'Pending' THEN 1 END) AS uploads_pending
            FROM assessment_recordings"""
        ).fetchone()
    return {
        "summary": {
            "proctored_assessments": summary["proctored_assessments"] or 0,
            "camera_permission_denied_assessments": summary["camera_denied"] or 0,
            "flagged_assessments": summary["flagged_assessments"] or 0,
            "tab_switch_events": summary["tab_switches"] or 0,
            "face_not_visible_warnings": summary["face_warnings"] or 0,
            "total_recordings": recording_stats["total_recordings"] or 0,
            "upload_failures": recording_stats["upload_failures"] or 0,
            "uploads_pending": recording_stats["uploads_pending"] or 0,
        },
        "items": [
            {
                "assessment_id": row["id"],
                "application_id": row["application_id"],
                "candidate_id": row["candidate_id"],
                "candidate_name": row["candidate_name"],
                "candidate_email": row["candidate_email"],
                "job_id": row["job_id"],
                "job_title": row["job_title"],
                "recruiter_id": row["recruiter_id"],
                "recruiter_name": row["recruiter_name"],
                "assessment_status": row["status"],
                "warning_count": row["warning_count"],
                "flagged_for_review": bool(row["flagged_for_review"]),
                "flagged_at": row["flagged_at"],
                "camera_permission_granted": bool(row["camera_permission_granted_at"]),
                "submitted_at": row["submitted_at"],
                "created_at": row["created_at"],
                "recording_required": bool(row["recording_required"]),
                "recording_status": row["recording_status"],
                "recording_id": row["recording_id"],
                "recording_duration": row["recording_duration"],
                "recording_file_size": row["recording_file_size"],
                "has_recording": bool(row["recording_id"] and row["recording_status"] == "Uploaded"),
            }
            for row in assessments
        ],
        "top_candidates": [dict(row) for row in top_candidates],
        "recent_activity": [dict(row) for row in recent_events],
        "jobs": [dict(row) for row in job_filters],
        "recruiters": [dict(row) for row in recruiter_filters],
    }


def assessment_from_token(token: str, allow_started_timeout: bool = False) -> sqlite3.Row:
    if len(token) < 32 or len(token) > 200:
        raise HTTPException(status_code=404, detail="Assessment link is invalid or has expired.")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    rejection: tuple[int, str] | None = None
    with connect() as db:
        row = db.execute(
            """SELECT assessment.*, application.status AS application_status,
            job.title AS job_title, job.company AS company
            FROM assessments assessment
            JOIN applications application ON application.id = assessment.application_id
            JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.token_hash = ?""",
            (token_hash,),
        ).fetchone()
        if not row or row["status"] in {"Completed", "Expired", "Not Sent", "Manual Topic Required"}:
            raise HTTPException(status_code=404, detail="Assessment link is invalid, revoked, or already used.")
        if row["application_status"] in {"Withdrawn", "Rejected", "Selected", "Accepted"}:
            db.execute("UPDATE assessments SET status = 'Expired', token_hash = NULL WHERE id = ?", (row["id"],))
            rejection = (404, "This assessment invitation is no longer active.")
        elif row["expires_at"] and row["expires_at"] <= now() and not (
            allow_started_timeout and row["status"] == "Started"
        ):
            rejection = (410, "This assessment link has expired.")
    if rejection:
        if rejection[0] == 410 and row:
            expire_assessment(row["id"])
        elif row:
            with connect() as db:
                db.execute(
                    "UPDATE assessments SET status = 'Expired', token_hash = NULL WHERE id = ?",
                    (row["id"],),
                )
        raise HTTPException(status_code=rejection[0], detail=rejection[1])
    return row


def proctoring_event_message(event_type: str) -> str:
    return {
        "camera_permission_granted": "Camera permission was granted.",
        "camera_permission_denied": "Camera permission was not granted.",
        "camera_unavailable": "A camera was unavailable for this assessment.",
        "camera_stream_stopped": "The camera stream stopped during the assessment.",
        "face_detected": "Face visibility was detected.",
        "face_not_detected": "No face was visible for the reported duration.",
        "face_detected_again": "Face visibility recovered.",
        "tab_hidden": "The assessment page was hidden.",
        "tab_visible_again": "The assessment page became visible again.",
        "window_blur": "The assessment window lost focus.",
        "window_focus": "The assessment window regained focus.",
        "fullscreen_exited": "Fullscreen mode was exited.",
        "warning_shown": "A proctoring warning was shown to the candidate.",
        "assessment_flagged": "The assessment reached its proctoring warning threshold.",
    }[event_type]


def insert_proctoring_event(
    db: sqlite3.Connection,
    assessment: sqlite3.Row,
    event_type: str,
    severity: str,
    duration_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    occurred_at = now()
    db.execute(
        """INSERT INTO assessment_proctoring_events
        (assessment_id, candidate_id, application_id, event_type, severity, message,
        occurred_at, duration_seconds, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            assessment["id"], assessment["candidate_id"], assessment["application_id"],
            event_type, severity, proctoring_event_message(event_type), occurred_at,
            duration_seconds, json.dumps(metadata or {}), occurred_at,
        ),
    )


def proctoring_summary(db: sqlite3.Connection, assessment_id: int) -> dict[str, Any]:
    assessment = db.execute(
        """SELECT proctoring_required, proctoring_status, warning_count,
        flagged_for_review, flagged_at, camera_permission_granted_at
        FROM assessments WHERE id = ?""",
        (assessment_id,),
    ).fetchone()
    event_counts = {
        row["event_type"]: row["count"]
        for row in db.execute(
            """SELECT event_type, COUNT(*) AS count
            FROM assessment_proctoring_events WHERE assessment_id = ? GROUP BY event_type""",
            (assessment_id,),
        ).fetchall()
    }
    return {
        "proctoring_required": bool(assessment["proctoring_required"]),
        "proctoring_status": assessment["proctoring_status"],
        "camera_permission_granted": bool(assessment["camera_permission_granted_at"]),
        "camera_permission_granted_at": assessment["camera_permission_granted_at"],
        "warning_count": assessment["warning_count"],
        "flagged_for_review": bool(assessment["flagged_for_review"]),
        "flagged_at": assessment["flagged_at"],
        "tab_switch_count": event_counts.get("tab_hidden", 0),
        "face_not_visible_incidents": db.execute(
            """SELECT COUNT(*) FROM assessment_proctoring_events
            WHERE assessment_id = ? AND event_type = 'face_not_detected'
            AND severity = 'Warning'""",
            (assessment_id,),
        ).fetchone()[0],
        "camera_permission_denied_count": event_counts.get("camera_permission_denied", 0),
    }


@app.post("/api/assessments/{token}/proctoring/start")
def start_proctoring(token: str, body: ProctoringStartBody) -> dict[str, Any]:
    assessment = assessment_from_token(token)
    if not body.permission_granted:
        with connect() as db:
            insert_proctoring_event(db, assessment, "camera_permission_denied", "Warning")
        raise HTTPException(status_code=403, detail="Camera access is required before this assessment can start.")
    if assessment["status"] not in {"Sent", "Started"}:
        raise HTTPException(status_code=409, detail="This assessment is not available to start proctoring.")
    with connect() as db:
        row = db.execute("SELECT * FROM assessments WHERE id = ?", (assessment["id"],)).fetchone()
        if row["status"] not in {"Sent", "Started"}:
            raise HTTPException(status_code=409, detail="This assessment is no longer active.")
        if not row["camera_permission_granted_at"] or row["proctoring_status"] != "Active":
            insert_proctoring_event(db, row, "camera_permission_granted", "Info")
        db.execute(
            """UPDATE assessments SET camera_permission_granted_at = COALESCE(camera_permission_granted_at, ?),
            proctoring_status = 'Active' WHERE id = ?""",
            (now(), row["id"]),
        )
        current = db.execute("SELECT * FROM assessments WHERE id = ?", (row["id"],)).fetchone()
        return {
            "permission_granted": True,
            "proctoring_required": bool(current["proctoring_required"]),
            "warning_count": current["warning_count"],
            "flagged_for_review": bool(current["flagged_for_review"]),
            "max_warnings": max_proctoring_warnings(),
            "face_missing_warning_seconds": proctoring_face_missing_seconds(),
        }


@app.post("/api/assessments/{token}/proctoring/events")
def save_proctoring_event(token: str, body: ProctoringEventBody) -> dict[str, Any]:
    if body.event_type not in PROCTORING_EVENT_TYPES or body.event_type in {
        "camera_permission_granted", "assessment_flagged"
    }:
        raise HTTPException(status_code=422, detail="Unsupported proctoring event.")
    assessment = assessment_from_token(token)
    if assessment["status"] not in {"Sent", "Started"}:
        raise HTTPException(status_code=409, detail="This assessment is no longer active.")
    if assessment["status"] == "Sent" and body.event_type not in {
        "camera_permission_denied", "camera_unavailable"
    }:
        raise HTTPException(status_code=409, detail="Start camera proctoring before recording assessment activity.")
    if assessment["status"] == "Started" and assessment["proctoring_required"] and (
        not assessment["camera_permission_granted_at"]
        or assessment["proctoring_status"] != "Active"
    ):
        raise HTTPException(status_code=409, detail="Start camera proctoring before recording assessment activity.")

    warning_events = {
        "tab_hidden", "window_blur", "face_not_detected", "camera_stream_stopped", "fullscreen_exited"
    }
    increments_warning = body.event_type in warning_events
    if body.event_type == "face_not_detected" and (
        body.duration_seconds is None or body.duration_seconds < proctoring_face_missing_seconds()
    ):
        increments_warning = False
    with connect() as db:
        row = db.execute("SELECT * FROM assessments WHERE id = ?", (assessment["id"],)).fetchone()
        if body.event_type == "window_blur":
            last_hidden = db.execute(
                """SELECT occurred_at FROM assessment_proctoring_events
                WHERE assessment_id = ? AND event_type = 'tab_hidden'
                ORDER BY id DESC LIMIT 1""",
                (row["id"],),
            ).fetchone()
            if last_hidden and (
                datetime.now(timezone.utc) - datetime.fromisoformat(last_hidden["occurred_at"])
            ).total_seconds() < 3:
                increments_warning = False
        recent = db.execute(
            """SELECT occurred_at, severity FROM assessment_proctoring_events
            WHERE assessment_id = ? AND event_type = ?
            ORDER BY id DESC LIMIT 1""",
            (row["id"], body.event_type),
        ).fetchone()
        if recent and (
            datetime.now(timezone.utc) - datetime.fromisoformat(recent["occurred_at"])
        ).total_seconds() < 5 and not (
            body.event_type == "face_not_detected"
            and increments_warning
            and recent["severity"] == "Info"
        ):
            return {
                "accepted": False,
                "warning_count": row["warning_count"],
                "flagged_for_review": bool(row["flagged_for_review"]),
                "max_warnings": max_proctoring_warnings(),
                "auto_submit": False,
            }
        severity = "Warning" if increments_warning else "Info"
        warning_count = row["warning_count"] + int(increments_warning)
        metadata = {"warning_number": warning_count} if increments_warning else {}
        insert_proctoring_event(
            db, row, body.event_type, severity, body.duration_seconds, metadata
        )
        if body.event_type in {"face_detected", "face_detected_again"}:
            db.execute("UPDATE assessments SET last_face_detected_at = ? WHERE id = ?", (now(), row["id"]))
        if increments_warning:
            db.execute("UPDATE assessments SET warning_count = ? WHERE id = ?", (warning_count, row["id"]))
        flagged_now = warning_count >= max_proctoring_warnings() and not row["flagged_for_review"]
        if flagged_now:
            flagged_at = now()
            db.execute(
                "UPDATE assessments SET flagged_for_review = 1, flagged_at = ? WHERE id = ?",
                (flagged_at, row["id"]),
            )
            insert_proctoring_event(
                db, row, "assessment_flagged", "High", metadata={"warning_number": warning_count}
            )
        return {
            "accepted": True,
            "warning_count": warning_count,
            "flagged_for_review": bool(row["flagged_for_review"] or flagged_now),
            "max_warnings": max_proctoring_warnings(),
            "auto_submit": bool(flagged_now and auto_submit_on_max_proctoring_warnings()),
        }


@app.get("/api/assessments/{token}/proctoring/status")
def get_proctoring_status(token: str) -> dict[str, Any]:
    assessment = assessment_from_token(token, allow_started_timeout=True)
    return {
        "proctoring_required": bool(assessment["proctoring_required"]),
        "proctoring_status": assessment["proctoring_status"],
        "warning_count": assessment["warning_count"],
        "max_warnings": max_proctoring_warnings(),
        "face_missing_warning_seconds": proctoring_face_missing_seconds(),
        "flagged_for_review": bool(assessment["flagged_for_review"]),
        "recording_required": bool(assessment["recording_required"]),
        "recording_status": assessment["recording_status"],
        "recording_consent_given": bool(assessment["recording_consent_given_at"]),
    }


@app.post("/api/assessments/{token}/recording/start")
def start_assessment_recording(token: str, body: RecordingStartBody) -> dict[str, Any]:
    assessment = assessment_from_token(token)
    if not body.consent_given:
        raise HTTPException(status_code=422, detail="Candidate consent is required for webcam recording.")
    if assessment["status"] not in {"Sent", "Started"}:
        raise HTTPException(status_code=409, detail="This assessment is no longer active.")
    with connect() as db:
        now_iso = now()
        db.execute(
            """UPDATE assessments
               SET recording_consent_given_at = COALESCE(recording_consent_given_at, ?),
                   recording_consent_version = ?,
                   recording_status = 'Pending'
               WHERE id = ?""",
            (now_iso, body.consent_version, assessment["id"]),
        )
        existing = db.execute(
            "SELECT id FROM assessment_recordings WHERE assessment_id = ?",
            (assessment["id"],),
        ).fetchone()
        if not existing:
            db.execute(
                """INSERT INTO assessment_recordings (
                    assessment_id, application_id, candidate_id, recording_status,
                    started_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'Pending', ?, ?, ?)""",
                (
                    assessment["id"],
                    assessment["application_id"],
                    assessment["candidate_id"],
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
        else:
            db.execute(
                "UPDATE assessment_recordings SET updated_at = ? WHERE id = ?",
                (now_iso, existing["id"]),
            )
    return {
        "consent_recorded": True,
        "recording_required": bool(assessment["recording_required"]),
        "status": "Pending",
    }


@app.post("/api/assessments/{token}/recording/upload")
def upload_assessment_recording(
    token: str,
    file: UploadFile = File(...),
    duration_seconds: int | None = Form(None),
) -> dict[str, Any]:
    assessment = assessment_from_token(token, allow_started_timeout=True)
    content = file.file.read()
    max_bytes = recording_max_upload_bytes()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Recording file size ({len(content)} bytes) exceeds the maximum allowed limit of {max_bytes} bytes.",
        )

    now_iso = now()
    content_format = "webm"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[-1].lower()
        if ext in {"webm", "mp4", "mkv", "mov"}:
            content_format = ext

    upload_error = None
    upload_result = None
    public_id = f"skillsphere/recordings/assessment_{assessment['id']}_{int(datetime.now(timezone.utc).timestamp())}"

    if cloudinary_configured():
        try:
            upload_result = upload_video_to_cloudinary(
                content,
                public_id=public_id,
                tags=[f"assessment_{assessment['id']}", f"candidate_{assessment['candidate_id']}", "skillsphere_proctoring"],
            )
        except Exception as exc:
            upload_error = str(exc)
            notify_admins(
                "recording_upload_failed",
                "Assessment recording upload failed",
                f"Webcam recording upload failed for assessment #{assessment['id']}: {upload_error}",
                "/",
            )
    else:
        upload_result = {
            "public_id": public_id,
            "asset_id": f"mock_asset_{assessment['id']}",
            "resource_type": "video",
            "secure_url": "",
            "duration": duration_seconds or 0,
            "format": content_format,
        }

    with connect() as db:
        existing = db.execute(
            "SELECT id FROM assessment_recordings WHERE assessment_id = ?",
            (assessment["id"],),
        ).fetchone()

        status = "Uploaded" if upload_result and not upload_error else "Failed"
        effective_duration = (
            int(upload_result.get("duration") or 0)
            if upload_result and upload_result.get("duration")
            else duration_seconds
        )

        if existing:
            db.execute(
                """UPDATE assessment_recordings
                   SET cloudinary_public_id = ?,
                       cloudinary_asset_id = ?,
                       cloudinary_resource_type = ?,
                       secure_url = ?,
                       duration_seconds = ?,
                       file_size_bytes = ?,
                       format = ?,
                       recording_status = ?,
                       upload_error = ?,
                       ended_at = COALESCE(ended_at, ?),
                       uploaded_at = ?,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    upload_result.get("public_id") if upload_result else None,
                    upload_result.get("asset_id") if upload_result else None,
                    upload_result.get("resource_type", "video") if upload_result else "video",
                    upload_result.get("secure_url") if upload_result else None,
                    effective_duration,
                    len(content),
                    upload_result.get("format", content_format) if upload_result else content_format,
                    status,
                    upload_error,
                    now_iso,
                    now_iso if status == "Uploaded" else None,
                    now_iso,
                    existing["id"],
                ),
            )
        else:
            db.execute(
                """INSERT INTO assessment_recordings (
                    assessment_id, application_id, candidate_id, cloudinary_public_id,
                    cloudinary_asset_id, cloudinary_resource_type, secure_url, duration_seconds,
                    file_size_bytes, format, recording_status, upload_error, started_at,
                    ended_at, uploaded_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment["id"],
                    assessment["application_id"],
                    assessment["candidate_id"],
                    upload_result.get("public_id") if upload_result else None,
                    upload_result.get("asset_id") if upload_result else None,
                    upload_result.get("resource_type", "video") if upload_result else "video",
                    upload_result.get("secure_url") if upload_result else None,
                    effective_duration,
                    len(content),
                    upload_result.get("format", content_format) if upload_result else content_format,
                    status,
                    upload_error,
                    now_iso,
                    now_iso,
                    now_iso if status == "Uploaded" else None,
                    now_iso,
                    now_iso,
                ),
            )

        db.execute(
            """UPDATE assessments
               SET recording_status = ?,
                   recording_failure_reason = ?,
                   recording_available_at = ?
               WHERE id = ?""",
            (
                status,
                upload_error,
                now_iso if status == "Uploaded" else None,
                assessment["id"],
            ),
        )

    return {
        "success": status == "Uploaded",
        "status": status,
        "duration_seconds": effective_duration,
        "file_size_bytes": len(content),
        "error": upload_error,
        "non_blocking": True,
    }


@app.post("/api/assessments/{token}/recording/complete")
def complete_assessment_recording(token: str, body: RecordingCompleteBody) -> dict[str, Any]:
    assessment = assessment_from_token(token, allow_started_timeout=True)
    with connect() as db:
        now_iso = now()
        db.execute(
            """UPDATE assessment_recordings
               SET ended_at = ?,
                   duration_seconds = COALESCE(?, duration_seconds),
                   updated_at = ?
               WHERE assessment_id = ?""",
            (now_iso, body.duration_seconds, now_iso, assessment["id"]),
        )
    return {"completed": True}


@app.get("/api/admin/assessments/{assessment_id}/recordings")
def list_assessment_recordings(
    assessment_id: int,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> list[dict[str, Any]]:
    del user
    with connect() as db:
        rows = db.execute(
            """SELECT id, assessment_id, application_id, candidate_id, recording_status,
                      duration_seconds, file_size_bytes, format, upload_error, started_at,
                      ended_at, uploaded_at, created_at, updated_at
               FROM assessment_recordings WHERE assessment_id = ?
               ORDER BY id DESC""",
            (assessment_id,),
        ).fetchall()
        return [dict(row) for row in rows]


@app.get("/api/admin/recordings/{recording_id}/playback")
def get_recording_playback(
    recording_id: int,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    with connect() as db:
        recording = db.execute(
            "SELECT * FROM assessment_recordings WHERE id = ?",
            (recording_id,),
        ).fetchone()
        if not recording:
            raise HTTPException(status_code=404, detail="Assessment recording not found.")
        if recording["recording_status"] != "Uploaded":
            raise HTTPException(
                status_code=400,
                detail=f"Recording is not ready for playback (status: {recording['recording_status']}).",
            )

        db.execute(
            "INSERT INTO admin_recording_access_logs (recording_id, admin_id, accessed_at) VALUES (?, ?, ?)",
            (recording_id, user["id"], now()),
        )

        playback_url = ""
        if cloudinary_configured() and recording["cloudinary_public_id"]:
            playback_url = generate_signed_playback_url(
                recording["cloudinary_public_id"],
                resource_type=recording["cloudinary_resource_type"] or "video",
                format=recording["format"] or "webm",
                expires_in_seconds=3600,
            )
        elif recording["secure_url"]:
            playback_url = recording["secure_url"]

        return {
            "recording_id": recording["id"],
            "assessment_id": recording["assessment_id"],
            "playback_url": playback_url,
            "expires_in_seconds": 3600,
            "duration_seconds": recording["duration_seconds"],
            "format": recording["format"],
            "file_size_bytes": recording["file_size_bytes"],
            "uploaded_at": recording["uploaded_at"],
        }


@app.post("/api/admin/recordings/cleanup")
def cleanup_old_recordings(
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    del user
    days = recording_retention_days()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    cleaned = 0
    with connect() as db:
        expired_recordings = db.execute(
            """SELECT recording.id, recording.cloudinary_public_id, recording.cloudinary_resource_type
               FROM assessment_recordings recording
               JOIN assessments assessment ON assessment.id = recording.assessment_id
               WHERE recording.uploaded_at < ?
                 AND recording.recording_status = 'Uploaded'
                 AND assessment.flagged_for_review = 0""",
            (cutoff,),
        ).fetchall()

        for rec in expired_recordings:
            if cloudinary_configured() and rec["cloudinary_public_id"]:
                try:
                    import cloudinary.uploader
                    cloudinary.uploader.destroy(
                        rec["cloudinary_public_id"],
                        resource_type=rec["cloudinary_resource_type"] or "video",
                    )
                except Exception:
                    pass
            db.execute(
                """UPDATE assessment_recordings
                   SET recording_status = 'Expired',
                       secure_url = NULL,
                       cloudinary_public_id = NULL,
                       updated_at = ?
                   WHERE id = ?""",
                (now(), rec["id"]),
            )
            cleaned += 1

    return {"cleaned_count": cleaned, "retention_days": days}


@app.get("/api/assessments/{token}")
def get_assessment(token: str) -> dict[str, Any]:
    assessment = assessment_from_token(token)
    with connect() as db:
        questions = assessment_questions_for_client(db, assessment["id"])
    return {
        "job_title": assessment["job_title"],
        "company": assessment["company"],
        "technology": assessment["technology"],
        "assessment_name": assessment["assessment_name"],
        "assessment_round": assessment["assessment_round"],
        "pass_percentage": assessment["pass_percentage"],
        "status": assessment["status"],
        "question_count": assessment["total_questions"],
        "duration_minutes": assessment["duration_minutes"],
        "expires_at": assessment["expires_at"],
        "started_at": assessment["starts_at"],
        "proctoring_required": bool(assessment["proctoring_required"]),
        "proctoring_status": assessment["proctoring_status"],
        "recording_required": bool(assessment["recording_required"]),
        "recording_status": assessment["recording_status"],
        "recording_consent_given": bool(assessment["recording_consent_given_at"]),
        "questions": questions if assessment["status"] == "Started" and (
            not assessment["proctoring_required"] or assessment["proctoring_status"] == "Active"
        ) else [],
    }


@app.post("/api/assessments/{token}/start")
def start_assessment(token: str) -> dict[str, Any]:
    assessment = assessment_from_token(token)
    started_application = None
    with connect() as db:
        row = db.execute("SELECT * FROM assessments WHERE id = ?", (assessment["id"],)).fetchone()
        if row["proctoring_required"] and (
            not row["camera_permission_granted_at"] or row["proctoring_status"] != "Active"
        ):
            raise HTTPException(status_code=409, detail="Grant camera permission before starting the assessment.")
        if row["recording_required"] and recording_required() and not row["recording_consent_given_at"]:
            raise HTTPException(status_code=409, detail="Consent to webcam recording before starting the assessment.")
        if row["status"] == "Sent":
            started_at = datetime.now(timezone.utc)
            expires_at = min(
                datetime.fromisoformat(row["expires_at"]),
                started_at + timedelta(minutes=row["duration_minutes"]),
            ).isoformat()
            updated = db.execute(
                """UPDATE assessments SET status = 'Started', starts_at = ?, expires_at = ?
                WHERE id = ? AND status = 'Sent'""",
                (started_at.isoformat(), expires_at, row["id"]),
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=409, detail="This assessment has already been started.")
            application = db.execute(
                """SELECT application.id, application.status, application.match_percentage,
                application.candidate_id, job.recruiter_id, job.title, job.company
                FROM applications application JOIN jobs job ON job.id = application.job_id
                WHERE application.id = ?""",
                (row["application_id"],),
            ).fetchone()
            if application["status"] == "Assessment Sent":
                record_application_status(db, application["id"], "Assessment Started", None)
            started_application = application
        elif row["status"] != "Started":
            raise HTTPException(status_code=409, detail="This assessment cannot be started.")
        row = db.execute("SELECT * FROM assessments WHERE id = ?", (assessment["id"],)).fetchone()
        questions = assessment_questions_for_client(db, row["id"])
    if started_application:
        message = f"The candidate started the {row['technology']} assessment for {started_application['title']}."
        notify_user(
            started_application["recruiter_id"], "assessment_started", "Candidate started an assessment",
            message, application_id=started_application["id"], assessment_id=row["id"], action_url="/",
        )
        notify_admins("assessment_started", "Assessment started", message, "/")
    return {
        "status": row["status"],
        "technology": row["technology"],
        "assessment_name": row["assessment_name"],
        "assessment_round": row["assessment_round"],
        "pass_percentage": row["pass_percentage"],
        "started_at": row["starts_at"],
        "expires_at": row["expires_at"],
        "questions": questions,
    }


@app.put("/api/assessments/{token}/answers")
def save_assessment_answers(token: str, body: AssessmentSubmissionBody) -> dict[str, Any]:
    if any(answer < -1 or answer > 3 for answer in body.answers):
        raise HTTPException(status_code=422, detail="Choose one of the four options for every question.")
    assessment = assessment_from_token(token)
    if assessment["status"] != "Started":
        raise HTTPException(status_code=409, detail="Start the assessment before saving answers.")
    with connect() as db:
        updated = db.executemany(
            """UPDATE assessment_questions SET selected_answer = ?
            WHERE assessment_id = ? AND question_order = ?""",
            [
                (answer, assessment["id"], order)
                for order, answer in enumerate(body.answers, start=1)
            ],
        )
        if updated.rowcount != 20:
            raise HTTPException(status_code=409, detail="The assessment question set is incomplete.")
    return {"saved": True}


@app.post("/api/assessments/{token}/submit")
def submit_assessment(token: str, body: AssessmentSubmissionBody) -> dict[str, Any]:
    if any(answer < -1 or answer > 3 for answer in body.answers):
        raise HTTPException(status_code=422, detail="Select one of the four options for every question.")
    assessment = assessment_from_token(token, allow_started_timeout=True)
    submitted_at = now()
    expired = False
    with connect() as db:
        row = db.execute("SELECT * FROM assessments WHERE id = ?", (assessment["id"],)).fetchone()
        if row["status"] != "Started":
            raise HTTPException(status_code=409, detail="This assessment has already been submitted or was not started.")
        expired = not row["expires_at"] or row["expires_at"] <= submitted_at
        questions = db.execute(
            """SELECT question_order, correct_index FROM assessment_questions
            WHERE assessment_id = ? ORDER BY question_order""",
            (row["id"],),
        ).fetchall()
        if len(questions) != 20:
            raise HTTPException(status_code=500, detail="The assessment question set is incomplete.")
        score_count = 0
        final_answers = (
            [question["selected_answer"] for question in db.execute(
                """SELECT selected_answer FROM assessment_questions
                WHERE assessment_id = ? ORDER BY question_order""",
                (row["id"],),
            ).fetchall()]
            if expired
            else body.answers
        )
        for question, selected_answer in zip(questions, final_answers):
            selected_answer = selected_answer if selected_answer is not None else -1
            is_correct = int(selected_answer >= 0 and question["correct_index"] == selected_answer)
            score_count += is_correct
            db.execute(
                """UPDATE assessment_questions SET selected_answer = ?, is_correct = ?, answered_at = ?
                WHERE assessment_id = ? AND question_order = ?""",
                (selected_answer, is_correct, submitted_at, row["id"], question["question_order"]),
            )
        total_questions = len(questions)
        score_percentage = round(score_count / total_questions * 100, 1)
        score = round(score_percentage)
        assessment_result = "Passed" if score_percentage >= row["pass_percentage"] else "Failed"
        time_taken_seconds = max(
            0,
            int((
                datetime.fromisoformat(submitted_at) - datetime.fromisoformat(row["starts_at"])
            ).total_seconds()),
        )
        updated = db.execute(
            """UPDATE assessments SET status = 'Completed', score = ?, score_percentage = ?,
            correct_answer_count = ?, incorrect_answer_count = ?, result = ?,
            result_processed_at = ?, time_taken_seconds = ?, submitted_at = ?, token_hash = NULL,
            proctoring_status = CASE WHEN proctoring_required = 1 THEN 'Completed' ELSE proctoring_status END
            WHERE id = ? AND status = 'Started'""",
            (
                score, score_percentage, score_count, total_questions - score_count,
                assessment_result, submitted_at, time_taken_seconds, submitted_at, row["id"],
            ),
        )
        if updated.rowcount != 1:
            raise HTTPException(status_code=409, detail="This assessment has already been submitted.")
        application = db.execute(
            """SELECT application.id, application.status, application.candidate_id,
            job.recruiter_id, job.title, job.company, candidate.name AS candidate_name
            FROM applications application JOIN jobs job ON job.id = application.job_id
            JOIN users candidate ON candidate.id = application.candidate_id
            WHERE application.id = ?""",
            (row["application_id"],),
        ).fetchone()
        if application["status"] in {"Assessment Sent", "Assessment Started"}:
            record_application_status(db, application["id"], "Assessment Completed", None)
        final_status = f"Round 1 {assessment_result}"
        if application["status"] != final_status:
            record_application_status(db, application["id"], final_status, None)
        result_record = {
            "assessment_id": row["id"],
            "application_id": application["id"],
            "candidate_id": application["candidate_id"],
            "recruiter_id": application["recruiter_id"],
            "candidate_name": application["candidate_name"],
            "title": application["title"],
            "company": application["company"],
            "assessment_name": row["assessment_name"],
            "assessment_round": row["assessment_round"],
            "total_questions": total_questions,
            "correct_answer_count": score_count,
            "incorrect_answer_count": total_questions - score_count,
            "score_percentage": score_percentage,
            "pass_percentage": row["pass_percentage"],
            "result": assessment_result,
            "submitted_at": submitted_at,
            "time_taken_seconds": time_taken_seconds,
        }
    candidate_message = (
        f"You scored {result_record['score_percentage']:g}% on Round 1 for "
        f"{result_record['title']} at {result_record['company']}. "
        + (
            "The recruiter will review your profile for next steps."
            if result_record["result"] == "Passed"
            else "You did not reach the required passing score. Thank you for completing the assessment; the recruiter will review your profile."
        )
    )
    notify_user(
        result_record["candidate_id"],
        "round1_result",
        "You passed Round 1" if result_record["result"] == "Passed" else "Round 1 result",
        candidate_message,
        application_id=result_record["application_id"],
        assessment_id=result_record["assessment_id"],
        action_url="/",
        send_email=True,
    )
    notify_user(
        result_record["recruiter_id"],
        "round1_result",
        "Candidate completed Round 1",
        f"{result_record['candidate_name']} completed {result_record['assessment_name']} for "
        f"{result_record['title']} at {result_record['company']}: "
        f"{result_record['score_percentage']:g}% ({result_record['result']}).",
        application_id=result_record["application_id"],
        assessment_id=result_record["assessment_id"],
        action_url="/",
    )
    notify_admins(
        "round1_result",
        "Round 1 assessment completed",
        f"{result_record['candidate_name']} scored {result_record['score_percentage']:g}% "
        f"({result_record['result']}) for {result_record['title']} at {result_record['company']}.",
        "/",
        application_id=result_record["application_id"],
        assessment_id=result_record["assessment_id"],
    )
    return {
        "status": "Completed",
        "assessment_name": result_record["assessment_name"],
        "assessment_round": result_record["assessment_round"],
        "total_questions": result_record["total_questions"],
        "correct_answer_count": result_record["correct_answer_count"],
        "incorrect_answer_count": result_record["incorrect_answer_count"],
        "score": result_record["score_percentage"],
        "pass_percentage": result_record["pass_percentage"],
        "result": result_record["result"],
        "result_message": (
            "Congratulations, you have cleared Round 1."
            if result_record["result"] == "Passed"
            else "Thank you for completing Round 1. You did not reach the required passing score."
        ),
        "submitted_at": result_record["submitted_at"],
        "time_taken_seconds": result_record["time_taken_seconds"],
        "timed_out": expired,
    }


@app.get("/api/applications/{application_id}/resume")
def download_application_resume(
    application_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> FileResponse:
    with connect() as db:
        row = db.execute(
            """SELECT r.storage_path, r.filename, r.content_type FROM applications a
            JOIN jobs j ON j.id = a.job_id JOIN resumes r ON r.id = a.resume_id
            WHERE a.id = ? AND (? = 'admin' OR j.recruiter_id = ?)""",
            (application_id, user["role"], user["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Resume not found for your job listings")
    path = Path(row["storage_path"]).resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Resume file is unavailable")
    return FileResponse(path, filename=row["filename"], media_type=row["content_type"])


@app.post("/api/resume/upload", status_code=201)
async def upload_resume(
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    content = await file.read(MAX_RESUME_BYTES + 1)
    if not content:
        raise HTTPException(status_code=422, detail="This file is empty")
    if len(content) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=413, detail="Resume must be 10 MB or smaller")
    name = Path(file.filename or "resume").name
    suffix = Path(name).suffix.lower()
    mime_by_suffix = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
    expected_type = mime_by_suffix.get(suffix)
    if not expected_type:
        raise HTTPException(status_code=415, detail="Use a PDF, JPG, JPEG, or PNG resume")
    if expected_type == "application/pdf" and not content.startswith(b"%PDF-"):
        raise HTTPException(status_code=415, detail="This file does not contain a valid PDF")
    if expected_type == "image/jpeg" and not content.startswith(b"\xff\xd8\xff"):
        raise HTTPException(status_code=415, detail="This file does not contain a valid JPEG image")
    if expected_type == "image/png" and not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HTTPException(status_code=415, detail="This file does not contain a valid PNG image")
    storage_path = UPLOAD_DIR / f"{uuid.uuid4().hex}{suffix}"
    status = "completed"
    processing_error = ""
    try:
        text = await run_in_threadpool(extract_resume_text, content, expected_type)
        if not text:
            status = "needs_review"
            processing_error = "No readable text was found. Try a clearer, text-based PDF or image."
    except HTTPException:
        raise
    except Exception as error:
        text = ""
        status = "needs_review"
        if error.__class__.__name__ == "TesseractNotFoundError":
            processing_error = "Resume uploaded, but OCR is unavailable. Install Tesseract OCR and try again."
        elif expected_type == "application/pdf":
            processing_error = f"Resume uploaded, but text could not be extracted: {error.__class__.__name__}. Try a text-based PDF."
        else:
            processing_error = f"Resume uploaded, but text could not be extracted: {error.__class__.__name__}. Try a clearer image."
    storage_path.write_bytes(content)
    profile = detect_profile(text)
    try:
        with connect() as db:
            old = db.execute("SELECT storage_path FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
            cursor = db.execute(
                """INSERT INTO resumes
                (candidate_id, filename, storage_path, content_type, extracted_text, parsed_profile_json, processing_status, processing_error, uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(candidate_id) DO UPDATE SET
                filename = excluded.filename, storage_path = excluded.storage_path, content_type = excluded.content_type,
                extracted_text = excluded.extracted_text, parsed_profile_json = excluded.parsed_profile_json,
                processing_status = excluded.processing_status, processing_error = excluded.processing_error,
                uploaded_at = excluded.uploaded_at""",
                (user["id"], name, str(storage_path), expected_type, text, json.dumps(profile), status, processing_error, now()),
            )
            row = db.execute("SELECT * FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
        if old:
            old_path = Path(old["storage_path"])
            if old_path != storage_path and old_path.is_file():
                old_path.unlink()
    except Exception:
        storage_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()
    return public_resume(row)


@app.get("/api/resume")
def get_resume(user: dict[str, Any] = Depends(require_role("candidate"))) -> dict[str, Any] | None:
    with connect() as db:
        row = db.execute("SELECT * FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
    if not row:
        return None
    return public_resume(row)


@app.get("/api/resume/profile")
def resume_profile(user: dict[str, Any] = Depends(require_role("candidate"))) -> dict[str, Any]:
    with connect() as db:
        row = db.execute("SELECT * FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No resume found")
    return public_resume(row)


@app.get("/api/resume/download")
def download_resume(user: dict[str, Any] = Depends(require_role("candidate"))) -> FileResponse:
    with connect() as db:
        row = db.execute("SELECT * FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="No resume found")
    path = Path(row["storage_path"]).resolve()
    if not path.is_relative_to(UPLOAD_DIR.resolve()) or not path.is_file():
        raise HTTPException(status_code=404, detail="Resume file is unavailable")
    return FileResponse(path, filename=row["filename"], media_type=row["content_type"])


@app.get("/api/matches/{job_id}")
def match_job(job_id: int, user: dict[str, Any] = Depends(require_role("candidate"))) -> dict[str, Any]:
    with connect() as db:
        job = db.execute("SELECT * FROM jobs WHERE id = ? AND status = 'Open'", (job_id,)).fetchone()
        resume = db.execute("SELECT extracted_text, parsed_profile_json FROM resumes WHERE candidate_id = ?", (user["id"],)).fetchone()
        saved_profile = db.execute("SELECT profile_json FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not job:
        raise HTTPException(status_code=404, detail="This role is no longer available")
    if not resume:
        raise HTTPException(status_code=409, detail="Upload a resume to see your match")
    required = json.loads(job["skills_json"])
    result = calculate_match(
        required, resume["extracted_text"], resume["parsed_profile_json"], saved_profile["profile_json"]
    )
    if not result["matched_skills"]:
        recommendation = "Add relevant experience or skills to your profile to strengthen your application."
    elif result["missing_skills"]:
        recommendation = f"Highlight your experience with {', '.join(result['missing_skills'])} if it reflects your background."
    else:
        recommendation = "Your resume mentions every listed skill. Make sure your experience shows how you use them."
    return {
        "job_id": job_id,
        "match_percentage": result["match_percentage"],
        "matched_skills": result["matched_skills"],
        "missing_skills": result["missing_skills"],
        "recommendation": recommendation,
    }


@app.post("/api/resume/analyze")
def analyze_resume(
    body: MatchBody,
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    return match_job(body.job_id, user)


@app.get("/api/recruiter/applicants")
def recruiter_applicants(user: dict[str, Any] = Depends(require_role("recruiter"))) -> dict[str, Any]:
    return list_applications(user)


def interview_query() -> str:
    return """SELECT i.id, i.application_id, i.recruiter_id, i.candidate_id, i.starts_at,
    i.teams_url, i.meeting_platform, i.meeting_url, i.duration_minutes, i.timezone,
    i.recruiter_message, i.code, i.language, i.status, i.invitation_sent_at,
    i.candidate_viewed_at, i.created_at, i.updated_at,
    j.id AS job_id, j.title, j.company, candidate.name AS candidate_name,
    candidate.email AS candidate_email, recruiter.name AS recruiter_name
    FROM interviews i
    JOIN applications a ON a.id = i.application_id
    JOIN jobs j ON j.id = a.job_id
    JOIN users candidate ON candidate.id = i.candidate_id
    JOIN users recruiter ON recruiter.id = i.recruiter_id"""


def interview_for_participant(interview_id: int, user: dict[str, Any]) -> sqlite3.Row:
    with connect() as db:
        if user["role"] == "admin":
            row = db.execute(f"{interview_query()} WHERE i.id = ?", (interview_id,)).fetchone()
        else:
            row = db.execute(
                f"{interview_query()} WHERE i.id = ? AND (i.candidate_id = ? OR i.recruiter_id = ?)",
                (interview_id, user["id"], user["id"]),
            ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Interview not found")
    return row


def validate_interview_schedule(
    starts_at: datetime,
    timezone_name: str,
    meeting_url: str,
) -> tuple[datetime, str]:
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Choose an interview time with a timezone")
    if starts_at.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="Choose an interview date and time in the future")
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, TypeError) as error:
        raise HTTPException(status_code=422, detail="Choose a valid time zone") from error
    if meeting_url:
        parsed_url = urlsplit(meeting_url.strip())
        if parsed_url.scheme.lower() != "https" or not parsed_url.netloc or parsed_url.username or parsed_url.password:
            raise HTTPException(status_code=422, detail="Meeting URL must be a valid HTTPS URL")
        meeting_url = meeting_url.strip()
    return starts_at.astimezone(timezone.utc), meeting_url


def interview_schedule_label(starts_at: str, timezone_name: str) -> str:
    local_time = datetime.fromisoformat(starts_at).astimezone(ZoneInfo(timezone_name))
    return local_time.strftime("%d %B %Y, %I:%M %p")


def notify_interview_candidate(interview_id: int, event: str) -> None:
    with connect() as db:
        row = db.execute(
            f"{interview_query()} WHERE i.id = ?",
            (interview_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Interview {interview_id} disappeared before notification.")
    titles = {
        "scheduled": "Interview scheduled",
        "rescheduled": "Interview rescheduled",
        "updated": "Interview details updated",
        "cancelled": "Interview cancelled",
        "completed": "Interview completed",
    }
    title = titles[event]
    date_label = interview_schedule_label(row["starts_at"], row["timezone"])
    message = (
        f"Your interview for {row['title']} at {row['company']} is {event} for "
        f"{date_label} ({row['timezone']}). Duration: {row['duration_minutes']} minutes. "
        f"Platform: {row['meeting_platform']}."
    )
    if row["recruiter_message"]:
        message += f" Recruiter instructions: {row['recruiter_message']}"
    notification_id = notify_user(
        row["candidate_id"],
        "interview_" + event,
        title,
        message,
        application_id=row["application_id"],
        action_url=(
            row["meeting_url"]
            if row["meeting_url"] and event not in {"cancelled", "completed"}
            else "/"
        ),
        email_delivery_status="pending",
    )
    try:
        delivery = send_interview_email(
            row["candidate_email"],
            row["title"],
            row["company"],
            date_label,
            row["timezone"],
            row["duration_minutes"],
            row["meeting_platform"],
            row["meeting_url"] if event not in {"cancelled", "completed"} else "",
            row["recruiter_message"],
        )
        status = "sent" if delivery == "email" else "development_console"
    except EmailDeliveryError as error:
        logger.error("Interview email delivery failed for interview %s: %s", interview_id, error)
        status = "failed"
    with connect() as db:
        db.execute(
            "UPDATE notifications SET email_delivery_status = ? WHERE id = ?",
            (status, notification_id),
        )


def create_interview(
    application_id: int,
    starts_at: datetime,
    timezone_name: str,
    duration_minutes: int,
    meeting_platform: str,
    meeting_url: str,
    recruiter_message: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    starts_utc, meeting_url = validate_interview_schedule(starts_at, timezone_name, meeting_url)
    allowed_platforms = {
        "google meet": "Google Meet",
        "microsoft teams": "Microsoft Teams",
        "zoom": "Zoom",
        "other": "Other",
    }
    platform = allowed_platforms.get(meeting_platform.strip().casefold())
    if not platform:
        raise HTTPException(status_code=422, detail="Choose Google Meet, Microsoft Teams, Zoom, or Other")
    current_time = now()
    with connect() as db:
        application = db.execute(
            """SELECT a.id, a.candidate_id, a.status, j.recruiter_id, candidate.email
            FROM applications a JOIN jobs j ON j.id = a.job_id
            JOIN users candidate ON candidate.id = a.candidate_id WHERE a.id = ?""",
            (application_id,),
        ).fetchone()
        if user["role"] != "admin" and (not application or application["recruiter_id"] != user["id"]):
            raise HTTPException(status_code=404, detail="Application not found for your job listings")
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")
        if application["status"] in {"Rejected", "Withdrawn", "Accepted", "Selected"}:
            raise HTTPException(status_code=409, detail="Interviews cannot be scheduled for a closed application")
        active = db.execute(
            """SELECT 1 FROM interviews WHERE application_id = ?
            AND status IN ('Scheduled', 'Rescheduled') LIMIT 1""",
            (application_id,),
        ).fetchone()
        if active:
            raise HTTPException(status_code=409, detail="Reschedule the existing interview instead")
        cursor = db.execute(
            """INSERT INTO interviews
            (application_id, recruiter_id, candidate_id, starts_at, teams_url, meeting_platform,
            meeting_url, duration_minutes, timezone, recruiter_message, status,
            invitation_sent_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Scheduled', ?, ?, ?)""",
            (
                application_id,
                application["recruiter_id"],
                application["candidate_id"],
                starts_utc.isoformat(),
                meeting_url,
                platform,
                meeting_url,
                duration_minutes,
                timezone_name,
                recruiter_message.strip(),
                current_time,
                current_time,
                current_time,
            ),
        )
        record_application_status(
            db,
            application_id,
            "Interview",
            None if user["role"] == "admin" else user["id"],
        )
        row = db.execute(
            f"{interview_query()} WHERE i.id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    notify_interview_candidate(row["id"], "scheduled")
    return dict(row)


@app.post("/api/applications/{application_id}/interviews", status_code=201)
def schedule_application_interview(
    application_id: int,
    body: InterviewScheduleBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    return create_interview(
        application_id,
        body.starts_at,
        body.timezone,
        body.duration_minutes,
        body.meeting_platform,
        body.meeting_url,
        body.recruiter_message,
        user,
    )


@app.post("/api/interviews", status_code=201)
def schedule_interview(
    body: InterviewBody,
    user: dict[str, Any] = Depends(require_role("recruiter")),
) -> dict[str, Any]:
    starts_at = body.starts_at
    if starts_at.tzinfo is None or starts_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Choose an interview time with a timezone")
    teams_url = str(body.teams_url)
    if not re.match(
        r"^https://([a-z0-9-]+\.)*(teams\.microsoft\.com|teams\.live\.com)(/|$)",
        teams_url,
        re.IGNORECASE,
    ):
        raise HTTPException(status_code=422, detail="Use a valid Microsoft Teams meeting link")
    return create_interview(
        body.application_id,
        starts_at,
        "UTC",
        60,
        "Microsoft Teams",
        teams_url,
        "",
        user,
    )


@app.patch("/api/applications/{application_id}/interviews/{interview_id}")
def update_application_interview(
    application_id: int,
    interview_id: int,
    body: InterviewUpdateBody,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=True, exclude_none=True)
    with connect() as db:
        row = db.execute(
            f"""{interview_query()} WHERE i.id = ? AND i.application_id = ?
            AND (? = 'admin' OR i.recruiter_id = ?)""",
            (interview_id, application_id, user["role"], user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Interview not found for this application")
        if row["status"] in {"Cancelled", "Completed"}:
            raise HTTPException(status_code=409, detail="Cancelled or completed interviews cannot be changed")
        starts_at = values.get("starts_at", datetime.fromisoformat(row["starts_at"]))
        timezone_name = values.get("timezone", row["timezone"])
        meeting_url = values.get("meeting_url", row["meeting_url"])
        starts_utc, meeting_url = validate_interview_schedule(starts_at, timezone_name, meeting_url)
        platform_value = values.get("meeting_platform", row["meeting_platform"])
        platform_map = {
            "google meet": "Google Meet",
            "microsoft teams": "Microsoft Teams",
            "zoom": "Zoom",
            "other": "Other",
        }
        platform = platform_map.get(platform_value.strip().casefold())
        if not platform:
            raise HTTPException(status_code=422, detail="Choose Google Meet, Microsoft Teams, Zoom, or Other")
        changed_schedule = starts_utc.isoformat() != row["starts_at"] or timezone_name != row["timezone"]
        changed_link = meeting_url != row["meeting_url"]
        duration = values.get("duration_minutes", row["duration_minutes"])
        message = values.get("recruiter_message", row["recruiter_message"]).strip()
        updated_at = now()
        status = "Rescheduled" if changed_schedule or row["status"] == "Rescheduled" else "Scheduled"
        db.execute(
            """UPDATE interviews SET starts_at = ?, teams_url = ?, meeting_platform = ?,
            meeting_url = ?, duration_minutes = ?, timezone = ?, recruiter_message = ?,
            status = ?, invitation_sent_at = ?, updated_at = ? WHERE id = ?""",
            (
                starts_utc.isoformat(), meeting_url, platform, meeting_url, duration,
                timezone_name, message, status, updated_at, updated_at, interview_id,
            ),
        )
    notify_interview_candidate(
        interview_id,
        "rescheduled" if changed_schedule else "updated" if changed_link else "updated",
    )
    return dict(interview_for_participant(interview_id, user))


def update_interview_terminal_status(
    application_id: int,
    interview_id: int,
    status: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            f"""{interview_query()} WHERE i.id = ? AND i.application_id = ?
            AND (? = 'admin' OR i.recruiter_id = ?)""",
            (interview_id, application_id, user["role"], user["id"]),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Interview not found for this application")
        if row["status"] in {"Cancelled", "Completed"}:
            raise HTTPException(status_code=409, detail="This interview is already closed")
        db.execute(
            "UPDATE interviews SET status = ?, updated_at = ? WHERE id = ?",
            (status, now(), interview_id),
        )
    notify_interview_candidate(interview_id, status.lower())
    return dict(interview_for_participant(interview_id, user))


@app.post("/api/applications/{application_id}/interviews/{interview_id}/cancel")
def cancel_application_interview(
    application_id: int,
    interview_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    return update_interview_terminal_status(application_id, interview_id, "Cancelled", user)


@app.post("/api/applications/{application_id}/interviews/{interview_id}/complete")
def complete_application_interview(
    application_id: int,
    interview_id: int,
    user: dict[str, Any] = Depends(require_role("recruiter", "admin")),
) -> dict[str, Any]:
    return update_interview_terminal_status(application_id, interview_id, "Completed", user)


@app.get("/api/interviews")
def list_interviews(user: dict[str, Any] = Depends(require_role("candidate", "recruiter", "admin"))) -> dict[str, Any]:
    participant_filter = ""
    parameters: tuple[Any, ...] = ()
    if user["role"] == "candidate":
        participant_filter = "WHERE i.candidate_id = ?"
        parameters = (user["id"],)
    elif user["role"] == "recruiter":
        participant_filter = "WHERE i.recruiter_id = ?"
        parameters = (user["id"],)
    with connect() as db:
        rows = db.execute(
            f"{interview_query()} {participant_filter} ORDER BY i.starts_at ASC",
            parameters,
        ).fetchall()
    return {"items": [interview_public_payload(row, user) for row in rows]}


@app.get("/api/interviews/upcoming")
def upcoming_candidate_interviews(
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    with connect() as db:
        rows = db.execute(
            f"""{interview_query()} WHERE i.candidate_id = ?
            AND i.status IN ('Scheduled', 'Rescheduled') AND i.starts_at > ?
            ORDER BY i.starts_at ASC""",
            (user["id"], now()),
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.post("/api/interviews/{interview_id}/viewed")
def mark_interview_viewed(
    interview_id: int,
    user: dict[str, Any] = Depends(require_role("candidate")),
) -> dict[str, Any]:
    with connect() as db:
        result = db.execute(
            """UPDATE interviews SET candidate_viewed_at = COALESCE(candidate_viewed_at, ?)
            WHERE id = ? AND candidate_id = ?""",
            (now(), interview_id, user["id"]),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Interview not found")
    return {"status": "viewed"}


@app.get("/api/interviews/{interview_id}")
def get_interview(
    interview_id: int,
    user: dict[str, Any] = Depends(require_role("candidate", "recruiter", "admin")),
) -> dict[str, Any]:
    return interview_public_payload(interview_for_participant(interview_id, user), user)


@app.post("/api/interviews/{interview_id}/run")
async def run_interview_code(
    interview_id: int,
    body: CodeRunBody,
    user: dict[str, Any] = Depends(require_role("candidate", "recruiter")),
) -> dict[str, Any]:
    interview_for_participant(interview_id, user)
    language_id = CODE_LANGUAGES.get(body.language)
    if not language_id:
        raise HTTPException(status_code=422, detail="Choose a supported programming language")
    runner_url = os.environ.get("SKILLSPHERE_JUDGE0_URL", "").rstrip("/")
    if not runner_url:
        raise HTTPException(
            status_code=503,
            detail="Code execution is not configured. Set up a private Judge0 runner and SKILLSPHERE_JUDGE0_URL.",
        )
    headers = {"Content-Type": "application/json"}
    runner_token = os.environ.get("SKILLSPHERE_JUDGE0_TOKEN")
    if runner_token:
        headers["X-Auth-Token"] = runner_token
    try:
        import httpx

        async with httpx.AsyncClient(timeout=12, follow_redirects=False) as client:
            response = await client.post(
                f"{runner_url}/submissions?base64_encoded=false&wait=true",
                headers=headers,
                json={
                    "language_id": language_id,
                    "source_code": body.code,
                    "stdin": body.stdin,
                },
            )
    except httpx.TimeoutException as error:
        raise HTTPException(status_code=504, detail="The isolated code runner timed out") from error
    except httpx.HTTPError as error:
        raise HTTPException(status_code=502, detail="The isolated code runner is unavailable") from error
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="The isolated code runner rejected the request")
    try:
        result = response.json()
    except ValueError as error:
        raise HTTPException(status_code=502, detail="The isolated code runner returned an invalid response") from error
    return {
        "stdout": (result.get("stdout") or "")[:10_000],
        "stderr": (result.get("stderr") or "")[:10_000],
        "compile_output": (result.get("compile_output") or "")[:10_000],
        "message": (result.get("message") or "")[:2_000],
        "time": result.get("time"),
        "memory": result.get("memory"),
        "status": (result.get("status") or {}).get("description", "Unknown"),
    }


def sync_save_interview_code(interview_id: int, code: str) -> None:
    with connect() as db:
        db.execute("UPDATE interviews SET code = ? WHERE id = ?", (code, interview_id))


def sync_save_interview_language(interview_id: int, language: str) -> None:
    with connect() as db:
        db.execute("UPDATE interviews SET language = ? WHERE id = ?", (language, interview_id))


@app.websocket("/api/interviews/{interview_id}/code")
async def interview_code_socket(websocket: WebSocket, interview_id: int) -> None:
    await websocket.accept()
    try:
        auth_message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(auth_message, dict) or auth_message.get("type") != "auth":
            await websocket.close(code=1008, reason="Authentication required")
            return
        token = auth_message.get("token")
        session_cookie = websocket.cookies.get(AUTH_COOKIE_NAME)
        if not session_cookie and not isinstance(token, str):
            await websocket.close(code=1008, reason="Authentication required")
            return
        user = get_current_user(token=session_cookie or f"Bearer {token}")
        if user["role"] not in {"candidate", "recruiter"}:
            await websocket.close(code=1008, reason="Interview access denied")
            return
        row = interview_for_participant(interview_id, user)
    except (asyncio.TimeoutError, HTTPException, ValueError):
        await websocket.close(code=1008, reason="Interview access denied")
        return

    async with interview_connection_lock:
        room = interview_connections.setdefault(interview_id, set())
        room.add(websocket)
    await websocket.send_json({"type": "snapshot", "code": row["code"], "language": row["language"]})
    try:
        while True:
            message = await websocket.receive_json()
            if not isinstance(message, dict):
                continue
            if message.get("type") == "code" and isinstance(message.get("code"), str):
                code = message["code"]
                if len(code) > MAX_INTERVIEW_CODE_LENGTH:
                    await websocket.send_json({"type": "error", "message": "Code is limited to 30,000 characters."})
                    continue
                await run_in_threadpool(sync_save_interview_code, interview_id, code)
                outgoing = {"type": "code", "code": code}
            elif message.get("type") == "language" and message.get("language") in CODE_LANGUAGES:
                language = message["language"]
                await run_in_threadpool(sync_save_interview_language, interview_id, language)
                outgoing = {"type": "language", "language": language}
            else:
                continue
            async with interview_connection_lock:
                connections = tuple(interview_connections.get(interview_id, ()))
            for connection in connections:
                if connection is websocket:
                    continue
                try:
                    await connection.send_json(outgoing)
                except (RuntimeError, WebSocketDisconnect):
                    async with interview_connection_lock:
                        interview_connections.get(interview_id, set()).discard(connection)
    except WebSocketDisconnect:
        pass
    finally:
        async with interview_connection_lock:
            room = interview_connections.get(interview_id)
            if room:
                room.discard(websocket)
                if not room:
                    interview_connections.pop(interview_id, None)


@app.patch("/api/profile")
def update_profile(body: ProfileBody, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    profile = dict(body.profile)
    profile.pop("email", None)
    if len(json.dumps(profile, ensure_ascii=False)) > 8_000:
        raise HTTPException(status_code=422, detail="Profile details must be 8 KB or smaller")
    with connect() as db:
        db.execute("UPDATE users SET name = ?, profile_json = ? WHERE id = ?", (body.name.strip(), json.dumps(profile), user["id"]))
        row = db.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    return public_user(row)


@app.get("/api/admin/jobs")
def admin_jobs(user: dict[str, Any] = Depends(require_role("admin"))) -> dict[str, Any]:
    del user
    with connect() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created_at DESC, id ASC LIMIT 500").fetchall()
    return {"items": [public_job(row) for row in rows]}


@app.patch("/api/admin/jobs/{job_id}/status")
def update_job_status(
    job_id: int,
    body: JobStatusBody,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    del user
    if body.status not in {"Open", "Closed"}:
        raise HTTPException(status_code=422, detail="Choose Open or Closed")
    with connect() as db:
        result = db.execute("UPDATE jobs SET status = ? WHERE id = ?", (body.status, job_id))
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Job listing not found")
    return {"id": job_id, "status": body.status}


@app.patch("/api/admin/users/{user_id}/status")
def update_user_status(
    user_id: int,
    body: UserStatusBody,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    if user_id == user["id"] and not body.active:
        raise HTTPException(status_code=409, detail="You cannot disable your own admin account")
    with connect() as db:
        result = db.execute(
            "UPDATE users SET active = ? WHERE id = ? AND role IN ('candidate', 'recruiter')",
            (int(body.active), user_id),
        )
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Account not found")
    return {"id": user_id, "active": body.active}


@app.get("/api/admin/users")
def admin_users(user: dict[str, Any] = Depends(require_role("admin"))) -> dict[str, Any]:
    del user
    with connect() as db:
        rows = db.execute(
            """SELECT users.id, users.name, users.email, users.role, users.active,
            users.created_at,
            MAX(
                COALESCE((SELECT MAX(application.applied_at) FROM applications application
                    WHERE application.candidate_id = users.id), ''),
                COALESCE((SELECT MAX(notification.created_at) FROM notifications notification
                    WHERE notification.user_id = users.id), ''),
                COALESCE((SELECT MAX(resume.uploaded_at) FROM resumes resume
                    WHERE resume.candidate_id = users.id), ''),
                COALESCE((SELECT MAX(job.created_at) FROM jobs job
                    WHERE job.recruiter_id = users.id), ''),
                COALESCE((SELECT MAX(interview.created_at) FROM interviews interview
                    WHERE interview.candidate_id = users.id OR interview.recruiter_id = users.id), '')
            ) AS last_activity
            FROM users ORDER BY users.created_at DESC LIMIT 500"""
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/admin/analytics")
def analytics(
    range: str = "this_week",
    start_date: str | None = None,
    end_date: str | None = None,
    user: dict[str, Any] = Depends(require_role("admin")),
) -> dict[str, Any]:
    today = datetime.now(timezone.utc).date()
    this_monday = today - timedelta(days=today.weekday())
    if range == "this_week":
        start = datetime.combine(this_monday, datetime.min.time(), timezone.utc)
        end = start + timedelta(days=7)
    elif range == "last_week":
        end = datetime.combine(this_monday, datetime.min.time(), timezone.utc)
        start = end - timedelta(days=7)
    elif range == "custom":
        if not start_date or not end_date:
            raise HTTPException(status_code=422, detail="Custom analytics requires start_date and end_date.")
        try:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Use ISO date values for the custom range.") from error
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if len(end_date) == 10:
            end += timedelta(days=1)
        if end <= start:
            raise HTTPException(status_code=422, detail="end_date must be later than start_date.")
    else:
        raise HTTPException(status_code=422, detail="Choose this_week, last_week, or custom.")
    start_text = start.astimezone(timezone.utc).isoformat()
    end_text = end.astimezone(timezone.utc).isoformat()
    period = (start_text, end_text)
    notify_expiring_assessments(user)
    with connect() as db:
        expired_ids = [
            row["id"] for row in db.execute(
                """SELECT id FROM assessments WHERE status IN ('Sent', 'Started')
                AND expires_at IS NOT NULL AND expires_at <= ?""",
                (now(),),
            ).fetchall()
        ]
    for assessment_id in expired_ids:
        expire_assessment(assessment_id)
    with connect() as db:
        def count(sql: str, values: tuple[Any, ...] = ()) -> int:
            return db.execute(sql, values).fetchone()[0]

        totals = {
            "users": count("SELECT COUNT(*) FROM users"),
            "candidates": count("SELECT COUNT(*) FROM users WHERE role = 'candidate'"),
            "recruiters": count("SELECT COUNT(*) FROM users WHERE role = 'recruiter'"),
            "jobs": count("SELECT COUNT(*) FROM jobs"),
            "open_jobs": count("SELECT COUNT(*) FROM jobs WHERE status = 'Open'"),
            "applications": count("SELECT COUNT(*) FROM applications"),
            "shortlisted": count("SELECT COUNT(*) FROM applications WHERE status IN ('Shortlisted', 'Assessment Sent', 'Assessment Started', 'Assessment Completed', 'Round 1 Passed', 'Round 1 Failed')"),
            "assessments_sent": count("SELECT COUNT(*) FROM assessments WHERE email_sent_at IS NOT NULL"),
            "assessments_started": count("SELECT COUNT(*) FROM assessments WHERE starts_at IS NOT NULL"),
            "assessments_completed": count("SELECT COUNT(*) FROM assessments WHERE status = 'Completed'"),
            "assessments_expired": count("SELECT COUNT(*) FROM assessments WHERE expired_at IS NOT NULL"),
        }
        counts = {
            "new_candidates": count(
                "SELECT COUNT(*) FROM users WHERE role = 'candidate' AND created_at >= ? AND created_at < ?", period
            ),
            "new_recruiters": count(
                "SELECT COUNT(*) FROM users WHERE role = 'recruiter' AND created_at >= ? AND created_at < ?", period
            ),
            "jobs_posted": count(
                "SELECT COUNT(*) FROM jobs WHERE created_at >= ? AND created_at < ?", period
            ),
            "applications_received": count(
                "SELECT COUNT(*) FROM applications WHERE applied_at >= ? AND applied_at < ?", period
            ),
            "candidates_shortlisted": count(
                """SELECT COUNT(*) FROM application_status_history
                WHERE status = 'Shortlisted' AND updated_at >= ? AND updated_at < ?""", period
            ),
            "assessments_sent": count(
                "SELECT COUNT(*) FROM assessments WHERE email_sent_at >= ? AND email_sent_at < ?", period
            ),
            "assessments_started": count(
                "SELECT COUNT(*) FROM assessments WHERE starts_at >= ? AND starts_at < ?", period
            ),
            "assessments_completed": count(
                "SELECT COUNT(*) FROM assessments WHERE submitted_at >= ? AND submitted_at < ?", period
            ),
            "assessments_expired": count(
                "SELECT COUNT(*) FROM assessments WHERE expired_at >= ? AND expired_at < ?", period
            ),
            "candidates_in_interview": count(
                """SELECT COUNT(*) FROM application_status_history
                WHERE status = 'Interview' AND updated_at >= ? AND updated_at < ?""", period
            ),
            "accepted_candidates": count(
                """SELECT COUNT(*) FROM application_status_history
                WHERE status IN ('Accepted', 'Selected') AND updated_at >= ? AND updated_at < ?""", period
            ),
            "rejected_candidates": count(
                """SELECT COUNT(*) FROM application_status_history
                WHERE status = 'Rejected' AND updated_at >= ? AND updated_at < ?""", period
            ),
        }
        average_score = db.execute(
            """SELECT AVG(score) FROM assessments
            WHERE status = 'Completed' AND submitted_at >= ? AND submitted_at < ?""",
            period,
        ).fetchone()[0]
        counts["average_assessment_score"] = round(average_score, 1) if average_score is not None else None
        counts["assessment_completion_rate"] = round(
            counts["assessments_completed"] / counts["assessments_sent"] * 100, 1
        ) if counts["assessments_sent"] else 0
        round1_period = (
            "Round 1", "Completed", start_text, end_text,
        )
        counts["round1_assessments_completed"] = count(
            """SELECT COUNT(*) FROM assessments
            WHERE assessment_round = ? AND status = ? AND result_processed_at >= ? AND result_processed_at < ?""",
            round1_period,
        )
        counts["round1_passed"] = count(
            """SELECT COUNT(*) FROM assessments
            WHERE assessment_round = ? AND status = ? AND result = 'Passed'
            AND result_processed_at >= ? AND result_processed_at < ?""",
            round1_period,
        )
        counts["round1_failed"] = count(
            """SELECT COUNT(*) FROM assessments
            WHERE assessment_round = ? AND status = ? AND result = 'Failed'
            AND result_processed_at >= ? AND result_processed_at < ?""",
            round1_period,
        )
        counts["round1_pass_rate"] = round(
            counts["round1_passed"] / counts["round1_assessments_completed"] * 100, 1
        ) if counts["round1_assessments_completed"] else 0
        round1_average = db.execute(
            """SELECT AVG(score_percentage) FROM assessments
            WHERE assessment_round = ? AND status = ? AND result_processed_at >= ? AND result_processed_at < ?""",
            round1_period,
        ).fetchone()[0]
        counts["round1_average_score"] = round(round1_average, 1) if round1_average is not None else None

        pipeline_rows = db.execute(
            """SELECT status, COUNT(*) AS count FROM applications GROUP BY status ORDER BY count DESC"""
        ).fetchall()
        assessment_rows = db.execute(
            """SELECT status, COUNT(*) AS count FROM assessments GROUP BY status ORDER BY count DESC"""
        ).fetchall()
        score_rows = db.execute(
            """SELECT CASE WHEN score < 50 THEN '0-49' WHEN score < 70 THEN '50-69'
            WHEN score < 90 THEN '70-89' ELSE '90-100' END AS band, COUNT(*) AS count
            FROM assessments WHERE status = 'Completed' AND submitted_at >= ? AND submitted_at < ?
            GROUP BY band ORDER BY band""",
            period,
        ).fetchall()
        round1_score_rows = db.execute(
            """SELECT result AS band, COUNT(*) AS count
            FROM assessments
            WHERE assessment_round = 'Round 1' AND status = 'Completed'
            AND result_processed_at >= ? AND result_processed_at < ?
            GROUP BY result ORDER BY result""",
            period,
        ).fetchall()
        jobs_by_applications = db.execute(
            """SELECT job.title, job.company, COUNT(application.id) AS applications
            FROM applications application JOIN jobs job ON job.id = application.job_id
            WHERE application.applied_at >= ? AND application.applied_at < ?
            GROUP BY job.id ORDER BY applications DESC, job.title LIMIT 5""",
            period,
        ).fetchall()
        jobs_by_shortlists = db.execute(
            """SELECT job.title, job.company, COUNT(DISTINCT history.application_id) AS shortlisted
            FROM application_status_history history
            JOIN applications application ON application.id = history.application_id
            JOIN jobs job ON job.id = application.job_id
            WHERE history.status = 'Shortlisted' AND history.updated_at >= ? AND history.updated_at < ?
            GROUP BY job.id ORDER BY shortlisted DESC, job.title LIMIT 5""",
            period,
        ).fetchall()
        round1_passed_by_job = db.execute(
            """SELECT job.title, job.company, COUNT(*) AS candidates
            FROM assessments assessment JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.assessment_round = 'Round 1' AND assessment.result = 'Passed'
            AND assessment.result_processed_at >= ? AND assessment.result_processed_at < ?
            GROUP BY job.id ORDER BY candidates DESC, job.title LIMIT 10""",
            period,
        ).fetchall()
        round1_failed_by_job = db.execute(
            """SELECT job.title, job.company, COUNT(*) AS candidates
            FROM assessments assessment JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.assessment_round = 'Round 1' AND assessment.result = 'Failed'
            AND assessment.result_processed_at >= ? AND assessment.result_processed_at < ?
            GROUP BY job.id ORDER BY candidates DESC, job.title LIMIT 10""",
            period,
        ).fetchall()
        technologies = db.execute(
            """SELECT technology, COUNT(*) AS assessments FROM assessments
            WHERE technology IS NOT NULL AND created_at >= ? AND created_at < ?
            GROUP BY technology ORDER BY assessments DESC, technology LIMIT 10""",
            period,
        ).fetchall()
        question_technologies = db.execute(
            """SELECT technology, COUNT(*) AS questions FROM job_questions
            WHERE active = 1 GROUP BY technology""",
        ).fetchall()
        activity = db.execute(
            """SELECT notification.type, notification.title, notification.message,
            notification.created_at, user.name AS user_name
            FROM notifications notification JOIN users user ON user.id = notification.user_id
            WHERE notification.created_at >= ? AND notification.created_at < ?
            ORDER BY notification.created_at DESC LIMIT 10""",
            period,
        ).fetchall()
        recent_applications = db.execute(
            """SELECT candidate.name AS candidate_name, job.title, job.company,
            application.status, application.match_percentage, application.applied_at
            FROM applications application JOIN users candidate ON candidate.id = application.candidate_id
            JOIN jobs job ON job.id = application.job_id
            WHERE application.applied_at >= ? AND application.applied_at < ?
            ORDER BY application.applied_at DESC LIMIT 10""",
            period,
        ).fetchall()
        recent_assessments = db.execute(
            """SELECT candidate.name AS candidate_name, job.title, assessment.technology,
            assessment.score, assessment.submitted_at
            FROM assessments assessment JOIN users candidate ON candidate.id = assessment.candidate_id
            JOIN jobs job ON job.id = assessment.job_id
            WHERE assessment.status = 'Completed' AND assessment.submitted_at >= ? AND assessment.submitted_at < ?
            ORDER BY assessment.submitted_at DESC LIMIT 10""",
            period,
        ).fetchall()
        users_list_rows = db.execute(
            """SELECT users.id, users.name, users.email, users.role, users.active,
            users.created_at,
            MAX(
                COALESCE((SELECT MAX(application.applied_at) FROM applications application
                    WHERE application.candidate_id = users.id), ''),
                COALESCE((SELECT MAX(notification.created_at) FROM notifications notification
                    WHERE notification.user_id = users.id), ''),
                COALESCE((SELECT MAX(resume.uploaded_at) FROM resumes resume
                    WHERE resume.candidate_id = users.id), ''),
                COALESCE((SELECT MAX(job.created_at) FROM jobs job
                    WHERE job.recruiter_id = users.id), ''),
                COALESCE((SELECT MAX(interview.created_at) FROM interviews interview
                    WHERE interview.candidate_id = users.id OR interview.recruiter_id = users.id), '')
            ) AS last_activity
            FROM users ORDER BY users.created_at DESC LIMIT 500"""
        ).fetchall()
        trend_rows = db.execute(
            """SELECT substr(applied_at, 1, 10) AS day, COUNT(*) AS applications
            FROM applications WHERE applied_at >= ? AND applied_at < ?
            GROUP BY day""",
            period,
        ).fetchall()
        sent_rows = db.execute(
            """SELECT substr(email_sent_at, 1, 10) AS day, COUNT(*) AS count
            FROM assessments WHERE email_sent_at >= ? AND email_sent_at < ?
            GROUP BY day""",
            period,
        ).fetchall()
        started_rows = db.execute(
            """SELECT substr(starts_at, 1, 10) AS day, COUNT(*) AS count
            FROM assessments WHERE starts_at >= ? AND starts_at < ?
            GROUP BY day""",
            period,
        ).fetchall()
        completed_rows = db.execute(
            """SELECT substr(submitted_at, 1, 10) AS day, COUNT(*) AS count
            FROM assessments WHERE submitted_at >= ? AND submitted_at < ?
            GROUP BY day""",
            period,
        ).fetchall()
        admins = db.execute(
            "SELECT id FROM users WHERE role = 'admin' AND active = 1"
        ).fetchall()
        weekly_report_admins = [
            row["id"] for row in admins
            if not db.execute(
                """SELECT 1 FROM notifications WHERE user_id = ? AND type = 'weekly_report'
                AND created_at >= ? AND created_at < ? LIMIT 1""",
                (row["id"], start_text, end_text),
            ).fetchone()
        ] if range == "this_week" else []
    trend = []
    current_day = start.date()
    while current_day < end.date():
        day = current_day.isoformat()
        trend.append({"date": day, "applications": 0, "assessments_sent": 0, "assessments_started": 0, "assessments_completed": 0})
        current_day += timedelta(days=1)
    trend_by_day = {item["date"]: item for item in trend}
    for row in trend_rows:
        if row["day"] in trend_by_day:
            trend_by_day[row["day"]]["applications"] = row["applications"]
    for field, rows in (
        ("assessments_sent", sent_rows),
        ("assessments_started", started_rows),
        ("assessments_completed", completed_rows),
    ):
        for row in rows:
            if row["day"] in trend_by_day:
                trend_by_day[row["day"]][field] = row["count"]
    question_counts = {row["technology"]: row["questions"] for row in question_technologies}
    assessment_counts = {row["technology"]: row["assessments"] for row in technologies}
    top_technologies = [
        {"technology": technology, "questions": question_counts.get(technology, 0), "assessments": assessment_counts.get(technology, 0)}
        for technology in sorted(
            set(question_counts) | set(assessment_counts),
            key=lambda key: (-assessment_counts.get(key, 0), -question_counts.get(key, 0), key),
        )[:10]
    ]
    for admin_id in weekly_report_admins:
        notify_user(
            admin_id,
            "weekly_report",
            "Weekly report available",
            f"The platform report for {start.date().isoformat()} through {(end - timedelta(days=1)).date().isoformat()} is available in the Admin dashboard.",
            action_url="/",
        )
    return {
        **totals,
        **counts,
        "range": range,
        "start_date": start_text,
        "end_date": end_text,
        "users_list": [dict(row) for row in users_list_rows],
        "recent_applications": [dict(row) for row in recent_applications],
        "recent_assessments": [dict(row) for row in recent_assessments],
        "recent_activity": [dict(row) for row in activity],
        "pipeline_breakdown": [dict(row) for row in pipeline_rows],
        "assessment_breakdown": [dict(row) for row in assessment_rows],
        "score_distribution": [dict(row) for row in score_rows],
        "round1_score_distribution": [dict(row) for row in round1_score_rows],
        "round1_passed_by_job": [dict(row) for row in round1_passed_by_job],
        "round1_failed_by_job": [dict(row) for row in round1_failed_by_job],
        "top_jobs_by_applications": [dict(row) for row in jobs_by_applications],
        "top_jobs_by_shortlists": [dict(row) for row in jobs_by_shortlists],
        "top_technologies": top_technologies,
        "weekly_trend": trend,
    }


@app.get("/assessment", include_in_schema=False)
def assessment_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "assessment.html")


app.mount("/", StaticFiles(directory=FRONTEND_DIR), name="frontend")
