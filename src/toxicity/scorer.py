"""
Toxicity scoring engine.

Combines database lookups with LLM reasoning to assign a 1-10 toxicity
score and generate human-readable harm explanations for each ingredient.
"""

from __future__ import annotations

import json
import logging

from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODEL, LLM_TEMPERATURE
from src.toxicity.database import ToxicityDatabase
from src.toxicity.models import (
    Ingredient,
    IngredientScore,
    ProductReport,
    RiskLevel,
    ToxicityData,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring system prompt
# ---------------------------------------------------------------------------

_SCORING_SYSTEM_PROMPT = """\
You are a toxicology and food safety expert. Your job is to evaluate a food
ingredient and assign a TOXICITY SCORE on a scale of 1 to 10.

SCORING CRITERIA:
  1-2  (SAFE):      Natural, widely consumed, no known adverse effects.
                     Examples: Water, Salt (in normal qty), Citric Acid.
  3-4  (LOW RISK):  Generally safe, minor concerns only at very high doses.
                     Examples: Sodium Benzoate, Sorbic Acid.
  5-6  (MODERATE):  Some studies show adverse effects; ADI can be exceeded
                     with regular consumption. Examples: Aspartame, MSG.
  7-8  (HIGH RISK): Banned in some countries or linked to health issues in
                     multiple studies. Examples: Tartrazine, BHA, BHT.
  9-10 (CRITICAL):  Banned substances, known carcinogens, or potent toxins.
                     Examples: Trans fats, certain azo dyes, lead contamination.

INSTRUCTIONS:
1. Consider the toxicity data provided (ADI, NOAEL, bans, known effects).
2. If no database data is available, use your scientific knowledge.
3. Assign the score conservatively — when in doubt, rate slightly higher.
4. Write a concise one-sentence summary of the ingredient's safety.
5. Write a detailed harm_explanation (2-4 sentences) covering:
   - Whether and why it's harmful
   - How much consumption is actually dangerous
   - The biological mechanism of harm (if applicable)
6. Return ONLY valid JSON. No markdown fences, no commentary.
"""

_SCORING_USER_TEMPLATE = """\
Evaluate the following food ingredient for human consumption toxicity.

INGREDIENT: {name}
{e_number_line}
CATEGORY: {category}

{db_context}

Return a JSON object with these exact fields:
{{
  "toxicity_score": <integer 1-10>,
  "summary": "<one-sentence safety summary>",
  "harm_explanation": "<2-4 sentence explanation of harm/safety>"
}}
"""


def _format_db_context(data: ToxicityData | None) -> str:
    """Format database toxicity data as context for the LLM prompt."""
    if data is None:
        return "DATABASE CONTEXT: No data found in the toxicity database for this ingredient."

    parts = [f"DATABASE CONTEXT (Source: {data.source}):"]
    if data.adi:
        parts.append(f"  - Acceptable Daily Intake (ADI): {data.adi}")
    if data.noael:
        parts.append(f"  - NOAEL: {data.noael}")
    if data.hazard_class:
        parts.append(f"  - GHS Hazard Classification: {data.hazard_class}")
    if data.safety_opinion:
        parts.append(f"  - Safety Opinion: {data.safety_opinion}")
    if data.banned_in:
        parts.append(f"  - Banned In: {', '.join(data.banned_in)}")
    if data.known_effects:
        parts.append(f"  - Known Adverse Effects: {', '.join(data.known_effects)}")

    return "\n".join(parts)


def _get_client() -> genai.Client:
    """Create a Gemini client."""
    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Add it to your .env file."
        )
    return genai.Client(api_key=GEMINI_API_KEY)


def score_ingredient(
    ingredient: Ingredient,
    toxicity_data: ToxicityData | None = None,
) -> IngredientScore:
    """Score a single ingredient for toxicity using LLM + DB context.

    Args:
        ingredient: The parsed Ingredient object.
        toxicity_data: Optional pre-fetched toxicity data from the DB.

    Returns:
        An IngredientScore with the toxicity rating and explanations.
    """
    client = _get_client()

    e_number_line = (
        f"E-NUMBER: {ingredient.e_number}" if ingredient.e_number else ""
    )
    db_context = _format_db_context(toxicity_data)

    user_prompt = _SCORING_USER_TEMPLATE.format(
        name=ingredient.name,
        e_number_line=e_number_line,
        category=ingredient.category.value,
        db_context=db_context,
    )

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_prompt,
        config=types.GenerateContentConfig(
            system_instruction=_SCORING_SYSTEM_PROMPT,
            temperature=LLM_TEMPERATURE,
            response_mime_type="application/json",
        ),
    )

    raw = response.text.strip()
    logger.debug("Scoring LLM output for '%s': %s", ingredient.name, raw)

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"LLM returned invalid JSON for '{ingredient.name}': {raw[:500]}"
        ) from exc

    score = int(result.get("toxicity_score", 5))
    score = max(1, min(10, score))  # Clamp to valid range

    data_sources = []
    if toxicity_data:
        data_sources.append(toxicity_data.source)

    return IngredientScore(
        ingredient=ingredient,
        toxicity_score=score,
        risk_level=RiskLevel.from_score(score),
        summary=result.get("summary", "No summary available."),
        harm_explanation=result.get("harm_explanation", "No explanation available."),
        adi=toxicity_data.adi if toxicity_data else None,
        data_sources=data_sources,
        toxicity_data=toxicity_data,
    )


def score_all_ingredients(
    ingredients: list[Ingredient],
    db: ToxicityDatabase | None = None,
) -> list[IngredientScore]:
    """Score a list of ingredients.

    For each ingredient, looks up toxicity data in the DB (if available)
    and then calls the LLM scorer.

    Args:
        ingredients: List of parsed ingredients.
        db: Optional ToxicityDatabase instance. If None, a new one is created.

    Returns:
        List of IngredientScore objects, one per ingredient.
    """
    if db is None:
        db = ToxicityDatabase()

    scores: list[IngredientScore] = []

    for ingredient in ingredients:
        logger.info("Scoring ingredient: %s", ingredient.name)

        # Look up by E-number first, then by name
        toxicity_data = None
        try:
            if ingredient.e_number:
                toxicity_data = db.lookup_by_e_number(ingredient.e_number)
            if toxicity_data is None:
                toxicity_data = db.lookup(ingredient.name)
        except FileNotFoundError:
            logger.warning(
                "Toxicity database not found — scoring without DB context"
            )

        score = score_ingredient(ingredient, toxicity_data)
        scores.append(score)

    return scores


def generate_report(
    ingredients: list[Ingredient],
    image_path: str = "",
    product_name: str = "Unknown Product",
    raw_ocr_text: str = "",
) -> ProductReport:
    """Run the full scoring pipeline and produce a ProductReport.

    Args:
        ingredients: List of parsed Ingredient objects.
        image_path: Path to the original image.
        product_name: Detected or user-provided product name.
        raw_ocr_text: Raw OCR text for reference.

    Returns:
        A complete ProductReport with scored ingredients and aggregates.
    """
    scored = score_all_ingredients(ingredients)

    report = ProductReport(
        product_name=product_name,
        image_path=image_path,
        raw_ocr_text=raw_ocr_text,
        ingredients=scored,
    )
    report.compute_aggregates()

    # Generate overall summary
    if report.high_risk_count > 0:
        report.summary = (
            f"⚠️ This product contains {report.high_risk_count} high-risk "
            f"ingredient(s) out of {report.total_ingredients} total. "
            f"Overall toxicity score: {report.overall_score}/10 "
            f"({report.overall_risk.value}). Review the detailed breakdown below."
        )
    else:
        report.summary = (
            f"✅ This product's {report.total_ingredients} ingredients score "
            f"an average of {report.overall_score}/10 ({report.overall_risk.value}). "
            "No high-risk ingredients were detected."
        )

    return report
