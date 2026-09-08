"""
pubmed_agent — busca publicaciones en PubMed y filtra homonimos.

Dos mitades, deliberadamente separadas:

  MITAD DE RED (habla con internet, cachea en cache/):
    search_pmids(query)      -> lista de PMIDs
    fetch_papers(pmids)      -> lista de papers parseados

  MITAD PURA (sin red, testeable sola):
    filter_homonyms(papers, surname, initial, location_terms, orcid)
        -> clasifica cada paper en: verificado / sin_verificar / excluido,
           con un log de cuantos se excluyeron y por que.

El filtrado de homonimos es el corazon del sistema (problema #1 del dominio,
caso real 'San Miguel'). Por eso vive en una funcion PURA con su propio test.
"""

import hashlib
import logging
import os
import threading
import time
import xml.etree.ElementTree as ET

import requests

from . import cache_utils
from .text_utils import matches_any, normalize, strip_accents

logger = logging.getLogger(__name__)


class RespuestaInvalida(Exception):
    """PubMed devolvio algo que no se puede parsear.

    Es DISTINTO de "este autor no tiene papers". Antes ambos casos acababan
    en una lista vacia y el dossier publicaba "0 publicaciones" como si fuera
    un hecho comprobado.
    """

# --- Configuracion de las E-utilities de NCBI ---
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL = "kol-intelligence-system"          # NCBI pide identificar la herramienta
TIMEOUT = 30                               # segundos por peticion
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")

# NCBI limita a 3 peticiones/segundo sin api_key. Generando varios perfiles
# seguidos se choca con ese limite y devuelve 429; no es un error del que haya
# que rendirse, solo hay que esperar y repetir.
REINTENTOS = 4
ESPERA_INICIAL = 2                         # segundos, se duplica en cada intento


# NCBI admite 3 peticiones/segundo sin api_key. Al paginar (hasta 1.000 PMIDs)
# se hacen varias seguidas, asi que espaciamos nosotros en vez de provocar el
# 429 y esperar al backoff: sale mas rapido y es mas educado con la API.
INTERVALO_MIN = 0.34                       # segundos entre peticiones
_ultima_peticion = [0.0]
_cerrojo = threading.Lock()


def _esperar_turno():
    """Espacia las peticiones. Seguro entre hilos (Flask es multihilo)."""
    with _cerrojo:
        ahora = time.monotonic()
        pendiente = INTERVALO_MIN - (ahora - _ultima_peticion[0])
        if pendiente > 0:
            time.sleep(pendiente)
        _ultima_peticion[0] = time.monotonic()


def _peticion(metodo, url, **kwargs):
    """GET/POST con reintentos ante 429 y ante errores de red transitorios.

    Antes solo se reintentaba el 429. Pero en una conexion inestable lo que
    falla es la conexion, no el limite de peticiones: un ConnectionError o un
    timeout tumbaban el perfil entero al primer intento.

    Un error HTTP que no sea 429 (400, 404...) se propaga sin reintentar:
    repetir no lo arregla y es mejor fallar rapido con el mensaje real.
    """
    espera = ESPERA_INICIAL
    ultimo_error = None

    for intento in range(REINTENTOS):
        _esperar_turno()
        try:
            r = requests.request(metodo, url, timeout=TIMEOUT, **kwargs)
        except (requests.ConnectionError, requests.Timeout) as e:
            ultimo_error = e
            logger.warning("red inestable (%s), intento %d/%d",
                           e.__class__.__name__, intento + 1, REINTENTOS)
            if intento < REINTENTOS - 1:
                time.sleep(espera)
                espera *= 2
                continue
            raise

        if r.status_code != 429:
            r.raise_for_status()
            return r

        logger.info("PubMed 429 (límite de peticiones), intento %d/%d",
                    intento + 1, REINTENTOS)
        if intento < REINTENTOS - 1:
            time.sleep(espera)
            espera *= 2

    if ultimo_error:
        raise ultimo_error
    r.raise_for_status()
    return r


# ======================================================================
#  MITAD DE RED
# ======================================================================

def _cache_file(prefix, clave):
    """Ruta de cache para una clave (query o lista de ids)."""
    h = hashlib.md5(clave.encode("utf-8")).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{prefix}_{h}.txt")


def _leer_cache(ruta, use_cache):
    """Delegado en cache_utils para que el TTL aplique tambien a PubMed.

    Este modulo tenia su propia copia de la cache, asi que la caducidad no le
    afectaba — justo en la fuente de datos principal.
    """
    return cache_utils.read(ruta, use_cache)


def _guardar_cache(ruta, contenido):
    """Delegado en cache_utils para que la escritura sea atomica."""
    cache_utils.write(ruta, contenido)


# PubMed sirve como maximo 10.000 PMIDs por consulta con esearch clasico, y
# cada pagina son 200. Este tope acota el trabajo de un KOL hiperprolifico
# sin recortar a nadie real: por encima de 1.000 papers ya avisamos.
PAGE_SIZE = 200
MAX_PAPERS = 1000


def _esearch_page(query, retstart, retmax, api_key, email, use_cache):
    """Una pagina de esearch. Devuelve (idlist, total_real_en_pubmed)."""
    ruta = _cache_file("esearch", f"{query}|{retstart}|{retmax}")
    crudo = _leer_cache(ruta, use_cache)
    if crudo is None:
        params = {
            "db": "pubmed", "term": query, "retmode": "json",
            "retstart": retstart, "retmax": retmax, "tool": TOOL,
        }
        if api_key:
            params["api_key"] = api_key
        if email:
            params["email"] = email
        r = _peticion("GET", f"{EUTILS}/esearch.fcgi", params=params)
        crudo = r.text
        _guardar_cache(ruta, crudo)

    import json
    datos = json.loads(crudo).get("esearchresult", {})
    try:
        total = int(datos.get("count", 0))
    except (TypeError, ValueError):
        total = 0
    return datos.get("idlist", []), total


def search_pmids_with_total(query, max_papers=MAX_PAPERS, api_key=None,
                            email=None, use_cache=True):
    """Busca PMIDs paginando, y devuelve (pmids, total_en_pubmed).

    `total` es lo que PubMed dice que existe, NO lo que hemos traido. La
    diferencia entre ambos es justo lo que antes se perdia en silencio y
    hacia que un KOL de 674 papers apareciera como si tuviera 200 — con su
    biografia recortada a los ultimos anios.
    """
    pmids = []
    total = 0
    retstart = 0

    while len(pmids) < max_papers:
        pagina = min(PAGE_SIZE, max_papers - len(pmids))
        ids, total = _esearch_page(query, retstart, pagina, api_key, email,
                                   use_cache)
        if not ids:
            break
        pmids.extend(ids)
        retstart += len(ids)
        if retstart >= total:
            break

    return pmids[:max_papers], total


def search_pmids(query, retmax=MAX_PAPERS, api_key=None, email=None,
                 use_cache=True):
    """esearch.fcgi -> lista de PMIDs (como strings).

    Envoltorio de search_pmids_with_total para el codigo que solo quiere
    los ids. Cachea la respuesta cruda JSON para reproducibilidad.
    """
    pmids, _ = search_pmids_with_total(query, max_papers=retmax,
                                       api_key=api_key, email=email,
                                       use_cache=use_cache)
    return pmids


def fetch_papers(pmids, api_key=None, email=None, use_cache=True):
    """efetch.fcgi -> lista de papers parseados (ver _parse_articles).

    Devuelve [] si no hay PMIDs. Cachea el XML crudo.
    """
    if not pmids:
        return []
    # Por lotes: una sola peticion con 674 ids es fragil y desperdicia la
    # cache (cambiar un id invalida el bloque entero).
    if len(pmids) > PAGE_SIZE:
        papers = []
        for i in range(0, len(pmids), PAGE_SIZE):
            papers.extend(fetch_papers(pmids[i:i + PAGE_SIZE], api_key=api_key,
                                       email=email, use_cache=use_cache))
        return papers
    ids = ",".join(pmids)
    ruta = _cache_file("efetch", ids)
    crudo = _leer_cache(ruta, use_cache)
    if crudo is None:
        params = {"db": "pubmed", "id": ids, "retmode": "xml", "tool": TOOL}
        if api_key:
            params["api_key"] = api_key
        if email:
            params["email"] = email
        # POST: la lista de ids puede ser larga para un GET.
        r = _peticion("POST", f"{EUTILS}/efetch.fcgi", data=params)
        crudo = r.text
        _guardar_cache(ruta, crudo)
    try:
        return _parse_articles(crudo)
    except RespuestaInvalida as e:
        if not use_cache:
            raise
        # El culpable puede ser una entrada de cache corrupta: se descarta y
        # se pide fresco una sola vez. Si vuelve a fallar, es de PubMed.
        logger.warning("efetch corrupto (%s); reintento sin caché", e)
        try:
            os.unlink(ruta)
        except OSError:
            pass
        return fetch_papers(pmids, api_key=api_key, email=email,
                            use_cache=False)


def _text(elem, path):
    """Texto de un subelemento, o '' si no existe."""
    hijo = elem.find(path)
    return hijo.text.strip() if hijo is not None and hijo.text else ""


def _parse_articles(xml_text):
    """Convierte el XML de efetch en una lista de dicts normalizados.

    Cada paper:
        {pmid, title, journal, year, mesh:[...], keywords:[...],
         authors:[{last, fore, initials, affiliation, orcid}]}

    `mesh` son los descriptores MeSH que los indexadores de la NLM asignan a
    mano a cada articulo: el vocabulario controlado con el que sabemos DE QUE
    trata el paper. Es lo que permite deducir la especialidad y las lineas de
    investigacion del KOL sin preguntarselas (ver perfil_cientifico.py).
    Los `keywords` (palabras clave de los propios autores) sirven de apoyo
    cuando el articulo aun no esta indexado con MeSH.
    """
    papers = []
    if not (xml_text or "").strip():
        raise RespuestaInvalida("efetch devolvió una respuesta vacía")
    try:
        raiz = ET.fromstring(xml_text)
    except ET.ParseError as e:
        # Un XML cortado daba 0 papers sin rechistar: el KOL aparecia sin
        # obra publicada. Preferimos fallar y que se reintente.
        raise RespuestaInvalida(
            f"XML de efetch ilegible ({e}); {len(xml_text)} caracteres") from e

    for art in raiz.findall(".//PubmedArticle"):
        cita = art.find(".//MedlineCitation")
        if cita is None:
            continue
        pmid = _text(cita, "PMID")
        article = cita.find("Article")
        if article is None:
            continue

        title = _text(article, "ArticleTitle")
        journal = (_text(article, "Journal/ISOAbbreviation")
                   or _text(article, "Journal/Title"))
        year = _text(article, "Journal/JournalIssue/PubDate/Year")
        if not year:
            medline_date = _text(article, "Journal/JournalIssue/PubDate/MedlineDate")
            year = medline_date[:4] if medline_date else ""

        autores = []
        for a in article.findall("AuthorList/Author"):
            last = _text(a, "LastName")
            if not last:
                continue  # autores colectivos (CollectiveName) los saltamos
            fore = _text(a, "ForeName")
            initials = _text(a, "Initials")
            afiliaciones = [af.text.strip() for af in
                            a.findall("AffiliationInfo/Affiliation")
                            if af.text]
            orcid = ""
            ident = a.find("Identifier[@Source='ORCID']")
            if ident is not None and ident.text:
                orcid = ident.text.strip()
            autores.append({
                "last": last,
                "fore": fore,
                "initials": initials,
                "affiliation": " | ".join(afiliaciones),
                "orcid": orcid,
            })

        # Descriptores MeSH. Marcamos con '*' los "major topics": los temas
        # centrales del articulo, no los secundarios.
        mesh, mesh_major = [], []
        for mh in cita.findall("MeshHeadingList/MeshHeading"):
            desc = mh.find("DescriptorName")
            if desc is None or not desc.text:
                continue
            nombre = desc.text.strip()
            mesh.append(nombre)
            if desc.get("MajorTopicYN") == "Y":
                mesh_major.append(nombre)

        keywords = [k.text.strip() for k in cita.findall("KeywordList/Keyword")
                    if k is not None and k.text]

        # Tipos de publicacion: distinguen un ensayo clinico o una guia de
        # practica de una revision cualquiera (senal de peso para el MSL).
        pubtypes = [pt.text.strip() for pt in
                    article.findall("PublicationTypeList/PublicationType")
                    if pt.text]

        papers.append({
            "pmid": pmid, "title": title, "journal": journal,
            "year": year, "authors": autores,
            "mesh": mesh, "mesh_major": mesh_major,
            "keywords": keywords, "pubtypes": pubtypes,
        })
    return papers


# ======================================================================
#  MITAD PURA  (sin red — testeable sola)
# ======================================================================

def _surname_coincide(autor_last, surname):
    """True si el apellido del autor contiene TODOS los apellidos del KOL.

    Compara por tokens normalizados (sin tildes, guiones -> espacios). El
    apellido del autor debe incluir todas las palabras del apellido buscado:
      - KOL 'Martinez Lopez' vs autor 'Martinez Lopez' o 'Martinez Lopez Ruiz'
        -> coincide.
      - KOL 'Martinez Lopez' vs autor 'Lopez' (solo un apellido) -> NO coincide
        (evita arrastrar a cualquier 'Lopez').
      - KOL 'San-Miguel' ({san, miguel}) vs autor 'San-Miguel' -> coincide.
    """
    tokens_autor = set(normalize(autor_last).split())
    tokens_kol = set(normalize(surname).split())
    if not tokens_autor or not tokens_kol:
        return False
    return tokens_kol.issubset(tokens_autor)


def _inicial_coincide(autor_initials, inicial):
    """True si la inicial del nombre del autor casa con la del KOL.

    Si no se especifico inicial (inicial=''), no filtramos por inicial.
    """
    if not inicial:
        return True
    if not autor_initials:
        return False
    return strip_accents(autor_initials)[0].upper() == inicial.upper()


def _autor_orcid_coincide(orcid_autor, orcid_kol):
    if not orcid_autor or not orcid_kol:
        return False
    limpia = lambda s: s.replace("-", "").replace(" ", "").lower()
    return limpia(orcid_autor) == limpia(orcid_kol)


def _posicion_autoria(indice, total):
    if total <= 0:
        return "desconocida"
    if indice == 0:
        return "primera"
    if indice == total - 1:
        return "última"
    return "intermedia"


def filter_homonyms(papers, surname, initial, location_terms, orcid=None,
                    strong_terms=None):
    """Clasifica papers en verificado / sin_verificar / excluido.

    LOGICA (por cada paper):
      1. Busca al autor objetivo: apellido coincide Y (inicial coincide o no
         se dio inicial). Si no hay ninguno -> EXCLUIDO ('sin autor ...').
      2. Con el autor objetivo localizado, se decide por afiliacion:
         - ORCID del autor == ORCID del KOL          -> VERIFICADO
         - no hay terminos de localizacion            -> SIN_VERIFICAR
         - no hay ninguna afiliacion en el paper       -> SIN_VERIFICAR
         - coincide un termino FUERTE (institucion)   -> VERIFICADO
         - coincide solo un termino debil (ciudad)    -> SIN_VERIFICAR
         - en otro caso (afiliacion apunta a otro sitio)  -> EXCLUIDO

    `strong_terms` son los terminos que bastan para verificar (los del nombre
    del centro). Los que estan en `location_terms` pero no en `strong_terms`
    son debiles (la ciudad): amplian la busqueda, pero coincidir solo con
    ellos no confirma nada — en una ciudad grande hay muchos homonimos. Si no
    se pasa `strong_terms`, todos los terminos cuentan como fuertes.

    'SIN_VERIFICAR' = probablemente si, pero no hemos podido confirmarlo. Se
    conserva pero se marca (honestidad). 'EXCLUIDO' = evidencia de homonimo.

    Devuelve un dict con listas y un log de conteos/razones.
    """
    if strong_terms is None:
        strong_terms = location_terms
    verificados, sin_verificar, excluidos = [], [], []
    razones = {}

    def _anota_razon(motivo):
        razones[motivo] = razones.get(motivo, 0) + 1

    for paper in papers:
        autores = paper.get("authors", [])
        total = len(autores)

        # Paso 1: localizar al autor objetivo.
        objetivo, indice = None, None
        for i, a in enumerate(autores):
            if _surname_coincide(a["last"], surname) and \
               _inicial_coincide(a["initials"], initial):
                objetivo, indice = a, i
                break

        if objetivo is None:
            motivo = f"sin autor «{surname} {initial}»".replace("  »", "»")
            _anota_razon(motivo)
            excluidos.append({**paper, "_motivo": motivo})
            continue

        enriquecido = {
            **paper,
            "author_position": _posicion_autoria(indice, total),
            "matched_affiliation": objetivo["affiliation"],
        }

        # Paso 2a: ORCID coincide -> verificado directo.
        if _autor_orcid_coincide(objetivo["orcid"], orcid):
            enriquecido["_motivo"] = "ORCID coincide"
            verificados.append(enriquecido)
            continue

        # Texto de afiliacion a comprobar: la del propio autor, o (fallback)
        # todas las afiliaciones del paper.
        afil_autor = objetivo["affiliation"]
        afil_texto = afil_autor
        fallback = False
        if not afil_texto:
            afil_texto = " | ".join(a["affiliation"] for a in autores
                                    if a["affiliation"])
            fallback = bool(afil_texto)

        # Paso 2b: no podemos verificar por localizacion.
        if not location_terms:
            enriquecido["_motivo"] = "sin términos de localización (no verificable)"
            sin_verificar.append(enriquecido)
            continue
        if not afil_texto:
            enriquecido["_motivo"] = "sin afiliación en el registro (no verificable)"
            sin_verificar.append(enriquecido)
            continue

        # Paso 2c: comparar afiliacion con los terminos de localizacion
        # (por palabra completa: 'fe' no debe coincidir dentro de 'Tenerife').
        acierto = matches_any(afil_texto, location_terms)
        if acierto and acierto in strong_terms:
            nota = f"afiliación coincide con «{acierto}»"
            if fallback:
                nota += " (vía afiliación de coautor)"
            enriquecido["_motivo"] = nota
            verificados.append(enriquecido)
        elif acierto:
            # Solo casa la ciudad: probable, pero no confirmado. Decirlo.
            enriquecido["_motivo"] = (
                f"solo coincide la ciudad «{acierto}», no la institución "
                "(no verificable)")
            sin_verificar.append(enriquecido)
        else:
            corta = (afil_autor or afil_texto)[:80]
            motivo = "afiliación no coincide con la localización del KOL"
            _anota_razon(motivo)
            enriquecido["_motivo"] = f"{motivo}: «{corta}»"
            excluidos.append(enriquecido)

    log = {
        "input_count": len(papers),
        "verified_count": len(verificados),
        "unverified_count": len(sin_verificar),
        "excluded_count": len(excluidos),
        "excluded_reasons": razones,
    }
    return {
        "verified": verificados,
        "unverified": sin_verificar,
        "excluded": excluidos,
        "log": log,
    }


# ======================================================================
#  ORQUESTACION (une las dos mitades)
# ======================================================================

def analyze(strategy, retmax=MAX_PAPERS, api_key=None, email=None,
            use_cache=True):
    """Ejecuta busqueda + fetch + filtrado a partir de una estrategia
    (la que devuelve disambiguator.build_strategy).

    Devuelve un dict con los papers clasificados, el log del filtro y
    `coverage`: cuantos papers dice PubMed que hay frente a cuantos hemos
    analizado. Si no coinciden, TODO lo que se derive del set (biografia,
    media anual, primer anio) describe solo una parte de la obra y hay que
    decirlo, no dar la cifra recortada como si fuera completa.
    """
    pmids, total_pubmed = search_pmids_with_total(
        strategy["query_used"], max_papers=retmax,
        api_key=api_key, email=email, use_cache=use_cache)
    papers = fetch_papers(pmids, api_key=api_key, email=email,
                          use_cache=use_cache)
    resultado = filter_homonyms(
        papers,
        surname=strategy["surname"],
        initial=strategy["initial"],
        location_terms=strategy["location_terms"],
        orcid=strategy.get("orcid"),
        strong_terms=strategy.get("strong_terms"),
    )
    resultado["pmids_found"] = pmids
    resultado["coverage"] = {
        "total_en_pubmed": total_pubmed,
        "analizados": len(pmids),
        "truncado": bool(total_pubmed and len(pmids) < total_pubmed),
        "tope": retmax,
    }
    return resultado
