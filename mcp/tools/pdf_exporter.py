"""Generate downloadable PDF reports from agent data."""

import re
import uuid
from pathlib import Path

from fpdf import FPDF

# Cobblestone brand colors
_GREEN = (30, 75, 50)       # #1E4B32
_ACCENT = (218, 118, 45)    # #DA762D
_WHITE = (255, 255, 255)
_LIGHT_BG = (245, 243, 240) # table stripe
_DARK_TEXT = (30, 30, 30)
_GRAY_TEXT = (100, 100, 100)


class _ReportPDF(FPDF):
    """PDF with branded header/footer."""

    def __init__(self, title: str = "Report", **kwargs):
        super().__init__(**kwargs)
        self.report_title = title
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        # Green bar
        self.set_fill_color(*_GREEN)
        self.rect(0, 0, self.w, 16, "F")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_WHITE)
        self.set_xy(10, 3)
        self.cell(0, 10, "Cobblestone Fruit Company", align="L")
        self.set_font("Helvetica", "", 9)
        self.set_xy(-60, 3)
        self.cell(50, 10, self.report_title, align="R")
        self.ln(18)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(*_GRAY_TEXT)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


class PDFExporter:
    """Generate downloadable PDF reports."""

    def __init__(self, export_path: str = "./exports"):
        self.export_path = Path(export_path)
        self.export_path.mkdir(exist_ok=True)

    def _make_filename(self, filename: str) -> str:
        file_id = str(uuid.uuid4())[:8]
        if not filename:
            filename = f"report_{file_id}"
        safe_name = "".join(c for c in filename if c.isalnum() or c in "_- ").strip()
        if not safe_name:
            safe_name = f"report_{file_id}"
        return f"{safe_name}_{file_id}.pdf"

    def _add_text_block(self, pdf: _ReportPDF, text: str):
        """Render a text block with basic markdown-like formatting."""
        pdf.set_text_color(*_DARK_TEXT)
        for line in text.split("\n"):
            stripped = line.strip()
            if not stripped:
                pdf.ln(4)
                continue

            # Headings
            if stripped.startswith("### "):
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(*_GREEN)
                pdf.cell(0, 7, stripped[4:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(2)
            elif stripped.startswith("## "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.set_text_color(*_GREEN)
                pdf.cell(0, 8, stripped[3:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(2)
            elif stripped.startswith("# "):
                pdf.set_font("Helvetica", "B", 16)
                pdf.set_text_color(*_ACCENT)
                pdf.cell(0, 10, stripped[2:], new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(3)
            elif stripped.startswith("- ") or stripped.startswith("* "):
                pdf.set_font("Helvetica", "", 10)
                pdf.cell(6, 5, chr(8226))  # bullet
                pdf.multi_cell(0, 5, stripped[2:])
            elif stripped.startswith("**") and stripped.endswith("**"):
                pdf.set_font("Helvetica", "B", 10)
                pdf.multi_cell(0, 5, stripped[2:-2])
            else:
                pdf.set_font("Helvetica", "", 10)
                pdf.multi_cell(0, 5, _strip_md(stripped))

    def _add_table(self, pdf: _ReportPDF, columns: list[str], rows: list[list]):
        """Render a data table."""
        if not columns or not rows:
            return

        # Calculate column widths based on content
        usable = pdf.w - 20  # margins
        col_widths = []
        for i, col in enumerate(columns):
            max_len = len(str(col))
            for row in rows[:50]:
                if i < len(row):
                    max_len = max(max_len, len(str(row[i] if row[i] is not None else "")))
            col_widths.append(min(max_len, 40))

        total = sum(col_widths) or 1
        col_widths = [w / total * usable for w in col_widths]

        # If table is too wide, use landscape-like scaling
        if sum(col_widths) > usable:
            scale = usable / sum(col_widths)
            col_widths = [w * scale for w in col_widths]

        # Header row
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_fill_color(*_GREEN)
        pdf.set_text_color(*_WHITE)
        row_height = 6
        for i, col in enumerate(columns):
            pdf.cell(col_widths[i], row_height, str(col)[:30], border=1, fill=True, align="C")
        pdf.ln()

        # Data rows
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_DARK_TEXT)
        for row_idx, row in enumerate(rows):
            if pdf.get_y() > pdf.h - 25:
                pdf.add_page()
                # Re-draw header on new page
                pdf.set_font("Helvetica", "B", 8)
                pdf.set_fill_color(*_GREEN)
                pdf.set_text_color(*_WHITE)
                for i, col in enumerate(columns):
                    pdf.cell(col_widths[i], row_height, str(col)[:30], border=1, fill=True, align="C")
                pdf.ln()
                pdf.set_font("Helvetica", "", 8)
                pdf.set_text_color(*_DARK_TEXT)

            # Alternate row shading
            if row_idx % 2 == 1:
                pdf.set_fill_color(*_LIGHT_BG)
                fill = True
            else:
                fill = False

            for i, col_w in enumerate(col_widths):
                val = str(row[i]) if i < len(row) and row[i] is not None else ""
                # Truncate to fit
                while pdf.get_string_width(val) > col_w - 2 and len(val) > 1:
                    val = val[:-1]
                pdf.cell(col_w, row_height, val, border=1, fill=fill)
            pdf.ln()

        pdf.ln(4)

    def export(self, title: str = "Report", content: str = None,
               sections: list[dict] = None, filename: str = "") -> dict:
        """Export a PDF report.

        Args:
            title: Report title (shown in header and first page).
            content: Markdown-ish text content to render.
            sections: Structured sections, each a dict with optional keys:
                - heading (str): Section heading
                - text (str): Body text (markdown-ish)
                - columns (list[str]) + rows (list[list]): Table data
            filename: Output filename (without extension).
        """
        if not content and not sections:
            return {"success": False, "error": "No content or sections provided"}

        pdf_name = self._make_filename(filename)
        pdf = _ReportPDF(title=title, orientation="P", unit="mm", format="A4")
        pdf.alias_nb_pages()
        pdf.add_page()

        # Title block
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_ACCENT)
        pdf.cell(0, 12, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*_ACCENT)
        pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(6)

        if content:
            self._add_text_block(pdf, content)

        if sections:
            for section in sections:
                heading = section.get("heading")
                text = section.get("text")
                columns = section.get("columns")
                rows = section.get("rows")

                if heading:
                    pdf.set_font("Helvetica", "B", 14)
                    pdf.set_text_color(*_GREEN)
                    pdf.cell(0, 9, heading, new_x="LMARGIN", new_y="NEXT")
                    pdf.set_draw_color(*_GREEN)
                    pdf.line(10, pdf.get_y(), 80, pdf.get_y())
                    pdf.ln(4)
                    pdf.set_text_color(*_DARK_TEXT)

                if text:
                    self._add_text_block(pdf, text)
                    pdf.ln(2)

                if columns and rows:
                    self._add_table(pdf, columns, rows)

        filepath = self.export_path / pdf_name
        pdf.output(filepath)

        return {
            "success": True,
            "file_id": pdf_name,
            "download_url": f"/download/{pdf_name}",
            "message": f"PDF report ready: {pdf_name}"
        }

    def export_from_query(self, title: str, sql: str, database: str = None,
                          filename: str = "", summary: str = None) -> dict:
        """Run a SQL query and export results directly to a PDF table."""
        from .query_executor import QueryExecutor

        executor = QueryExecutor()
        result = executor.execute(sql, database=database, _internal_limit=50000)
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Query failed")}

        columns = result["columns"]
        rows = result["rows"]
        if not rows:
            return {"success": False, "error": "Query returned no data"}

        sections = []
        if summary:
            sections.append({"text": summary})
        sections.append({"columns": columns, "rows": rows})

        return self.export(title=title, sections=sections, filename=filename)


def _strip_md(text: str) -> str:
    """Strip basic markdown formatting for plain text rendering."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    text = re.sub(r'`(.+?)`', r'\1', text)
    text = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', text)
    return text


TOOL_DEFINITIONS = [
    {
        "name": "export_pdf",
        "description": "Export a formatted PDF report. Use for professional-looking reports the user can print or email. Supports two modes: (1) Pass 'content' with markdown-like text for a text-heavy report. (2) Pass 'sections' array for structured reports with headings, text, and data tables. Each section can have a heading, text, and/or table (columns + rows). Returns a download link.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Report title displayed at the top and in the header"
                },
                "content": {
                    "type": "string",
                    "description": "Markdown-like text content. Supports # headings, **bold**, - bullets. Use this for text-heavy reports."
                },
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "heading": {"type": "string", "description": "Section heading"},
                            "text": {"type": "string", "description": "Section body text (markdown-like)"},
                            "columns": {"type": "array", "items": {"type": "string"}, "description": "Table column headers"},
                            "rows": {"type": "array", "items": {"type": "array"}, "description": "Table data rows"}
                        }
                    },
                    "description": "Structured sections. Each section can have a heading, text, and/or a table (columns + rows)."
                },
                "filename": {
                    "type": "string",
                    "description": "Descriptive filename without extension (e.g., 'production_schedule_march')"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "export_sql_to_pdf",
        "description": "Run a SQL query and export results directly to a formatted PDF table. Use for data-heavy reports where completeness matters. Optionally include a summary paragraph above the table.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Report title"
                },
                "sql": {
                    "type": "string",
                    "description": "SELECT query to run"
                },
                "database": {
                    "type": "string",
                    "enum": ["DM03", "DM01"],
                    "description": "Target database (default DM03)"
                },
                "summary": {
                    "type": "string",
                    "description": "Optional summary text to display above the table"
                },
                "filename": {
                    "type": "string",
                    "description": "Descriptive filename without extension"
                }
            },
            "required": ["title", "sql"]
        }
    },
]


def register_handlers(exporter: PDFExporter) -> dict:
    return {
        "export_pdf": lambda p: exporter.export(
            title=p.get("title", "Report"),
            content=p.get("content"),
            sections=p.get("sections"),
            filename=p.get("filename", ""),
        ),
        "export_sql_to_pdf": lambda p: exporter.export_from_query(
            title=p.get("title", "Report"),
            sql=p.get("sql", ""),
            database=p.get("database"),
            filename=p.get("filename", ""),
            summary=p.get("summary"),
        ),
    }
