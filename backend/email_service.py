import logging
import os
import smtplib
from email.message import EmailMessage
from urllib.parse import urljoin


logger = logging.getLogger(__name__)


class EmailDeliveryError(Exception):
    pass


def send_assessment_email(
    recipient: str,
    link: str,
    technology: str,
    job_title: str,
    company: str,
    duration_minutes: int,
    expires_at: str,
    assessment_name: str = "Round 1: Technical MCQ Test",
    pass_percentage: float = 75,
) -> str:
    host = os.environ.get("SKILLSPHERE_SMTP_HOST", "").strip()
    sender = os.environ.get("SKILLSPHERE_SMTP_FROM", "").strip()
    if not host or not sender:
        if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production":
            raise EmailDeliveryError("Assessment email is not configured for production.")
        logger.warning("Development assessment link for %s: %s", recipient, link)
        return "development_console"

    try:
        port = int(os.environ.get("SKILLSPHERE_SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailDeliveryError("SKILLSPHERE_SMTP_PORT must be a valid port number.") from error
    username = os.environ.get("SKILLSPHERE_SMTP_USERNAME", "")
    password = os.environ.get("SKILLSPHERE_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailDeliveryError(
            "Configure both SKILLSPHERE_SMTP_USERNAME and SKILLSPHERE_SMTP_PASSWORD, or neither."
        )

    message = EmailMessage()
    message["Subject"] = f"{assessment_name} for {job_title}"
    message["From"] = sender
    message["To"] = recipient
    message.set_content(
        f"You have been shortlisted for {job_title} at {company}.\n\n"
        f"Complete your 20-question {technology} assessment independently.\n"
        f"Assessment: {assessment_name}.\n"
        f"Time limit: {duration_minutes} minutes.\n"
        f"Passing score: {pass_percentage:g}%.\n"
        f"Invitation expires: {expires_at}.\n\n"
        f"Open your private assessment link:\n{link}\n"
    )

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if os.environ.get("SKILLSPHERE_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}:
                    server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("The assessment email could not be delivered.") from error
    return "email"


def send_notification_email(
    recipient: str,
    title: str,
    message_text: str,
    action_url: str | None = None,
) -> str:
    host = os.environ.get("SKILLSPHERE_SMTP_HOST", "").strip()
    sender = os.environ.get("SKILLSPHERE_SMTP_FROM", "").strip()
    if not host or not sender:
        if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production":
            raise EmailDeliveryError("Notification email is not configured for production.")
        logger.info("Development notification for %s: %s", recipient, title)
        return "development_console"

    try:
        port = int(os.environ.get("SKILLSPHERE_SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailDeliveryError("SKILLSPHERE_SMTP_PORT must be a valid port number.") from error
    username = os.environ.get("SKILLSPHERE_SMTP_USERNAME", "")
    password = os.environ.get("SKILLSPHERE_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailDeliveryError(
            "Configure both SKILLSPHERE_SMTP_USERNAME and SKILLSPHERE_SMTP_PASSWORD, or neither."
        )

    message = EmailMessage()
    message["Subject"] = title
    message["From"] = sender
    message["To"] = recipient
    content = message_text
    if action_url:
        base_url = os.environ.get("SKILLSPHERE_PUBLIC_BASE_URL", "").strip()
        if not base_url:
            if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production":
                raise EmailDeliveryError("SKILLSPHERE_PUBLIC_BASE_URL is required for notification links.")
            base_url = "http://127.0.0.1:8000"
        content = f"{content}\n\nOpen SkillSphere:\n{urljoin(base_url.rstrip('/') + '/', action_url)}"
    message.set_content(content)

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if os.environ.get("SKILLSPHERE_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}:
                    server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("The notification email could not be delivered.") from error
    return "email"


def send_interview_email(
    recipient: str,
    title: str,
    company: str,
    scheduled_at: str,
    timezone: str,
    duration_minutes: int,
    meeting_platform: str,
    meeting_url: str,
    recruiter_message: str,
) -> str:
    host = os.environ.get("SKILLSPHERE_SMTP_HOST", "").strip()
    sender = os.environ.get("SKILLSPHERE_SMTP_FROM", "").strip()
    if not host or not sender:
        if os.environ.get("SKILLSPHERE_ENV", "development").lower() == "production":
            raise EmailDeliveryError("Interview email is not configured for production.")
        return "development_console"

    try:
        port = int(os.environ.get("SKILLSPHERE_SMTP_PORT", "587"))
    except ValueError as error:
        raise EmailDeliveryError("SKILLSPHERE_SMTP_PORT must be a valid port number.") from error
    username = os.environ.get("SKILLSPHERE_SMTP_USERNAME", "")
    password = os.environ.get("SKILLSPHERE_SMTP_PASSWORD", "")
    if bool(username) != bool(password):
        raise EmailDeliveryError(
            "Configure both SKILLSPHERE_SMTP_USERNAME and SKILLSPHERE_SMTP_PASSWORD, or neither."
        )

    message = EmailMessage()
    message["Subject"] = f"Interview {title} at {company}"
    message["From"] = sender
    message["To"] = recipient
    instructions = f"\nRecruiter instructions:\n{recruiter_message}\n" if recruiter_message else ""
    link = meeting_url or "The recruiter has not added a meeting link yet."
    message.set_content(
        f"Your interview for {title} at {company} is scheduled for {scheduled_at} ({timezone}).\n"
        f"Duration: {duration_minutes} minutes.\n"
        f"Meeting platform: {meeting_platform}.\n"
        f"{instructions}\nJoin the interview:\n{link}\n"
    )

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                if username:
                    server.login(username, password)
                server.send_message(message)
        else:
            with smtplib.SMTP(host, port, timeout=15) as server:
                if os.environ.get("SKILLSPHERE_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"}:
                    server.starttls()
                if username:
                    server.login(username, password)
                server.send_message(message)
    except (OSError, smtplib.SMTPException) as error:
        raise EmailDeliveryError("The interview email could not be delivered.") from error
    return "email"
