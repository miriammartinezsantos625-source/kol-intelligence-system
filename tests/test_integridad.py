"""
Test de integridad de datos: la caché y el parseo no pueden mentir.

Los tres fallos críticos de la auditoría compartían raíz — el motor confiaba
en que lo que había en disco (o en la respuesta) estaba completo.
"""

import json
import os
import threading

import pytest

from kol_engine import cache_utils, pubmed_agent
from kol_engine.pubmed_agent import RespuestaInvalida, _parse_articles

XML_OK = """<?xml version="1.0"?><PubmedArticleSet>
<PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
<ArticleTitle>Un título</ArticleTitle>
<Journal><Title>Revista</Title></Journal>
</Article></MedlineCitation></PubmedArticle>
</PubmedArticleSet>"""


# ----------------------------------------------------------------------
#  Parseo: 0 papers y "no se pudo leer" son cosas distintas
# ----------------------------------------------------------------------

def test_xml_valido_se_parsea():
    papers = _parse_articles(XML_OK)
    assert len(papers) == 1
    assert papers[0]["pmid"] == "123"


def test_set_vacio_legitimo_devuelve_lista_vacia():
    """Un autor sin papers es un resultado válido, no un error."""
    assert _parse_articles(
        '<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>') == []


def test_xml_truncado_lanza_en_vez_de_devolver_cero():
    """Antes devolvía [] en silencio: el KOL aparecía sin obra publicada."""
    with pytest.raises(RespuestaInvalida):
        _parse_articles(XML_OK[:len(XML_OK) // 2])


def test_xml_vacio_lanza():
    for basura in ("", "   ", "\n"):
        with pytest.raises(RespuestaInvalida):
            _parse_articles(basura)


# ----------------------------------------------------------------------
#  Caché: atómica, y lo incompleto no cuenta
# ----------------------------------------------------------------------

def test_fichero_vacio_es_fallo_de_cache_no_respuesta_valida(tmp_path):
    """'' no es None: pasaba el `is None` y reventaba en json.loads()."""
    f = tmp_path / "c.txt"
    f.write_text("", encoding="utf-8")
    assert cache_utils.read(str(f)) is None

    f.write_text("   \n  ", encoding="utf-8")
    assert cache_utils.read(str(f)) is None


def test_escritura_atomica_sin_lecturas_a_medias(tmp_path):
    """Flask es multihilo: un lector no puede ver el fichero a medio escribir."""
    ruta = str(tmp_path / "c.txt")
    grande = "X" * 400_000
    cache_utils.write(ruta, grande)

    vistos, parar = [], threading.Event()

    def escritor():
        for _ in range(30):
            cache_utils.write(ruta, "Y" * 400_000)
            cache_utils.write(ruta, "X" * 400_000)

    def lector():
        while not parar.is_set():
            c = cache_utils.read(ruta)
            if c is not None:
                vistos.append(len(c))

    t1, t2 = threading.Thread(target=escritor), threading.Thread(target=lector)
    t2.start(); t1.start(); t1.join(); parar.set(); t2.join()

    assert vistos, "el lector no llegó a leer nada"
    assert all(n == 400_000 for n in vistos), \
        f"lecturas truncadas: {sorted(set(n for n in vistos if n != 400_000))[:5]}"


def test_la_escritura_no_deja_temporales(tmp_path):
    ruta = str(tmp_path / "c.txt")
    cache_utils.write(ruta, "hola")
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_un_fallo_a_media_escritura_no_deja_basura(tmp_path, monkeypatch):
    ruta = str(tmp_path / "c.txt")

    def revienta(*a, **kw):
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", revienta)
    with pytest.raises(OSError):
        cache_utils.write(ruta, "contenido")
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_prune_borra_solo_lo_caducado(tmp_path, monkeypatch):
    import time
    monkeypatch.setattr(cache_utils, "CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("KOL_CACHE_TTL_DAYS", "7")

    viejo, nuevo = tmp_path / "v.txt", tmp_path / "n.txt"
    viejo.write_text("x", encoding="utf-8")
    nuevo.write_text("y", encoding="utf-8")
    hace_8_dias = time.time() - 8 * 86400
    os.utime(viejo, (hace_8_dias, hace_8_dias))

    assert cache_utils.prune() == 1
    assert not viejo.exists()
    assert nuevo.exists()


# ----------------------------------------------------------------------
#  Red: reintentar lo que se puede reintentar
# ----------------------------------------------------------------------

def test_reintenta_ante_error_de_red(monkeypatch):
    """Antes solo se reintentaba el 429; un ConnectionError tumbaba el perfil."""
    import requests
    intentos = []

    class RespuestaOk:
        status_code = 200

        def raise_for_status(self):
            return None

    def flaky(metodo, url, **kw):
        intentos.append(1)
        if len(intentos) < 3:
            raise requests.ConnectionError("red inestable")
        return RespuestaOk()

    monkeypatch.setattr(pubmed_agent.requests, "request", flaky)
    monkeypatch.setattr(pubmed_agent, "ESPERA_INICIAL", 0)
    monkeypatch.setattr(pubmed_agent, "_esperar_turno", lambda: None)

    assert pubmed_agent._peticion("GET", "http://x").status_code == 200
    assert len(intentos) == 3


def test_un_400_no_se_reintenta(monkeypatch):
    """Repetir un 400 no lo arregla: fallar rápido con el mensaje real."""
    import requests
    intentos = []

    class Respuesta400:
        status_code = 400

        def raise_for_status(self):
            raise requests.HTTPError("400 Bad Request")

    def siempre400(metodo, url, **kw):
        intentos.append(1)
        return Respuesta400()

    monkeypatch.setattr(pubmed_agent.requests, "request", siempre400)
    monkeypatch.setattr(pubmed_agent, "_esperar_turno", lambda: None)

    with pytest.raises(requests.HTTPError):
        pubmed_agent._peticion("GET", "http://x")
    assert len(intentos) == 1


def test_el_throttling_espacia_las_peticiones(monkeypatch):
    import time
    monkeypatch.setattr(pubmed_agent, "INTERVALO_MIN", 0.05)
    pubmed_agent._ultima_peticion[0] = 0.0

    t0 = time.monotonic()
    for _ in range(4):
        pubmed_agent._esperar_turno()
    assert time.monotonic() - t0 >= 0.10


# ----------------------------------------------------------------------
#  Escritura de entregables (hueco que dejo pasar un NameError)
# ----------------------------------------------------------------------

def _perfil_minimo():
    """Perfil real generado por build_profile, sin red.

    Construirlo con la funcion de produccion (en vez de a mano) garantiza que
    el fixture cumple el contrato completo: si build_profile anade un campo,
    estos tests lo ven en cuanto se ejecutan.
    """
    from kol_engine.profile import build_profile

    analysis = {
        "verified": [], "unverified": [], "excluded": [],
        "log": {"input_count": 0, "verified_count": 0, "unverified_count": 0,
                "excluded_count": 0, "excluded_reasons": {}},
        "pmids_found": [],
        "coverage": {"total_en_pubmed": 0, "analizados": 0,
                     "truncado": False, "tope": 1000},
    }
    strategy = {"query_used": "q", "confidence": "medium", "notes": "",
                "location_terms": ["madrid"], "surname": "Ruiz", "initial": "a"}
    metrics = {"hindex_europepmc": "NOT VERIFIED", "citations": "NOT VERIFIED",
               "epmc_raw_hits": None, "note": ""}

    return build_profile("Ana Ruiz", "Hospital X", "Madrid", "ES", None, None,
                         strategy, analysis, {"trials": None, "log": {}},
                         metrics)


def test_save_profile_escribe_json_legible(tmp_path):
    """Cubre la ruta de guardado: un NameError aquí pasaba desapercibido
    porque ningún test la ejecutaba."""
    from kol_engine.profile import save_profile

    ruta = save_profile(_perfil_minimo(), str(tmp_path))
    assert os.path.exists(ruta)
    recargado = json.loads(open(ruta, encoding="utf-8").read())
    assert recargado["identity"]["full_name"] == "Ana Ruiz"
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_render_dashboard_escribe_html(tmp_path):
    from kol_engine.dashboard import render_dashboard

    ruta = render_dashboard(_perfil_minimo(), str(tmp_path))
    html = open(ruta, encoding="utf-8").read()
    assert "Ana Ruiz" in html
    assert "__KOL_DATA__" not in html          # el placeholder se sustituyó
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []


def test_render_pdf_escribe_pdf_y_no_deja_temporales(tmp_path):
    from kol_engine.pdf import render_pdf

    ruta = render_pdf(_perfil_minimo(), str(tmp_path))
    assert open(ruta, "rb").read(4) == b"%PDF"
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == []
