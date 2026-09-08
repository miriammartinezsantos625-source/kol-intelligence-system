"""
Test de robustez: caducidad de cache, nombres de fichero y honestidad del
dossier cuando una fuente falla.

Todos los hallazgos de la auditoria tienen aqui su red de seguridad.
"""

import os
import time

import pytest

from kol_engine import cache_utils
from kol_engine.profile import _slug, build_profile


# ----------------------------------------------------------------------
#  Cache con TTL
# ----------------------------------------------------------------------

def test_entrada_fresca_se_usa(tmp_path, monkeypatch):
    monkeypatch.setenv("KOL_CACHE_TTL_DAYS", "7")
    f = tmp_path / "x.txt"
    f.write_text("datos", encoding="utf-8")
    assert cache_utils.read(str(f)) == "datos"


def test_entrada_caducada_se_ignora(tmp_path, monkeypatch):
    """Sin TTL, regenerar un perfil meses despues devolvia datos viejos
    mientras el pie estampaba la fecha de hoy."""
    monkeypatch.setenv("KOL_CACHE_TTL_DAYS", "7")
    f = tmp_path / "x.txt"
    f.write_text("datos viejos", encoding="utf-8")

    viejo = time.time() - 8 * 86400          # 8 dias > TTL de 7
    os.utime(f, (viejo, viejo))

    assert cache_utils.esta_caducada(str(f)) is True
    assert cache_utils.read(str(f)) is None


def test_ttl_cero_desactiva_la_caducidad(tmp_path, monkeypatch):
    monkeypatch.setenv("KOL_CACHE_TTL_DAYS", "0")
    f = tmp_path / "x.txt"
    f.write_text("datos", encoding="utf-8")
    viejo = time.time() - 3650 * 86400
    os.utime(f, (viejo, viejo))
    assert cache_utils.read(str(f)) == "datos"


def test_ttl_invalido_cae_al_valor_por_defecto(monkeypatch):
    monkeypatch.setenv("KOL_CACHE_TTL_DAYS", "no-es-un-numero")
    assert cache_utils.ttl_segundos() == cache_utils.DEFAULT_TTL_DAYS * 86400


def test_pubmed_usa_la_misma_cache_que_el_resto():
    """pubmed_agent tenia su propia copia de la cache y se saltaba el TTL,
    justo en la fuente de datos principal."""
    from kol_engine import pubmed_agent
    f = pubmed_agent._leer_cache.__doc__ or ""
    assert "cache_utils" in f
    assert pubmed_agent.cache_utils is cache_utils


# ----------------------------------------------------------------------
#  Nombre de fichero estable
# ----------------------------------------------------------------------

@pytest.mark.parametrize("escrito", [
    "ELIAS MARTINEZ LOPEZ",
    "Elías Martínez López",
    "elias martinez lopez",
    "Dr. Elías Martínez López",
])
def test_la_caja_del_nombre_no_duplica_entregables(escrito):
    assert _slug(escrito) == "Elias_Martinez_Lopez"


def test_los_guiones_se_conservan():
    assert _slug("Teresa San-Miguel") == "Teresa_San-Miguel"


# ----------------------------------------------------------------------
#  Honestidad cuando una fuente falla
# ----------------------------------------------------------------------

def _analysis_minimo():
    return {"verified": [], "unverified": [], "excluded": [],
            "log": {"input_count": 0, "verified_count": 0,
                    "unverified_count": 0, "excluded_count": 0,
                    "excluded_reasons": {}},
            "pmids_found": [],
            "coverage": {"total_en_pubmed": 0, "analizados": 0,
                         "truncado": False, "tope": 1000}}


def _metrics():
    return {"hindex_europepmc": "NOT VERIFIED", "citations": "NOT VERIFIED",
            "epmc_raw_hits": None, "note": ""}


def test_cero_ensayos_real_se_declara_valido():
    perfil = build_profile("Ana Ruiz", "Hospital X", "Madrid", "ES", None, None,
                           {"query_used": "q", "confidence": "medium",
                            "notes": "", "location_terms": ["madrid"],
                            "surname": "Ruiz", "initial": "a"},
                           _analysis_minimo(), {"trials": None, "log": {}},
                           _metrics())
    nota = perfil["verification_note"]["trial_note"]
    assert "a valid result" in nota
    assert "NOT CHECKED" not in nota


def test_fallo_de_api_no_se_presenta_como_cero_verificado():
    """El bug mas grave: una caida de red se publicaba como
    '0 ensayos verificados (resultado valido)'."""
    perfil = build_profile("Ana Ruiz", "Hospital X", "Madrid", "ES", None, None,
                           {"query_used": "q", "confidence": "medium",
                            "notes": "", "location_terms": ["madrid"],
                            "surname": "Ruiz", "initial": "a"},
                           _analysis_minimo(),
                           {"trials": None, "log": {}, "error": "timeout"},
                           _metrics())
    nota = perfil["verification_note"]["trial_note"]
    assert "NOT CHECKED" in nota
    assert "a valid result" not in nota
    # y el score no penaliza por algo que no se ha mirado
    assert "trials" in perfil["score"]["excluded"]


def test_el_perfil_publica_la_cobertura():
    perfil = build_profile("Ana Ruiz", "Hospital X", "Madrid", "ES", None, None,
                           {"query_used": "q", "confidence": "medium",
                            "notes": "", "location_terms": ["madrid"],
                            "surname": "Ruiz", "initial": "a"},
                           _analysis_minimo(), {"trials": None, "log": {}},
                           _metrics())
    assert perfil["coverage"]["truncado"] is False
    assert "metrics_verified" in perfil


# ----------------------------------------------------------------------
#  Cobertura: nunca truncar en silencio
# ----------------------------------------------------------------------

def _falso_esearch(total):
    """Simula PubMed: `total` resultados servidos de 200 en 200."""
    def _pagina(query, retstart, retmax, api_key, email, use_cache):
        ids = [str(i) for i in range(retstart, min(retstart + retmax, total))]
        return ids, total
    return _pagina


def test_pagina_hasta_traerse_todo(monkeypatch):
    """Antes se cortaba en 200: un KOL de 674 papers perdia el 70% de su obra
    y su biografia empezaba en el ano equivocado."""
    from kol_engine import pubmed_agent
    monkeypatch.setattr(pubmed_agent, "_esearch_page", _falso_esearch(674))

    pmids, total = pubmed_agent.search_pmids_with_total("q", max_papers=1000)
    assert total == 674
    assert len(pmids) == 674


def test_el_tope_se_respeta_y_se_puede_detectar(monkeypatch):
    from kol_engine import pubmed_agent
    monkeypatch.setattr(pubmed_agent, "_esearch_page", _falso_esearch(5000))

    pmids, total = pubmed_agent.search_pmids_with_total("q", max_papers=1000)
    assert len(pmids) == 1000
    assert total == 5000            # el total REAL sigue siendo visible
    assert len(pmids) < total       # -> truncado


def test_analyze_publica_el_bloque_coverage(monkeypatch):
    from kol_engine import pubmed_agent
    monkeypatch.setattr(pubmed_agent, "_esearch_page", _falso_esearch(5000))
    monkeypatch.setattr(pubmed_agent, "fetch_papers",
                        lambda pmids, **kw: [])

    res = pubmed_agent.analyze(
        {"query_used": "q", "surname": "Ruiz", "initial": "a",
         "location_terms": ["madrid"]}, retmax=1000)

    cov = res["coverage"]
    assert cov["total_en_pubmed"] == 5000
    assert cov["analizados"] == 1000
    assert cov["truncado"] is True


def test_sin_truncamiento_la_bandera_es_falsa(monkeypatch):
    from kol_engine import pubmed_agent
    monkeypatch.setattr(pubmed_agent, "_esearch_page", _falso_esearch(42))
    monkeypatch.setattr(pubmed_agent, "fetch_papers", lambda pmids, **kw: [])

    res = pubmed_agent.analyze(
        {"query_used": "q", "surname": "Ruiz", "initial": "a",
         "location_terms": ["madrid"]}, retmax=1000)
    assert res["coverage"]["truncado"] is False


# ----------------------------------------------------------------------
#  Verificacion: un coautor real no es contaminacion de plantilla
# ----------------------------------------------------------------------

def test_un_coautor_llamado_como_la_blocklist_no_es_fuga(tmp_path):
    """La blocklist lleva «Jesus San Miguel». Si firma como coautor de otro
    hematologo, marcarlo como fuga invalidaria un dossier correcto."""
    from kol_engine.verify import DEFAULT_BLOCKLIST, verify_deliverables

    perfil = {
        "identity": {"full_name": "Ana Ruiz", "badge": {"tier": "Tier 2", "score": 50}},
        "score": {"total": 50, "tier": "Tier 2"},
        "publications": {"items": [{"pmid": "123"}]},
        "perfil_cientifico": {"colaboradores": [{"nombre": "Jesus San Miguel"}]},
        "trials": None,
    }

    html = tmp_path / "d.html"
    html.write_text("<p>Ana Ruiz colabora con Jesus San Miguel</p>", encoding="utf-8")

    class _PdfFalso:
        pages = [object()] * 5

    import kol_engine.verify as v
    original = v._leer_pdf_texto
    v._leer_pdf_texto = lambda ruta: (5, "Ana Ruiz y Jesus San Miguel")
    try:
        informe = verify_deliverables(perfil, str(html), "no-usado.pdf")
    finally:
        v._leer_pdf_texto = original

    fuga = [c for c in informe["checks"] if "previous KOLs" in c["name"]][0]
    assert fuga["passed"], fuga["detail"]
    assert "Jesus San Miguel" in DEFAULT_BLOCKLIST


def test_una_fuga_de_verdad_sigue_detectandose(tmp_path):
    from kol_engine.verify import verify_deliverables

    perfil = {
        "identity": {"full_name": "Ana Ruiz", "badge": {"tier": "Tier 2", "score": 50}},
        "score": {"total": 50, "tier": "Tier 2"},
        "publications": {"items": [{"pmid": "123"}]},
        "perfil_cientifico": {"colaboradores": []},   # NO es coautor suyo
        "trials": None,
    }
    html = tmp_path / "d.html"
    html.write_text("<p>Ana Ruiz</p><p>John Doe</p>", encoding="utf-8")

    import kol_engine.verify as v
    original = v._leer_pdf_texto
    v._leer_pdf_texto = lambda ruta: (5, "Ana Ruiz")
    try:
        informe = verify_deliverables(perfil, str(html), "no-usado.pdf")
    finally:
        v._leer_pdf_texto = original

    fuga = [c for c in informe["checks"] if "previous KOLs" in c["name"]][0]
    assert not fuga["passed"]
    assert "John Doe" in fuga["detail"]
