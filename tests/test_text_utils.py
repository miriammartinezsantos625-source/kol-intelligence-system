"""
Test de text_utils: normalizacion y comparacion por palabra completa.

Blinda los dos bugs reales que encontramos en la Fase 2:
  - 'fe' NO debe coincidir dentro de 'Tenerife' (comparacion por palabra).
  - 'Valencia,' (con coma) SI debe contar como la palabra 'valencia'
    (normalize quita la puntuacion).
"""

from kol_engine.text_utils import (contains_term, matches_any, normalize,
                                    strip_accents)


def test_strip_accents():
    assert strip_accents("Málaga Peña") == "Malaga Pena"


def test_normalize_quita_puntuacion_y_tildes():
    assert normalize("Valencia, Spain.") == "valencia spain"
    assert normalize("San-Miguel") == "san miguel"
    assert normalize("Málaga.") == "malaga"


def test_contains_term_palabra_completa():
    # El bug de 'Tenerife': 'fe' no debe coincidir dentro.
    assert contains_term("Santa Cruz de Tenerife", "fe") is False
    # Pero 'La Fe' si.
    assert contains_term("Hospital La Fe, Valencia", "fe") is True


def test_contains_term_ignora_puntuacion():
    # El bug de la coma: 'Valencia,' debe contar como 'valencia'.
    assert contains_term("University of Valencia, Valencia, Spain", "valencia")


def test_matches_any_devuelve_el_termino():
    assert matches_any("Hospital La Fe, Valencia", ["madrid", "valencia"]) \
        == "valencia"
    assert matches_any("Hospital de Barcelona", ["madrid", "valencia"]) is None
