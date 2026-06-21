"""
Pydantic data models for the toxicity analysis pipeline.

These models define the structured data flowing through every stage of the
pipeline — from raw OCR output to the final scored report.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class RiskLevel(str, Enum):
    """Human-readable risk classification for an ingredient."""
    SAFE = "SAFE"             # Score 1-2
    LOW = "LOW"               # Score 3-4
    MODERATE = "MODERATE"     # Score 5-6
    HIGH = "HIGH"             # Score 7-8
    CRITICAL = "CRITICAL"     # Score 9-10

    @classmethod
    def from_score(cls, score: int) -> RiskLevel:
        """Derive the risk level from a 1-10 toxicity score."""
        if score <= 2:
            return cls.SAFE
        if score <= 4:
            return cls.LOW
        if score <= 6:
            return cls.MODERATE
        if score <= 8:
            return cls.HIGH
        return cls.CRITICAL


class FunctionalCategory(str, Enum):
    """Common functional categories for food additives."""
    PRESERVATIVE = "Preservative"
    COLORANT = "Colorant"
    SWEETENER = "Sweetener"
    EMULSIFIER = "Emulsifier"
    STABILIZER = "Stabilizer"
    THICKENER = "Thickener"
    FLAVOR_ENHANCER = "Flavor Enhancer"
    ACIDITY_REGULATOR = "Acidity Regulator"
    ANTIOXIDANT = "Antioxidant"
    RAISING_AGENT = "Raising Agent"
    NATURAL_INGREDIENT = "Natural Ingredient"
    OTHER = "Other"


# ---------------------------------------------------------------------------
# Pipeline Data Models
# ---------------------------------------------------------------------------

class Ingredient(BaseModel):
    """A single ingredient extracted from a food label."""
    name: str = Field(description="Cleaned, standardized ingredient name")
    raw_text: str = Field(
        default="",
        description="Original OCR text before cleaning",
    )
    e_number: str | None = Field(
        default=None,
        description="E-number if the ingredient is a food additive (e.g. E621)",
    )
    category: FunctionalCategory = Field(
        default=FunctionalCategory.OTHER,
        description="Functional category of the ingredient",
    )


class ToxicityData(BaseModel):
    """Toxicological data retrieved from the knowledge base for one ingredient."""
    ingredient_name: str
    source: str = Field(
        default="Unknown",
        description="Data source (e.g. EFSA, JECFA, FDA GRAS)",
    )
    adi: str | None = Field(
        default=None,
        description="Acceptable Daily Intake (e.g. '0-5 mg/kg bw/day')",
    )
    noael: str | None = Field(
        default=None,
        description="No Observed Adverse Effect Level",
    )
    hazard_class: str | None = Field(
        default=None,
        description="GHS hazard classification if applicable",
    )
    safety_opinion: str | None = Field(
        default=None,
        description="Regulatory safety opinion or GRAS status",
    )
    banned_in: list[str] = Field(
        default_factory=list,
        description="List of countries/regions where this substance is banned",
    )
    known_effects: list[str] = Field(
        default_factory=list,
        description="Known adverse health effects from literature",
    )


class IngredientScore(BaseModel):
    """Complete toxicity assessment for a single ingredient."""
    ingredient: Ingredient
    toxicity_score: int = Field(
        ge=1, le=10,
        description="Toxicity score from 1 (safe) to 10 (critical)",
    )
    risk_level: RiskLevel = Field(
        description="Risk classification derived from the toxicity score",
    )
    summary: str = Field(
        description=(
            "One-sentence summary of the ingredient's safety profile"
        ),
    )
    harm_explanation: str = Field(
        description=(
            "Detailed explanation of why this ingredient is harmful "
            "(or safe), including how much consumption is dangerous "
            "and the biological mechanism"
        ),
    )
    adi: str | None = Field(
        default=None,
        description="Acceptable Daily Intake for reference",
    )
    data_sources: list[str] = Field(
        default_factory=list,
        description="Sources used to derive this score",
    )
    toxicity_data: ToxicityData | None = Field(
        default=None,
        description="Raw toxicity data from the knowledge base",
    )


class ProductReport(BaseModel):
    """Full toxicity report for a food product."""
    product_name: str = Field(
        default="Unknown Product",
        description="Name of the product (if detected)",
    )
    image_path: str = Field(
        default="",
        description="Path to the original image that was analyzed",
    )
    raw_ocr_text: str = Field(
        default="",
        description="Full raw text extracted by OCR",
    )
    ingredients: list[IngredientScore] = Field(
        default_factory=list,
        description="List of scored ingredients",
    )
    overall_score: float = Field(
        default=0.0,
        description="Weighted average toxicity score for the whole product",
    )
    overall_risk: RiskLevel = Field(
        default=RiskLevel.SAFE,
        description="Overall risk level for the product",
    )
    total_ingredients: int = Field(
        default=0,
        description="Total number of ingredients found",
    )
    high_risk_count: int = Field(
        default=0,
        description="Number of ingredients with score >= 7",
    )
    summary: str = Field(
        default="",
        description="Overall product safety summary",
    )

    def compute_aggregates(self) -> None:
        """Recalculate aggregate fields from the ingredient list."""
        if not self.ingredients:
            return

        self.total_ingredients = len(self.ingredients)
        scores = [i.toxicity_score for i in self.ingredients]
        self.overall_score = round(sum(scores) / len(scores), 1)
        self.overall_risk = RiskLevel.from_score(round(self.overall_score))
        self.high_risk_count = sum(1 for s in scores if s >= 7)
