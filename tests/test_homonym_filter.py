"""
Test del filtrado de homonimos — el corazon del sistema.

Caso real: la KOL es la Dra. Teresa San-Miguel (Valencia, Hospital La Fe,
neuropatologia). Existe un homonimo famoso, el Dr. Jesús F. San-Miguel
(Pamplona, hematologia). El filtro NO debe atribuir a Teresa el trabajo de
Jesús.

Los papers son ficticios (fixtures) para no depender de internet: probamos la
funcion PURA filter_homonyms, que es donde vive toda la logica de decision.

Ejecutar:  cd 02_Motor_KOL && python -m pytest tests/test_homonym_filter.py -v
"""

from kol_engine.pubmed_agent import _surname_coincide, filter_homonyms


def test_apellido_compuesto_exige_todos_los_apellidos():
    # 'Lopez' a secas NO debe contar como 'Martinez Lopez' (evita homónimos).
    assert _surname_coincide("Martinez Lopez", "Martinez Lopez") is True
    assert _surname_coincide("Martinez-Lopez", "Martinez Lopez") is True
    assert _surname_coincide("Lopez", "Martinez Lopez") is False
    assert _surname_coincide("Martinez", "Martinez Lopez") is False
    # Un apellido con guion sigue funcionando.
    assert _surname_coincide("San-Miguel", "San-Miguel") is True

# La KOL objetivo (lo que devolveria disambiguator.build_strategy):
SURNAME = "San-Miguel"
INITIAL = "T"
LOCATION_TERMS = ["valencia", "fe"]   # de 'Valencia' + 'Hospital La Fe'


def _aut(last, initials, aff="", orcid=""):
    return {"last": last, "fore": "", "initials": initials,
            "affiliation": aff, "orcid": orcid}


# --- Fixtures: cada paper reproduce un escenario distinto ---
PAPERS = [
    # 1) Teresa, primera autora, afiliacion Valencia/La Fe -> VERIFICADO
    {"pmid": "1", "title": "Glioblastoma markers", "journal": "Neuropathology",
     "year": "2023", "authors": [
        _aut("San-Miguel", "T", "Hospital Universitari i Politecnic La Fe, Valencia, Spain"),
        _aut("Lopez", "A", "La Fe, Valencia, Spain")]},

    # 2) Jesús F. San-Miguel (Pamplona) -> EXCLUIDO (inicial J != T)
    {"pmid": "2", "title": "Multiple myeloma therapy", "journal": "Blood",
     "year": "2023", "authors": [
        _aut("San-Miguel", "JF", "Clinica Universidad de Navarra, Pamplona, Spain"),
        _aut("Perez", "R", "CUN, Pamplona, Spain")]},

    # 3) Un 'San-Miguel T' pero en Pamplona (colision de inicial)
    #    -> EXCLUIDO por afiliacion, no por inicial
    {"pmid": "3", "title": "Hematologic study", "journal": "Blood",
     "year": "2022", "authors": [
        _aut("San-Miguel", "T", "Clinica Universidad de Navarra, Pamplona, Spain")]},

    # 4) Teresa como ULTIMA autora, sin afiliacion propia, pero un coautor
    #    tiene Valencia -> VERIFICADO por fallback (afiliacion de coautor)
    {"pmid": "4", "title": "Neuro-oncology review", "journal": "J Neurooncol",
     "year": "2024", "authors": [
        _aut("Garcia", "M", "Universitat de Valencia, Valencia, Spain"),
        _aut("San-Miguel", "T", "")]},

    # 5) San-Miguel T sin ninguna afiliacion en el registro
    #    -> SIN_VERIFICAR (probablemente si, pero no confirmable)
    {"pmid": "5", "title": "Case report", "journal": "Rev Esp",
     "year": "2019", "authors": [
        _aut("San-Miguel", "T", "")]},

    # 6) Paper sin ningun San-Miguel -> EXCLUIDO ('sin autor')
    {"pmid": "6", "title": "Unrelated paper", "journal": "PLoS One",
     "year": "2021", "authors": [
        _aut("Garcia", "M", "Valencia, Spain"),
        _aut("Ruiz", "P", "Valencia, Spain")]},
]


def _pmids(lista):
    return {p["pmid"] for p in lista}


def test_teresa_se_conserva_y_jesus_se_excluye():
    """La afirmacion central del brief."""
    res = filter_homonyms(PAPERS, SURNAME, INITIAL, LOCATION_TERMS)

    # Jesús F. San-Miguel (Pamplona, pmid 2) NUNCA debe darse por bueno.
    assert "2" not in _pmids(res["verified"])
    assert "2" not in _pmids(res["unverified"])
    assert "2" in _pmids(res["excluded"])

    # Teresa (Valencia, pmid 1) si.
    assert "1" in _pmids(res["verified"])


def test_clasificacion_completa():
    """Cada paper cae en la categoria esperada."""
    res = filter_homonyms(PAPERS, SURNAME, INITIAL, LOCATION_TERMS)
    assert _pmids(res["verified"]) == {"1", "4"}
    assert _pmids(res["unverified"]) == {"5"}
    assert _pmids(res["excluded"]) == {"2", "3", "6"}


def test_afiliacion_manda_sobre_inicial():
    """Un 'San-Miguel T' en Pamplona (pmid 3) se excluye por afiliacion."""
    res = filter_homonyms(PAPERS, SURNAME, INITIAL, LOCATION_TERMS)
    assert "3" in _pmids(res["excluded"])


def test_fallback_por_coautor_marca_el_motivo():
    """El paper 4 se verifica via la afiliacion de un coautor y se anota."""
    res = filter_homonyms(PAPERS, SURNAME, INITIAL, LOCATION_TERMS)
    paper4 = next(p for p in res["verified"] if p["pmid"] == "4")
    assert paper4["author_position"] == "last"
    assert "co-author" in paper4["_motivo"]


def test_log_cuenta_bien():
    """El log refleja los conteos y las razones de exclusion."""
    res = filter_homonyms(PAPERS, SURNAME, INITIAL, LOCATION_TERMS)
    log = res["log"]
    assert log["input_count"] == 6
    assert log["verified_count"] == 2
    assert log["unverified_count"] == 1
    assert log["excluded_count"] == 3
    # Hay al menos una exclusion por afiliacion y una por 'sin autor'.
    assert sum(log["excluded_reasons"].values()) == 3


def test_orcid_verifica_aunque_falle_la_afiliacion():
    """Si el ORCID del autor coincide, se verifica aunque la afiliacion no."""
    papers = [{"pmid": "9", "title": "x", "journal": "y", "year": "2023",
               "authors": [_aut("San-Miguel", "T",
                                "Somewhere Else, Berlin, Germany",
                                orcid="0000-0001-2345-6789")]}]
    res = filter_homonyms(papers, SURNAME, INITIAL, LOCATION_TERMS,
                          orcid="0000-0001-2345-6789")
    assert "9" in _pmids(res["verified"])
    assert "ORCID" in res["verified"][0]["_motivo"]


# ----------------------------------------------------------------------
#  Coincidencia FUERTE (institucion) vs DEBIL (ciudad)
# ----------------------------------------------------------------------

def test_la_ciudad_sola_no_verifica_un_paper():
    """Caso real: María Blasco (CNIO) arrastraba a otra M. Blasco de Madrid.

    Compartir ciudad no identifica a nadie en una ciudad de tres millones de
    habitantes. Un paper cuya afiliacion solo casa con «madrid» es *probable*,
    no confirmado: va a 'sin verificar', que es exactamente lo que es.
    """
    papers = [{
        "pmid": "1", "title": "Nefrologia", "journal": "J", "year": "2020",
        "authors": [{"last": "Blasco", "initials": "M", "fore": "Maria",
                     "affiliation": "Nephrology Department, Hospital de Madrid",
                     "orcid": ""}],
    }]
    res = filter_homonyms(papers, surname="Blasco", initial="M",
                          location_terms=["cnio", "madrid"],
                          strong_terms=["cnio"])
    assert len(res["verified"]) == 0
    assert len(res["unverified"]) == 1
    assert "only the city" in res["unverified"][0]["_motivo"]


def test_la_institucion_si_verifica():
    papers = [{
        "pmid": "2", "title": "Telomeros", "journal": "J", "year": "2020",
        "authors": [{"last": "Blasco", "initials": "M", "fore": "Maria",
                     "affiliation": "Telomeres Group, CNIO, Madrid",
                     "orcid": ""}],
    }]
    res = filter_homonyms(papers, surname="Blasco", initial="M",
                          location_terms=["cnio", "madrid"],
                          strong_terms=["cnio"])
    assert len(res["verified"]) == 1
    assert "cnio" in res["verified"][0]["_motivo"]


def test_sin_strong_terms_todo_cuenta_como_fuerte():
    """Compatibilidad: si no se pasan terminos fuertes, se comporta como antes."""
    papers = [{
        "pmid": "3", "title": "X", "journal": "J", "year": "2020",
        "authors": [{"last": "Blasco", "initials": "M", "fore": "",
                     "affiliation": "Hospital de Madrid", "orcid": ""}],
    }]
    res = filter_homonyms(papers, surname="Blasco", initial="M",
                          location_terms=["madrid"])
    assert len(res["verified"]) == 1
