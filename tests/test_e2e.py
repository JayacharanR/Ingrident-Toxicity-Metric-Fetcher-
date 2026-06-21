"""
End-to-end pipeline verification test.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from src.ocr.extractor import TextExtractor
from src.parser.ingredient_parser import parse_ingredients
from src.toxicity.scorer import generate_report
from src.report.generator import generate_pdf


@pytest.mark.skipif(
    not Path("input/images2.jpg").exists(),
    reason="Sample image input/images2.jpg is required for E2E test",
)
@patch("src.parser.ingredient_parser._get_client")
@patch("src.toxicity.scorer._get_client")
def test_e2e_pipeline(mock_scorer_client, mock_parser_client, tmp_path):
    """Test the complete OCR -> Parsing -> Scoring -> PDF report generation pipeline."""
    image_path = "input/images2.jpg"

    # --- Stage 1: OCR ---
    extractor = TextExtractor()
    raw_text, confidence = extractor.extract_with_confidence(image_path)

    assert isinstance(raw_text, str)
    assert len(raw_text) > 0
    assert confidence > 0.5

    # --- Stage 2: Parsing (Mocked Gemini) ---
    # Setup mock parser response text (JSON array format)
    mock_parser = MagicMock()
    mock_parser_response = MagicMock()
    mock_parser_response.text = """
    [
        {"name": "Potatoes", "e_number": null, "category": "Natural Ingredient"},
        {"name": "Vegetable Oil", "e_number": null, "category": "Natural Ingredient"},
        {"name": "Salt", "e_number": null, "category": "Natural Ingredient"},
        {"name": "Monosodium Glutamate", "e_number": "E621", "category": "Flavor Enhancer"}
    ]
    """
    mock_parser.models.generate_content.return_value = mock_parser_response
    mock_parser_client.return_value = mock_parser

    ingredients = parse_ingredients(raw_text)
    assert len(ingredients) == 4
    assert ingredients[0].name == "Potatoes"
    assert ingredients[3].e_number == "E621"

    # --- Stage 3 & 4: Lookup + Scoring (Mocked Gemini) ---
    mock_scorer = MagicMock()
    # Simple sequence of mocked scorer responses for the 4 ingredients
    res1 = MagicMock(text='{"toxicity_score": 1, "summary": "Safe ingredient.", "harm_explanation": "Potatoes are a natural starch widely consumed as a staple food."}')
    res2 = MagicMock(text='{"toxicity_score": 2, "summary": "Generally safe.", "harm_explanation": "Vegetable oil is generally safe, though high in fats."}')
    res3 = MagicMock(text='{"toxicity_score": 2, "summary": "Safe in moderation.", "harm_explanation": "Salt is an essential mineral but high consumption is linked to hypertension."}')
    res4 = MagicMock(text='{"toxicity_score": 5, "summary": "Moderate risk flavor enhancer.", "harm_explanation": "Monosodium Glutamate is linked to headaches or sensitivity reactions in some individuals."}')

    mock_scorer.models.generate_content.side_effect = [res1, res2, res3, res4]
    mock_scorer_client.return_value = mock_scorer

    report = generate_report(
        ingredients=ingredients,
        product_name="Lay's Chips",
        image_path=image_path,
        raw_ocr_text=raw_text,
    )

    assert report.product_name == "Lay's Chips"
    assert report.total_ingredients == 4
    assert len(report.ingredients) == 4
    assert report.ingredients[3].ingredient.name == "Monosodium Glutamate"
    assert report.ingredients[3].toxicity_score == 5
    assert report.overall_score > 0.0

    # --- Stage 5: Report PDF generation ---
    pdf_output = tmp_path / "e2e_report.pdf"
    output_path = generate_pdf(report, pdf_output)

    assert output_path.exists()
    assert output_path.stat().st_size > 0
