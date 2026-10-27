"""Record sheet export ('Save A Copy'): printable PDF or Excel from the audit database.

The file respects whatever filter is on screen (search text and date range).
"""
import os
from datetime import datetime
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core import config
from database import db_manager

HEADERS = ["Last Name", "First Name", "Student Number", "Date", "Time", "Violation", "Status"]
_COL_MM = [36, 36, 32, 24, 20, 78, 47]


def default_path(ext: str = "pdf") -> str:
    return os.path.join(config.REPORTS_DIR, f"record_sheet_{datetime.now():%Y%m%d_%H%M%S}.{ext}")


def _table_rows(rows) -> list:
    return [[r["last_name"], r["first_name"], r["student_id"], r["log_date"], r["log_time"],
             r["violation_type"], r["verification_status"]] for r in rows]


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.grey)
    canvas.drawString(12 * mm, 8 * mm, "SmartGuard-Vision  |  Campus Checkpoint Record Sheet")
    canvas.drawRightString(landscape(A4)[0] - 12 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def _pdf(path, rows, summary, period, search) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=16 * mm, title="SmartGuard-Vision Record Sheet")
    meta = f"Period: {escape(period)}" + (f" &nbsp;|&nbsp; Search: {escape(search)}" if search else "")
    meta += f" &nbsp;|&nbsp; Generated: {datetime.now():%Y-%m-%d %H:%M}"
    by_status = ", ".join(f"{k}: {v}" for k, v in summary["by_status"].items()) or "none"
    by_type = ", ".join(f"{k}: {v}" for k, v in summary["by_violation"].items()) or "none"
    story = [Paragraph("Checkpoint Record Sheet", styles["Title"]), Paragraph(meta, styles["Normal"]),
             Spacer(1, 4 * mm),
             Paragraph(f"<b>Total records:</b> {summary['total']}", styles["Normal"]),
             Paragraph(f"<b>By status:</b> {escape(by_status)}", styles["Normal"]),
             Paragraph(f"<b>By violation:</b> {escape(by_type)}", styles["Normal"]),
             Spacer(1, 5 * mm)]
    if rows:
        table = Table([HEADERS] + _table_rows(rows), repeatRows=1, colWidths=[w * mm for w in _COL_MM])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e6e6e6")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#b0b0b0")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f4f7fb")]),
        ]))
        story.append(table)
    else:
        story.append(Paragraph("No records for the selected filters.", styles["Italic"]))
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)


def _excel(path, rows) -> None:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Records"
    ws.append(HEADERS)
    for row in _table_rows(rows):
        ws.append(row)
    wb.save(path)


def export(path: Optional[str] = None, search: str = "", date_from: str = "", date_to: str = "",
           period: str = "All dates", db_path: Optional[str] = None) -> str:
    """Write the sheet (.pdf or .xlsx by extension) and return its path."""
    path = path or default_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    rows = db_manager.fetch_report_rows(search, date_from, date_to, db_path)
    if path.lower().endswith(".xlsx"):
        _excel(path, rows)
    else:
        _pdf(path, rows, db_manager.fetch_summary(date_from, date_to, db_path), period, search.strip())
    return path
