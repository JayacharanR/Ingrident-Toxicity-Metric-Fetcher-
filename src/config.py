"""
Configuration module for the Ingredient Toxicity Metric Fetcher.

Loads settings from environment variables and .env files.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


# --- API Keys ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# --- Paths ---
DATA_DIR: Path = _PROJECT_ROOT / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
SAMPLE_IMAGES_DIR: Path = DATA_DIR / "samples"
TOXICITY_DB_PATH: Path = PROCESSED_DATA_DIR / "toxicity.db"

# --- OCR Settings ---
OCR_LANGUAGE: str = "en"
OCR_MIN_CONFIDENCE: float = 0.5  # Minimum confidence to keep a detected text box

# --- LLM Settings ---
GEMINI_MODEL: str = "gemini-2.5-flash"
LLM_TEMPERATURE: float = 0.1  # Low temperature for factual/consistent outputs
LLM_MAX_TOKENS: int = 4096

# --- Toxicity Scoring ---
TOXICITY_SCALE_MIN: int = 1
TOXICITY_SCALE_MAX: int = 10
FUZZY_MATCH_THRESHOLD: int = 80  # Minimum fuzzy match score (0-100) for ingredient lookup


def validate_config() -> list[str]:
    """Validate that required configuration values are set.

    Returns:
        A list of warning/error messages. Empty list means all is well.
    """
    issues: list[str] = []

    if not GEMINI_API_KEY or "your_api_key" in GEMINI_API_KEY.lower() or "your_key" in GEMINI_API_KEY.lower():
        issues.append(
            "GEMINI_API_KEY is set to a placeholder value or not configured. "
            "Please add your actual Gemini API key from https://aistudio.google.com/apikey to the .env file."
        )

    if not TOXICITY_DB_PATH.exists():
        issues.append(
            f"Toxicity database not found at {TOXICITY_DB_PATH}. "
            "Run 'python scripts/build_database.py' to create it."
        )

    return issues
