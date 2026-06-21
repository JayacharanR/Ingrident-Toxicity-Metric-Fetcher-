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

_BATCH_SCORING_SYSTEM_PROMPT = """\
You are a toxicology and food safety expert. Your job is to evaluate a list of food
ingredients and assign a TOXICITY SCORE to each on a scale of 1 to 10.

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
1. For each ingredient in the list, consider the database context provided (if any).
2. If no database data is available, use your scientific knowledge.
3. Assign the score conservatively — when in doubt, rate slightly higher.
4. Write a concise one-sentence summary of the ingredient's safety.
5. Write a detailed harm_explanation (2-4 sentences) covering:
   - Whether and why it's harmful
   - How much consumption is actually dangerous
   - The biological mechanism of harm (if applicable)
6. Return a JSON array of objects, one for each ingredient, in the exact same order.
7. Return ONLY valid JSON. No markdown fences, no commentary.
"""

_BATCH_SCORING_USER_TEMPLATE = """\
Evaluate the following food ingredients for human consumption toxicity:

INGREDIENTS TO EVALUATE:
---
{ingredients_list}
---

Return a JSON array of objects. Each object must correspond to the ingredient in the list in the same order, and have these exact fields:
[
  {{
    "toxicity_score": <integer 1-10>,
    "summary": "<one-sentence safety summary>",
    "harm_explanation": "<2-4 sentence explanation of harm/safety>"
  }}
]
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


def _score_all_ingredients_batch(
    ingredients: list[Ingredient],
    db_contexts: list[str],
    toxicity_datas: list[ToxicityData | None],
) -> list[IngredientScore] | None:
    """Attempt to score all ingredients in a single batch LLM call."""
    if not ingredients:
        return []

    client = _get_client()

    # Format the user prompt
    items = []
    for i, ing in enumerate(ingredients):
        e_str = f" (E-number: {ing.e_number})" if ing.e_number else ""
        ctx = db_contexts[i]
        items.append(
            f"Ingredient [{i + 1}]:\n"
            f"  Name: {ing.name}{e_str}\n"
            f"  Category: {ing.category.value}\n"
            f"  {ctx}\n"
        )
    ingredients_list = "\n".join(items)

    user_prompt = _BATCH_SCORING_USER_TEMPLATE.format(ingredients_list=ingredients_list)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=_BATCH_SCORING_SYSTEM_PROMPT,
                temperature=LLM_TEMPERATURE,
                response_mime_type="application/json",
            ),
        )
        
        raw = response.text.strip()
        logger.debug("Batch scoring LLM output: %s", raw)
        
        parsed = json.loads(raw)
        if not isinstance(parsed, list) or len(parsed) != len(ingredients):
            logger.warning("Batch scoring output length mismatch or not a list, falling back to individual scoring")
            return None
            
        scores = []
        for i, item_data in enumerate(parsed):
            ing = ingredients[i]
            tox_data = toxicity_datas[i]
            
            score_val = int(item_data.get("toxicity_score", 5))
            score_val = max(1, min(10, score_val))
            
            data_sources = []
            if tox_data:
                data_sources.append(tox_data.source)
                
            scores.append(IngredientScore(
                ingredient=ing,
                toxicity_score=score_val,
                risk_level=RiskLevel.from_score(score_val),
                summary=item_data.get("summary", "No summary available."),
                harm_explanation=item_data.get("harm_explanation", "No explanation available."),
                adi=tox_data.adi if tox_data else None,
                data_sources=data_sources,
                toxicity_data=tox_data,
            ))
            
        return scores
        
    except Exception as exc:
        logger.warning("Batch scoring failed: %s. Falling back to individual scoring.", exc)
        return None


def score_all_ingredients(
    ingredients: list[Ingredient],
    db: ToxicityDatabase | None = None,
) -> list[IngredientScore]:
    """Score a list of ingredients.

    Attempts to score all ingredients in a single batch call to respect rate limits.
    If the batch call fails, falls back to scoring ingredients one-by-one with
    a rate-limit-friendly delay.

    Args:
        ingredients: List of parsed ingredients.
        db: Optional ToxicityDatabase instance.

    Returns:
        List of IngredientScore objects.
    """
    if db is None:
        db = ToxicityDatabase()

    # Pre-fetch database context for all ingredients
    toxicity_datas = []
    db_contexts = []
    for ingredient in ingredients:
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
        
        toxicity_datas.append(toxicity_data)
        db_contexts.append(_format_db_context(toxicity_data))

    # Try batch scoring first
    logger.info("Attempting batch scoring for %d ingredients using %s...", len(ingredients), GEMINI_MODEL)
    scores = _score_all_ingredients_batch(ingredients, db_contexts, toxicity_datas)
    if scores is not None:
        logger.info("Batch scoring succeeded!")
        return scores

    # Fallback to individual scoring
    logger.info("Falling back to individual scoring with rate limit delays...")
    import time
    scores = []
    for i, ingredient in enumerate(ingredients):
        if i > 0:
            logger.info("Waiting 4.0 seconds to respect rate limits...")
            time.sleep(4.0)
            
        logger.info("Scoring ingredient [%d/%d]: %s", i + 1, len(ingredients), ingredient.name)
        score = score_ingredient(ingredient, toxicity_datas[i])
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
