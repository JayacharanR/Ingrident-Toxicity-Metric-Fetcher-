"""
CLI entry point for the Ingredient Toxicity Metric Fetcher.

Usage:
    python main.py --image path/to/food_label.jpg
    python main.py --image path/to/food_label.jpg --output report.pdf
    python main.py --image path/to/food_label.jpg --json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from src.config import validate_config
from src.ocr.extractor import TextExtractor
from src.parser.ingredient_parser import parse_ingredients
from src.report.generator import generate_pdf
from src.toxicity.models import RiskLevel
from src.toxicity.scorer import generate_report

# ---------------------------------------------------------------------------
# Color codes for terminal output
# ---------------------------------------------------------------------------

_COLORS = {
    RiskLevel.SAFE:     "\033[92m",   # Green
    RiskLevel.LOW:      "\033[93m",   # Yellow
    RiskLevel.MODERATE: "\033[33m",   # Orange-ish
    RiskLevel.HIGH:     "\033[91m",   # Red
    RiskLevel.CRITICAL: "\033[31;1m", # Bold Red
}
_RESET = "\033[0m"

_RISK_ICONS = {
    RiskLevel.SAFE:     "🟢",
    RiskLevel.LOW:      "🟡",
    RiskLevel.MODERATE: "🟠",
    RiskLevel.HIGH:     "🔴",
    RiskLevel.CRITICAL: "⛔",
}


def main() -> None:
    """Run the full ingredient toxicity analysis pipeline from the CLI."""
    parser = argparse.ArgumentParser(
        description="Analyze food label images for ingredient toxicity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python main.py --image label.jpg
  python main.py --image label.jpg --output report.pdf
  python main.py --image label.jpg --json > results.json
        """,
    )
    parser.add_argument(
        "--image", "-i",
        required=True,
        help="Path to the food label image",
    )
    parser.add_argument(
        "--output", "-o",
        help="Output path for PDF report (optional)",
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON instead of formatted text",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Validate configuration
    issues = validate_config()
    for issue in issues:
        if "GEMINI_API_KEY" in issue:
            print(f"❌ {issue}", file=sys.stderr)
            sys.exit(1)
        else:
            print(f"⚠️  {issue}", file=sys.stderr)

    # --- Stage 1: OCR ---
    print(f"\n📷 Extracting text from: {args.image}")
    extractor = TextExtractor()
    raw_text, confidence = extractor.extract_with_confidence(args.image)

    if not raw_text.strip():
        print("❌ No text could be extracted from the image.", file=sys.stderr)
        sys.exit(1)

    print(f"✅ OCR complete (confidence: {confidence:.1%})")
    print(f"   Raw text preview: {raw_text[:150]}...")

    # --- Stage 2: Parse ingredients ---
    print("\n🧠 Parsing ingredients with AI...")
    ingredients = parse_ingredients(raw_text)

    if not ingredients:
        print("❌ No ingredients could be identified.", file=sys.stderr)
        sys.exit(1)

    print(f"✅ Found {len(ingredients)} ingredients:")
    for ing in ingredients:
        e_tag = f" ({ing.e_number})" if ing.e_number else ""
        print(f"   • {ing.name}{e_tag} [{ing.category.value}]")

    # --- Stages 3 & 4: Lookup + Score ---
    print("\n⚖️  Scoring toxicity for each ingredient...")
    report = generate_report(
        ingredients=ingredients,
        image_path=args.image,
        raw_ocr_text=raw_text,
    )

    # --- Stage 5: Output ---
    if args.json:
        # JSON output
        print(report.model_dump_json(indent=2))
    else:
        # Formatted terminal output
        _print_report(report)

    # Generate PDF if requested
    if args.output:
        print(f"\n📄 Generating PDF report: {args.output}")
        generate_pdf(report, args.output)
        print(f"✅ Report saved to {args.output}")


def _print_report(report) -> None:
    """Pretty-print the toxicity report to the terminal."""
    print("\n" + "=" * 60)
    print("  INGREDIENT TOXICITY REPORT")
    print("=" * 60)

    print(f"\n📦 Product: {report.product_name}")
    print(f"📊 Overall Score: {report.overall_score}/10 ({report.overall_risk.value})")
    print(f"📝 {report.summary}")

    print(f"\n{'─' * 60}")
    print(f"{'Ingredient':<30} {'Score':>5}  {'Risk':<10}")
    print(f"{'─' * 60}")

    for item in report.ingredients:
        color = _COLORS.get(item.risk_level, "")
        icon = _RISK_ICONS.get(item.risk_level, "")
        name = item.ingredient.name[:28]
        print(
            f"  {color}{icon} {name:<28} {item.toxicity_score:>3}/10  "
            f"{item.risk_level.value:<10}{_RESET}"
        )

    print(f"\n{'─' * 60}")
    print("\n📋 DETAILED ANALYSIS:\n")

    for item in report.ingredients:
        color = _COLORS.get(item.risk_level, "")
        icon = _RISK_ICONS.get(item.risk_level, "")
        print(f"{color}{icon} {item.ingredient.name} — {item.toxicity_score}/10 ({item.risk_level.value}){_RESET}")
        print(f"   Summary: {item.summary}")
        print(f"   Details: {item.harm_explanation}")
        if item.adi:
            print(f"   ADI: {item.adi}")
        if item.data_sources:
            print(f"   Sources: {', '.join(item.data_sources)}")
        print()


if __name__ == "__main__":
    main()
