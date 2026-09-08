"""
clinicaltrials_agent — verificacion de ensayos clinicos por localizacion.

Consulta ClinicalTrials.gov (API v2) por el nombre del KOL y verifica CADA
ensayo contra su ciudad/institucion. La logica es deliberadamente estricta:
un ensayo solo cuenta si un investigador con el apellido del KOL aparece Y la
localizacion (afiliacion del investigador o alguna sede del ensayo) coincide.

REGLA DURA: si ningun ensayo verifica -> devuelve None -> el sistema muestra
"0 ensayos verificados". Es un resultado VALIDO: mejor 0 honesto que atribuir
al KOL el ensayo de un homonimo.
"""

import json

import requests

from . import cache_utils
from .text_utils import contains_term, matches_any, normalize

API_V2 = "https://clinicaltrials.gov/api/v2/studies"
TIMEOUT = 30


# ----------------------------------------------------------------------
#  MITAD DE RED
# ----------------------------------------------------------------------

def search_studies(term, city=None, page_size=100, use_cache=True):
    """Busca estudios por termino (nombre) y, si hay ciudad, la usa para
    acotar. Devuelve la lista cruda de estudios (dicts de la API v2)."""
    clave = f"{term}|{city}|{page_size}"
    ruta = cache_utils.cache_path("ctgov", clave)
    crudo = cache_utils.read(ruta, use_cache)
    if crudo is None:
        params = {
            "query.term": term,
            "pageSize": page_size,
            "format": "json",
        }
        if city:
            params["query.locn"] = city
        r = requests.get(API_V2, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        crudo = r.text
        cache_utils.write(ruta, crudo)
    datos = json.loads(crudo)
    return datos.get("studies", [])


# ----------------------------------------------------------------------
#  MITAD PURA (parseo + verificacion por localizacion)
# ----------------------------------------------------------------------

def _parse_study(study):
    """Extrae de un estudio crudo los campos que nos interesan."""
    ps = study.get("protocolSection", {})
    ident = ps.get("identificationModule", {})
    design = ps.get("designModule", {})
    contacts = ps.get("contactsLocationsModule", {})

    fases = design.get("phases", []) or []
    officials = []
    for o in contacts.get("overallOfficials", []) or []:
        officials.append({
            "name": o.get("name", ""),
            "affiliation": o.get("affiliation", ""),
            "role": o.get("role", ""),
        })
    locations = []
    for loc in contacts.get("locations", []) or []:
        locations.append({
            "facility": loc.get("facility", ""),
            "city": loc.get("city", ""),
            "country": loc.get("country", ""),
        })

    return {
        "nct": ident.get("nctId", ""),
        "title": ident.get("briefTitle", "") or ident.get("officialTitle", ""),
        "phase": ", ".join(f.replace("PHASE", "Fase ") for f in fases) or "N/A",
        "officials": officials,
        "locations": locations,
    }


def _localizacion_coincide(texto, location_terms):
    """True si algun termino de localizacion aparece como PALABRA en el texto
    ('fe' no coincide dentro de 'Tenerife')."""
    return matches_any(texto, location_terms) is not None


def _official_coincide(nombre_official, surname, initial):
    """True si el investigador es (plausiblemente) nuestro KOL.

    En ClinicalTrials los investigadores aparecen con NOMBRE COMPLETO
    ('Teresa San-Miguel'), no con inicial. Estrategia:
      1. El apellido debe aparecer como palabra en el nombre.
      2. Si tenemos inicial, algun nombre de pila (los tokens que NO son el
         apellido) debe empezar por ella. Asi 'Jesús F. San-Miguel' (J, F) se
         rechaza frente a la inicial 'T' de Teresa.
      3. Si el nombre es solo el apellido (sin nombre de pila), NO se puede
         confirmar la identidad -> se rechaza (honestidad ante homonimos).
    """
    if not contains_term(nombre_official, surname):
        return False
    if not initial:
        return True
    palabras_apellido = set(normalize(surname).split())
    nombres_pila = [w for w in normalize(nombre_official).split()
                    if w not in palabras_apellido]
    if not nombres_pila:
        return False  # solo el apellido: no verificable
    return any(w[0] == initial.lower() for w in nombres_pila)


def verify_trials(studies, surname, initial, location_terms):
    """Verifica cada estudio contra el KOL. Devuelve (verificados, log).

    Un estudio verifica si:
      - hay un 'overall official' cuyo apellido coincide con el del KOL, Y
      - la localizacion coincide: bien en la afiliacion de ese investigador,
        bien en alguna sede (location) del ensayo.
    Si no hay location_terms, no podemos verificar -> ninguno cuenta.
    """
    verificados = []
    razones = {}

    def _anota(m):
        razones[m] = razones.get(m, 0) + 1

    for study in studies:
        info = _parse_study(study)

        # Busca un investigador que sea (plausiblemente) nuestro KOL:
        # apellido como palabra + nombre de pila que empiece por la inicial.
        official = next((o for o in info["officials"]
                         if _official_coincide(o["name"], surname, initial)),
                        None)

        if official is None:
            _anota("sin investigador que coincida con el KOL (apellido+inicial)")
            continue

        if not location_terms:
            _anota("sin términos de localización (no verificable)")
            continue

        # Localizacion: afiliacion del investigador o alguna sede del ensayo.
        sedes_txt = " | ".join(f"{l['facility']} {l['city']} {l['country']}"
                               for l in info["locations"])
        coincide = (_localizacion_coincide(official["affiliation"], location_terms)
                    or _localizacion_coincide(sedes_txt, location_terms))

        if not coincide:
            _anota("localización no coincide con la del KOL")
            continue

        # Sede legible para el output.
        sede = next((f"{l['facility']}, {l['city']}".strip(", ")
                     for l in info["locations"]
                     if _localizacion_coincide(f"{l['facility']} {l['city']}", location_terms)),
                    official["affiliation"] or "verificada")
        verificados.append({
            "nct": info["nct"],
            "title": info["title"],
            "phase": info["phase"],
            "role": official["role"].replace("_", " ").title() or "Investigador",
            "location": sede,
        })

    log = {
        "studies_found": len(studies),
        "verified_count": len(verificados),
        "excluded_reasons": razones,
    }
    return verificados, log


# ----------------------------------------------------------------------
#  ORQUESTACION
# ----------------------------------------------------------------------

def find_trials(full_name, surname, initial, location_terms, city=None,
                use_cache=True):
    """Busca y verifica ensayos. Devuelve un dict con:
        {"trials": None | {verified_count, items}, "log": {...}}

    trials=None cuando 0 verifican (el bloque "0 ensayos verificados").
    """
    term = surname or full_name
    studies = search_studies(term, city=city, use_cache=use_cache)
    verificados, log = verify_trials(studies, surname, initial, location_terms)

    if not verificados:
        return {"trials": None, "log": log}
    return {
        "trials": {"verified_count": len(verificados), "items": verificados},
        "log": log,
    }
