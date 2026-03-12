"""Background report scheduler — runs scheduled reports and emails results.

Stores schedules in MongoDB. A background thread checks every 60 seconds
for reports due to run, executes the SQL, exports to the requested format,
and emails the file via O365.

Schedules are per-user (scoped by clerk_user_id) so each user's O365 tokens
are used for sending.

All user-facing times are in Pacific (PST/PDT). Cron expressions are stored
as-entered (Pacific) and converted to UTC at evaluation time.
"""

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from croniter import croniter
from zoneinfo import ZoneInfo

from db import _get_db
import norman_email

log = logging.getLogger("report_scheduler")

_COLLECTION = "report_schedules"
_PACIFIC = ZoneInfo("America/Los_Angeles")
_UTC = ZoneInfo("UTC")


def _next_run_utc(cron_expr: str) -> datetime:
    """Compute the next run time in UTC from a Pacific-time cron expression."""
    now_pac = datetime.now(_PACIFIC)
    # croniter works in naive datetimes, so strip tz for calculation
    next_pac_naive = croniter(cron_expr, now_pac.replace(tzinfo=None)).get_next(datetime)
    # Localize to Pacific, then convert to UTC, then strip tz for MongoDB
    next_pac = next_pac_naive.replace(tzinfo=_PACIFIC)
    next_utc = next_pac.astimezone(_UTC)
    return next_utc.replace(tzinfo=None)


def _utc_to_pacific_str(dt) -> str:
    """Format a UTC datetime as a Pacific time string for display."""
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    pac = dt.astimezone(_PACIFIC)
    return pac.strftime("%Y-%m-%d %I:%M %p %Z")


# ── Schedule CRUD ────────────────────────────────────────────────────────────

def create_schedule(user_id: str, name: str, sql: str, cron: str,
                    recipients: list[str], format: str = "xlsx",
                    subject: str = "", body: str = "", database: str = None,
                    template: str = None, template_params: dict = None) -> dict:
    """Create a new scheduled report. Cron expression is in Pacific time."""
    if not croniter.is_valid(cron):
        return {"success": False, "error": f"Invalid cron expression: {cron}"}

    if format not in ("xlsx", "pdf"):
        return {"success": False, "error": f"Unsupported format: {format}. Use 'xlsx' or 'pdf'."}

    if not recipients:
        return {"success": False, "error": "At least one recipient email is required"}

    if not sql and not template:
        return {"success": False, "error": "Either sql or template is required"}

    now = datetime.utcnow()
    next_run = _next_run_utc(cron)

    doc = {
        "user_id": user_id,
        "name": name,
        "sql": sql,
        "database": database or "DM03",
        "cron": cron,
        "recipients": recipients,
        "format": format,
        "subject": subject or f"Scheduled Report: {name}",
        "body": body or f"Please find the attached report: {name}",
        "template": template,
        "template_params": template_params or {},
        "enabled": True,
        "created_at": now,
        "next_run": next_run,
        "last_run": None,
        "last_status": None,
    }

    result = _get_db()[_COLLECTION].insert_one(doc)
    doc["_id"] = str(result.inserted_id)

    return {
        "success": True,
        "schedule_id": str(result.inserted_id),
        "name": name,
        "cron": cron,
        "next_run": next_run.isoformat(),
        "next_run_pacific": _utc_to_pacific_str(next_run),
        "message": f"Schedule created: '{name}' — next run at {_utc_to_pacific_str(next_run)}"
    }


def list_schedules(user_id: str) -> dict:
    """List all schedules for a user."""
    docs = list(_get_db()[_COLLECTION].find(
        {"user_id": user_id},
        {"sql": 0}  # omit SQL from listing for brevity
    ).sort("next_run", 1))

    schedules = []
    for doc in docs:
        schedules.append({
            "schedule_id": str(doc["_id"]),
            "name": doc.get("name", ""),
            "cron": doc.get("cron", ""),
            "recipients": doc.get("recipients", []),
            "format": doc.get("format", "xlsx"),
            "subject": doc.get("subject", ""),
            "database": doc.get("database", "DM03"),
            "enabled": doc.get("enabled", True),
            "next_run": doc.get("next_run", "").isoformat() if doc.get("next_run") else None,
            "next_run_pacific": _utc_to_pacific_str(doc.get("next_run")),
            "last_run": doc.get("last_run", "").isoformat() if doc.get("last_run") else None,
            "last_run_pacific": _utc_to_pacific_str(doc.get("last_run")),
            "last_status": doc.get("last_status"),
        })

    return {"success": True, "schedules": schedules, "count": len(schedules)}


def get_schedule(user_id: str, schedule_id: str) -> dict:
    """Get a single schedule by ID (includes SQL for editing)."""
    from bson import ObjectId

    doc = _get_db()[_COLLECTION].find_one(
        {"_id": ObjectId(schedule_id), "user_id": user_id}
    )
    if not doc:
        return {"success": False, "error": "Schedule not found"}

    return {
        "success": True,
        "schedule": {
            "schedule_id": str(doc["_id"]),
            "name": doc.get("name", ""),
            "sql": doc.get("sql", ""),
            "cron": doc.get("cron", ""),
            "recipients": doc.get("recipients", []),
            "format": doc.get("format", "xlsx"),
            "subject": doc.get("subject", ""),
            "body": doc.get("body", ""),
            "database": doc.get("database", "DM03"),
            "enabled": doc.get("enabled", True),
            "next_run": doc.get("next_run", "").isoformat() if doc.get("next_run") else None,
            "next_run_pacific": _utc_to_pacific_str(doc.get("next_run")),
            "last_run": doc.get("last_run", "").isoformat() if doc.get("last_run") else None,
            "last_run_pacific": _utc_to_pacific_str(doc.get("last_run")),
            "last_status": doc.get("last_status"),
        },
    }


def update_schedule(user_id: str, schedule_id: str, **updates) -> dict:
    """Update fields on a schedule."""
    from bson import ObjectId

    allowed = {"name", "sql", "cron", "recipients", "format", "subject",
               "body", "database", "enabled", "template", "template_params"}
    filtered = {k: v for k, v in updates.items() if k in allowed and v is not None}

    if "cron" in filtered:
        if not croniter.is_valid(filtered["cron"]):
            return {"success": False, "error": f"Invalid cron expression: {filtered['cron']}"}
        filtered["next_run"] = _next_run_utc(filtered["cron"])

    result = _get_db()[_COLLECTION].update_one(
        {"_id": ObjectId(schedule_id), "user_id": user_id},
        {"$set": filtered}
    )

    if result.matched_count == 0:
        return {"success": False, "error": "Schedule not found"}

    return {"success": True, "message": f"Schedule updated ({', '.join(filtered.keys())})"}


def delete_schedule(user_id: str, schedule_id: str) -> dict:
    """Delete a schedule."""
    from bson import ObjectId

    result = _get_db()[_COLLECTION].delete_one(
        {"_id": ObjectId(schedule_id), "user_id": user_id}
    )

    if result.deleted_count == 0:
        return {"success": False, "error": "Schedule not found"}

    return {"success": True, "message": "Schedule deleted"}


# ── Background execution ─────────────────────────────────────────────────────

def _execute_report(schedule: dict):
    """Execute a single scheduled report: query → export → email."""
    from bson import ObjectId
    from pathlib import Path
    from tools.query_executor import QueryExecutor
    from tools.excel_exporter import ExcelExporter
    from tools.pdf_exporter import PDFExporter

    schedule_id = schedule["_id"]
    user_id = schedule["user_id"]
    name = schedule.get("name", "Report")
    sql = schedule.get("sql", "")
    database = schedule.get("database")
    fmt = schedule.get("format", "xlsx")
    recipients = schedule.get("recipients", [])
    subject = schedule.get("subject", f"Scheduled Report: {name}")
    body = schedule.get("body", "")

    exports_dir = str(Path(__file__).resolve().parent / "exports")

    try:
        # Run query
        executor = QueryExecutor()
        result = executor.execute(sql, database=database, _internal_limit=50000)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Query failed"))

        columns = result["columns"]
        rows = result["rows"]
        if not rows:
            raise RuntimeError("Query returned no data")

        # Export
        if fmt == "xlsx":
            exporter = ExcelExporter(export_path=exports_dir)
            export_result = exporter.export(columns=columns, rows=rows, filename=name)
        else:
            exporter = PDFExporter(export_path=exports_dir)
            export_result = exporter.export(
                title=name,
                sections=[{"columns": columns, "rows": rows}],
                filename=name,
            )

        if not export_result.get("success"):
            raise RuntimeError(export_result.get("error", "Export failed"))

        file_id = export_result["file_id"]

        # Email via Norman's service account
        if not norman_email.is_configured():
            raise RuntimeError("Norman's email not configured (NORMAN_EMAIL / NORMAN_PASSWORD)")

        result = norman_email.send(
            to=recipients,
            subject=subject,
            body=body,
            attachments=[file_id],
        )
        if not result.get("success"):
            raise RuntimeError(result.get("error", "Email send failed"))

        status = f"OK — emailed {file_id} to {', '.join(recipients)}"
        log.info(f"Schedule '{name}' executed: {status}")

    except Exception as e:
        status = f"ERROR: {e}"
        log.error(f"Schedule '{name}' failed: {e}")

    # Update last_run and advance next_run
    now = datetime.utcnow()
    cron = schedule.get("cron", "0 7 * * *")
    next_run = _next_run_utc(cron)

    _get_db()[_COLLECTION].update_one(
        {"_id": schedule_id},
        {"$set": {"last_run": now, "last_status": status, "next_run": next_run}}
    )


def _scheduler_loop():
    """Main scheduler loop — runs every 60 seconds."""
    log.info("Report scheduler started")
    while True:
        try:
            now = datetime.utcnow()
            due = list(_get_db()[_COLLECTION].find({
                "enabled": True,
                "next_run": {"$lte": now},
            }))

            for schedule in due:
                name = schedule.get("name", "?")
                log.info(f"Running scheduled report: {name}")
                try:
                    _execute_report(schedule)
                except Exception as e:
                    log.error(f"Unhandled error in schedule '{name}': {e}")

        except Exception as e:
            log.error(f"Scheduler loop error: {e}")

        time.sleep(60)


def start():
    """Start the scheduler background thread (call once at server startup)."""
    t = threading.Thread(target=_scheduler_loop, daemon=True, name="report-scheduler")
    t.start()
    log.info("Report scheduler thread started")
