"""
Test de verify (Paso 9). Genera entregables reales (sin red: dashboard y PDF
son offline) y comprueba las verificaciones finales.
"""

from kol_engine import dashboard, disambiguator, pdf, profile, verify


def _perfil(titulo_pub="Estudio sobre glioblastoma"):
    """Construye un perfil completo con datos sinteticos (build_profile es puro)."""
    est = disambiguator.build_strategy(
        "Dra. Teresa San-Miguel", institution="Hospital La Fe", city="Valencia")
    items = [{"pmid": "12345678", "title": titulo_pub, "journal": "Neuropath",
              "year": "2024", "author_position": "first"}]
    analysis = {"verified": items, "unverified": [],
                "log": {"excluded_count": 0, "excluded_reasons": {}}}
    metrics = {"hindex_europepmc": "NOT VERIFIED",
               "citations": "NOT VERIFIED", "epmc_raw_hits": 10, "note": "x"}
    return profile.build_profile(
        "Dra. Teresa San-Miguel", "Hospital La Fe", "Valencia", "España",
        None, "Neuropatologia", est, analysis,
        {"trials": None, "log": {}}, metrics)


def _render(perfil, tmp):
    html = dashboard.render_dashboard(perfil, str(tmp))
    ppdf = pdf.render_pdf(perfil, str(tmp))
    return html, ppdf


def test_deliverables_validos_pasan(tmp_path):
    perfil = _perfil()
    html, ppdf = _render(perfil, tmp_path)
    informe = verify.verify_deliverables(perfil, html, ppdf)
    assert informe["ok"] is True
    assert informe["pdf_pages"] == 5


def test_detecta_fuga_de_nombre_previo(tmp_path):
    # Un titulo con un nombre de KOL previo se debe detectar.
    perfil = _perfil(titulo_pub="Trabajo conjunto con Zzz Previous Kol")
    html, ppdf = _render(perfil, tmp_path)
    informe = verify.verify_deliverables(perfil, html, ppdf,
                                         blocklist=["Zzz Previous Kol"])
    fuga = next(c for c in informe["checks"]
                if c["name"] == "0 names from previous KOLs")
    assert fuga["passed"] is False
    assert informe["ok"] is False


def test_detecta_badge_incoherente(tmp_path):
    perfil = _perfil()
    html, ppdf = _render(perfil, tmp_path)
    perfil["identity"]["badge"]["score"] = 999  # cifra heredada / incoherente
    informe = verify.verify_deliverables(perfil, html, ppdf)
    badge = next(c for c in informe["checks"]
                 if c["name"] == "Badge consistent with the score")
    assert badge["passed"] is False
    assert informe["ok"] is False
