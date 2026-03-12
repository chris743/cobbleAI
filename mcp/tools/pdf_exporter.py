"""Generate downloadable PDF reports from agent data."""

import re
import uuid
from datetime import date
from pathlib import Path

from fpdf import FPDF

# Cobblestone brand colors
_GREEN = (30, 75, 50)       # #1E4B32
_ACCENT = (218, 118, 45)    # #DA762D
_WHITE = (255, 255, 255)
_LIGHT_BG = (245, 243, 240) # table stripe
_DARK_TEXT = (30, 30, 30)
_GRAY_TEXT = (100, 100, 100)
_LIGHT_GRAY = (200, 200, 200)

# Regex to strip emoji and other non-latin-1 symbols
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"  # misc symbols, emoticons, etc.
    "\U00002702-\U000027B0"  # dingbats
    "\U0000FE00-\U0000FE0F"  # variation selectors
    "\U0000200D"             # zero width joiner
    "\U000020E3"             # combining enclosing keycap
    "]+",
    flags=re.UNICODE,
)


def _safe(text) -> str:
    """Sanitize text for latin-1 encoding (built-in fonts only support latin-1)."""
    if text is None:
        return ""
    text = str(text)
    # Strip emojis entirely (replacement chars cause width issues)
    text = _EMOJI_RE.sub("", text)
    # Encode remaining to latin-1, drop anything that still doesn't fit
    return text.encode("latin-1", "ignore").decode("latin-1").strip()


class _ReportPDF(FPDF):
    """PDF with branded header/footer."""

    def __init__(self, title: str = "Report", **kwargs):
        super().__init__(**kwargs)
        self.report_title = title
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_fill_color(*_GREEN)
        self.rect(0, 0, self.w, 16, "F")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*_WHITE)
        self.set_xy(10, 3)
        self.cell(0, 10, _safe("Cobblestone Fruit Company"), align="L")
        self.set_font("Helvetica", "", 9)
        self.set_xy(-60, 3)
        self.cell(50, 10, _safe(self.report_title), align="R")
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
        """Render a text block with basic markdown-like formatting.

        Detects tab-separated or pipe-separated tables in the text and
        renders them as proper PDF tables instead of plain text.
        """
        pdf.set_text_color(*_DARK_TEXT)
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            stripped = lines[i].strip()
            if not stripped:
                pdf.ln(4)
                i += 1
                continue

            # Detect tabular blocks: 2+ consecutive lines with tabs or pipes
            if "\t" in stripped or ("|" in stripped and stripped.count("|") >= 2):
                table_lines = []
                sep = "\t" if "\t" in stripped else "|"
                while i < len(lines):
                    s = lines[i].strip()
                    if not s:
                        break
                    # Skip markdown table separator rows (---|---|---)
                    if sep == "|" and re.match(r'^[\s|:-]+$', s):
                        i += 1
                        continue
                    cells = [c.strip() for c in s.split(sep) if c.strip()]
                    if len(cells) >= 2:
                        table_lines.append(cells)
                        i += 1
                    else:
                        break
                if table_lines:
                    # First row is header
                    columns = table_lines[0]
                    rows = table_lines[1:]
                    if rows:
                        self._add_table(pdf, columns, rows)
                    else:
                        # Single row — render as bold text
                        pdf.set_font("Helvetica", "B", 10)
                        pdf.multi_cell(0, 5, _safe("  ".join(columns)))
                    continue
                # Fall through if no valid table found

            # Reset x to left margin before rendering any text
            pdf.set_x(10)

            # Headings
            if stripped.startswith("### "):
                pdf.set_font("Helvetica", "B", 11)
                pdf.set_text_color(*_GREEN)
                pdf.cell(0, 7, _safe(stripped[4:]))
                pdf.ln()
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(2)
            elif stripped.startswith("## "):
                pdf.set_font("Helvetica", "B", 13)
                pdf.set_text_color(*_GREEN)
                pdf.cell(0, 8, _safe(stripped[3:]))
                pdf.ln()
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(2)
            elif stripped.startswith("# "):
                pdf.set_font("Helvetica", "B", 16)
                pdf.set_text_color(*_ACCENT)
                pdf.cell(0, 10, _safe(stripped[2:]))
                pdf.ln()
                pdf.set_text_color(*_DARK_TEXT)
                pdf.ln(3)
            elif stripped.startswith("- ") or stripped.startswith("* "):
                pdf.set_font("Helvetica", "", 10)
                pdf.set_x(10)
                pdf.multi_cell(pdf.w - 20, 5, _safe("  -  " + stripped[2:]))
            elif stripped.startswith("**") and stripped.endswith("**"):
                pdf.set_font("Helvetica", "B", 10)
                pdf.multi_cell(0, 5, _safe(stripped[2:-2]))
            else:
                pdf.set_font("Helvetica", "", 10)
                try:
                    pdf.multi_cell(0, 5, _safe(_strip_md(stripped)))
                except Exception:
                    # Fallback: truncate line to fit
                    safe_text = _safe(_strip_md(stripped))[:120]
                    pdf.cell(0, 5, safe_text)
                    pdf.ln()
            i += 1

    def _add_table(self, pdf: _ReportPDF, columns: list[str], rows: list[list]):
        """Render a data table."""
        if not columns or not rows:
            return

        num_cols = len(columns)
        usable = pdf.w - 20

        # Normalize rows to have same number of columns as header
        norm_rows = []
        for row in rows:
            if len(row) < num_cols:
                norm_rows.append(list(row) + [""] * (num_cols - len(row)))
            else:
                norm_rows.append(list(row[:num_cols]))

        # Calculate column widths based on actual rendered text width
        pdf.set_font("Helvetica", "B", 8)
        col_widths = [pdf.get_string_width(_safe(str(c))) + 6 for c in columns]

        pdf.set_font("Helvetica", "", 8)
        for row in norm_rows[:50]:
            for i in range(num_cols):
                val = _safe(row[i]) if row[i] is not None else ""
                w = pdf.get_string_width(val) + 6
                col_widths[i] = max(col_widths[i], w)

        # Cap individual columns and scale to fit usable width
        col_widths = [min(w, usable * 0.4) for w in col_widths]
        total = sum(col_widths) or 1
        if total > usable:
            # Shrink to fit
            col_widths = [w / total * usable for w in col_widths]
        elif total < usable * 0.6:
            # Small table — expand gently but don't stretch across full page
            col_widths = [w / total * usable * 0.75 for w in col_widths]
        else:
            # Medium table — fill the page width
            col_widths = [w / total * usable for w in col_widths]

        # Final safety: ensure sum never exceeds usable
        final_total = sum(col_widths)
        if final_total > usable:
            col_widths = [w / final_total * usable for w in col_widths]

        row_height = 6

        def _draw_header():
            pdf.set_x(10)
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(*_GREEN)
            pdf.set_text_color(*_WHITE)
            for i, col in enumerate(columns):
                pdf.cell(col_widths[i], row_height, _safe(str(col)[:30]), border=1, fill=True, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(*_DARK_TEXT)

        _draw_header()

        for row_idx, row in enumerate(norm_rows):
            if pdf.get_y() > pdf.h - 25:
                pdf.add_page()
                _draw_header()

            pdf.set_x(10)
            if row_idx % 2 == 1:
                pdf.set_fill_color(*_LIGHT_BG)
                fill = True
            else:
                fill = False

            for i, col_w in enumerate(col_widths):
                val = _safe(row[i]) if row[i] is not None else ""
                while pdf.get_string_width(val) > col_w - 2 and len(val) > 1:
                    val = val[:-1]
                pdf.cell(col_w, row_height, val, border=1, fill=fill)
            pdf.ln()

        pdf.ln(4)

    def _add_label_value(self, pdf: _ReportPDF, label: str, value: str, label_w: float = 40):
        """Render a label: value pair."""
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(label_w, 6, _safe(label))
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _safe(value))
        pdf.ln()

    # ── Generic report export ────────────────────────────────────────────────

    def export(self, title: str = "Report", content: str = None,
               sections: list[dict] = None, filename: str = "") -> dict:
        if not content and not sections:
            return {"success": False, "error": "No content or sections provided"}

        pdf_name = self._make_filename(filename)
        pdf = _ReportPDF(title=title, orientation="P", unit="mm", format="A4")
        pdf.alias_nb_pages()
        pdf.add_page()

        # Title block
        pdf.set_font("Helvetica", "B", 20)
        pdf.set_text_color(*_ACCENT)
        pdf.cell(0, 12, _safe(title))
        pdf.ln()
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
                    pdf.cell(0, 9, _safe(heading))
                    pdf.ln()
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

    # ── SQL-to-PDF ───────────────────────────────────────────────────────────

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

    # ── Invoice template ─────────────────────────────────────────────────────

    def export_invoice(self, invoice_number: str, invoice_date: str = None,
                       bill_to: dict = None, ship_to: dict = None,
                       line_items: list[dict] = None, notes: str = None,
                       due_date: str = None, terms: str = None,
                       filename: str = "") -> dict:
        """Generate a branded invoice PDF.

        Args:
            invoice_number: Invoice # (e.g. "INV-2026-0042")
            invoice_date: Date string (defaults to today)
            bill_to: {name, address, city_state_zip, phone, email}
            ship_to: {name, address, city_state_zip} (optional, falls back to bill_to)
            line_items: [{description, quantity, unit_price, amount}]
            notes: Footer notes / payment instructions
            due_date: Payment due date
            terms: Payment terms (e.g. "Net 30")
            filename: Output filename without extension
        """
        if not line_items:
            return {"success": False, "error": "No line items provided"}

        bill_to = bill_to or {}
        ship_to = ship_to or {}
        invoice_date = invoice_date or date.today().isoformat()

        pdf_name = self._make_filename(filename or f"invoice_{invoice_number}")
        pdf = _ReportPDF(title="Invoice", orientation="P", unit="mm", format="A4")
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── Invoice title + number ──
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_text_color(*_ACCENT)
        pdf.cell(0, 14, "INVOICE")
        pdf.ln()
        pdf.set_draw_color(*_ACCENT)
        pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(6)

        # ── Invoice details (right-aligned block) ──
        y_start = pdf.get_y()
        pdf.set_text_color(*_DARK_TEXT)
        self._add_label_value(pdf, "Invoice #:", invoice_number)
        self._add_label_value(pdf, "Date:", invoice_date)
        if due_date:
            self._add_label_value(pdf, "Due Date:", due_date)
        if terms:
            self._add_label_value(pdf, "Terms:", terms)
        pdf.ln(4)

        # ── Bill To / Ship To ──
        col_w = (pdf.w - 20) / 2

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_GREEN)
        pdf.cell(col_w, 6, "BILL TO")
        pdf.cell(col_w, 6, "SHIP TO")
        pdf.ln()
        pdf.set_draw_color(*_LIGHT_GRAY)
        pdf.line(10, pdf.get_y(), 10 + col_w - 5, pdf.get_y())
        pdf.line(10 + col_w, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_DARK_TEXT)
        bill_lines = [bill_to.get("name", ""), bill_to.get("address", ""),
                      bill_to.get("city_state_zip", ""), bill_to.get("phone", ""),
                      bill_to.get("email", "")]
        ship_lines = [ship_to.get("name", bill_to.get("name", "")),
                      ship_to.get("address", bill_to.get("address", "")),
                      ship_to.get("city_state_zip", bill_to.get("city_state_zip", "")),
                      ship_to.get("phone", ""), ship_to.get("email", "")]

        for b, s in zip(bill_lines, ship_lines):
            if b or s:
                pdf.cell(col_w, 5, _safe(b))
                pdf.cell(col_w, 5, _safe(s))
                pdf.ln()
        pdf.ln(6)

        # ── Line items table ──
        columns = ["Description", "Qty", "Unit Price", "Amount"]
        widths = [95, 20, 35, 35]  # total ~185 for A4
        usable = pdf.w - 20
        scale = usable / sum(widths)
        widths = [w * scale for w in widths]

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(*_GREEN)
        pdf.set_text_color(*_WHITE)
        aligns = ["L", "C", "R", "R"]
        for i, col in enumerate(columns):
            pdf.cell(widths[i], 7, col, border=1, fill=True, align=aligns[i])
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK_TEXT)
        subtotal = 0.0
        for idx, item in enumerate(line_items):
            desc = item.get("description", "")
            qty = item.get("quantity", 0)
            unit_price = item.get("unit_price", 0)
            amount = item.get("amount", qty * unit_price)
            subtotal += float(amount)

            if idx % 2 == 1:
                pdf.set_fill_color(*_LIGHT_BG)
                fill = True
            else:
                fill = False

            pdf.cell(widths[0], 6, _safe(desc), border=1, fill=fill)
            pdf.cell(widths[1], 6, _safe(str(qty)), border=1, fill=fill, align="C")
            pdf.cell(widths[2], 6, _safe(f"${float(unit_price):,.2f}"), border=1, fill=fill, align="R")
            pdf.cell(widths[3], 6, _safe(f"${float(amount):,.2f}"), border=1, fill=fill, align="R")
            pdf.ln()

        # ── Totals ──
        pdf.ln(2)
        totals_x = sum(widths[:2]) + 10  # offset to align with price columns
        total_label_w = widths[2]
        total_val_w = widths[3]

        tax = sum(float(item.get("tax", 0)) for item in line_items)
        grand_total = subtotal + tax

        pdf.set_x(totals_x)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(total_label_w, 6, "Subtotal:", align="R")
        pdf.cell(total_val_w, 6, _safe(f"${subtotal:,.2f}"), align="R")
        pdf.ln()

        if tax > 0:
            pdf.set_x(totals_x)
            pdf.cell(total_label_w, 6, "Tax:", align="R")
            pdf.cell(total_val_w, 6, _safe(f"${tax:,.2f}"), align="R")
            pdf.ln()

        pdf.set_x(totals_x)
        pdf.set_draw_color(*_GREEN)
        pdf.line(totals_x, pdf.get_y(), totals_x + total_label_w + total_val_w, pdf.get_y())
        pdf.ln(1)
        pdf.set_x(totals_x)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*_GREEN)
        pdf.cell(total_label_w, 8, "Total:", align="R")
        pdf.cell(total_val_w, 8, _safe(f"${grand_total:,.2f}"), align="R")
        pdf.ln()

        # ── Notes ──
        if notes:
            pdf.ln(10)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*_GREEN)
            pdf.cell(0, 6, "Notes")
            pdf.ln()
            pdf.set_draw_color(*_LIGHT_GRAY)
            pdf.line(10, pdf.get_y(), 80, pdf.get_y())
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_GRAY_TEXT)
            pdf.multi_cell(0, 5, _safe(notes))

        filepath = self.export_path / pdf_name
        pdf.output(filepath)

        return {
            "success": True,
            "file_id": pdf_name,
            "download_url": f"/download/{pdf_name}",
            "message": f"Invoice {invoice_number} ready: {pdf_name} (Total: ${grand_total:,.2f})"
        }

    # ── Purchase Order template ──────────────────────────────────────────────

    def export_purchase_order(self, po_number: str, po_date: str = None,
                              vendor: dict = None, ship_to: dict = None,
                              line_items: list[dict] = None, notes: str = None,
                              delivery_date: str = None, terms: str = None,
                              filename: str = "") -> dict:
        """Generate a branded purchase order PDF.

        Args:
            po_number: PO # (e.g. "PO-2026-0105")
            po_date: Date string (defaults to today)
            vendor: {name, address, city_state_zip, phone, email, contact}
            ship_to: {name, address, city_state_zip}
            line_items: [{description, quantity, unit_price, amount}]
            notes: Additional instructions or notes
            delivery_date: Requested delivery date
            terms: Payment terms (e.g. "Net 30")
            filename: Output filename without extension
        """
        if not line_items:
            return {"success": False, "error": "No line items provided"}

        vendor = vendor or {}
        ship_to = ship_to or {}
        po_date = po_date or date.today().isoformat()

        pdf_name = self._make_filename(filename or f"po_{po_number}")
        pdf = _ReportPDF(title="Purchase Order", orientation="P", unit="mm", format="A4")
        pdf.alias_nb_pages()
        pdf.add_page()

        # ── PO title ──
        pdf.set_font("Helvetica", "B", 24)
        pdf.set_text_color(*_ACCENT)
        pdf.cell(0, 14, "PURCHASE ORDER")
        pdf.ln()
        pdf.set_draw_color(*_ACCENT)
        pdf.line(10, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(6)

        # ── PO details ──
        pdf.set_text_color(*_DARK_TEXT)
        self._add_label_value(pdf, "PO #:", po_number)
        self._add_label_value(pdf, "Date:", po_date)
        if delivery_date:
            self._add_label_value(pdf, "Delivery By:", delivery_date)
        if terms:
            self._add_label_value(pdf, "Terms:", terms)
        pdf.ln(4)

        # ── Vendor / Ship To ──
        col_w = (pdf.w - 20) / 2

        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*_GREEN)
        pdf.cell(col_w, 6, "VENDOR")
        pdf.cell(col_w, 6, "SHIP TO")
        pdf.ln()
        pdf.set_draw_color(*_LIGHT_GRAY)
        pdf.line(10, pdf.get_y(), 10 + col_w - 5, pdf.get_y())
        pdf.line(10 + col_w, pdf.get_y(), pdf.w - 10, pdf.get_y())
        pdf.ln(2)

        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(*_DARK_TEXT)
        vendor_lines = [vendor.get("name", ""), vendor.get("contact", ""),
                        vendor.get("address", ""), vendor.get("city_state_zip", ""),
                        vendor.get("phone", ""), vendor.get("email", "")]
        ship_lines = [ship_to.get("name", "Cobblestone Fruit Company"),
                      "", ship_to.get("address", ""),
                      ship_to.get("city_state_zip", ""),
                      ship_to.get("phone", ""), ship_to.get("email", "")]

        for v, s in zip(vendor_lines, ship_lines):
            if v or s:
                pdf.cell(col_w, 5, _safe(v))
                pdf.cell(col_w, 5, _safe(s))
                pdf.ln()
        pdf.ln(6)

        # ── Line items table ──
        columns = ["Item", "Description", "Qty", "Unit Price", "Amount"]
        widths = [15, 80, 20, 35, 35]
        usable = pdf.w - 20
        scale = usable / sum(widths)
        widths = [w * scale for w in widths]

        pdf.set_font("Helvetica", "B", 9)
        pdf.set_fill_color(*_GREEN)
        pdf.set_text_color(*_WHITE)
        aligns = ["C", "L", "C", "R", "R"]
        for i, col in enumerate(columns):
            pdf.cell(widths[i], 7, col, border=1, fill=True, align=aligns[i])
        pdf.ln()

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_DARK_TEXT)
        subtotal = 0.0
        for idx, item in enumerate(line_items):
            desc = item.get("description", "")
            qty = item.get("quantity", 0)
            unit_price = item.get("unit_price", 0)
            amount = item.get("amount", qty * unit_price)
            subtotal += float(amount)

            if idx % 2 == 1:
                pdf.set_fill_color(*_LIGHT_BG)
                fill = True
            else:
                fill = False

            pdf.cell(widths[0], 6, _safe(str(idx + 1)), border=1, fill=fill, align="C")
            pdf.cell(widths[1], 6, _safe(desc), border=1, fill=fill)
            pdf.cell(widths[2], 6, _safe(str(qty)), border=1, fill=fill, align="C")
            pdf.cell(widths[3], 6, _safe(f"${float(unit_price):,.2f}"), border=1, fill=fill, align="R")
            pdf.cell(widths[4], 6, _safe(f"${float(amount):,.2f}"), border=1, fill=fill, align="R")
            pdf.ln()

        # ── Totals ──
        pdf.ln(2)
        totals_x = sum(widths[:3]) + 10
        total_label_w = widths[3]
        total_val_w = widths[4]

        pdf.set_x(totals_x)
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*_GREEN)
        pdf.set_draw_color(*_GREEN)
        pdf.line(totals_x, pdf.get_y(), totals_x + total_label_w + total_val_w, pdf.get_y())
        pdf.ln(1)
        pdf.set_x(totals_x)
        pdf.cell(total_label_w, 8, "Total:", align="R")
        pdf.cell(total_val_w, 8, _safe(f"${subtotal:,.2f}"), align="R")
        pdf.ln()

        # ── Notes ──
        if notes:
            pdf.ln(10)
            pdf.set_font("Helvetica", "B", 10)
            pdf.set_text_color(*_GREEN)
            pdf.cell(0, 6, "Notes / Instructions")
            pdf.ln()
            pdf.set_draw_color(*_LIGHT_GRAY)
            pdf.line(10, pdf.get_y(), 80, pdf.get_y())
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_GRAY_TEXT)
            pdf.multi_cell(0, 5, _safe(notes))

        # ── Signature lines ──
        pdf.ln(20)
        sig_y = pdf.get_y()
        pdf.set_draw_color(*_DARK_TEXT)
        pdf.line(10, sig_y, 85, sig_y)
        pdf.line(110, sig_y, 185, sig_y)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*_GRAY_TEXT)
        pdf.set_xy(10, sig_y + 1)
        pdf.cell(75, 5, "Authorized Signature")
        pdf.set_xy(110, sig_y + 1)
        pdf.cell(75, 5, "Date")

        filepath = self.export_path / pdf_name
        pdf.output(filepath)

        return {
            "success": True,
            "file_id": pdf_name,
            "download_url": f"/download/{pdf_name}",
            "message": f"Purchase Order {po_number} ready: {pdf_name} (Total: ${subtotal:,.2f})"
        }


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
        "description": "Export a formatted PDF report. IMPORTANT: For any tabular data, ALWAYS use 'sections' with columns/rows arrays — do NOT put tables as text in 'content'. Use 'content' only for narrative text. Use 'sections' for structured data: each section can have a heading, text, and/or table (columns + rows). You can mix both — use 'content' for an intro and 'sections' for the data tables. Returns a download link.",
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
    {
        "name": "export_invoice",
        "description": "Generate a professional branded invoice PDF. Use when the user asks to create an invoice. Pass bill_to/ship_to as address objects and line_items as an array of {description, quantity, unit_price, amount}. Amounts are auto-calculated from qty * unit_price if not provided. Returns a download link.",
        "parameters": {
            "type": "object",
            "properties": {
                "invoice_number": {
                    "type": "string",
                    "description": "Invoice number (e.g. 'INV-2026-0042')"
                },
                "invoice_date": {
                    "type": "string",
                    "description": "Invoice date (YYYY-MM-DD). Defaults to today."
                },
                "bill_to": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"},
                        "city_state_zip": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"}
                    },
                    "description": "Billing address"
                },
                "ship_to": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "address": {"type": "string"},
                        "city_state_zip": {"type": "string"}
                    },
                    "description": "Shipping address (defaults to bill_to if omitted)"
                },
                "line_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "amount": {"type": "number", "description": "Line total (auto-calculated from qty * unit_price if omitted)"},
                            "tax": {"type": "number", "description": "Tax amount for this line (default 0)"}
                        },
                        "required": ["description", "quantity", "unit_price"]
                    },
                    "description": "Invoice line items"
                },
                "due_date": {
                    "type": "string",
                    "description": "Payment due date (YYYY-MM-DD)"
                },
                "terms": {
                    "type": "string",
                    "description": "Payment terms (e.g. 'Net 30', 'Due on receipt')"
                },
                "notes": {
                    "type": "string",
                    "description": "Footer notes or payment instructions"
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename without extension"
                }
            },
            "required": ["invoice_number", "line_items"]
        }
    },
    {
        "name": "export_purchase_order",
        "description": "Generate a professional branded purchase order (PO) PDF. Use when the user asks to create a PO. Pass vendor info, ship-to address, and line_items as an array of {description, quantity, unit_price, amount}. Includes signature lines at the bottom. Returns a download link.",
        "parameters": {
            "type": "object",
            "properties": {
                "po_number": {
                    "type": "string",
                    "description": "PO number (e.g. 'PO-2026-0105')"
                },
                "po_date": {
                    "type": "string",
                    "description": "PO date (YYYY-MM-DD). Defaults to today."
                },
                "vendor": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "contact": {"type": "string"},
                        "address": {"type": "string"},
                        "city_state_zip": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"}
                    },
                    "description": "Vendor/supplier info"
                },
                "ship_to": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "Defaults to 'Cobblestone Fruit Company'"},
                        "address": {"type": "string"},
                        "city_state_zip": {"type": "string"}
                    },
                    "description": "Delivery address"
                },
                "line_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "description": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit_price": {"type": "number"},
                            "amount": {"type": "number", "description": "Line total (auto-calculated if omitted)"}
                        },
                        "required": ["description", "quantity", "unit_price"]
                    },
                    "description": "PO line items"
                },
                "delivery_date": {
                    "type": "string",
                    "description": "Requested delivery date (YYYY-MM-DD)"
                },
                "terms": {
                    "type": "string",
                    "description": "Payment terms (e.g. 'Net 30')"
                },
                "notes": {
                    "type": "string",
                    "description": "Additional instructions or notes"
                },
                "filename": {
                    "type": "string",
                    "description": "Output filename without extension"
                }
            },
            "required": ["po_number", "line_items"]
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
        "export_invoice": lambda p: exporter.export_invoice(
            invoice_number=p.get("invoice_number", ""),
            invoice_date=p.get("invoice_date"),
            bill_to=p.get("bill_to"),
            ship_to=p.get("ship_to"),
            line_items=p.get("line_items"),
            notes=p.get("notes"),
            due_date=p.get("due_date"),
            terms=p.get("terms"),
            filename=p.get("filename", ""),
        ),
        "export_purchase_order": lambda p: exporter.export_purchase_order(
            po_number=p.get("po_number", ""),
            po_date=p.get("po_date"),
            vendor=p.get("vendor"),
            ship_to=p.get("ship_to"),
            line_items=p.get("line_items"),
            notes=p.get("notes"),
            delivery_date=p.get("delivery_date"),
            terms=p.get("terms"),
            filename=p.get("filename", ""),
        ),
    }
