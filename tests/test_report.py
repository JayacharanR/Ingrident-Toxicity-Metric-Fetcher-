"""
Unit tests for the PDF report generator.
"""

from pathlib import Path
import pytest

from src.report.generator import generate_pdf
from src.toxicity.models import (
    Ingredient,
    FunctionalCategory,
    RiskLevel,
    ToxicityData,
    IngredientScore,
    ProductReport,
)


def test_generate_pdf(tmp_path):
    """Test generating a PDF report file from a ProductReport."""
    # Create sample report
    ing1 = Ingredient(name="Citric Acid", category=FunctionalCategory.ACIDITY_REGULATOR)
    score1 = IngredientScore(
        ingredient=ing1,
        toxicity_score=2,
        risk_level=RiskLevel.SAFE,
        summary="Generally recognized as safe.",
        harm_explanation="Naturally occurring organic acid found in citrus fruits.",
        adi="Not limited",
        data_sources=["EFSA"],
    )

    ing2 = Ingredient(name="Titanium Dioxide", e_number="E171", category=FunctionalCategory.COLORANT)
    score2 = IngredientScore(
        ingredient=ing2,
        toxicity_score=9,
        risk_level=RiskLevel.CRITICAL,
        summary="Banned in Europe due to genotoxicity concerns.",
        harm_explanation="Linked to potential DNA damage and genetic toxicity when ingested.",
        adi="No safe level",
        data_sources=["EFSA"],
    )

    report = ProductReport(
        product_name="Mock Lay's Bag",
        image_path="mock_image.jpg",
        raw_ocr_text="Ingredients: Citric Acid, Titanium Dioxide",
        ingredients=[score1, score2],
    )
    report.compute_aggregates()

    pdf_output = tmp_path / "test_report.pdf"
    output_path = generate_pdf(report, pdf_output)

    # Assertions
    assert output_path == pdf_output
    assert pdf_output.exists()
    assert pdf_output.stat().st_size > 0
