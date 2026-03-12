"""Agent tools for managing scheduled reports."""

from .user_context import get_user_id


def _uid():
    uid = get_user_id()
    if not uid:
        return None
    return uid


def _no_user():
    return {"success": False, "error": "User not authenticated"}


def create_scheduled_report(params: dict) -> dict:
    uid = _uid()
    if not uid:
        return _no_user()

    import report_scheduler
    return report_scheduler.create_schedule(
        user_id=uid,
        name=params.get("name", ""),
        sql=params.get("sql", ""),
        cron=params.get("cron", ""),
        recipients=params.get("recipients", []),
        format=params.get("format", "xlsx"),
        subject=params.get("subject", ""),
        body=params.get("body", ""),
        database=params.get("database"),
    )


def list_scheduled_reports(params: dict) -> dict:
    uid = _uid()
    if not uid:
        return _no_user()

    import report_scheduler
    return report_scheduler.list_schedules(uid)


def update_scheduled_report(params: dict) -> dict:
    uid = _uid()
    if not uid:
        return _no_user()

    schedule_id = params.pop("schedule_id", "")
    if not schedule_id:
        return {"success": False, "error": "schedule_id is required"}

    import report_scheduler
    return report_scheduler.update_schedule(uid, schedule_id, **params)


def delete_scheduled_report(params: dict) -> dict:
    uid = _uid()
    if not uid:
        return _no_user()

    schedule_id = params.get("schedule_id", "")
    if not schedule_id:
        return {"success": False, "error": "schedule_id is required"}

    import report_scheduler
    return report_scheduler.delete_schedule(uid, schedule_id)


# ── Cron helper examples for the agent ───────────────────────────────────────

_CRON_EXAMPLES = """Common cron patterns:
  "0 7 * * *"       = Every day at 7:00 AM
  "0 7 * * 1-5"     = Weekdays at 7:00 AM
  "0 7 * * 1"       = Every Monday at 7:00 AM
  "0 8 1 * *"       = 1st of every month at 8:00 AM
  "0 7,16 * * 1-5"  = Weekdays at 7 AM and 4 PM
  "0 */4 * * *"     = Every 4 hours
All times are UTC."""


TOOL_DEFINITIONS = [
    {
        "name": "create_scheduled_report",
        "description": f"Schedule a recurring report that runs a SQL query, exports to Excel or PDF, and emails the file to specified recipients. Use standard cron expressions for timing. {_CRON_EXAMPLES}",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Human-readable name for this schedule (e.g. 'Daily Bin Inventory')"
                },
                "sql": {
                    "type": "string",
                    "description": "The SELECT query to run each time the schedule fires"
                },
                "cron": {
                    "type": "string",
                    "description": "Cron expression for when to run (e.g. '0 7 * * *' for daily at 7 AM UTC)"
                },
                "recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Email addresses to send the report to"
                },
                "format": {
                    "type": "string",
                    "enum": ["xlsx", "pdf"],
                    "description": "Export format (default: xlsx)"
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line (defaults to 'Scheduled Report: {name}')"
                },
                "body": {
                    "type": "string",
                    "description": "Email body text (defaults to a generic message)"
                },
                "database": {
                    "type": "string",
                    "enum": ["DM03", "DM01"],
                    "description": "Database to query (default: DM03)"
                }
            },
            "required": ["name", "sql", "cron", "recipients"]
        }
    },
    {
        "name": "list_scheduled_reports",
        "description": "List all scheduled reports for the current user. Shows name, cron schedule, next run time, last run status, and recipients.",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "update_scheduled_report",
        "description": "Update a scheduled report. Can change the name, SQL, cron schedule, recipients, format, subject, body, database, or enabled status. Pass only the fields you want to change.",
        "parameters": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "The schedule ID to update (from list_scheduled_reports)"
                },
                "name": {"type": "string", "description": "New name"},
                "sql": {"type": "string", "description": "New SQL query"},
                "cron": {"type": "string", "description": "New cron expression"},
                "recipients": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "New recipient list"
                },
                "format": {"type": "string", "enum": ["xlsx", "pdf"]},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "database": {"type": "string", "enum": ["DM03", "DM01"]},
                "enabled": {
                    "type": "boolean",
                    "description": "Set to false to pause the schedule"
                }
            },
            "required": ["schedule_id"]
        }
    },
    {
        "name": "delete_scheduled_report",
        "description": "Delete a scheduled report. This is permanent.",
        "parameters": {
            "type": "object",
            "properties": {
                "schedule_id": {
                    "type": "string",
                    "description": "The schedule ID to delete (from list_scheduled_reports)"
                }
            },
            "required": ["schedule_id"]
        }
    },
]


def register_handlers() -> dict:
    return {
        "create_scheduled_report": create_scheduled_report,
        "list_scheduled_reports": list_scheduled_reports,
        "update_scheduled_report": update_scheduled_report,
        "delete_scheduled_report": delete_scheduled_report,
    }
