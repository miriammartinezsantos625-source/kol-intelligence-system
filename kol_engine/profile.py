"""
profile — ensambla el kol_profile.json (la UNICA fuente de verdad).

Recibe la salida de los agentes (ya con la red hecha por kol.py) y produce un
dict que cumple el contrato del brief (seccion 5). El dashboard (Fase 3) y el
PDF (Fase 3) se generaran EXCLUSIVAMENTE desde este dict: si el JSON es
correcto, los dos entregables lo son.

Es codigo PURO (sin red): facil de razonar y de testear.
"""

import datetime
import json
import logging
import os
import re

from . import perfil_cientifico, scoring
from .disambiguator import TITULOS
from .text_utils import strip_accents
from .cache_utils import escritura_atomica


# ----------------------------------------------------------------------
#  Helpers de identidad
# ----------------------------------------------------------------------

def _sin_titulo(full_name):
    """Nombre sin tratamiento ('Dra. Teresa San-Miguel' -> 'Teresa San-Miguel')."""
    tokens = full_name.split()
    limpio = [t for t in tokens
              if strip_accents(t).lower().strip(".") not in
              {x.strip(".") for x in TITULOS}]
    return " ".join(limpio)


def _iniciales(full_name):
    """Iniciales para el avatar: inicial del nombre + inicial de cada apellido.

    'Teresa San-Miguel' -> 'TSM'
    """
    nombre = _sin_titulo(full_name)
    piezas = re.split(r"[\s-]+", nombre)
    return "".join(p[0].upper() for p in piezas if p)[:3]


logger = logging.getLogger(__name__)


def _slug(full_name):
    """Nombre de fichero seguro y estable: 'Teresa_San-Miguel'.

    La caja se normaliza (Title Case): escribir «ELIAS MARTINEZ LOPEZ» o
    «Elías Martínez López» es el mismo medico y debe sobrescribir el mismo
    dossier, no dejar dos juegos de entregables casi identicos en output/.
    """
    nombre = _sin_titulo(full_name)
    limpio = re.sub(r"[^A-Za-z0-9\-]", "_", strip_accents(nombre)).strip("_")
    # Title Case por trozos, respetando guiones ('san-miguel' -> 'San-Miguel').
    partes = [
        "-".join(t.capitalize() for t in parte.split("-"))
        for parte in limpio.split("_") if parte
    ]
    return "_".join(partes)


# ----------------------------------------------------------------------
#  Estadisticas de publicaciones (del set filtrado de PubMed)
# ----------------------------------------------------------------------

def _pub_stats(analysis, anio_actual):
    """Calcula las metricas fiables a partir del resultado de pubmed_agent.

    Se consideran 'del KOL' los verificados + los sin_verificar (ambos tienen
    al autor; los sin_verificar solo carecen de afiliacion para confirmar).
    """
    verificados = analysis.get("verified", [])
    sin_verificar = analysis.get("unverified", [])
    kept = verificados + sin_verificar

    def _anio(p):
        try:
            return int(p.get("year", "0")[:4])
        except (ValueError, TypeError):
            return 0

    recent_5y = sum(1 for p in kept if _anio(p) >= anio_actual - 5)
    first_last = sum(1 for p in kept
                     if p.get("author_position") in ("first", "last"))
    journals = sorted({p.get("journal", "") for p in kept if p.get("journal")})

    items = []
    for p in kept:
        items.append({
            "pmid": p.get("pmid", ""),
            "title": p.get("title", ""),
            "journal": p.get("journal", ""),
            "year": p.get("year", ""),
            "author_position": p.get("author_position", "unknown"),
            "verified": p in verificados,
        })
    # Ordena por anio descendente (mas reciente primero).
    items.sort(key=lambda it: it.get("year", ""), reverse=True)

    log = analysis.get("log", {})
    return {
        "count": len(kept),
        "verified_count": len(verificados),
        "unverified_count": len(sin_verificar),
        "recent_5y": recent_5y,
        "journals": journals,
        "unique_journals": len(journals),
        "first_last_author_count": first_last,
        "excluded_count": log.get("excluded_count", 0),
        "excluded_reasons": log.get("excluded_reasons", {}),
        "items": items,
    }


# ----------------------------------------------------------------------
#  Briefing pre-visita
# ----------------------------------------------------------------------

def _recortar(texto, limite=90):
    """Recorta por el ÚLTIMO espacio antes del límite, nunca a mitad de palabra.

    Antes se cortaba con `texto[:80]` y salían cosas como
    "...retinopathy stage identificatio". Ahora se corta en la palabra
    anterior y se añade la elipsis.
    """
    texto = (texto or "").strip().rstrip(".")
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return corte.rstrip(",;:") + "…"


def _briefing(pub_stats, trials, perfil, identity):
    """Puntos de conversación y pautas, construidos con los datos REALES del KOL.

    Antes esta función devolvía plantilla fija: los mismos tres consejos para
    cualquier médico y, como "puntos de conversación", el título de un paper
    copiado y cortado. Ahora cada punto sale de algo que sabemos de él: sus
    líneas de investigación, su trayectoria, con quién publica y qué tipo de
    evidencia genera.
    """
    esp = perfil.get("especialidad") or {}
    area = esp.get("nombre")
    lineas = perfil.get("lineas_investigacion") or []
    tray = perfil.get("trayectoria") or {}
    colabs = perfil.get("colaboradores") or []
    tipos = perfil.get("tipos_publicacion") or []
    items = pub_stats["items"]

    # ---- Puntos de conversación ----
    puntos = []

    # 1. Sus temas. Distinguimos los que REPITE (línea de trabajo real) de los
    #    que solo aparecen una vez (obra dispersa): decir "su línea es X" con
    #    un solo paper detrás sería vendérselo al MSL como algo que no es.
    recurrentes = [l for l in lineas if l.get("recurrente")][:3]
    temas_centrales = recurrentes or lineas[:3]
    if recurrentes:
        listado = ", ".join(f"{l['tema']} ({l['papers']} papers)"
                            for l in recurrentes)
        puntos.append(f"Their steadiest lines are {listado}. "
                      "This is the ground where the conversation will feel "
                      "like their own.")
    elif lineas:
        listado = ", ".join(f"{l['tema']} ({l['ultimo_anio']})"
                            for l in lineas[:3])
        puntos.append(
            f"No topic repeats: their work is thematically scattered. The "
            f"most recent ground they covered is {listado}. Better to ask "
            "what they are working on now than to assume a line.")

    # 2. Dónde lidera: primer o último autor es donde firma como responsable.
    lidera = [it for it in items
              if it["author_position"] in ("first", "last")]
    if lidera:
        it = lidera[0]
        rol = "first" if it["author_position"] == "first" else "last"
        puntos.append(
            f"They sign as {rol} author on «{_recortar(it['title'])}» "
            f"({it['journal']}, {it['year']}): their own work, not a group's "
            "they merely take part in.")
    elif items:
        it = items[0]
        puntos.append(
            f"Their most recent publication is «{_recortar(it['title'])}» "
            f"({it['journal']}, {it['year']}), in a middle position — they "
            "take part in large groups rather than leading.")

    # 3. Ritmo de producción: dice con quién estás hablando hoy, no hace 10 años.
    if tray:
        if tray["activo"]:
            puntos.append(
                f"Publishing since {tray['primer_anio']} at {tray['media_anual']} "
                f"papers/year and still active (latest in {tray['ultimo_anio']}): "
                "an interlocutor in full production.")
        else:
            puntos.append(
                f"Their latest indexed publication is from {tray['ultimo_anio']}. "
                "Worth asking what they are working on now before assuming "
                "they are still on the same line.")

    # 4. Tipo de evidencia que genera.
    relevantes = [t for t in tipos if t["tipo"] not in
                  ("Review", "Comment", "Editorial", "Case report")]
    if relevantes:
        listado = ", ".join(t["texto"] for t in relevantes[:3])
        puntos.append(f"Generates evidence: {listado}. "
                      "A profile you can discuss study design with.")

    # 5. Su red: puertas de entrada.
    if colabs:
        listado = ", ".join(f"{c['nombre']} ({c['papers']})" for c in colabs[:3])
        puntos.append(f"Frequent co-authors: {listado}. "
                      "If there is already a relationship with any of them, "
                      "that is a way in.")

    if not puntos:
        puntos = ["Not enough publications were verified to prepare concrete "
                  "points. Open with questions about what currently interests "
                  "them and about their clinical work."]

    # ---- Hacer ----
    hacer = []
    if recurrentes:
        n = recurrentes[0]['papers']
        hacer.append(f"Open with {recurrentes[0]['tema']}: their most "
                     f"developed topic ({n} paper{'' if n == 1 else 's'}).")
    elif temas_centrales:
        hacer.append(f"Open with {temas_centrales[0]['tema']}, the subject of "
                     f"their most recent paper ({temas_centrales[0]['ultimo_anio']}).")
    if area:
        hacer.append(f"Prepare specific {area.lower()} questions, not generic "
                     "therapeutic-field ones.")
    if lidera:
        hacer.append(f"Reference «{_recortar(lidera[0]['title'], 60)}», where "
                     "they appear as the responsible author.")
    hacer.append("Listen for their unmet scientific needs and record them "
                 "verbatim.")
    if trials:
        hacer.append(f"Ask about their role in the {trials['verified_count']} "
                     "verified trial(s) and about their recruitment capacity.")

    # ---- Evitar ----
    evitar = ["Do not bring promotional messages: this is a scientific contact."]
    if pub_stats["excluded_count"]:
        evitar.append(
            f"Do not attribute to them the {pub_stats['excluded_count']} paper(s) "
            "excluded by affiliation: they belong to homonyms, and confusing "
            "them destroys credibility in the first minute.")
    else:
        evitar.append("Do not attribute unverified work to them.")
    if pub_stats["unverified_count"]:
        evitar.append(
            f"Do not take the {pub_stats['unverified_count']} publication(s) "
            "without a confirmed affiliation as certain.")
    if not trials:
        evitar.append("Do not assume they take part in trials: none was "
                      "verified at their centre.")
    evitar.append("Do not quote the Europe PMC h-index: it is not disambiguated.")

    # ---- Congresos ----
    congresos = []
    if area:
        congresos.append({
            "name": f"National {area.lower()} congress",
            "note": "suggested by their field — check the KOL's real agenda",
        })
    else:
        congresos.append({
            "name": "Congress in their field of work",
            "note": "field undetermined — confirm with the KOL directly",
        })

    # ---- Checklist ----
    checklist = [
        "Confirm availability and meeting format.",
        "Review their latest verified publications before going in.",
    ]
    if temas_centrales:
        checklist.append(f"Bring scientific material specific to "
                         f"{temas_centrales[0]['tema']}.")
    else:
        checklist.append("Bring scientific material for their clinical field.")
    checklist.append("Log the interaction in the CRM after the visit.")

    return {
        "talking_points": puntos,
        "do": hacer,
        "dont": evitar,
        "next_congresses": congresos,
        "checklist": checklist,
    }


# ----------------------------------------------------------------------
#  Ensamblado principal
# ----------------------------------------------------------------------

def build_profile(full_name, institution, city, country, orcid, specialty,
                  strategy, analysis, trials_result, metrics, hoy=None,
                  metrics_verified=None):
    """Devuelve el dict kol_profile completo (contrato seccion 5)."""
    hoy = hoy or datetime.date.today()
    anio_actual = hoy.year

    pub_stats = _pub_stats(analysis, anio_actual)
    trials = trials_result.get("trials")  # None o {"verified_count", "items"}
    trials_error = trials_result.get("error")  # str si ClinicalTrials fallo

    # Perfil cientifico: quien es este medico, deducido de sus propios papers
    # (MeSH, afiliaciones, coautores). Se calcula sobre el set YA filtrado de
    # homonimos, para no describir a otra persona.
    papers_del_kol = analysis.get("verified", []) + analysis.get("unverified", [])
    perfil_sci = perfil_cientifico.construir(
        papers_del_kol,
        surname=strategy.get("surname", ""),
        anio_actual=anio_actual,
        especialidad_declarada=specialty,
        pub_stats=pub_stats)

    # La especialidad efectiva es la declarada o, si no la hay, la inferida.
    # El score la usa: un KOL de area conocida puntua mas en relevancia.
    especialidad_efectiva = perfil_sci["especialidad"].get("nombre")

    score = scoring.compute_score(pub_stats, trials,
                                  specialty=especialidad_efectiva,
                                  trials_available=not trials_error)

    identity = {
        "full_name": _sin_titulo(full_name),
        "header_name": full_name,
        "initials": _iniciales(full_name),
        "institution": institution or "",
        "city": city or "",
        "country": country or "",
        "specialty": especialidad_efectiva or "",
        "specialty_origin": perfil_sci["especialidad"].get("origen"),
        "service": (perfil_sci["servicio"] or {}).get("nombre", ""),
        "orcid": orcid or "",
        "badge": {"tier": score["tier"], "score": score["total"]},
    }

    publications = {
        "count": pub_stats["count"],
        "verified_count": pub_stats["verified_count"],
        "unverified_count": pub_stats["unverified_count"],
        "recent_5y": pub_stats["recent_5y"],
        "journals": pub_stats["journals"],
        "first_last_author_count": pub_stats["first_last_author_count"],
        "excluded_count": pub_stats["excluded_count"],
        "excluded_reasons": pub_stats["excluded_reasons"],
        "items": pub_stats["items"],
    }

    if trials_error:
        # Nunca afirmar "0 ensayos" cuando en realidad no se pudo mirar.
        trial_note = ("NOT CHECKED: ClinicalTrials.gov could not be queried "
                      f"({trials_error}). The trials section is left "
                      "unverified; do not read it as an absence of trials.")
    elif trials is None:
        trial_note = ("0 trials verified against the KOL's location "
                      "(a valid result: no work by homonyms is attributed).")
    else:
        trial_note = (f"{trials['verified_count']} trial(s) verified by "
                      "location.")

    profile = {
        "identity": identity,
        "disambiguation": {
            "query_used": strategy["query_used"],
            "confidence": strategy["confidence"],
            "notes": strategy["notes"],
            "location_terms": strategy["location_terms"],
        },
        "perfil_cientifico": perfil_sci,
        "publications": publications,
        "trials": trials,
        "metrics_unverified": metrics,
        "metrics_verified": metrics_verified,
        "coverage": analysis.get("coverage"),
        "score": score,
        "briefing": _briefing(pub_stats, trials, perfil_sci, identity),
        "verification_note": {
            "sources": ["PubMed (E-utilities)", "ClinicalTrials.gov API v2",
                        "Europe PMC"],
            "date": hoy.isoformat(),
            "trial_note": trial_note,
        },
    }
    return profile


def save_profile(profile, output_dir):
    """Escribe kol_profile_{Nombre}.json y devuelve la ruta."""
    os.makedirs(output_dir, exist_ok=True)
    slug = _slug(profile["identity"]["full_name"])
    ruta = os.path.join(output_dir, f"kol_profile_{slug}.json")
    # Atomica: si dos perfiles del mismo KOL se generan a la vez (Flask es
    # multihilo), nadie debe poder leer un JSON a medio escribir.
    escritura_atomica(ruta, json.dumps(profile, ensure_ascii=False, indent=2))
    logger.info("perfil guardado: %s", ruta)
    return ruta
