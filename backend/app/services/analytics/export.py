"""Result export (F17).

CSV, JSON and Excel are pure serialisation of the result set. The PDF is a
report: question, SQL, narrative, the chart the browser drew, statistics, and
a sample of rows - the thing someone actually attaches to an email.

The chart arrives from the client as a PNG, because the chart is a Recharts
SVG that only exists in the browser. Re-drawing it server-side would mean a
second charting implementation whose output could silently disagree with what
the user saw, which is worse than the coupling.

PNG export of the chart alone never reaches this module - the browser
serialises its own SVG to a canvas and saves it directly, with no round trip.
"""

import base64
import binascii
import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.core.logging import get_logger
from app.services.analytics.analyze import Analysis
from app.services.analytics.profile import ColumnKind

log = get_logger(__name__)

# Rows listed in the PDF. A PDF is a summary document; anyone who wants all
# 10,000 rows wants the CSV.
PDF_ROW_LIMIT = 50

MAX_CHART_IMAGE_BYTES = 4 * 1024 * 1024


class ExportFormat(str, Enum):
    CSV = "csv"
    JSON = "json"
    XLSX = "xlsx"
    PDF = "pdf"


MEDIA_TYPES: dict[ExportFormat, str] = {
    ExportFormat.CSV: "text/csv",
    ExportFormat.JSON: "application/json",
    ExportFormat.XLSX: (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ),
    ExportFormat.PDF: "application/pdf",
}


@dataclass
class ReportContext:
    """Everything the PDF says beyond the rows themselves."""

    title: str = "Query result"
    question: str = ""
    sql: str = ""
    generated_at: datetime = field(default_factory=lambda: datetime.now())
    headline: str = ""
    summary: str = ""
    findings: list[str] = field(default_factory=list)
    narrator: str = ""
    chart_png: bytes | None = None
    analysis: Analysis | None = None


def _cell(value: Any) -> Any:
    """Coerce a driver value into something the writers accept."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, bytes | bytearray | memoryview):
        return f"<{len(bytes(value))} bytes>"
    return value


def decode_chart_image(data_url: str | None) -> bytes | None:
    """Decode a client-supplied `data:image/png;base64,...` chart.

    Returns None on anything unexpected. A malformed image must not fail an
    export the user is waiting on - the report is still complete without it.
    """
    if not data_url:
        return None

    _, _, encoded = data_url.partition(",")
    if not encoded:
        return None

    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        log.warning("chart_image_undecodable")
        return None

    if len(raw) > MAX_CHART_IMAGE_BYTES:
        log.warning("chart_image_too_large", size=len(raw))
        return None
    # PNG magic number. Anything else is not what the client claimed to send.
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        log.warning("chart_image_not_png")
        return None
    return raw


def to_csv(columns: list[str], rows: list[list[Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(columns)
    writer.writerows([_cell(v) for v in row] for row in rows)
    # BOM so Excel opens UTF-8 correctly rather than mangling every accent.
    return b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")


def to_json(columns: list[str], rows: list[list[Any]]) -> bytes:
    records = [
        {
            column: _cell(row[index]) if index < len(row) else None
            for index, column in enumerate(columns)
        }
        for row in rows
    ]
    return json.dumps(records, indent=2, default=str).encode("utf-8")


def to_xlsx(
    columns: list[str], rows: list[list[Any]], sheet_name: str = "Result"
) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    workbook = Workbook()
    sheet = workbook.active
    # Excel rejects sheet names over 31 characters or containing []:*?/\.
    sheet.title = "".join(c for c in sheet_name if c not in "[]:*?/\\")[:31] or "Result"

    sheet.append(list(columns))
    header_fill = PatternFill("solid", fgColor="1F2937")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for row in rows:
        sheet.append([_cell(v) for v in row])

    # Freeze the header and turn on filters - what anyone does by hand on
    # opening a data export.
    sheet.freeze_panes = "A2"
    if rows:
        sheet.auto_filter.ref = sheet.dimensions

    for index, column in enumerate(columns, start=1):
        widest = max(
            [len(str(column))]
            + [
                len(str(_cell(row[index - 1])))
                for row in rows[:200]
                if index - 1 < len(row) and row[index - 1] is not None
            ]
        )
        sheet.column_dimensions[get_column_letter(index)].width = min(
            max(widest + 2, 10), 60
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _statistics_table(analysis: Analysis) -> list[list[str]]:
    header = ["Column", "Type", "Non-null", "Distinct", "Range", "Mean / most common"]
    body: list[list[str]] = [header]

    for column in analysis.profile.columns:
        if column.kind is ColumnKind.NUMERIC:
            span = f"{column.minimum:,.2f} - {column.maximum:,.2f}"
            centre = f"{column.mean:,.2f}"
        elif column.kind is ColumnKind.TEMPORAL:
            span = f"{column.earliest} - {column.latest}"
            centre = "-"
        elif column.top_values:
            span = "-"
            centre = f"{column.top_values[0].value} ({column.top_values[0].count})"
        else:
            span = centre = "-"

        body.append(
            [
                column.name,
                column.kind.value,
                str(column.count),
                str(column.distinct_count),
                span,
                centre,
            ]
        )
    return body


def to_pdf(columns: list[str], rows: list[list[Any]], context: ReportContext) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
    )

    buffer = io.BytesIO()
    # Landscape because result tables are wide; portrait would force the row
    # sample down to three or four columns.
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=context.title,
        author="NLQ Analytics Platform",
    )

    styles = getSampleStyleSheet()
    heading = ParagraphStyle(
        "ReportHeading",
        parent=styles["Heading1"],
        fontSize=18,
        spaceAfter=2,
        textColor=colors.HexColor("#111827"),
    )
    subtle = ParagraphStyle(
        "Subtle",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#6B7280"),
    )
    section = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=11,
        spaceBefore=12,
        spaceAfter=4,
        textColor=colors.HexColor("#374151"),
    )
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9, leading=13)
    code = ParagraphStyle(
        "Code",
        parent=styles["Normal"],
        fontName="Courier",
        fontSize=8,
        leading=11,
        alignment=TA_LEFT,
        backColor=colors.HexColor("#F3F4F6"),
        borderPadding=6,
    )

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story: list[Any] = [
        Paragraph(escape(context.title), heading),
        Paragraph(
            f"Generated {context.generated_at.strftime('%d %B %Y, %H:%M')}"
            + (f" · summary by {escape(context.narrator)}" if context.narrator else ""),
            subtle,
        ),
        Spacer(1, 8),
    ]

    if context.question:
        story += [
            Paragraph("Question", section),
            Paragraph(escape(context.question), body),
        ]

    if context.headline or context.summary:
        story.append(Paragraph("Summary", section))
        if context.headline:
            story.append(Paragraph(f"<b>{escape(context.headline)}</b>", body))
        if context.summary:
            story.append(Paragraph(escape(context.summary), body))
        for finding in context.findings:
            story.append(Paragraph(f"• {escape(finding)}", body))

    if context.chart_png:
        story.append(Paragraph("Chart", section))
        try:
            image = Image(io.BytesIO(context.chart_png))
            available = document.width
            scale = min(
                available / image.imageWidth, (95 * mm) / image.imageHeight, 1.0
            )
            image.drawWidth = image.imageWidth * scale
            image.drawHeight = image.imageHeight * scale
            image.hAlign = "LEFT"
            story.append(image)
        except Exception:  # noqa: BLE001 - a bad image must not lose the report
            log.warning("chart_image_unrenderable")
            story.append(Paragraph("The chart image could not be rendered.", subtle))

    if context.analysis:
        story.append(Paragraph("Column statistics", section))
        story.append(_grid(_statistics_table(context.analysis), document.width))

    if context.sql:
        story += [
            Paragraph("SQL", section),
            Paragraph(escape(context.sql).replace("\n", "<br/>"), code),
        ]

    story.append(PageBreak())
    shown = rows[:PDF_ROW_LIMIT]
    story.append(
        Paragraph(
            f"Rows ({len(shown):,} of {len(rows):,} shown)"
            if len(rows) > len(shown)
            else f"Rows ({len(rows):,})",
            section,
        )
    )
    if shown:
        grid = [list(columns)] + [
            ["" if v is None else str(_cell(v)) for v in row] for row in shown
        ]
        story.append(_grid(grid, document.width))
    else:
        story.append(Paragraph("The query returned no rows.", body))

    document.build(story)
    return buffer.getvalue()


def _grid(data: list[list[str]], width: float):
    """A readable table that fits the page whatever its column count."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Table, TableStyle

    columns = max(len(row) for row in data)
    column_width = width / columns

    cell_style = ParagraphStyle("Cell", fontName="Helvetica", fontSize=7, leading=9)
    header_style = ParagraphStyle(
        "HeaderCell",
        fontName="Helvetica-Bold",
        fontSize=7,
        leading=9,
        textColor=colors.white,
    )

    def escape(text: str) -> str:
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # Paragraphs rather than raw strings so long values wrap instead of
    # overflowing into the next column.
    wrapped = [
        [
            Paragraph(escape(str(cell)), header_style if index == 0 else cell_style)
            for cell in row
        ]
        for index, row in enumerate(data)
    ]

    table = Table(wrapped, colWidths=[column_width] * columns, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
                (
                    "ROWBACKGROUNDS",
                    (0, 1),
                    (-1, -1),
                    [colors.white, colors.HexColor("#F9FAFB")],
                ),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return table


def render(
    fmt: ExportFormat,
    columns: list[str],
    rows: list[list[Any]],
    context: ReportContext | None = None,
) -> bytes:
    """Serialise a result set in the requested format."""
    if fmt is ExportFormat.CSV:
        return to_csv(columns, rows)
    if fmt is ExportFormat.JSON:
        return to_json(columns, rows)
    if fmt is ExportFormat.XLSX:
        return to_xlsx(
            columns, rows, sheet_name=(context.title if context else "Result")
        )
    return to_pdf(columns, rows, context or ReportContext())


__all__ = [
    "MEDIA_TYPES",
    "PDF_ROW_LIMIT",
    "ExportFormat",
    "ReportContext",
    "decode_chart_image",
    "render",
    "to_csv",
    "to_json",
    "to_pdf",
    "to_xlsx",
]
