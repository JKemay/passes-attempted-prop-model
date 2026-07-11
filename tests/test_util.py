from passmodel.util import normalize_name


def test_strips_accents_and_case():
    assert normalize_name("Manuel Akanji") == "manuel akanji"
    assert normalize_name("  Rúben  Días ") == "ruben dias"
