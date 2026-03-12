"""Norman's service email — SMTP for sending, O365 client credentials for inbox.

Used as the default sender for all agent-initiated emails.
User's own O365 OAuth account is used only when they explicitly
ask to send "from my account" or "on my behalf".

Norman's inbox is accessed via O365 client credentials flow (Application
permissions: Mail.Read, Mail.ReadWrite, Mail.Send).
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
NORMAN_ADDRESS = "norman@cobblestonefruit.com"

_EXPORTS_DIR = Path(__file__).resolve().parent / "exports"

# Cached O365 Account for Norman (client credentials — no user interaction)
_norman_account = None


def _get_credentials() -> tuple[str, str]:
    email = os.getenv("NORMAN_EMAIL", "")
    password = os.getenv("NORMAN_PASSWORD", "")
    return email, password


def is_configured() -> bool:
    email, password = _get_credentials()
    return bool(email and password)


def get_account():
    """Get an authenticated O365 Account for Norman using client credentials.

    Uses the same Azure app (O365_CLIENT_ID / O365_CLIENT_SECRET) with
    Application permissions to access Norman's mailbox.
    Returns an Account or None.
    """
    global _norman_account

    if _norman_account and _norman_account.is_authenticated:
        return _norman_account

    from O365 import Account

    client_id = os.getenv("O365_CLIENT_ID", "")
    client_secret = os.getenv("O365_CLIENT_SECRET", "")
    tenant_id = os.getenv("O365_TENANT_ID", "")

    if not client_id or not client_secret or not tenant_id:
        log.warning("O365 app credentials not configured — Norman inbox unavailable")
        return None

    try:
        account = Account(
            (client_id, client_secret),
            auth_flow_type="credentials",
            tenant_id=tenant_id,
            main_resource=NORMAN_ADDRESS,
        )
        if account.authenticate():
            _norman_account = account
            log.info("Norman O365 client credentials authenticated")
            return account
        else:
            log.error("Norman O365 client credentials auth returned False")
            return None
    except Exception as e:
        log.error(f"Norman O365 client credentials auth failed: {e}")
        return None


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
