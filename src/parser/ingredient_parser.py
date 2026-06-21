"""
LLM-based ingredient parser using Google Gemini.

Takes raw OCR text from a food label and uses Gemini to:
  1. Fix OCR errors and typos
  2. Identify individual ingredients
  3. Return structured JSON with ingredient names, E-numbers, and categories
"""

from __future__ import annotations

import json
import logging

from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE
from src.toxicity.models import FunctionalCategory, Ingredient

logger = logging.getLogger(__name__)

# System prompt that instructs Gemini to parse ingredient text
_PARSING_SYSTEM_PROMPT = """\
You are a food science expert. Your job is to extract a structured list of
individual ingredients from raw OCR text taken from a food product label.

RULES:
1. Fix any obvious OCR errors or typos in ingredient names.
2. Split compound ingredient lists (e.g. "Sugar, Salt, E621" → 3 ingredients).
3. Ignore non-ingredient text like brand names, weight, barcodes, or
   nutritional information.
4. For each ingredient, determine:
   - name: The standardized, correctly-spelled ingredient name.
   - e_number: The E-number code if applicable (e.g. "E621"), or null.
   - category: One of the allowed functional categories.
5. If the text contains NO recognizable ingredients, return an empty list.
6. Return ONLY valid JSON. No markdown fences, no commentary.

ALLOWED CATEGORIES:
- Preservative
- Colorant
- Sweetener
- Emulsifier
- Stabilizer
- Thickener
- Flavor Enhancer
- Acidity Regulator
- Antioxidant
- Raising Agent
- Natural Ingredient
- Other
"""

_PARSING_USER_TEMPLATE = """\
Extract all ingredients from the following raw OCR text from a food product label.

RAW OCR TEXT:
---
{ocr_text}
---

Return a JSON array of objects. Each object must have these fields:
  - "name": string (cleaned ingredient name)
  - "e_number": string or null
  - "category": string (one of the allowed categories)

Example output:
[
  {{"name": "Sugar", "e_number": null, "category": "Natural Ingredient"}},
  {{"name": "Monosodium Glutamate", "e_number": "E621", "category": "Flavor Enhancer"}}
]
"""


def _get_client() -> genai.Client:
    """Create a Gemini client with the configured API key."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )
    return genai.Client(api_key=GEMINI_API_KEY)


def parse_ingredients(ocr_text: str) -> list[Ingredient]:
    """Parse raw OCR text into a structured list of Ingredient objects.

    Args:
        ocr_text: Raw text extracted from a food label by the OCR module.

    Returns:
        List of Ingredient objects with cleaned names, E-numbers, and
        functional categories.

    Raises:
        RuntimeError: If the LLM returns invalid or unparseable output.
    """
    if not ocr_text.strip():
        logger.warning("Empty OCR text provided — returning empty list")
        return []

    client = _get_client()

    user_prompt = _PARSING_USER_TEMPLATE.format(ocr_text=ocr_text)

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_PARSING_SYSTEM_PROMPT,
            temperature=LLM_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )

    raw_output = response.text.strip()
    logger.debug("LLM raw output: %s", raw_output)

    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned invalid JSON: {raw_output[:500]}"
        ) from exc

    if not isinstance(parsed, list):
        raise RuntimeError(
            f"Expected a JSON array, got {type(parsed).__name__}"
        )

    ingredients: list[Ingredient] = []
    for item in parsed:
        if not isinstance(item, dict) or "name" not in item:
            logger.warning("Skipping malformed ingredient entry: %s", item)
            continue

        # Map the category string to the enum (fall back to OTHER)
        cat_str = item.get("category", "Other")
        try:
            category = FunctionalCategory(cat_str)
        except ValueError:
            category = FunctionalCategory.OTHER

        ingredients.append(Ingredient(
            name=item["name"],
            raw_text=item.get("raw_text", ""),
            e_number=item.get("e_number"),
            category=category,
        ))

    logger.info("Parsed %d ingredients from OCR text", len(ingredients))
    return ingredients
