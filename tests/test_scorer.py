"""
Unit tests for the toxicity scoring engine.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.toxicity.models import (
    Ingredient,
    FunctionalCategory,
    ToxicityData,
    RiskLevel,
    IngredientScore,
)
from src.toxicity.scorer import (
    _format_db_context,
    score_ingredient,
    score_all_ingredients,
    generate_report,
)


def test_format_db_context_none():
    """Test format_db_context with None input."""
    res = _format_db_context(None)
    assert "No data found" in res


def test_format_db_context_valid():
    """Test format_db_context with fully populated ToxicityData."""
    data = ToxicityData(
        ingredient_name="Test Substance",
        source="Test EFSA",
        adi="0-10 mg/kg bw/day",
        noael="500 mg/kg",
        hazard_class="Skin Irrit. 2",
        safety_opinion="Safe within limits",
        banned_in=["EU", "India"],
        known_effects=["Skin irritation", "Headache"],
    )
    res = _format_db_context(data)
    assert "Source: Test EFSA" in res
    assert "Acceptable Daily Intake (ADI): 0-10 mg/kg bw/day" in res
    assert "NOAEL: 500 mg/kg" in res
    assert "GHS Hazard Classification: Skin Irrit. 2" in res
    assert "Safety Opinion: Safe within limits" in res
    assert "Banned In: EU, India" in res
    assert "Known Adverse Effects: Skin irritation, Headache" in res


@patch("src.toxicity.scorer._get_client")
def test_score_ingredient(mock_get_client):
    """Test scoring a single ingredient with mocked LLM response."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = """
    {
        "toxicity_score": 7,
        "summary": "This is a high risk ingredient.",
        "harm_explanation": "Highly harmful based on simulated test data."
    }
    """
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    ingredient = Ingredient(
        name="Sunset Yellow",
        e_number="E110",
        category=FunctionalCategory.COLORANT,
    )
    toxicity_data = ToxicityData(
        ingredient_name="Sunset Yellow",
        source="EFSA",
        adi="0-4 mg/kg",
    )

    score = score_ingredient(ingredient, toxicity_data)
    assert score.toxicity_score == 7
    assert score.risk_level == RiskLevel.HIGH
    assert "high risk" in score.summary
    assert score.adi == "0-4 mg/kg"
    assert "EFSA" in score.data_sources


@patch("src.toxicity.scorer.score_ingredient")
def test_score_all_ingredients(mock_score_ingredient):
    """Test scoring all ingredients with a mocked database lookup."""
    # Mock database
    mock_db = MagicMock()
    # Let E621 find MSG in the DB
    mock_db.lookup_by_e_number.return_value = ToxicityData(
        ingredient_name="Monosodium Glutamate",
        source="EFSA",
    )
    # Let Sugar not be found in DB
    mock_db.lookup.return_value = None

    # Setup mocked scorer return values
    ingredient_sugar = Ingredient(name="Sugar", category=FunctionalCategory.NATURAL_INGREDIENT)
    ingredient_msg = Ingredient(name="Monosodium Glutamate", e_number="E621", category=FunctionalCategory.FLAVOR_ENHANCER)

    # Return dummy scores
    score_sugar = MagicMock(toxicity_score=1)
    score_msg = MagicMock(toxicity_score=5)
    mock_score_ingredient.side_effect = [score_sugar, score_msg]

    scores = score_all_ingredients([ingredient_sugar, ingredient_msg], db=mock_db)

    assert len(scores) == 2
    mock_db.lookup_by_e_number.assert_called_with("E621")
    mock_db.lookup.assert_called_with("Sugar")


@patch("src.toxicity.scorer.score_all_ingredients")
def test_generate_report(mock_score_all_ingredients):
    """Test ProductReport generation and aggregates calculation."""
    ingredient_1 = Ingredient(name="A", category=FunctionalCategory.NATURAL_INGREDIENT)
    ingredient_2 = Ingredient(name="B", category=FunctionalCategory.COLORANT)

    # Create real IngredientScore objects to satisfy Pydantic validation
    score_1 = IngredientScore(
        ingredient=ingredient_1,
        toxicity_score=2,
        risk_level=RiskLevel.SAFE,
        summary="Safe substance",
        harm_explanation="No known toxicity at normal dietary levels.",
        adi=None,
        data_sources=[],
    )
    score_2 = IngredientScore(
        ingredient=ingredient_2,
        toxicity_score=8,
        risk_level=RiskLevel.HIGH,
        summary="High risk colorant",
        harm_explanation="Linked to adverse health effects.",
        adi=None,
        data_sources=[],
    )

    mock_score_all_ingredients.return_value = [score_1, score_2]

    report = generate_report(
        ingredients=[ingredient_1, ingredient_2],
        product_name="Test Product",
        image_path="test.jpg",
        raw_ocr_text="Raw OCR text",
    )

    assert report.product_name == "Test Product"
    assert report.image_path == "test.jpg"
    assert report.raw_ocr_text == "Raw OCR text"
    assert report.total_ingredients == 2
    # Overall score = (2 + 8) / 2 = 5.0
    assert report.overall_score == 5.0
    assert report.overall_risk == RiskLevel.MODERATE  # 5 is MODERATE risk
    assert report.high_risk_count == 1
    assert "high-risk ingredient" in report.summary
