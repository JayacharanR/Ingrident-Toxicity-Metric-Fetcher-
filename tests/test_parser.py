"""
Unit tests for the ingredient parser module.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.parser.ingredient_parser import parse_ingredients
from src.toxicity.models import FunctionalCategory


def test_parse_ingredients_empty():
    """Test that parsing empty OCR text returns an empty list."""
    assert parse_ingredients("") == []
    assert parse_ingredients("   ") == []


@patch("src.parser.ingredient_parser._get_client")
def test_parse_ingredients_success(mock_get_client):
    """Test successful parsing of ingredients with mocked Gemini response."""
    # Mock client and its return structure
    mock_client = MagicMock()
    mock_response = MagicMock()
    # Response contains valid JSON string as requested by response_mime_type="application/json"
    mock_response.text = """
    [
        {"name": "Sugar", "e_number": null, "category": "Natural Ingredient"},
        {"name": "Monosodium Glutamate", "e_number": "E621", "category": "Flavor Enhancer"},
        {"name": "Invalid Category Ingredient", "e_number": "E999", "category": "Super Dangerous"}
    ]
    """
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    ocr_text = "Ingredients: Sugar, Monosodium Glutamate (E621), and something else."
    ingredients = parse_ingredients(ocr_text)

    # We should have parsed 3 ingredients
    assert len(ingredients) == 3

    assert ingredients[0].name == "Sugar"
    assert ingredients[0].e_number is None
    assert ingredients[0].category == FunctionalCategory.NATURAL_INGREDIENT

    assert ingredients[1].name == "Monosodium Glutamate"
    assert ingredients[1].e_number == "E621"
    assert ingredients[1].category == FunctionalCategory.FLAVOR_ENHANCER

    # The third ingredient has an invalid category, which should fall back to OTHER
    assert ingredients[2].name == "Invalid Category Ingredient"
    assert ingredients[2].e_number == "E999"
    assert ingredients[2].category == FunctionalCategory.OTHER


@patch("src.parser.ingredient_parser._get_client")
def test_parse_ingredients_invalid_json(mock_get_client):
    """Test that parser handles invalid JSON output gracefully by raising RuntimeError."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = "This is not JSON text at all"
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    with pytest.raises(RuntimeError) as exc_info:
        parse_ingredients("some text")
    assert "LLM returned invalid JSON" in str(exc_info.value)


@patch("src.parser.ingredient_parser._get_client")
def test_parse_ingredients_not_a_list(mock_get_client):
    """Test that parser handles JSON object instead of array gracefully by raising RuntimeError."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"name": "Sugar"}'  # JSON object instead of a list
    mock_client.models.generate_content.return_value = mock_response
    mock_get_client.return_value = mock_client

    with pytest.raises(RuntimeError) as exc_info:
        parse_ingredients("some text")
    assert "Expected a JSON array" in str(exc_info.value)
