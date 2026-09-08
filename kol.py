#!/usr/bin/env python3
"""
kol.py — punto de entrada (CLI) del KOL Intelligence System.

Uso (basta con nombre + centro):
    python kol.py "Dra. Teresa San-Miguel" "Hospital La Fe"

La ciudad se deduce del centro y la especialidad de sus publicaciones; los
flags --ciudad / --especialidad solo hacen falta para forzar un valor.

Flags:
    --solo-json  --solo-dashboard  --solo-pdf  --no-cache
"""

import argparse
import json
import logging
import os
import sys

from kol_engine import (centros, clinicaltrials_agent, dashboard,
                        disambiguator, europepmc_agent, pdf, profile,
                        pubmed_agent, verify)
from kol_engine.profile import _slug

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")


def _render(perfil):
    """Genera dashboard HTML + dossier PDF. Devuelve (ruta_html, ruta_pdf)."""
    ruta_html = dashboard.render_dashboard(perfil, OUTPUT_DIR)
    print(f"✓ Dashboard: {ruta_html}")
    ruta_pdf = pdf.render_pdf(perfil, OUTPUT_DIR)
    print(f"✓ Dossier PDF: {ruta_pdf}")
    return ruta_html, ruta_pdf


def _verificar(perfil, ruta_html, ruta_pdf):
    """Corre la verificacion final (Paso 9) e imprime el informe.
    Devuelve True si pasan todas las comprobaciones criticas."""
    _titulo("Final verification (step 9)")
    informe = verify.verify_deliverables(perfil, ruta_html, ruta_pdf)
    for c in informe["checks"]:
        marca = "✓" if c["passed"] else "✗"
        print(f"  {marca} {c['name']}: {c['detail']}")
    print("\n" + ("✓ VERIFICATION OK" if informe["ok"]
                  else "✗ VERIFICATION FAILED — check the ✗ above"))
    return informe["ok"]


def _cargar_json(nombre):
    """Carga output/kol_profile_{Nombre}.json (para --solo-dashboard/pdf)."""
    ruta = os.path.join(OUTPUT_DIR, f"kol_profile_{_slug(nombre)}.json")
    if not os.path.exists(ruta):
        print(f"✗ {ruta} does not exist. Run without --*-only first to "
              "generate the JSON.")
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Builds intelligence on a KOL from their name and "
                    "institution.")
    # Los posicionales conservan su `dest` en castellano (args.nombre,
    # args.institucion): solo cambia el nombre que se muestra en la ayuda.
    p.add_argument("nombre", metavar="name",
                   help="KOL name, e.g. 'Dra. Teresa San-Miguel'")
    p.add_argument("institucion", nargs="?", default=None,
                   metavar="institution",
                   help="Where they work, e.g. 'Hospital La Fe'. The city is "
                        "derived from this.")
    p.add_argument("--city", dest="ciudad", metavar="CITY", default=None,
                   help="Only to force it; derived by default.")
    p.add_argument("--country", dest="pais", metavar="COUNTRY", default=None)
    p.add_argument("--orcid", default=None)
    p.add_argument("--specialty", dest="especialidad", metavar="SPECIALTY",
                   default=None,
                   help="Only to force it; inferred by default.")
    p.add_argument("--surname", dest="apellidos", metavar="SURNAME",
                   default=None,
                   help="Explicit surname(s), for ambiguous names.")
    p.add_argument("--retmax", type=int, default=pubmed_agent.MAX_PAPERS,
                   help="Maximum PMIDs to retrieve (1000 by default).")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Show the detail of the process (network, cache).")
    p.add_argument("--no-cache", action="store_true",
                   help="Force fresh calls to the APIs.")
    p.add_argument("--json-only", dest="solo_json", action="store_true")
    p.add_argument("--dashboard-only", dest="solo_dashboard", action="store_true")
    p.add_argument("--pdf-only", dest="solo_pdf", action="store_true")
    return p.parse_args(argv)


def _titulo(texto):
    print("\n" + texto)
    print("=" * len(texto))


def main(argv=None):
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    # Con -v se ven los avisos del motor (429, red inestable, caché corrupta).
    # Sin -v solo se muestran los errores: la salida normal sigue limpia.
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.ERROR,
        format="  [%(levelname)s] %(message)s")

    # --solo-dashboard / --solo-pdf: regenerar desde un JSON ya existente.
    if args.solo_dashboard or args.solo_pdf:
        perfil = _cargar_json(args.nombre)
        if perfil is None:
            return 1
        if args.solo_dashboard:
            ruta = dashboard.render_dashboard(perfil, OUTPUT_DIR)
            print(f"✓ Dashboard regenerado: {ruta}")
        if args.solo_pdf:
            ruta = pdf.render_pdf(perfil, OUTPUT_DIR)
            print(f"✓ Dossier PDF regenerado: {ruta}")
        return 0

    # --- Paso 0: completar lo que no hace falta preguntar ---
    # Bastan nombre + centro: la ciudad se deduce del centro y la especialidad
    # se infiere despues de los propios papers (ver perfil_cientifico.py).
    ciudad_deducida = None
    if not args.ciudad and args.institucion:
        ciudad_deducida = centros.deducir_ciudad(args.institucion)
        args.ciudad = ciudad_deducida
    if args.institucion:
        args.institucion = centros.limpiar_centro(args.institucion)

    # --- Paso 1: estrategia de desambiguacion ---
    estrategia = disambiguator.build_strategy(
        args.nombre, institution=args.institucion, city=args.ciudad,
        country=args.pais, orcid=args.orcid, specialty=args.especialidad,
        surname=args.apellidos)

    _titulo(f"KOL: {args.nombre}")
    print(f"Institution  : {args.institucion or '(not given)'}")
    sufijo_ciudad = " (derived from the centre)" if ciudad_deducida else ""
    print(f"City         : {(args.ciudad or '(not given)')}{sufijo_ciudad}")
    print(f"PubMed query : {estrategia['query_used']}")
    print(f"Location     : {estrategia['location_terms'] or '(none)'}")
    print(f"Confidence   : {estrategia['confidence'].upper()}")
    print(f"Notes        : {estrategia['notes']}")

    # --- Paso 2: busqueda + filtrado en PubMed ---
    _titulo("PubMed — search and homonym filtering")
    try:
        res = pubmed_agent.analyze(
            estrategia, retmax=args.retmax, email=None,
            use_cache=not args.no_cache)
    except Exception as e:  # red caida, timeout, etc.: fallar con honestidad
        print(f"✗ Error querying PubMed: {e}")
        return 2

    log = res["log"]
    print(f"PMIDs found by the query   : {len(res['pmids_found'])}")
    print(f"Papers analysed            : {log['input_count']}")
    print(f"  ✓ verified (the KOL's)   : {log['verified_count']}")
    print(f"  ~ unverified (probable)  : {log['unverified_count']}")
    print(f"  ✗ excluded (homonyms)    : {log['excluded_count']}")
    if log["excluded_reasons"]:
        print("  Exclusion reasons:")
        for motivo, n in sorted(log["excluded_reasons"].items(),
                                key=lambda kv: -kv[1]):
            print(f"    - {motivo}: {n}")

    # Muestra los 5 papers verificados mas recientes como muestra.
    verificados = sorted(res["verified"],
                         key=lambda p: p.get("year", ""), reverse=True)
    if verificados:
        _titulo("Sample of verified publications (max. 5)")
        for p in verificados[:5]:
            print(f"  [{p['year']}] {p['title'][:70]}")
            print(f"          {p['journal']} · PMID {p['pmid']} · "
                  f"{p['author_position']} author")

    # --- Paso 3: ensayos clinicos (verificados por localizacion) ---
    _titulo("ClinicalTrials.gov — trials verified by location")
    try:
        trials_result = clinicaltrials_agent.find_trials(
            args.nombre, estrategia["surname"], estrategia["initial"],
            estrategia["location_terms"], city=args.ciudad,
            use_cache=not args.no_cache)
    except Exception as e:
        print(f"⚠  ClinicalTrials.gov could not be queried ({e}).")
        # Se marca el fallo: "no se pudo mirar" NO es "no hay ensayos".
        trials_result = {"trials": None, "log": {},
                         "error": str(e) or e.__class__.__name__}

    ct_log = trials_result.get("log", {})
    if trials_result.get("error"):
        print("⚠  NOT CHECKED: the trials section is left unverified. "
              "Do not read it as an absence of trials.")
    elif trials_result["trials"] is None:
        print(f"Studies found : {ct_log.get('studies_found', 0)}")
        print("✓ 0 verified trials (VALID result — no work by homonyms is "
              "attributed).")
    else:
        t = trials_result["trials"]
        print(f"✓ {t['verified_count']} trial(s) verified by location:")
        for it in t["items"][:5]:
            print(f"    {it['nct']} · {it['phase']} · {it['role']} · {it['location'][:45]}")

    # --- Paso 4: metricas academicas ---
    # (a) agregado por nombre: NO VERIFICADO, mezcla homonimos.
    metrics = europepmc_agent.get_metrics(args.nombre,
                                          use_cache=not args.no_cache)
    # (b) h-index sobre el set YA desambiguado: este si es atribuible.
    pmids_del_kol = [pp.get("pmid") for pp in
                     (res.get("verified", []) + res.get("unverified", []))
                     if pp.get("pmid")]
    metrics_verified = europepmc_agent.get_verified_metrics(
        pmids_del_kol, use_cache=not args.no_cache)
    if metrics_verified:
        metrics_verified["papers_verificados"] = len(res.get("verified", []))
        metrics_verified["papers_sin_verificar"] = len(res.get("unverified", []))
        print(f"h-index (disambiguated set) : {metrics_verified['hindex']} "
              f"· {metrics_verified['citations']:,} citations")

    # --- Paso 5: ensamblar kol_profile.json (la fuente de verdad) ---
    perfil = profile.build_profile(
        args.nombre, args.institucion, args.ciudad, args.pais, args.orcid,
        args.especialidad, estrategia, res, trials_result, metrics,
        metrics_verified=metrics_verified)
    ruta_json = profile.save_profile(perfil, OUTPUT_DIR)

    _titulo("Scientific profile (derived from their publications)")
    sci = perfil["perfil_cientifico"]
    esp = sci["especialidad"]
    print(f"Field         : {esp['nombre'] or '(undetermined)'} "
          f"[{esp['origen']}, confidence {esp['confianza']}]")
    if sci["servicio"]:
        print(f"Department    : {sci['servicio']['nombre']}")
    lineas = sci["lineas_investigacion"]
    if lineas:
        etiqueta = ("Research lines" if any(l["recurrente"] for l in lineas)
                    else "Topics")
        print(f"{etiqueta:14}: " + ", ".join(
            f"{l['tema']} ({l['papers']})" for l in lineas[:5]))
    if sci["colaboradores"]:
        print("Co-authors    : " + ", ".join(
            f"{c['nombre']} ({c['papers']})" for c in sci["colaboradores"][:4]))
    print(f"\nSummary: {sci['resumen']}")

    _titulo("KOL Score and profile")
    sc = perfil["score"]
    print(f"KOL Score : {sc['total']}/100   →   {sc['tier']}")
    print("Breakdown :")
    for k, v in sc["breakdown"].items():
        print(f"    {k:22}: {v}")
    print(f"\n✓ Profile saved to: {ruta_json}")

    if args.solo_json:
        print("\n(--json-only) Done: only the JSON was generated.")
        return 0

    # --- Paso 6: render (dashboard HTML + dossier PDF) ---
    _titulo("Deliverables")
    ruta_html, ruta_pdf = _render(perfil)

    # --- Paso 7: verificación final automática ---
    ok = _verificar(perfil, ruta_html, ruta_pdf)

    print("\n✓ Done. Profile, dashboard and dossier built from the same "
          "source of truth (kol_profile.json).")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
