"""Norman's service email — sends mail via SMTP AUTH (Office 365).

Used as the default sender for all agent-initiated emails.
User's own O365 OAuth account is used only when they explicitly
ask to send "from my account" or "on my behalf".
"""

import os
import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

log = logging.getLogger("norman_email")

SMTP_HOST = "smtp.office365.com"
SMTP_PORT = 587

_EXPORTS_DIR = Path(__file__).resolve().parent / "exports"


def _get_credentials() -> tuple[str, str]:
    email = os.getenv("NORMAN_EMAIL", "")
    password = os.getenv("NORMAN_PASSWORD", "")
    return email, password


def is_configured() -> bool:
    email, password = _get_credentials()
    return bool(email and password)


def send(
    to: list[str],
    subject: str,
    body: str,
    attachments: list[str] | None = None,
    cc: list[str] | None = None,
    html: bool = True,
) -> dict:
    """Send an email from Norman's account via SMTP.

    Args:
        to: list of recipient email addresses
        subject: email subject
        body: email body (HTML by default)
        attachments: list of filenames in the exports directory
        cc: optional CC recipients
        html: if True, body is sent as HTML; otherwise plain text

    Returns:
        {"success": True/False, "message"/"error": ...}
    """
    email, password = _get_credentials()
    if not email or not password:
        return {"success": False, "error": "Norman's email is not configured (NORMAN_EMAIL / NORMAN_PASSWORD)"}

    msg = MIMEMultipart()
    msg["From"] = f"Norman <{email}>"
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)

    content_type = "html" if html else "plain"
    msg.attach(MIMEText(body, content_type))

    # Resolve and attach files
    resolved_files = []
    for filename in (attachments or []):
        if "/" in filename or "\\" in filename or ".." in filename:
            return {"success": False, "error": f"Invalid attachment filename: {filename}"}
        filepath = _EXPORTS_DIR / filename
        if not filepath.is_file():
            return {"success": False, "error": f"Attachment not found: {filename}"}
        resolved_files.append(filepath)

    for filepath in resolved_files:
        with open(filepath, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filepath.name}"')
        msg.attach(part)

    all_recipients = list(to) + (cc or [])

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(email, password)
            server.sendmail(email, all_recipients, msg.as_string())

        att_note = f" with {len(resolved_files)} attachment(s)" if resolved_files else ""
        log.info(f"Email sent from Norman to {', '.join(to)}: {subject}{att_note}")
        return {"success": True, "message": f"Email sent from Norman: {subject}{att_note}"}

    except smtplib.SMTPAuthenticationError as e:
        log.error(f"SMTP auth failed: {e}")
        return {"success": False, "error": "Norman's email authentication failed. Check NORMAN_EMAIL/NORMAN_PASSWORD."}
    except Exception as e:
        log.error(f"SMTP send failed: {e}")
        return {"success": False, "error": f"Failed to send email: {e}"}
