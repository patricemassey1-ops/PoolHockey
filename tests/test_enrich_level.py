# tests/test_enrich_level.py
import pandas as pd
import pytest

from pms_enrich import enrich_level_from_players_db


def _db():
    return pd.DataFrame(
        [
            {"Player": "Connor McDavid", "Level": "STD", "Expiry Year": 2031},
            {"Player": "Smith, John", "Level": "ELC", "Expiry Year": 2027},
            {"Player": "Alexis Lafrenière", "Level": "STD", "Expiry Year": 2028},
            {"Player": "Bad Exp", "Level": "STD", "Expiry Year": ""},  # vide
        ]
    )


def test_fills_level_and_expiry_for_simple_name():
    df = pd.DataFrame([{"Joueur": "Connor McDavid"}])
    out = enrich_level_from_players_db(df, _db())
    assert out.loc[0, "Level"] == "STD"
    assert out.loc[0, "Expiry Year"] == "2031"


def test_matches_last_first_to_first_last():
    df = pd.DataFrame([{"Joueur": "John Smith"}])
    out = enrich_level_from_players_db(df, _db())
    assert out.loc[0, "Level"] == "ELC"
    assert out.loc[0, "Expiry Year"] == "2027"


def test_handles_accents():
    df = pd.DataFrame([{"Joueur": "Alexis Lafreniere"}])  # sans accent
    out = enrich_level_from_players_db(df, _db())
    assert out.loc[0, "Level"] == "STD"
    assert out.loc[0, "Expiry Year"] == "2028"


def test_does_not_overwrite_valid_existing_level():
    df = pd.DataFrame([{"Joueur": "Connor McDavid", "Level": "ELC"}])  # déjà valide
    out = enrich_level_from_players_db(df, _db())
    assert out.loc[0, "Level"] == "ELC"  # inchangé


def test_never_crashes_on_nan_or_empty_expiry():
    df = pd.DataFrame([{"Joueur": "Bad Exp"}])
    out = enrich_level_from_players_db(df, _db())
    assert out.loc[0, "Level"] == "STD"
    assert out.loc[0, "Expiry Year"] in ("", "nan")


def test_when_player_not_found_outputs_blank_fields():
    df = pd.DataFrame([{"Joueur": "Unknown Player"}])
    out = enrich_level_from_players_db(df, _db())
    assert str(out.loc[0, "Level"]).strip().lower() in ("", "nan")
    assert str(out.loc[0, "Expiry Year"]).strip().lower() in ("", "nan")


def test_strict_all_rows_have_level_std_or_elc_when_matchable():
    """
    Test strict (utile en prod): si la DB contient une entrée matchable,
    on exige Level ∈ {STD, ELC}. Sinon, on tolère vide.
    """
    db = _db()
    df = pd.DataFrame(
        [
            {"Joueur": "Connor McDavid"},
            {"Joueur": "John Smith"},
            {"Joueur": "Unknown Player"},
        ]
    )
    out = enrich_level_from_players_db(df, db)

    # 2 joueurs matchables doivent être STD/ELC
    assert out.loc[0, "Level"] in ("STD", "ELC")
    assert out.loc[1, "Level"] in ("STD", "ELC")
    # celui non matché peut rester vide
    assert str(out.loc[2, "Level"]).strip().upper() in ("", "STD", "ELC")


@pytest.mark.parametrize(
    "name",
    [
        "Smith, John",
        "John Smith",
        "John   Smith",
        "John-Smith",
        "John.Smith",
    ],
)
def test_name_normalization_variants(name):
    db = _db()
    df = pd.DataFrame([{"Joueur": name}])
    out = enrich_level_from_players_db(df, db)
    # selon la variante, le match doit fonctionner
    assert out.loc[0, "Level"] == "ELC"
