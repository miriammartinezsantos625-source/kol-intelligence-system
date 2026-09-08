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
                     if p.get("author_position") in ("primera", "última"))
    journals = sorted({p.get("journal", "") for p in kept if p.get("journal")})

    items = []
    for p in kept:
        items.append({
            "pmid": p.get("pmid", ""),
            "title": p.get("title", ""),
            "journal": p.get("journal", ""),
            "year": p.get("year", ""),
            "author_position": p.get("author_position", "desconocida"),
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
        listado = ", ".join(f"{l['tema']} ({l['papers']} trabajos)"
                            for l in recurrentes)
        puntos.append(f"Sus líneas más constantes son {listado}. "
                      "Es el terreno donde la conversación le resultará propia.")
    elif lineas:
        listado = ", ".join(f"{l['tema']} ({l['ultimo_anio']})"
                            for l in lineas[:3])
        puntos.append(
            f"No repite tema: su obra es temáticamente dispersa. Lo más "
            f"reciente que ha tocado es {listado}. Mejor preguntar en qué "
            "trabaja ahora que asumir una línea.")

    # 2. Dónde lidera: primer o último autor es donde firma como responsable.
    lidera = [it for it in items
              if it["author_position"] in ("primera", "última", "ultima")]
    if lidera:
        it = lidera[0]
        rol = "primer" if it["author_position"] == "primera" else "último"
        puntos.append(
            f"Firma como {rol} autor «{_recortar(it['title'])}» "
            f"({it['journal']}, {it['year']}): trabajo suyo, no de un grupo "
            "en el que solo participa.")
    elif items:
        it = items[0]
        puntos.append(
            f"Su publicación más reciente es «{_recortar(it['title'])}» "
            f"({it['journal']}, {it['year']}), en posición intermedia — "
            "participa en grupos amplios más que liderando.")

    # 3. Ritmo de producción: dice con quién estás hablando hoy, no hace 10 años.
    if tray:
        if tray["activo"]:
            puntos.append(
                f"Publica desde {tray['primer_anio']} a un ritmo de "
                f"{tray['media_anual']} trabajos/año y sigue activo "
                f"(último en {tray['ultimo_anio']}): interlocutor en producción.")
        else:
            puntos.append(
                f"Su última publicación indexada es de {tray['ultimo_anio']}. "
                "Conviene preguntar en qué está trabajando ahora antes de "
                "asumir que sigue en la misma línea.")

    # 4. Tipo de evidencia que genera.
    relevantes = [t for t in tipos if t["tipo"] not in
                  ("Revisión", "Comentario", "Editorial", "Caso clínico")]
    if relevantes:
        listado = ", ".join(t["texto"] for t in relevantes[:3])
        puntos.append(f"Genera evidencia: {listado}. "
                      "Es un perfil con el que se puede hablar de diseño de estudio.")

    # 5. Su red: puertas de entrada.
    if colabs:
        listado = ", ".join(f"{c['nombre']} ({c['papers']})" for c in colabs[:3])
        puntos.append(f"Coautores habituales: {listado}. "
                      "Si ya hay relación con alguno, es una vía de acceso.")

    if not puntos:
        puntos = ["No se han verificado publicaciones suficientes para preparar "
                  "puntos concretos. Abrir con preguntas sobre su área de "
                  "interés actual y su actividad asistencial."]

    # ---- Hacer ----
    hacer = []
    if recurrentes:
        hacer.append(f"Entrar por {recurrentes[0]['tema']}: es su tema con "
                     f"más recorrido ({recurrentes[0]['papers']} trabajos).")
    elif temas_centrales:
        hacer.append(f"Entrar por {temas_centrales[0]['tema']}, el asunto de su "
                     f"trabajo más reciente ({temas_centrales[0]['ultimo_anio']}).")
    if area:
        hacer.append(f"Preparar preguntas concretas de {area.lower()}, no "
                     "genéricas de área terapéutica.")
    if lidera:
        hacer.append(f"Referenciar «{_recortar(lidera[0]['title'], 60)}», donde "
                     "figura como autor responsable.")
    hacer.append("Escuchar sus necesidades científicas no cubiertas y "
                 "registrarlas literalmente.")
    if trials:
        hacer.append(f"Preguntar por su papel en los {trials['verified_count']} "
                     "ensayo(s) verificado(s) y por su capacidad de reclutamiento.")

    # ---- Evitar ----
    evitar = ["No presentar mensajes promocionales: el contacto es científico."]
    if pub_stats["excluded_count"]:
        evitar.append(
            f"No atribuirle los {pub_stats['excluded_count']} trabajo(s) "
            "excluidos por afiliación: son de homónimos, y confundirlos "
            "destruye la credibilidad en el primer minuto.")
    else:
        evitar.append("No atribuirle trabajo no verificado.")
    if pub_stats["unverified_count"]:
        evitar.append(
            f"No dar por seguras las {pub_stats['unverified_count']} "
            "publicación(es) sin afiliación confirmada.")
    if not trials:
        evitar.append("No dar por hecho que participa en ensayos: no se ha "
                      "verificado ninguno en su centro.")
    evitar.append("No citar el h-index de Europe PMC: está sin desambiguar.")

    # ---- Congresos ----
    congresos = []
    if area:
        congresos.append({
            "name": f"Congreso nacional de {area.lower()}",
            "note": "sugerido por su área — verificar agenda real del KOL",
        })
    else:
        congresos.append({
            "name": "Congreso de su área de trabajo",
            "note": "sin área determinada — confirmar con el propio KOL",
        })

    # ---- Checklist ----
    checklist = [
        "Confirmar disponibilidad y formato de la reunión.",
        "Revisar sus últimas publicaciones verificadas antes de entrar.",
    ]
    if temas_centrales:
        checklist.append(f"Llevar material científico específico de "
                         f"{temas_centrales[0]['tema']}.")
    else:
        checklist.append("Llevar material científico de su área asistencial.")
    checklist.append("Registrar la interacción en el CRM tras la visita.")

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
        trial_note = ("NO COMPROBADO: no se pudo consultar ClinicalTrials.gov "
                      f"({trials_error}). El apartado de ensayos queda sin "
                      "verificar; no interpretar como ausencia de ensayos.")
    elif trials is None:
        trial_note = ("0 ensayos verificados contra la localización del KOL "
                      "(resultado válido: no se atribuye trabajo de homónimos).")
    else:
        trial_note = (f"{trials['verified_count']} ensayo(s) verificado(s) por "
                      "localización.")

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
