"""
SQLite interface for the toxicity knowledge base.

Provides lookup methods with fuzzy string matching so that minor OCR
errors or spelling differences still find the right substance data.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Any

from thefuzz import fuzz, process

from src.config import FUZZY_MATCH_THRESHOLD, TOXICITY_DB_PATH
from src.toxicity.models import ToxicityData

logger = logging.getLogger(__name__)


class ToxicityDatabase:
    """Interface to the merged toxicity SQLite database.

    The database contains a single ``substances`` table with columns:
      name, e_number, source, adi, noael, hazard_class,
      safety_opinion, banned_in, known_effects

    Usage:
        db = ToxicityDatabase()
        data = db.lookup("Monosodium Glutamate")
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self.db_path = Path(db_path) if db_path else TOXICITY_DB_PATH
        self._conn: sqlite3.Connection | None = None
        self._substance_names: list[str] | None = None

    def _connect(self) -> sqlite3.Connection:
        """Open (or return existing) database connection."""
        if self._conn is None:
            if not self.db_path.exists():
                raise FileNotFoundError(
                    f"Toxicity database not found at {self.db_path}. "
                    "Run 'python scripts/build_database.py' first."
                )
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._substance_names = None

    def _get_all_names(self) -> list[str]:
        """Cache the list of all substance names for fuzzy matching."""
        if self._substance_names is None:
            conn = self._connect()
            cursor = conn.execute("SELECT DISTINCT name FROM substances")
            self._substance_names = [row["name"] for row in cursor.fetchall()]
        return self._substance_names

    def _fuzzy_find(self, name: str) -> str | None:
        """Find the closest matching substance name in the database.

        Args:
            name: The ingredient name to search for.

        Returns:
            The best matching name from the DB, or None if nothing scores
            above the threshold.
        """
        all_names = self._get_all_names()
        if not all_names:
            return None

        # Try exact match first (case-insensitive)
        lower_name = name.lower()
        for db_name in all_names:
            if db_name.lower() == lower_name:
                return db_name

        # Fall back to fuzzy matching
        result = process.extractOne(
            name,
            all_names,
            scorer=fuzz.token_sort_ratio,
        )
        if result and result[1] >= FUZZY_MATCH_THRESHOLD:
            logger.debug(
                "Fuzzy matched '%s' → '%s' (score: %d)",
                name, result[0], result[1],
            )
            return result[0]

        return None

    def lookup(self, ingredient_name: str) -> ToxicityData | None:
        """Look up toxicity data for a single ingredient.

        First attempts an exact match, then falls back to fuzzy matching.

        Args:
            ingredient_name: The cleaned ingredient name.

        Returns:
            ToxicityData if a match is found, else None.
        """
        matched_name = self._fuzzy_find(ingredient_name)
        if matched_name is None:
            logger.info("No DB match for '%s'", ingredient_name)
            return None

        conn = self._connect()
        cursor = conn.execute(
            "SELECT * FROM substances WHERE name = ?",
            (matched_name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return _row_to_toxicity_data(row)

    def lookup_by_e_number(self, e_number: str) -> ToxicityData | None:
        """Look up toxicity data by E-number (e.g. 'E621').

        Args:
            e_number: The E-number string.

        Returns:
            ToxicityData if found, else None.
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT * FROM substances WHERE e_number = ? COLLATE NOCASE",
            (e_number,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return _row_to_toxicity_data(row)

    def lookup_by_fdc_number(self, fdc_number: str) -> ToxicityData | None:
        """Look up toxicity data by FD&C number (e.g. 'FD&C Red 40').

        Performs a case-insensitive search. Also matches partial FD&C
        references like 'Red 40' against stored values like 'FD&C Red 40'.

        Args:
            fdc_number: The FD&C number string.

        Returns:
            ToxicityData if found, else None.
        """
        conn = self._connect()

        # Try exact match first
        cursor = conn.execute(
            "SELECT * FROM substances WHERE fdc_number = ? COLLATE NOCASE",
            (fdc_number,),
        )
        row = cursor.fetchone()
        if row is not None:
            return _row_to_toxicity_data(row)

        # Try matching with "FD&C " prefix
        if not fdc_number.upper().startswith("FD&C"):
            prefixed = f"FD&C {fdc_number}"
            cursor = conn.execute(
                "SELECT * FROM substances WHERE fdc_number = ? COLLATE NOCASE",
                (prefixed,),
            )
            row = cursor.fetchone()
            if row is not None:
                return _row_to_toxicity_data(row)

        return None

    def get_all_substances(self) -> list[str]:
        """Return all substance names in the database."""
        return list(self._get_all_names())

    def get_all_artificial_colours(self) -> list[dict]:
        """Return all artificial colour entries from the database.

        Returns:
            List of dicts with colour metadata (name, e_number, fdc_number, etc).
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT name, e_number, fdc_number, ci_number, colour_shade, "
            "dye_class, southampton_six, fda_phase_out "
            "FROM substances WHERE is_artificial_colour = 1 "
            "ORDER BY name"
        )
        return [dict(row) for row in cursor.fetchall()]


def _safe_get(row: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from a sqlite3.Row, returning default if column missing."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return default


def _row_to_toxicity_data(row: Any) -> ToxicityData:
    """Convert a sqlite3.Row to a ToxicityData object."""
    return ToxicityData(
        ingredient_name=row["name"],
        source=row["source"] or "Unknown",
        adi=row["adi"],
        noael=row["noael"],
        hazard_class=row["hazard_class"],
        safety_opinion=row["safety_opinion"],
        banned_in=_parse_list(row["banned_in"]),
        known_effects=_parse_list(row["known_effects"]),
        is_artificial_colour=bool(_safe_get(row, "is_artificial_colour", 0)),
        fdc_number=_safe_get(row, "fdc_number"),
        ci_number=_safe_get(row, "ci_number"),
        colour_shade=_safe_get(row, "colour_shade"),
        dye_class=_safe_get(row, "dye_class"),
        southampton_six=bool(_safe_get(row, "southampton_six", 0)),
        fda_phase_out=bool(_safe_get(row, "fda_phase_out", 0)),
    )


def _parse_list(value: str | None) -> list[str]:
    """Parse a pipe-delimited string into a list."""
    if not value:
        return []
    return [item.strip() for item in value.split("|") if item.strip()]

