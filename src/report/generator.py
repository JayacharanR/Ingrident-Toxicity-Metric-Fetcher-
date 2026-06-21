"""
PDF report generator for toxicity analysis results.

Creates a professional-looking PDF report from a ProductReport object,
with color-coded risk indicators and a summary table.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fpdf import FPDF

from src.toxicity.models import ProductReport, RiskLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Color palette for risk levels
# ---------------------------------------------------------------------------

_RISK_COLORS: dict[RiskLevel, tuple[int, int, int]] = {
    RiskLevel.SAFE:     (34, 197, 94),    # Green
    RiskLevel.LOW:      (234, 179, 8),     # Yellow
    RiskLevel.MODERATE: (249, 115, 22),    # Orange
    RiskLevel.HIGH:     (239, 68, 68),     # Red
    RiskLevel.CRITICAL: (127, 29, 29),     # Dark Red
}

_RISK_EMOJI: dict[RiskLevel, str] = {
    RiskLevel.SAFE:     "SAFE",
    RiskLevel.LOW:      "LOW RISK",
    RiskLevel.MODERATE: "MODERATE",
    RiskLevel.HIGH:     "HIGH RISK",
    RiskLevel.CRITICAL: "CRITICAL",
}


class ReportPDF(FPDF):
    """Custom FPDF subclass with header and footer."""

    def header(self) -> None:
        self.set_font("Helvetica", "B", 14)
        self.set_text_color(30, 30, 30)
        self.cell(0, 10, "Ingredient Toxicity Report", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def _clean_pdf_text(text: str) -> str:
    """Replace or remove non-latin1 characters like emojis, smart quotes, etc."""
    if not text:
        return ""
    # Standardize common problematic characters
    replacements = {
        "✅": "[SAFE]",
        "⚠️": "[WARNING]",
        "🟢": "",
        "🟡": "",
        "🟠": "",
        "🔴": "",
        "⛔": "",
        "—": "-",
        "–": "-",
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    
    # Drop any other non-latin1 characters
    return text.encode("latin-1", errors="ignore").decode("latin-1")


def generate_pdf(report: ProductReport, output_path: str | Path) -> Path:
    """Generate a PDF toxicity report.

    Args:
        report: The completed ProductReport.
        output_path: Where to save the PDF.

    Returns:
        Path to the generated PDF file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = ReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # --- Product Summary ---
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, f"Product: {_clean_pdf_text(report.product_name)}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Overall score box
    risk_color = _RISK_COLORS[report.overall_risk]
    pdf.set_fill_color(*risk_color)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(
        95, 12,
        f"Overall Score: {report.overall_score}/10",
        fill=True, align="C",
    )
    pdf.cell(
        95, 12,
        f"Risk Level: {_RISK_EMOJI[report.overall_risk]}",
        fill=True, align="C", new_x="LMARGIN", new_y="NEXT",
    )
    pdf.ln(5)

    # Summary text
    pdf.set_text_color(60, 60, 60)
    pdf.set_font("Helvetica", "", 10)
    pdf.multi_cell(0, 5, _clean_pdf_text(report.summary))
    pdf.ln(5)

    # Stats
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 6, f"Total Ingredients: {report.total_ingredients}  |  High-Risk Ingredients: {report.high_risk_count}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # --- Ingredient Table ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Ingredient Breakdown", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    # Table header
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(45, 55, 72)
    pdf.set_text_color(255, 255, 255)
    col_widths = [60, 18, 25, 87]  # name, score, risk, summary
    headers = ["Ingredient", "Score", "Risk", "Summary"]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 8, header, border=1, fill=True, align="C")
    pdf.ln()

    # Table rows
    pdf.set_font("Helvetica", "", 8)
    for idx, item in enumerate(report.ingredients):
        bg = (245, 245, 245) if idx % 2 == 0 else (255, 255, 255)
        risk_color = _RISK_COLORS[item.risk_level]

        pdf.set_fill_color(*bg)
        pdf.set_text_color(30, 30, 30)

        # Calculate row height based on summary text
        clean_summary = _clean_pdf_text(item.summary)
        summary_text = clean_summary[:100] + ("..." if len(clean_summary) > 100 else "")
        line_height = 6
        row_height = max(8, line_height * ((len(summary_text) // 40) + 1))

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        # Check if we need a new page
        if y_start + row_height > 275:
            pdf.add_page()
            # Re-draw header
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(45, 55, 72)
            pdf.set_text_color(255, 255, 255)
            for i, header in enumerate(headers):
                pdf.cell(col_widths[i], 8, header, border=1, fill=True, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            x_start = pdf.get_x()
            y_start = pdf.get_y()

        # Name column
        pdf.set_fill_color(*bg)
        pdf.cell(col_widths[0], row_height, _clean_pdf_text(item.ingredient.name)[:30], border=1, fill=True)

        # Score column with color
        pdf.set_fill_color(*risk_color)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(col_widths[1], row_height, str(item.toxicity_score), border=1, fill=True, align="C")

        # Risk column
        pdf.cell(col_widths[2], row_height, item.risk_level.value, border=1, fill=True, align="C")

        # Summary column
        pdf.set_fill_color(*bg)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(col_widths[3], row_height, summary_text, border=1, fill=True)
        pdf.ln()

    pdf.ln(10)

    # --- Detailed Analysis ---
    pdf.set_font("Helvetica", "B", 13)
    pdf.set_text_color(30, 30, 30)
    pdf.cell(0, 10, "Detailed Analysis", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    for item in report.ingredients:
        # Check page space
        if pdf.get_y() > 240:
            pdf.add_page()

        risk_color = _RISK_COLORS[item.risk_level]
        pdf.set_fill_color(*risk_color)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(
            0, 8,
            f"  {_clean_pdf_text(item.ingredient.name)}  -  Score: {item.toxicity_score}/10 ({item.risk_level.value})",
            fill=True, new_x="LMARGIN", new_y="NEXT",
        )

        pdf.set_text_color(60, 60, 60)
        pdf.set_font("Helvetica", "", 9)
        pdf.ln(2)

        if item.adi:
            pdf.cell(0, 5, f"ADI: {_clean_pdf_text(item.adi)}", new_x="LMARGIN", new_y="NEXT")

        if item.data_sources:
            pdf.cell(0, 5, f"Sources: {_clean_pdf_text(', '.join(item.data_sources))}", new_x="LMARGIN", new_y="NEXT")

        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 9)
        pdf.multi_cell(0, 5, _clean_pdf_text(item.harm_explanation))
        pdf.ln(5)

    # Save
    pdf.output(str(output_path))
    logger.info("PDF report saved to %s", output_path)
    return output_path
