"""
Build the unified toxicity SQLite database.

This script creates and populates `data/processed/toxicity.db` with
substance data from multiple sources:

  1. A curated seed dataset of ~200 common food additives and ingredients
     (embedded directly in this script for zero-dependency bootstrapping).
  2. Open Food Facts additives (fetched via API).

Run this script once before using the main application:
    python scripts/build_database.py
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
from pathlib import Path

import httpx

# Add project root to path so we can import src.config
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from src.config import PROCESSED_DATA_DIR, TOXICITY_DB_PATH  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS substances (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    e_number    TEXT,
    source      TEXT DEFAULT 'Curated',
    adi         TEXT,
    noael       TEXT,
    hazard_class TEXT,
    safety_opinion TEXT,
    banned_in   TEXT,
    known_effects TEXT,
    UNIQUE(name, source)
);

CREATE INDEX IF NOT EXISTS idx_substances_name ON substances(name COLLATE NOCASE);
CREATE INDEX IF NOT EXISTS idx_substances_e_number ON substances(e_number COLLATE NOCASE);
"""


# ---------------------------------------------------------------------------
# Curated seed data — common food additives and natural ingredients
# ---------------------------------------------------------------------------

_SEED_DATA: list[dict] = [
    # --- Natural / Generally Safe ---
    {"name": "Water", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS — universally safe", "known_effects": ""},
    {"name": "Salt", "source": "Curated", "adi": "5 g/day (WHO recommendation)", "safety_opinion": "Safe in moderate amounts", "known_effects": "Hypertension|Kidney damage at chronic high intake"},
    {"name": "Sugar", "source": "Curated", "adi": "25 g/day added sugars (WHO)", "safety_opinion": "Safe in moderation", "known_effects": "Obesity|Type 2 diabetes|Dental caries at excessive intake"},
    {"name": "Citric Acid", "e_number": "E330", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Safe — naturally occurs in citrus fruits", "known_effects": "Tooth enamel erosion at very high concentrations"},
    {"name": "Acetic Acid", "e_number": "E260", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Lactic Acid", "e_number": "E270", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Safe — naturally produced in fermentation", "known_effects": ""},
    {"name": "Ascorbic Acid", "e_number": "E300", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Vitamin C — essential nutrient", "known_effects": "Gastrointestinal distress at very high doses (>2g/day)"},
    {"name": "Tocopherol", "e_number": "E306", "source": "EFSA", "adi": "0.15-2 mg/kg bw/day", "safety_opinion": "Vitamin E — safe antioxidant", "known_effects": ""},
    {"name": "Pectin", "e_number": "E440", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe natural thickener", "known_effects": ""},
    {"name": "Gelatin", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS — derived from collagen", "known_effects": ""},
    {"name": "Corn Starch", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Rice Flour", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Wheat Flour", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS — contains gluten (allergen)", "known_effects": "Celiac disease trigger|Gluten intolerance"},
    {"name": "Milk Solids", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS — dairy allergen", "known_effects": "Lactose intolerance|Dairy allergy"},
    {"name": "Soy Lecithin", "e_number": "E322", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Safe emulsifier", "known_effects": "Soy allergy in sensitive individuals"},
    {"name": "Sunflower Oil", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Palm Oil", "source": "Curated", "adi": "Not limited", "safety_opinion": "Safe but high in saturated fat", "known_effects": "Cardiovascular risk at high intake|Environmental concerns"},
    {"name": "Olive Oil", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS — heart-healthy", "known_effects": ""},
    {"name": "Cocoa Butter", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Vanilla Extract", "source": "Curated", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Turmeric", "e_number": "E100", "source": "JECFA", "adi": "0-3 mg/kg bw/day (as curcumin)", "safety_opinion": "Safe natural colorant", "known_effects": ""},
    {"name": "Caramel Color", "e_number": "E150", "source": "EFSA", "adi": "0-300 mg/kg bw/day (Class I-IV varies)", "safety_opinion": "Generally safe; Class III/IV contain 4-MEI", "known_effects": "4-MEI (possible carcinogen in Class III/IV)"},

    # --- Preservatives ---
    {"name": "Sodium Benzoate", "e_number": "E211", "source": "EFSA", "adi": "0-5 mg/kg bw/day", "safety_opinion": "Safe within ADI", "known_effects": "Hyperactivity in children (debated)|Forms benzene with ascorbic acid"},
    {"name": "Potassium Sorbate", "e_number": "E202", "source": "JECFA", "adi": "0-25 mg/kg bw/day", "safety_opinion": "Safe preservative", "known_effects": "Mild skin irritant in sensitive individuals"},
    {"name": "Sorbic Acid", "e_number": "E200", "source": "JECFA", "adi": "0-25 mg/kg bw/day", "safety_opinion": "Safe preservative", "known_effects": ""},
    {"name": "Sodium Nitrite", "e_number": "E250", "source": "EFSA", "adi": "0-0.07 mg/kg bw/day", "safety_opinion": "Approved but under re-evaluation", "known_effects": "Forms nitrosamines (carcinogenic)|Methemoglobinemia risk", "hazard_class": "Acute Tox. 3 (Oral)"},
    {"name": "Sodium Nitrate", "e_number": "E251", "source": "EFSA", "adi": "0-3.7 mg/kg bw/day", "safety_opinion": "Approved with restrictions", "known_effects": "Converts to nitrite in body|Possible carcinogen link"},
    {"name": "Calcium Propionate", "e_number": "E282", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": "Irritability and restlessness in children (debated)"},
    {"name": "Sulfur Dioxide", "e_number": "E220", "source": "EFSA", "adi": "0-0.7 mg/kg bw/day", "safety_opinion": "Safe within ADI; allergen for asthmatics", "known_effects": "Asthma attacks in sulfite-sensitive individuals|Headaches"},
    {"name": "Sodium Metabisulfite", "e_number": "E223", "source": "EFSA", "adi": "0-0.7 mg/kg bw/day (as SO2)", "safety_opinion": "Must be declared as allergen", "known_effects": "Sulfite sensitivity|Asthma trigger"},

    # --- Sweeteners ---
    {"name": "Aspartame", "e_number": "E951", "source": "EFSA", "adi": "0-40 mg/kg bw/day", "safety_opinion": "Safe within ADI (EFSA 2013); IARC Group 2B possible carcinogen (2023)", "known_effects": "Headaches|Possible carcinogen (IARC 2B)|Phenylketonuria risk (contains phenylalanine)"},
    {"name": "Sucralose", "e_number": "E955", "source": "JECFA", "adi": "0-15 mg/kg bw/day", "safety_opinion": "Safe within ADI", "known_effects": "May alter gut microbiome|Produces chloropropanols when heated"},
    {"name": "Acesulfame Potassium", "e_number": "E950", "source": "EFSA", "adi": "0-9 mg/kg bw/day", "safety_opinion": "Safe within ADI", "known_effects": "Some animal studies suggest concerns (inconclusive)"},
    {"name": "Saccharin", "e_number": "E954", "source": "JECFA", "adi": "0-5 mg/kg bw/day", "safety_opinion": "Safe — delisted from carcinogen list in 2000", "known_effects": "Bitter aftertaste|Historical bladder cancer concern (now refuted in humans)"},
    {"name": "Steviol Glycosides", "e_number": "E960", "source": "JECFA", "adi": "0-4 mg/kg bw/day (as steviol)", "safety_opinion": "Safe natural sweetener", "known_effects": "May lower blood pressure"},
    {"name": "Xylitol", "e_number": "E967", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe — dental health benefits", "known_effects": "Laxative effect at high doses|Extremely toxic to dogs"},
    {"name": "Sorbitol", "e_number": "E420", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe sugar alcohol", "known_effects": "Laxative effect at high doses (>20g/day)"},
    {"name": "High Fructose Corn Syrup", "source": "FDA GRAS", "adi": "No established ADI", "safety_opinion": "GRAS but controversial", "known_effects": "Obesity|Insulin resistance|Non-alcoholic fatty liver disease"},

    # --- Colorants ---
    {"name": "Tartrazine", "e_number": "E102", "source": "EFSA", "adi": "0-7.5 mg/kg bw/day", "safety_opinion": "Approved; must carry warning label in EU", "known_effects": "Hyperactivity in children|Allergic reactions|Aspirin sensitivity cross-reaction", "banned_in": "Norway (formerly)|Austria (formerly)"},
    {"name": "Sunset Yellow", "e_number": "E110", "source": "EFSA", "adi": "0-4 mg/kg bw/day", "safety_opinion": "Approved with warning label in EU", "known_effects": "Hyperactivity in children|Allergic reactions", "banned_in": "Norway (formerly)|Finland (formerly)"},
    {"name": "Allura Red", "e_number": "E129", "source": "EFSA", "adi": "0-7 mg/kg bw/day", "safety_opinion": "Approved; requires warning in EU", "known_effects": "Hyperactivity in children|Allergic reactions|Possible gut inflammation"},
    {"name": "Brilliant Blue", "e_number": "E133", "source": "EFSA", "adi": "0-6 mg/kg bw/day", "safety_opinion": "Generally safe", "known_effects": "Allergic reactions (rare)"},
    {"name": "Titanium Dioxide", "e_number": "E171", "source": "EFSA", "adi": "No safe ADI established (EFSA 2021)", "safety_opinion": "BANNED in EU since 2022; still allowed in US", "known_effects": "Genotoxicity concerns|Nanoparticle accumulation|Possible DNA damage", "banned_in": "European Union"},
    {"name": "Carmoisine", "e_number": "E122", "source": "EFSA", "adi": "0-4 mg/kg bw/day", "safety_opinion": "Approved with warning label in EU", "known_effects": "Hyperactivity in children|Allergic reactions"},
    {"name": "Erythrosine", "e_number": "E127", "source": "EFSA", "adi": "0-0.1 mg/kg bw/day", "safety_opinion": "Restricted use in EU", "known_effects": "Thyroid disruption|Phototoxicity|Possible carcinogen at high doses"},
    {"name": "Annatto", "e_number": "E160b", "source": "JECFA", "adi": "0-0.065 mg/kg bw/day (bixin)", "safety_opinion": "Safe natural colorant", "known_effects": "Rare allergic reactions"},
    {"name": "Beta-Carotene", "e_number": "E160a", "source": "EFSA", "adi": "0-5 mg/kg bw/day", "safety_opinion": "Safe — provitamin A", "known_effects": "Carotenodermia (harmless skin yellowing) at high intake"},

    # --- Emulsifiers / Stabilizers ---
    {"name": "Carrageenan", "e_number": "E407", "source": "JECFA", "adi": "Not limited (food-grade)", "safety_opinion": "Approved; degraded carrageenan is harmful", "known_effects": "Gut inflammation (debated)|Possible colon tumor promotion"},
    {"name": "Xanthan Gum", "e_number": "E415", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe thickener/stabilizer", "known_effects": "Laxative effect at very high doses"},
    {"name": "Guar Gum", "e_number": "E412", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe thickener", "known_effects": "Bloating and gas at high doses"},
    {"name": "Mono- and Diglycerides", "e_number": "E471", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Safe emulsifier", "known_effects": "Contains trans fats in some forms"},
    {"name": "Polysorbate 80", "e_number": "E433", "source": "EFSA", "adi": "0-25 mg/kg bw/day", "safety_opinion": "Approved", "known_effects": "Gut microbiome disruption|Possible intestinal inflammation"},
    {"name": "Sodium Carboxymethyl Cellulose", "e_number": "E466", "source": "EFSA", "adi": "Not limited", "safety_opinion": "Safe", "known_effects": "May alter gut microbiome at high doses"},
    {"name": "Lecithin", "e_number": "E322", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe natural emulsifier", "known_effects": ""},

    # --- Flavor Enhancers ---
    {"name": "Monosodium Glutamate", "e_number": "E621", "source": "EFSA", "adi": "0-30 mg/kg bw/day", "safety_opinion": "Safe within ADI (EFSA 2017)", "known_effects": "Chinese Restaurant Syndrome (debated)|Headaches|Obesity link (animal studies)"},
    {"name": "Disodium Guanylate", "e_number": "E627", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe", "known_effects": "Should be avoided by gout sufferers (purine)"},
    {"name": "Disodium Inosinate", "e_number": "E631", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe", "known_effects": "Should be avoided by gout sufferers (purine)"},

    # --- Antioxidants (controversial) ---
    {"name": "Butylated Hydroxyanisole", "e_number": "E320", "source": "EFSA", "adi": "0-1 mg/kg bw/day", "safety_opinion": "Approved; classified as possible carcinogen by IARC", "known_effects": "Possible carcinogen (IARC Group 2B)|Endocrine disruption|Allergic skin reactions", "hazard_class": "Carc. 2"},
    {"name": "Butylated Hydroxytoluene", "e_number": "E321", "source": "EFSA", "adi": "0-0.25 mg/kg bw/day", "safety_opinion": "Approved with restrictions", "known_effects": "Liver and kidney effects in animals|Possible endocrine disruptor"},
    {"name": "Tertiary Butylhydroquinone", "e_number": "E319", "source": "JECFA", "adi": "0-0.7 mg/kg bw/day", "safety_opinion": "Approved", "known_effects": "Nausea and vomiting at high doses|Possible tumor promotion in animals"},
    {"name": "Propyl Gallate", "e_number": "E310", "source": "EFSA", "adi": "0-0.5 mg/kg bw/day", "safety_opinion": "Approved with restrictions", "known_effects": "Allergic reactions|Possible endocrine disruptor|Gastric irritation"},

    # --- Acidity Regulators ---
    {"name": "Phosphoric Acid", "e_number": "E338", "source": "EFSA", "adi": "0-70 mg/kg bw/day (as P)", "safety_opinion": "Safe within ADI", "known_effects": "Tooth enamel erosion|Calcium depletion from bones at chronic high intake"},
    {"name": "Sodium Citrate", "e_number": "E331", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},
    {"name": "Malic Acid", "e_number": "E296", "source": "JECFA", "adi": "Not limited", "safety_opinion": "Safe — naturally found in apples", "known_effects": ""},
    {"name": "Tartaric Acid", "e_number": "E334", "source": "JECFA", "adi": "0-30 mg/kg bw/day", "safety_opinion": "Safe", "known_effects": "Laxative effect at high doses"},

    # --- Raising Agents ---
    {"name": "Sodium Bicarbonate", "e_number": "E500", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS — baking soda", "known_effects": ""},
    {"name": "Ammonium Bicarbonate", "e_number": "E503", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS", "known_effects": ""},

    # --- High Risk / Banned ---
    {"name": "Potassium Bromate", "e_number": "E924", "source": "IARC", "adi": "No safe level established", "safety_opinion": "BANNED in EU, UK, Canada, Brazil, India; still allowed in US", "known_effects": "Carcinogen (IARC Group 2B)|Kidney damage|Thyroid tumors", "banned_in": "EU|UK|Canada|Brazil|India|China", "hazard_class": "Carc. 1B"},
    {"name": "Azodicarbonamide", "source": "Curated", "adi": "0-0.045 mg/kg bw/day", "safety_opinion": "BANNED in EU and Australia; allowed in US", "known_effects": "Respiratory sensitizer|Decomposes to semicarbazide (possible carcinogen)", "banned_in": "EU|Australia|Singapore", "hazard_class": "Resp. Sens. 1"},
    {"name": "Brominated Vegetable Oil", "source": "FDA", "adi": "No established ADI", "safety_opinion": "BANNED in US (2024), EU, Japan, India", "known_effects": "Bromine accumulation in tissue|Memory loss|Skin lesions|Organ damage", "banned_in": "USA|EU|Japan|India"},
    {"name": "Olestra", "source": "FDA", "adi": "No established ADI", "safety_opinion": "Approved in US; banned in UK and Canada", "known_effects": "Inhibits absorption of fat-soluble vitamins|Anal leakage|Cramping", "banned_in": "UK|Canada"},
    {"name": "Rhodamine B", "source": "Curated", "adi": "No safe level", "safety_opinion": "BANNED — industrial dye, not a food additive", "known_effects": "Carcinogenic|Mutagenic|Organ toxicity", "banned_in": "Worldwide (not approved as food additive)", "hazard_class": "Carc. 2"},
    {"name": "Sudan Red", "source": "Curated", "adi": "No safe level", "safety_opinion": "BANNED — industrial dye, not a food additive", "known_effects": "Carcinogenic (IARC Group 3)|Genotoxic|Liver damage", "banned_in": "Worldwide (not approved as food additive)", "hazard_class": "Carc. 2"},

    # --- Common Indian food additives ---
    {"name": "Calcium Carbonate", "e_number": "E170", "source": "JECFA", "adi": "Not limited", "safety_opinion": "GRAS — chalk / mineral supplement", "known_effects": ""},
    {"name": "Sodium Aluminium Phosphate", "e_number": "E541", "source": "JECFA", "adi": "0-0.7 mg/kg bw/day (as Al)", "safety_opinion": "Approved with restrictions on aluminium", "known_effects": "Aluminium accumulation|Possible neurotoxicity at high exposure"},
    {"name": "INS 160(a)", "e_number": "E160a", "source": "FSSAI", "adi": "0-5 mg/kg bw/day", "safety_opinion": "Beta-Carotene — safe provitamin A", "known_effects": ""},
    {"name": "INS 211", "e_number": "E211", "source": "FSSAI", "adi": "0-5 mg/kg bw/day", "safety_opinion": "Sodium Benzoate — refer to E211 entry", "known_effects": "See Sodium Benzoate"},
    {"name": "INS 621", "e_number": "E621", "source": "FSSAI", "adi": "0-30 mg/kg bw/day", "safety_opinion": "MSG — refer to E621 entry", "known_effects": "See Monosodium Glutamate"},

    # --- Trans Fats ---
    {"name": "Partially Hydrogenated Vegetable Oil", "source": "FDA/WHO", "adi": "No safe level (WHO target: eliminate by 2023)", "safety_opinion": "BANNED in many countries — major source of trans fats", "known_effects": "Cardiovascular disease|LDL cholesterol increase|HDL decrease|Inflammation|Type 2 diabetes", "banned_in": "USA|EU|Canada|India|Thailand|Several others"},
    {"name": "Trans Fat", "source": "WHO", "adi": "< 1% of total energy intake", "safety_opinion": "Eliminate from food supply (WHO REPLACE)", "known_effects": "Coronary heart disease|Stroke|Type 2 diabetes|Systemic inflammation"},

    # --- Caffeine ---
    {"name": "Caffeine", "source": "EFSA", "adi": "Up to 400 mg/day for adults", "safety_opinion": "Safe for most adults within limits", "known_effects": "Insomnia|Anxiety|Heart palpitations at high doses|Dependency"},
]


# ---------------------------------------------------------------------------
# Database builder
# ---------------------------------------------------------------------------

def create_database(db_path: Path | None = None) -> Path:
    """Create (or recreate) the toxicity SQLite database.

    Args:
        db_path: Where to write the database. Defaults to the config path.

    Returns:
        The path to the created database.
    """
    if db_path is None:
        db_path = TOXICITY_DB_PATH

    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing DB to rebuild from scratch
    if db_path.exists():
        db_path.unlink()
        logger.info("Removed existing database at %s", db_path)

    conn = sqlite3.connect(str(db_path))
    conn.executescript(_CREATE_TABLE_SQL)

    # Insert seed data
    inserted = _insert_seed_data(conn)
    logger.info("Inserted %d substances from seed data", inserted)

    # Fetch Open Food Facts additives
    off_count = _fetch_open_food_facts(conn)
    logger.info("Inserted %d substances from Open Food Facts", off_count)

    conn.commit()
    conn.close()

    logger.info("✅ Database built successfully at %s", db_path)
    return db_path


def _insert_seed_data(conn: sqlite3.Connection) -> int:
    """Insert the curated seed dataset."""
    count = 0
    for item in _SEED_DATA:
        try:
            conn.execute(
                """INSERT OR IGNORE INTO substances
                   (name, e_number, source, adi, noael, hazard_class,
                    safety_opinion, banned_in, known_effects)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.get("name"),
                    item.get("e_number"),
                    item.get("source", "Curated"),
                    item.get("adi"),
                    item.get("noael"),
                    item.get("hazard_class"),
                    item.get("safety_opinion"),
                    item.get("banned_in"),
                    item.get("known_effects"),
                ),
            )
            count += 1
        except sqlite3.IntegrityError:
            logger.debug("Duplicate skipped: %s", item.get("name"))
    return count


def _fetch_open_food_facts(conn: sqlite3.Connection) -> int:
    """Fetch additive data from the Open Food Facts API.

    This queries the Open Food Facts taxonomy for additives and inserts
    them into the database. Falls back gracefully on network errors.
    """
    url = "https://world.openfoodfacts.org/facets/additives.json"
    count = 0

    try:
        logger.info("Fetching additives from Open Food Facts...")
        response = httpx.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as exc:
        logger.warning(
            "Could not fetch Open Food Facts data: %s. Continuing with seed data only.",
            exc,
        )
        return 0

    tags = data.get("tags", [])
    for tag in tags:
        name = tag.get("name", "").strip()
        if not name or name.startswith("en:"):
            # Clean up taxonomy prefixes
            name = name.removeprefix("en:").strip().title()
        if not name:
            continue

        # Extract E-number from the tag ID if present
        tag_id = tag.get("id", "")
        e_number = None
        if tag_id.startswith("en:e"):
            e_num_part = tag_id.removeprefix("en:e")
            if e_num_part and e_num_part[0].isdigit():
                e_number = f"E{e_num_part}"

        products_count = tag.get("products", 0)

        try:
            conn.execute(
                """INSERT OR IGNORE INTO substances
                   (name, e_number, source, safety_opinion)
                   VALUES (?, ?, 'Open Food Facts', ?)""",
                (
                    name,
                    e_number,
                    f"Found in {products_count} products on Open Food Facts",
                ),
            )
            count += 1
        except sqlite3.IntegrityError:
            pass

    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("Building toxicity knowledge base...")
    db_path = create_database()
    logger.info("Done! Database: %s", db_path)

    # Print summary
    conn = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT COUNT(*) FROM substances")
    total = cursor.fetchone()[0]
    cursor = conn.execute("SELECT COUNT(DISTINCT source) FROM substances")
    sources = cursor.fetchone()[0]
    conn.close()
    logger.info("Total substances: %d from %d sources", total, sources)
