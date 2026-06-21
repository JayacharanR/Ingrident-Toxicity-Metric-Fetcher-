"""
Unit tests for the SQLite toxicity database interface.
"""

import sqlite3
import pytest

from src.toxicity.database import ToxicityDatabase, _parse_list
from src.toxicity.models import ToxicityData


@pytest.fixture
def temp_db(tmp_path):
    """Fixture to create a temporary SQLite database with mock toxicity data."""
    db_file = tmp_path / "test_toxicity.db"
    conn = sqlite3.connect(str(db_file))

    # Create table
    conn.execute("""
    CREATE TABLE substances (
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
    """)

    # Insert sample data
    conn.execute("""
    INSERT INTO substances (name, e_number, source, adi, noael, safety_opinion, banned_in, known_effects)
    VALUES (
        'Monosodium Glutamate',
        'E621',
        'EFSA',
        '0-30 mg/kg',
        '3200 mg/kg',
        'Safe within limits',
        'None',
        'Headaches|Brain fog'
    );
    """)
    conn.execute("""
    INSERT INTO substances (name, e_number, source, adi, safety_opinion, banned_in, known_effects)
    VALUES (
        'Titanium Dioxide',
        'E171',
        'EFSA',
        'No safe ADI',
        'Banned in EU',
        'EU|France',
        'Genotoxicity|DNA damage'
    );
    """)

    conn.commit()
    conn.close()

    return db_file


def test_parse_list():
    """Test the pipe-delimited string parsing helper."""
    assert _parse_list(None) == []
    assert _parse_list("") == []
    assert _parse_list("  ") == []
    assert _parse_list("EU|France") == ["EU", "France"]
    assert _parse_list("  EU  |  France | ") == ["EU", "France"]


def test_db_lookup_exact(temp_db):
    """Test looking up an existing substance by exact name."""
    db = ToxicityDatabase(temp_db)
    data = db.lookup("Monosodium Glutamate")

    assert data is not None
    assert data.ingredient_name == "Monosodium Glutamate"
    assert data.source == "EFSA"
    assert data.adi == "0-30 mg/kg"
    assert data.noael == "3200 mg/kg"
    assert data.safety_opinion == "Safe within limits"
    assert data.banned_in == ["None"]
    assert data.known_effects == ["Headaches", "Brain fog"]

    db.close()


def test_db_lookup_fuzzy(temp_db):
    """Test looking up an existing substance using fuzzy name matching."""
    db = ToxicityDatabase(temp_db)

    # Typo in name
    data = db.lookup("Monosodum Glutamat")
    assert data is not None
    assert data.ingredient_name == "Monosodium Glutamate"

    # Completely different name should fail lookup
    data_none = db.lookup("Carrot juice")
    assert data_none is None

    db.close()


def test_db_lookup_by_e_number(temp_db):
    """Test looking up a substance by its E-number."""
    db = ToxicityDatabase(temp_db)

    data = db.lookup_by_e_number("E621")
    assert data is not None
    assert data.ingredient_name == "Monosodium Glutamate"

    data_lowercase = db.lookup_by_e_number("e171")
    assert data_lowercase is not None
    assert data_lowercase.ingredient_name == "Titanium Dioxide"

    data_none = db.lookup_by_e_number("E999")
    assert data_none is None

    db.close()


def test_get_all_substances(temp_db):
    """Test retrieving all substance names in the database."""
    db = ToxicityDatabase(temp_db)
    names = db.get_all_substances()
    assert "Monosodium Glutamate" in names
    assert "Titanium Dioxide" in names
    assert len(names) == 2
    db.close()
