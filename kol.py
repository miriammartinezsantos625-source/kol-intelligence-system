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
    _titulo("Verificación final (Paso 9)")
    informe = verify.verify_deliverables(perfil, ruta_html, ruta_pdf)
    for c in informe["checks"]:
        marca = "✓" if c["passed"] else "✗"
        print(f"  {marca} {c['name']}: {c['detail']}")
    print("\n" + ("✓ VERIFICACIÓN OK" if informe["ok"]
                  else "✗ VERIFICACIÓN FALLIDA — revisar los ✗ de arriba"))
    return informe["ok"]


def _cargar_json(nombre):
    """Carga output/kol_profile_{Nombre}.json (para --solo-dashboard/pdf)."""
    ruta = os.path.join(OUTPUT_DIR, f"kol_profile_{_slug(nombre)}.json")
    if not os.path.exists(ruta):
        print(f"✗ No existe {ruta}. Ejecuta primero sin --solo-* para "
              "generar el JSON.")
        return None
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)


def _parse_args(argv):
    p = argparse.ArgumentParser(
        description="Genera inteligencia sobre un KOL a partir de su nombre e "
                    "institucion.")
    p.add_argument("nombre", help="Nombre del KOL, ej. 'Dra. Teresa San-Miguel'")
    p.add_argument("institucion", nargs="?", default=None,
                   help="Donde trabaja, ej. 'Hospital La Fe'. La ciudad se "
                        "deduce de aqui.")
    p.add_argument("--ciudad", default=None,
                   help="Solo si quieres forzarla; por defecto se deduce.")
    p.add_argument("--pais", default=None)
    p.add_argument("--orcid", default=None)
    p.add_argument("--especialidad", default=None,
                   help="Solo si quieres forzarla; por defecto se infiere.")
    p.add_argument("--apellidos", default=None,
                   help="Apellido(s) explícitos (para nombres ambiguos).")
    p.add_argument("--retmax", type=int, default=pubmed_agent.MAX_PAPERS,
                   help="Maximo de PMIDs a recuperar (por defecto 1000).")
    p.add_argument("--verbose", "-v", action="store_true",
                   help="Muestra el detalle del proceso (avisos de red, caché).")
    p.add_argument("--no-cache", action="store_true",
                   help="Fuerza llamadas frescas a las APIs.")
    # Flags de fases futuras (se aceptan pero avisan de que aun no hacen nada).
    p.add_argument("--solo-json", action="store_true")
    p.add_argument("--solo-dashboard", action="store_true")
    p.add_argument("--solo-pdf", action="store_true")
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
    print(f"Institución   : {args.institucion or '(no indicada)'}")
    sufijo_ciudad = " (deducida del centro)" if ciudad_deducida else ""
    print(f"Ciudad        : {(args.ciudad or '(no indicada)')}{sufijo_ciudad}")
    print(f"Query PubMed  : {estrategia['query_used']}")
    print(f"Localización  : {estrategia['location_terms'] or '(ninguna)'}")
    print(f"Confianza     : {estrategia['confidence'].upper()}")
    print(f"Notas         : {estrategia['notes']}")

    # --- Paso 2: busqueda + filtrado en PubMed ---
    _titulo("PubMed — búsqueda y filtrado de homónimos")
    try:
        res = pubmed_agent.analyze(
            estrategia, retmax=args.retmax, email=None,
            use_cache=not args.no_cache)
    except Exception as e:  # red caida, timeout, etc.: fallar con honestidad
        print(f"✗ Error consultando PubMed: {e}")
        return 2

    log = res["log"]
    print(f"PMIDs encontrados por la query : {len(res['pmids_found'])}")
    print(f"Papers analizados             : {log['input_count']}")
    print(f"  ✓ verificados (del KOL)     : {log['verified_count']}")
    print(f"  ~ sin verificar (probables) : {log['unverified_count']}")
    print(f"  ✗ excluidos (homónimos)     : {log['excluded_count']}")
    if log["excluded_reasons"]:
        print("  Motivos de exclusión:")
        for motivo, n in sorted(log["excluded_reasons"].items(),
                                key=lambda kv: -kv[1]):
            print(f"    - {motivo}: {n}")

    # Muestra los 5 papers verificados mas recientes como muestra.
    verificados = sorted(res["verified"],
                         key=lambda p: p.get("year", ""), reverse=True)
    if verificados:
        _titulo("Muestra de publicaciones verificadas (máx. 5)")
        for p in verificados[:5]:
            print(f"  [{p['year']}] {p['title'][:70]}")
            print(f"          {p['journal']} · PMID {p['pmid']} · "
                  f"autoría {p['author_position']}")

    # --- Paso 3: ensayos clinicos (verificados por localizacion) ---
    _titulo("ClinicalTrials.gov — ensayos verificados por localización")
    try:
        trials_result = clinicaltrials_agent.find_trials(
            args.nombre, estrategia["surname"], estrategia["initial"],
            estrategia["location_terms"], city=args.ciudad,
            use_cache=not args.no_cache)
    except Exception as e:
        print(f"⚠  No se pudo consultar ClinicalTrials.gov ({e}).")
        # Se marca el fallo: "no se pudo mirar" NO es "no hay ensayos".
        trials_result = {"trials": None, "log": {},
                         "error": str(e) or e.__class__.__name__}

    ct_log = trials_result.get("log", {})
    if trials_result.get("error"):
        print("⚠  NO COMPROBADO: el apartado de ensayos queda sin verificar. "
              "No interpretar como ausencia de ensayos.")
    elif trials_result["trials"] is None:
        print(f"Estudios encontrados : {ct_log.get('studies_found', 0)}")
        print("✓ 0 ensayos verificados (resultado VÁLIDO — no se atribuye "
              "trabajo de homónimos).")
    else:
        t = trials_result["trials"]
        print(f"✓ {t['verified_count']} ensayo(s) verificado(s) por localización:")
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
        print(f"h-index (set desambiguado) : {metrics_verified['hindex']} "
              f"· {metrics_verified['citations']:,} citas".replace(",", "."))

    # --- Paso 5: ensamblar kol_profile.json (la fuente de verdad) ---
    perfil = profile.build_profile(
        args.nombre, args.institucion, args.ciudad, args.pais, args.orcid,
        args.especialidad, estrategia, res, trials_result, metrics,
        metrics_verified=metrics_verified)
    ruta_json = profile.save_profile(perfil, OUTPUT_DIR)

    _titulo("Perfil científico (deducido de sus publicaciones)")
    sci = perfil["perfil_cientifico"]
    esp = sci["especialidad"]
    print(f"Área          : {esp['nombre'] or '(no determinada)'} "
          f"[{esp['origen']}, confianza {esp['confianza']}]")
    if sci["servicio"]:
        print(f"Servicio      : {sci['servicio']['nombre']}")
    lineas = sci["lineas_investigacion"]
    if lineas:
        etiqueta = ("Líneas rec." if any(l["recurrente"] for l in lineas)
                    else "Temas")
        print(f"{etiqueta:14}: " + ", ".join(
            f"{l['tema']} ({l['papers']})" for l in lineas[:5]))
    if sci["colaboradores"]:
        print("Coautores     : " + ", ".join(
            f"{c['nombre']} ({c['papers']})" for c in sci["colaboradores"][:4]))
    print(f"\nResumen: {sci['resumen']}")

    _titulo("KOL Score y perfil")
    sc = perfil["score"]
    print(f"KOL Score : {sc['total']}/100   →   {sc['tier']}")
    print("Desglose  :")
    for k, v in sc["breakdown"].items():
        print(f"    {k:22}: {v}")
    print(f"\n✓ Perfil guardado en: {ruta_json}")

    if args.solo_json:
        print("\n(--solo-json) Fin: solo se generó el JSON.")
        return 0

    # --- Paso 6: render (dashboard HTML + dossier PDF) ---
    _titulo("Entregables")
    ruta_html, ruta_pdf = _render(perfil)

    # --- Paso 7: verificación final automática ---
    ok = _verificar(perfil, ruta_html, ruta_pdf)

    print("\n✓ Listo. Perfil, dashboard y dossier generados desde la misma "
          "fuente de verdad (kol_profile.json).")
    return 0 if ok else 3


if __name__ == "__main__":
    raise SystemExit(main())
