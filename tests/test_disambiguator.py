"""
Test del disambiguator: parseo de nombres, construccion de query y confianza.

Ejecutar:  cd 02_Motor_KOL && python -m pytest tests/test_disambiguator.py -v
"""

from kol_engine.disambiguator import parse_name, build_strategy


def test_parse_name_quita_titulo_y_saca_inicial():
    assert parse_name("Dra. Teresa San-Miguel") == ("San-Miguel", "T")
    assert parse_name("Jesús F. San-Miguel") == ("San-Miguel", "J")
    assert parse_name("Prof. Ana López") == ("López", "A")


def test_parse_name_apellidos_compuestos_espanoles():
    # Caso real que fallaba: tomaba solo 'Lopez' e ignoraba 'Martinez'.
    assert parse_name("Elias Martinez Lopez") == ("Martinez Lopez", "E")
    assert parse_name("Dr. Josep Tabernero Caturla") == ("Tabernero Caturla", "J")


def test_query_busca_apellido_compuesto():
    s = build_strategy("Elias Martinez Lopez", institution="Hospital Peset",
                       city="Valencia")
    assert "Martinez Lopez E[Author]" in s["query_used"]
    assert "Martinez-Lopez E[Author]" in s["query_used"]


def test_la_query_de_autor_va_sin_comillas():
    """Sin comillas, PubMed trunca las iniciales; con comillas, exige exactitud.

    Caso real: Juan Manuel Sepulveda Sanchez esta indexado como
    'Sepulveda-Sanchez JM'. Entrecomillado, 'Sepulveda-Sanchez J'[Author]
    devolvia 2 papers de los 64 suyos — perdiamos al KOL entero. Sin comillas
    PubMed casa 'J' con 'JM' y aparecen todos.
    """
    s = build_strategy("Juan Manuel Sepulveda Sanchez",
                       institution="Hospital 12 de Octubre")
    assert '"' not in s["query_used"].split(" AND ")[0]
    assert "Sepulveda-Sanchez J[Author]" in s["query_used"]


def test_la_ciudad_no_basta_para_verificar():
    """La ciudad amplia la busqueda, pero no confirma la identidad.

    'Madrid' en una afiliacion no distingue a nadie; 'CNIO' si. Por eso la
    ciudad entra en location_terms (para no perder papers) pero NO en
    strong_terms (para no dar por verificado a un homonimo de la misma ciudad).
    """
    s = build_strategy("Maria Blasco", institution="CNIO", city="Madrid")
    assert "madrid" in s["location_terms"]
    assert "madrid" not in s["strong_terms"]
    assert "cnio" in s["strong_terms"]


def test_sin_institucion_la_ciudad_si_verifica():
    """Si es lo unico que hay, la ciudad vale — con su confianza baja."""
    s = build_strategy("Maria Blasco", city="Madrid")
    assert s["strong_terms"] == ["madrid"]


def test_apellido_explicito_tiene_prioridad():
    # Nombre de pila compuesto ambiguo -> se pasa el apellido a mano.
    s = build_strategy("Maria Teresa Garcia", surname="Garcia",
                       institution="Hospital", city="Madrid")
    assert s["surname"] == "Garcia"


def test_doctor_no_es_termino_de_localizacion():
    s = build_strategy("Elias Martinez Lopez",
                       institution="Hospital Doctor Peset", city="Valencia")
    assert "doctor" not in s["location_terms"]
    assert "peset" in s["location_terms"]


def test_orcid_da_confianza_alta():
    s = build_strategy("Dra. Teresa San-Miguel", institution="Hospital La Fe",
                       city="Valencia", orcid="0000-0001-2345-6789")
    assert s["confidence"] == "alta"
    assert "[auid]" in s["query_used"]


def test_afiliacion_da_confianza_media():
    s = build_strategy("Dra. Teresa San-Miguel", institution="Hospital La Fe",
                       city="Valencia")
    assert s["confidence"] == "media"
    assert "[Author]" in s["query_used"]
    assert "[Affiliation]" in s["query_used"]


def test_solo_nombre_da_confianza_baja():
    s = build_strategy("Teresa San-Miguel")
    assert s["confidence"] == "baja"


def test_query_sin_tildes():
    """Regla dura: las queries a PubMed van SIN tildes."""
    s = build_strategy("Prof. Ana Peña", institution="Hospital", city="Málaga")
    assert "ñ" not in s["query_used"]
    assert "á" not in s["query_used"]
    assert "Pena" in s["query_used"]      # Peña -> Pena
    assert "malaga" in s["query_used"]    # Málaga -> malaga (en [Affiliation])


def test_location_terms_descartan_genericos():
    s = build_strategy("Dra. Teresa San-Miguel",
                       institution="Hospital Universitari i Politècnic La Fe",
                       city="Valencia")
    assert "valencia" in s["location_terms"]
    assert "fe" in s["location_terms"]
    # Palabras genericas NO deben usarse para verificar afiliacion.
    assert "hospital" not in s["location_terms"]
    assert "la" not in s["location_terms"]
