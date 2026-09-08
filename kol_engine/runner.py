"""
runner — ejecuta el pipeline completo y devuelve los datos (sin imprimir).

Une todos los agentes en una sola llamada, para que tanto el CLI (kol.py) como
la interfaz web (app.py) usen exactamente la misma logica. Devuelve un dict con
el perfil, las rutas de los entregables y el informe de verificacion.
"""

import logging
import os

from . import (cache_utils, centros, clinicaltrials_agent, dashboard,
               disambiguator, europepmc_agent, pdf, profile, pubmed_agent,
               verify)

logger = logging.getLogger(__name__)

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")


def run_pipeline(nombre, institucion=None, ciudad=None, pais=None, orcid=None,
                 especialidad=None, surname=None, retmax=None, use_cache=True,
                 output_dir=OUTPUT_DIR):
    """Ejecuta desambiguacion -> PubMed -> ensayos -> metricas -> perfil ->
    render (dashboard + PDF) -> verificacion.

    Solo son obligatorios `nombre` e `institucion`: la ciudad, si no se pasa,
    se deduce del nombre del centro (ver centros.py), y la especialidad se
    infiere de los propios papers (ver perfil_cientifico.py). Asi la interfaz
    puede pedir dos datos en vez de siete sin perder desambiguacion.

    `surname` (opcional): apellido(s) explicitos, para nombres ambiguos.

    Devuelve:
      {estrategia, analysis, trials_result, perfil, json_path, html_path,
       pdf_path, verify_report, ciudad_deducida}
    """
    # Las entradas ya caducadas solo ocupan disco: se limpian al empezar.
    try:
        cache_utils.prune()
    except OSError as e:
        logger.warning("could not prune the cache: %s", e)

    logger.info("profile requested: %s (%s)", nombre, institucion or "no centre")

    # Sin tope explicito se usa el del agente (1.000), no 200: con 200 un KOL
    # prolifico perdia el 70% de su obra y su biografia salia recortada.
    if retmax is None:
        retmax = pubmed_agent.MAX_PAPERS

    # La ciudad escrita a mano manda; si no la hay, la deducimos del centro.
    ciudad_deducida = None
    if not ciudad and institucion:
        ciudad_deducida = centros.deducir_ciudad(institucion)
        ciudad = ciudad_deducida
    # 'Hospital La Fe, Valencia' -> 'Hospital La Fe' (la ciudad ya va aparte).
    if institucion:
        institucion = centros.limpiar_centro(institucion)

    estrategia = disambiguator.build_strategy(
        nombre, institution=institucion, city=ciudad, country=pais,
        orcid=orcid, specialty=especialidad, surname=surname)

    analysis = pubmed_agent.analyze(estrategia, retmax=retmax,
                                    use_cache=use_cache)

    try:
        trials_result = clinicaltrials_agent.find_trials(
            nombre, estrategia["surname"], estrategia["initial"],
            estrategia["location_terms"], city=ciudad, use_cache=use_cache)
    except Exception as e:
        # "La API fallo" y "no hay ensayos" NO son lo mismo. Antes ambos
        # daban trials=None y el dossier afirmaba "resultado valido" sobre
        # algo que nunca se comprobo. Se marca el fallo y viaja al perfil.
        trials_result = {"trials": None, "log": {}, "error": str(e) or
                         e.__class__.__name__}

    metrics = europepmc_agent.get_metrics(nombre, use_cache=use_cache)

    # h-index real: solo sobre los papers que el filtro de homonimos ya ha
    # atribuido a este medico (verified + unverified, nunca los excluidos).
    pmids_del_kol = [pp.get("pmid") for pp in
                     (analysis.get("verified", []) + analysis.get("unverified", []))
                     if pp.get("pmid")]
    metrics_verified = europepmc_agent.get_verified_metrics(
        pmids_del_kol, use_cache=use_cache)
    if metrics_verified:
        # Sobre que se ha calculado exactamente: un h-index de 12 junto a
        # "0 publicaciones verificadas" desconcierta si no se dice que el
        # calculo incluye tambien los papers atribuidos pero sin confirmar
        # por afiliacion.
        metrics_verified["papers_verificados"] = len(analysis.get("verified", []))
        metrics_verified["papers_sin_verificar"] = len(
            analysis.get("unverified", []))

    perfil = profile.build_profile(
        nombre, institucion, ciudad, pais, orcid, especialidad,
        estrategia, analysis, trials_result, metrics,
        metrics_verified=metrics_verified)

    json_path = profile.save_profile(perfil, output_dir)
    html_path = dashboard.render_dashboard(perfil, output_dir)
    pdf_path = pdf.render_pdf(perfil, output_dir)
    verify_report = verify.verify_deliverables(perfil, html_path, pdf_path)
    if not verify_report["ok"]:
        fallos = [c["name"] for c in verify_report["checks"] if not c["passed"]]
        logger.error("verification FAILED for %s: %s", nombre, fallos)
    else:
        logger.info("profile complete: %s — score %s (%s), %d publications",
                    nombre, perfil["score"]["total"], perfil["score"]["tier"],
                    perfil["publications"]["verified_count"])

    return {
        "estrategia": estrategia,
        "analysis": analysis,
        "trials_result": trials_result,
        "perfil": perfil,
        "json_path": json_path,
        "html_path": html_path,
        "pdf_path": pdf_path,
        "verify_report": verify_report,
        "ciudad_deducida": ciudad_deducida,
    }
