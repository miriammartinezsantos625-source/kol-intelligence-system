"""
europepmc_agent — metricas academicas (h-index, citas).

REGLA DURA: h-index y citas de Europe PMC SIEMPRE se marcan 'NO VERIFICADO'.
Europe PMC no desambigua homonimos, asi que sus agregados mezclan a personas
distintas con el mismo nombre y no son fiables para un KOL concreto.

Las metricas fiables (nº papers, journals, posicion de autoria, actividad
reciente) se calculan del set YA filtrado de PubMed, en profile.py — no aqui.

Este modulo consulta Europe PMC solo para dejar constancia del volumen bruto
(cuantos hits devuelve el nombre), pero SIEMPRE etiquetado como no verificado.
"""

import json

import requests

from . import cache_utils

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
TIMEOUT = 30

NO_VERIFICADO = "NO VERIFICADO"


def get_metrics(full_name, use_cache=True):
    """Devuelve el bloque metrics_unverified del contrato.

    Nunca lanza excepcion hacia arriba: si Europe PMC falla, devuelve el
    bloque igualmente (con las metricas NO VERIFICADO), porque son opcionales.
    """
    bloque = {
        "hindex_europepmc": NO_VERIFICADO,
        "citations": NO_VERIFICADO,
        "epmc_raw_hits": None,
        "note": ("Europe PMC no desambigua homónimos; sus métricas agregadas "
                 "no son atribuibles a un KOL concreto. Cifras fiables: ver el "
                 "bloque de publicaciones (set filtrado de PubMed)."),
    }
    try:
        # Quita titulos simples para el nombre de autor.
        limpio = full_name.replace("Dra.", "").replace("Dr.", "").strip()
        query = f'AUTH:"{limpio}"'
        clave = f"epmc|{query}"
        ruta = cache_utils.cache_path("epmc", clave)
        crudo = cache_utils.read(ruta, use_cache)
        if crudo is None:
            params = {"query": query, "format": "json", "pageSize": 1}
            r = requests.get(EPMC, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            crudo = r.text
            cache_utils.write(ruta, crudo)
        datos = json.loads(crudo)
        bloque["epmc_raw_hits"] = datos.get("hitCount")
    except Exception:
        pass  # las metricas son opcionales; no rompemos el pipeline
    return bloque


# ======================================================================
#  METRICAS VERIFICADAS — h-index sobre el set YA desambiguado
# ======================================================================
#
# Lo de arriba (get_metrics) sigue siendo NO VERIFICADO y debe seguir siendolo:
# es el agregado que Europe PMC calcula por nombre de autor, mezclando
# homonimos.
#
# Lo de aqui es distinto: pedimos las citas paper a paper para los PMIDs que el
# filtro de homonimos YA ha atribuido a este medico, y calculamos el h-index
# nosotros. Al estar acotado al set desambiguado, el numero SI es atribuible —
# de hecho es mas riguroso que el de Scopus o Web of Science, que no filtran
# homonimos.

LOTE_CITAS = 50


def _citas_de_lote(pmids, use_cache=True):
    """Citas por paper de un lote de PMIDs. Devuelve {pmid: citedByCount}."""
    query = " OR ".join(f"EXT_ID:{p}" for p in pmids)
    clave = f"epmc_cites|{query}"
    ruta = cache_utils.cache_path("epmccit", clave)
    crudo = cache_utils.read(ruta, use_cache)
    if crudo is None:
        params = {"query": query, "format": "json", "resultType": "core",
                  "pageSize": len(pmids)}
        r = requests.get(EPMC, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        crudo = r.text
        cache_utils.write(ruta, crudo)

    datos = json.loads(crudo)
    salida = {}
    for item in datos.get("resultList", {}).get("result", []):
        pmid = item.get("pmid") or item.get("id")
        if pmid:
            salida[str(pmid)] = int(item.get("citedByCount") or 0)
    return salida


def hindex(citas):
    """h-index de una lista de recuentos de citas.

    h = mayor numero tal que h papers tienen al menos h citas cada uno.
    """
    ordenadas = sorted(citas, reverse=True)
    h = 0
    for i, c in enumerate(ordenadas, start=1):
        if c >= i:
            h = i
        else:
            break
    return h


def get_verified_metrics(pmids, use_cache=True):
    """h-index y citas calculados sobre el set desambiguado de PMIDs.

    Devuelve None si no hay PMIDs o si Europe PMC no responde: en ese caso el
    dashboard cae al bloque NO VERIFICADO de siempre. Nunca lanza hacia arriba.
    """
    pmids = [str(p) for p in (pmids or []) if str(p).isdigit()]
    if not pmids:
        return None

    citas_por_pmid = {}
    try:
        for i in range(0, len(pmids), LOTE_CITAS):
            citas_por_pmid.update(
                _citas_de_lote(pmids[i:i + LOTE_CITAS], use_cache=use_cache))
    except Exception:
        return None  # metrica opcional: no rompe el pipeline

    if not citas_por_pmid:
        return None

    # Los papers que Europe PMC no conoce cuentan como 0 citas, no se omiten:
    # omitirlos inflaria el h-index al reducir el denominador.
    citas = [citas_por_pmid.get(p, 0) for p in pmids]

    return {
        "hindex": hindex(citas),
        "citations": sum(citas),
        "papers_evaluados": len(pmids),
        "papers_encontrados": len(citas_por_pmid),
        "max_citas": max(citas) if citas else 0,
        "note": ("Calculado sobre el set de publicaciones ya filtrado de "
                 "homónimos, no sobre una búsqueda por nombre. Fuente de las "
                 "citas: Europe PMC (citedByCount)."),
    }
