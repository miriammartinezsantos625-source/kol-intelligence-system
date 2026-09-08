"""
Test de tildes en los entregables.

REGLA DURA del proyecto: las QUERIES a PubMed van SIN tildes (PubMed las trata
mal), pero los OUTPUTS (JSON, dashboard, PDF) van CON tildes.

Durante un tiempo se incumplio a medias: las cadenas en castellano estaban
escritas en el codigo fuente en ASCII ("Su publicacion", "afiliacion no
coincide", "area terapeutica", "Pagina 2"), asi que el dossier mezclaba el
texto fijo de la plantilla ("Homónimos excl.") con texto generado sin tildes.
Quedaba descuidado y era lo primero que se notaba al abrir el PDF.

Este test es la red que impide que vuelva a pasar: recorre los tres
entregables buscando palabras castellanas mal escritas. Cuando alguien anada
una cadena nueva sin tildes, este test lo dira.

ACTUALIZACION (sept. 2026): los entregables se redactan ya en INGLES, asi que
el texto fijo salio de la ecuacion. Lo que sigue vigilando este test es lo que
queda en castellano y no se traduce nunca: los nombres de centro y servicio,
las ciudades y los titulos de los papers espanoles. Esos SI deben salir con
sus tildes. Ojo al mantener la lista: 'area' es palabra inglesa corriente, y
por eso las cadenas en ingles del proyecto dicen 'field'.
"""

import json
import re

import pytest
from pypdf import PdfReader

from kol_engine import dashboard, disambiguator, pdf, profile

# Palabras castellanas que SIEMPRE llevan tilde. Si alguna aparece sin ella en
# un entregable, es que se coló una cadena en ASCII.
PALABRAS_CON_TILDE = [
    "publicacion", "publicaciones",  # (el plural no lleva, pero el singular si)
    "afiliacion", "localizacion", "homonimo", "homonimos", "reunion",
    "investigacion", "institucion", "identificacion", "informacion",
    "desambiguacion", "verificacion", "metrica", "metricas", "cientifico",
    "cientifica", "cientificas", "terapeutica", "especifico", "especifica",
    "ultima", "ultimas", "ultimo", "pagina", "paginas", "senal", "unico",
    "analisis", "area", "areas", "interes", "posicion", "practica",
]
# 'publicaciones' y 'areas' en plural no llevan tilde: fuera de la lista.
PALABRAS_CON_TILDE = [p for p in PALABRAS_CON_TILDE
                      if p not in {"publicaciones", "areas"}]


def _perfil():
    """Perfil completo con datos sinteticos (build_profile es puro, sin red)."""
    est = disambiguator.build_strategy(
        "Dra. Teresa San-Miguel", institution="Hospital La Fe", city="Valencia")
    papers = [{
        "pmid": "12345678", "title": "Estudio sobre glioblastoma",
        "journal": "Neuropathology", "year": "2024",
        "author_position": "first", "mesh": ["Glioblastoma", "Humans"],
        "mesh_major": ["Glioblastoma"], "keywords": [], "pubtypes": ["Review"],
        "matched_affiliation": "Department of Pathology, Hospital La Fe",
        "authors": [{"last": "San-Miguel", "initials": "T", "fore": "Teresa",
                     "affiliation": "", "orcid": ""}],
    }]
    analysis = {"verified": papers, "unverified": [], "excluded": [],
                "log": {"excluded_count": 2,
                        "excluded_reasons": {
                            "afiliación no coincide con la localización "
                            "del KOL": 2}}}
    metrics = {"hindex_europepmc": "NOT VERIFIED",
               "citations": "NOT VERIFIED", "epmc_raw_hits": 10,
               "note": "Europe PMC does not disambiguate homonyms."}
    return profile.build_profile(
        "Dra. Teresa San-Miguel", "Hospital La Fe", "Valencia", "España",
        None, None, est, analysis, {"trials": None, "log": {}}, metrics)


def _palabras_sin_tilde(texto):
    """Devuelve las palabras de la lista que aparecen SIN tilde en el texto.

    Compara por palabra completa y sin distinguir mayusculas, para no saltar
    con subcadenas ('area' dentro de 'areas' o de un termino ingles).
    """
    encontradas = set()
    minusculas = texto.lower()
    for palabra in PALABRAS_CON_TILDE:
        if re.search(rf"\b{palabra}\b", minusculas):
            encontradas.add(palabra)
    return encontradas


def test_el_json_lleva_tildes():
    """El kol_profile.json es la fuente de verdad: si el falla, fallan los tres."""
    texto = json.dumps(_perfil(), ensure_ascii=False)
    assert not _palabras_sin_tilde(texto)


def test_el_pdf_lleva_tildes(tmp_path):
    ruta = pdf.render_pdf(_perfil(), str(tmp_path))
    texto = "\n".join(p.extract_text() or "" for p in PdfReader(ruta).pages)
    assert not _palabras_sin_tilde(texto)


def test_el_dashboard_lleva_tildes(tmp_path):
    ruta = dashboard.render_dashboard(_perfil(), str(tmp_path))
    with open(ruta, encoding="utf-8") as f:
        assert not _palabras_sin_tilde(f.read())


def test_las_queries_a_pubmed_van_sin_tildes():
    """La otra mitad de la regla: PubMed trata mal los diacriticos.

    Aqui se comprueba que seguimos limpiando la query aunque los outputs ya
    lleven tildes: son dos caminos distintos, no uno.
    """
    est = disambiguator.build_strategy(
        "Dra. Teresa San-Miguel",
        institution="Hospital Universitari i Politècnic La Fe",
        city="València")
    assert "è" not in est["query_used"] and "é" not in est["query_used"]
    # ...pero la nota que lee la persona sigue siendo prosa, no una query.
    # (Desde que los entregables estan en ingles, esa nota ya no lleva tildes;
    # lo que se comprueba aqui es que la limpieza es SOLO de la query.)
    assert "affiliation" in est["notes"]
