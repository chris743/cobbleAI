"""Microsoft 365 agent tools — email, calendar, OneDrive, SharePoint."""

from datetime import datetime, timezone, timedelta
from pathlib import Path

_EXPORTS_DIR = Path(__file__).resolve().parent.parent / "exports"


def _get_account():
    """Get the O365 Account for the current user via context var."""
    from .user_context import get_user_id
    import o365_auth

    user_id = get_user_id()
    if not user_id:
        return None
    return o365_auth.get_account(user_id)


def _get_norman_account():
    """Get Norman's O365 Account (client credentials flow)."""
    import norman_email
    return norman_email.get_account()


def _not_connected():
    return {
        "success": False,
        "error": "Microsoft 365 is not connected. Please connect your account in Settings (gear icon in the top bar).",
    }


def _norman_not_connected():
    return {
        "success": False,
        "error": "Norman's mailbox is not accessible. Check O365 app credentials and Application permissions (Mail.Read, Mail.ReadWrite, Mail.Send).",
    }


# ── Shared email helpers ─────────────────────────────────────────────────────

def _list_emails_for_account(account, params: dict, mailbox_label: str) -> dict:
    folder_name = params.get("folder", "Inbox")
    limit = min(params.get("limit", 15), 50)
    search = params.get("search")

    try:
        mailbox = account.mailbox()

        if folder_name.lower() == "inbox":
            folder = mailbox.inbox_folder()
        elif folder_name.lower() == "sent":
            folder = mailbox.sent_folder()
        elif folder_name.lower() == "drafts":
            folder = mailbox.drafts_folder()
        else:
            folder = mailbox.inbox_folder()

        query = folder.new_query().order_by("receivedDateTime", ascending=False)
        if search:
            query = query.search(search)

        messages = folder.get_messages(limit=limit, query=query)
        results = []
        for msg in messages:
            results.append({
                "id": msg.object_id,
                "subject": msg.subject,
                "from": str(msg.sender),
                "date": msg.received.isoformat() if msg.received else None,
                "is_read": msg.is_read,
                "has_attachments": msg.has_attachments,
                "preview": (msg.body_preview or "")[:200],
            })

        return {"success": True, "mailbox": mailbox_label, "emails": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": f"Failed to list emails from {mailbox_label}: {e}"}


def _read_email_for_account(account, params: dict, mailbox_label: str) -> dict:
    email_id = params.get("email_id", "")
    if not email_id:
        return {"success": False, "error": "email_id is required"}

    try:
        mailbox = account.mailbox()
        msg = mailbox.get_message(object_id=email_id)
        if not msg:
            return {"success": False, "error": "Email not found"}

        return {
            "success": True,
            "mailbox": mailbox_label,
            "email": {
                "id": msg.object_id,
                "subject": msg.subject,
                "from": str(msg.sender),
                "to": [str(r) for r in msg.to],
                "cc": [str(r) for r in msg.cc] if msg.cc else [],
                "date": msg.received.isoformat() if msg.received else None,
                "body": msg.body,
                "has_attachments": msg.has_attachments,
                "attachments": [
                    {"name": a.name, "size": a.size}
                    for a in msg.attachments
                ] if msg.has_attachments else [],
            },
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to read email from {mailbox_label}: {e}"}


def _reply_email_for_account(account, params: dict, mailbox_label: str) -> dict:
    email_id = params.get("email_id", "")
    reply_body = params.get("body", "")
    reply_all = params.get("reply_all", False)

    if not email_id or not reply_body:
        return {"success": False, "error": "email_id and body are required"}

    try:
        mailbox = account.mailbox()
        msg = mailbox.get_message(object_id=email_id)
        if not msg:
            return {"success": False, "error": "Email not found"}

        reply = msg.reply(to_all=reply_all)
        reply.body = reply_body
        reply.send()

        return {"success": True, "message": f"Reply sent from {mailbox_label}: {msg.subject}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to send reply from {mailbox_label}: {e}"}


# ── Email tools ──────────────────────────────────────────────────────────────

def list_emails(params: dict) -> dict:
    """List emails from the user's mailbox."""
    account = _get_account()
    if not account:
        return _not_connected()
    return _list_emails_for_account(account, params, "user")


def read_email(params: dict) -> dict:
    """Read a specific email from the user's mailbox."""
    account = _get_account()
    if not account:
        return _not_connected()
    return _read_email_for_account(account, params, "user")


def reply_email(params: dict) -> dict:
    """Reply to an email from the user's mailbox."""
    account = _get_account()
    if not account:
        return _not_connected()
    return _reply_email_for_account(account, params, "user")


def norman_list_emails(params: dict) -> dict:
    """List emails from Norman's mailbox (norman@cobblestonefruit.com)."""
    account = _get_norman_account()
    if not account:
        return _norman_not_connected()
    return _list_emails_for_account(account, params, "norman")


def norman_read_email(params: dict) -> dict:
    """Read a specific email from Norman's mailbox."""
    account = _get_norman_account()
    if not account:
        return _norman_not_connected()
    return _read_email_for_account(account, params, "norman")


def norman_reply_email(params: dict) -> dict:
    """Reply to an email in Norman's mailbox (sends as norman@cobblestonefruit.com)."""
    account = _get_norman_account()
    if not account:
        return _norman_not_connected()
    return _reply_email_for_account(account, params, "norman")


def send_email(params: dict) -> dict:
    import norman_email

    to = params.get("to", [])
    subject = params.get("subject", "")
    body = params.get("body", "")
    attachments = params.get("attachments", [])
    send_as_user = params.get("send_as_user", False)

    if not to or not subject or not body:
        return {"success": False, "error": "to, subject, and body are required"}

    if isinstance(to, str):
        to = [to]
    if isinstance(attachments, str):
        attachments = [attachments]

    # If user explicitly wants to send from their own account
    if send_as_user:
        account = _get_account()
        if not account:
            return _not_connected()

        resolved_files = []
        for file_id in attachments:
            if "/" in file_id or "\\" in file_id or ".." in file_id:
                return {"success": False, "error": f"Invalid attachment filename: {file_id}"}
            filepath = _EXPORTS_DIR / file_id
            if not filepath.is_file():
                return {"success": False, "error": f"Attachment not found: {file_id}"}
            resolved_files.append(filepath)

        try:
            mailbox = account.mailbox()
            msg = mailbox.new_message()
            msg.to.add(to)
            msg.subject = subject
            msg.body = body

            for filepath in resolved_files:
                msg.attachments.add(str(filepath))

            msg.send()

            att_note = f" with {len(resolved_files)} attachment(s)" if resolved_files else ""
            return {"success": True, "message": f"Email sent from your account: {subject}{att_note}"}
        except Exception as e:
            return {"success": False, "error": f"Failed to send email: {e}"}

    # Default: send from Norman's service account via SMTP
    if not norman_email.is_configured():
        return {"success": False, "error": "Norman's email is not configured on the server (NORMAN_EMAIL / NORMAN_PASSWORD)"}

    return norman_email.send(
        to=to,
        subject=subject,
        body=body,
        attachments=attachments,
    )


# ── Calendar tools ───────────────────────────────────────────────────────────

def summarize_calendar(params: dict) -> dict:
    account = _get_account()
    if not account:
        return _not_connected()

    days_ahead = min(params.get("days_ahead", 7), 30)

    try:
        schedule = account.schedule()
        calendar = schedule.get_default_calendar()

        start = datetime.now(timezone.utc)
        end = start + timedelta(days=days_ahead)

        query = calendar.new_query("start").greater_equal(start)
        query.chain("and").on_attribute("end").less_equal(end)

        events = calendar.get_events(limit=50, query=query)
        results = []
        for event in events:
            results.append({
                "subject": event.subject,
                "start": event.start.isoformat() if event.start else None,
                "end": event.end.isoformat() if event.end else None,
                "location": str(event.location) if event.location else None,
                "is_all_day": event.is_all_day,
                "organizer": str(event.organizer) if event.organizer else None,
                "body_preview": (event.body or "")[:300],
            })

        return {
            "success": True,
            "events": results,
            "count": len(results),
            "range": f"{start.date().isoformat()} to {end.date().isoformat()}",
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to read calendar: {e}"}


# ── OneDrive tools ───────────────────────────────────────────────────────────

def list_onedrive(params: dict) -> dict:
    account = _get_account()
    if not account:
        return _not_connected()

    path = params.get("path", "/")

    try:
        storage = account.storage()
        drive = storage.get_default_drive()

        if path == "/" or not path:
            folder = drive.get_root_folder()
        else:
            folder = drive.get_item_by_path(path)
            if folder is None:
                return {"success": False, "error": f"Path not found: {path}"}

        items = folder.get_items(limit=50)
        results = []
        for item in items:
            results.append({
                "name": item.name,
                "type": "folder" if item.is_folder else "file",
                "size": item.size if not item.is_folder else None,
                "modified": item.modified.isoformat() if item.modified else None,
                "web_url": item.web_url,
            })

        return {"success": True, "items": results, "count": len(results), "path": path}
    except Exception as e:
        return {"success": False, "error": f"Failed to list OneDrive: {e}"}


# ── SharePoint tools ────────────────────────────────────────────────────────

def list_sharepoint(params: dict) -> dict:
    account = _get_account()
    if not account:
        return _not_connected()

    site_name = params.get("site_name")
    library = params.get("library")
    path = params.get("path", "/")

    try:
        sharepoint = account.sharepoint()

        if not site_name:
            # List available sites
            sites = sharepoint.search_site("*")
            results = []
            for site in sites:
                results.append({
                    "name": site.display_name,
                    "url": site.web_url,
                    "id": site.object_id,
                })
            return {"success": True, "sites": results, "count": len(results)}

        # Get specific site
        site = sharepoint.get_site(site_name)
        if not site:
            return {"success": False, "error": f"Site not found: {site_name}"}

        if not library:
            # List document libraries
            libs = site.list_document_libraries()
            results = []
            for lib in libs:
                results.append({
                    "name": lib.name,
                    "web_url": lib.web_url,
                    "id": lib.object_id,
                })
            return {"success": True, "libraries": results, "site": site_name}

        # List items in a library
        doc_lib = site.get_document_library(library)
        if not doc_lib:
            return {"success": False, "error": f"Library not found: {library}"}

        if path == "/" or not path:
            folder = doc_lib.get_root_folder()
        else:
            folder = doc_lib.get_item_by_path(path)
            if folder is None:
                return {"success": False, "error": f"Path not found: {path}"}

        items = folder.get_items(limit=50)
        results = []
        for item in items:
            results.append({
                "name": item.name,
                "type": "folder" if item.is_folder else "file",
                "size": item.size if not item.is_folder else None,
                "modified": item.modified.isoformat() if item.modified else None,
                "web_url": item.web_url,
            })

        return {
            "success": True,
            "items": results,
            "count": len(results),
            "site": site_name,
            "library": library,
            "path": path,
        }
    except Exception as e:
        return {"success": False, "error": f"Failed to access SharePoint: {e}"}


# ── Tool definitions ─────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "o365_list_emails",
        "description": "List recent emails from the user's personal Microsoft 365 mailbox. Use this when the user asks to check 'my emails' or 'my inbox'. Supports searching and filtering by folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "enum": ["Inbox", "Sent", "Drafts"],
                    "description": "Mail folder to read from (default: Inbox)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max emails to return (default: 15, max: 50)",
                },
                "search": {
                    "type": "string",
                    "description": "Search query to filter emails (searches subject, body, sender)",
                },
            },
        },
    },
    {
        "name": "o365_read_email",
        "description": "Read the full content of a specific email from the user's mailbox by its ID. Use after o365_list_emails.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email's unique ID (from o365_list_emails results)",
                },
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "o365_reply_email",
        "description": "Reply to an email in the user's mailbox. Sends from the user's own email address. Always confirm the reply content with the user before sending.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to reply to (from the user's mailbox)",
                },
                "body": {
                    "type": "string",
                    "description": "The reply message body (HTML supported)",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Reply to all recipients (default: false)",
                },
            },
            "required": ["email_id", "body"],
        },
    },
    {
        "name": "norman_list_emails",
        "description": "List recent emails from Norman's own mailbox (norman@cobblestonefruit.com). Use this to check Norman's inbox — e.g., to see replies to reports Norman sent, or emails addressed to Norman. This is Norman's service mailbox, separate from the user's personal mailbox.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder": {
                    "type": "string",
                    "enum": ["Inbox", "Sent", "Drafts"],
                    "description": "Mail folder to read from (default: Inbox)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max emails to return (default: 15, max: 50)",
                },
                "search": {
                    "type": "string",
                    "description": "Search query to filter emails (searches subject, body, sender)",
                },
            },
        },
    },
    {
        "name": "norman_read_email",
        "description": "Read the full content of a specific email from Norman's mailbox by its ID. Use after norman_list_emails.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email's unique ID (from norman_list_emails results)",
                },
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "norman_reply_email",
        "description": "Reply to an email in Norman's mailbox. Sends the reply as norman@cobblestonefruit.com. Use this to respond to emails that were sent to Norman or to follow up on threads Norman started. Follow the email reply rules: only reply to threads Norman started, emails addressed to Norman, or when the user explicitly asks.",
        "parameters": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to reply to (from Norman's mailbox)",
                },
                "body": {
                    "type": "string",
                    "description": "The reply message body (HTML supported)",
                },
                "reply_all": {
                    "type": "boolean",
                    "description": "Reply to all recipients (default: false)",
                },
            },
            "required": ["email_id", "body"],
        },
    },
    {
        "name": "o365_send_email",
        "description": "Send a new email, optionally with file attachments. By default, emails are sent from Norman's service account (norman@cobblestonefruit.com). Set send_as_user=true ONLY when the user explicitly asks to send from their own account or 'on my behalf'. To email a document, first export it (export_excel or export_sql_to_excel or export_pdf), then pass the file_id from the export result as an attachment. Always confirm the recipients, subject, and body with the user before sending.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (HTML supported)",
                },
                "attachments": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "File IDs to attach (from export_excel/export_sql_to_excel/export_pdf results, e.g. 'navel_inventory_a1b2c3d4.xlsx')",
                },
                "send_as_user": {
                    "type": "boolean",
                    "description": "If true, send from the user's own Microsoft 365 account (requires O365 connection). Default false — sends from Norman's account.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "o365_summarize_calendar",
        "description": "Get upcoming calendar events from the user's Microsoft 365 calendar. Returns events for the next N days with subject, time, location, and organizer. Great for summarizing the user's schedule.",
        "parameters": {
            "type": "object",
            "properties": {
                "days_ahead": {
                    "type": "integer",
                    "description": "Number of days ahead to look (default: 7, max: 30)",
                },
            },
        },
    },
    {
        "name": "o365_list_onedrive",
        "description": "List files and folders in the user's OneDrive. Navigate by providing a path. Returns file names, sizes, and modification dates.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Folder path to list (default: root '/'). Example: '/Documents/Reports'",
                },
            },
        },
    },
    {
        "name": "o365_list_sharepoint",
        "description": "Browse SharePoint sites and document libraries. Call without site_name to list available sites. Call with site_name to list document libraries. Call with site_name + library to list files in a library.",
        "parameters": {
            "type": "object",
            "properties": {
                "site_name": {
                    "type": "string",
                    "description": "SharePoint site name or URL fragment. Omit to list all sites.",
                },
                "library": {
                    "type": "string",
                    "description": "Document library name within the site. Omit to list libraries.",
                },
                "path": {
                    "type": "string",
                    "description": "Folder path within the library (default: root '/')",
                },
            },
        },
    },
]


def register_handlers() -> dict:
    return {
        "o365_list_emails": list_emails,
        "o365_read_email": read_email,
        "o365_reply_email": reply_email,
        "o365_send_email": send_email,
        "o365_summarize_calendar": summarize_calendar,
        "o365_list_onedrive": list_onedrive,
        "o365_list_sharepoint": list_sharepoint,
        "norman_list_emails": norman_list_emails,
        "norman_read_email": norman_read_email,
        "norman_reply_email": norman_reply_email,
    }
