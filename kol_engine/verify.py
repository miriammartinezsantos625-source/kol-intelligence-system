"""
verify — Paso 9 automatizado (verificacion final).

Antes era una checklist manual; ahora es una funcion que corre sola y devuelve
un informe de comprobaciones. Cablea las reglas duras del brief:

  - El PDF tiene exactamente 5 paginas.
  - El nombre del KOL ACTUAL aparece en ambos entregables.
  - NINGUN nombre de KOL previo (plantillas anteriores) se ha colado.  <- bug
    estrella del skill original (nombre/cifras heredados de una plantilla).
  - PMIDs y NCTs estan bien formados.
  - Las cifras del badge (score/tier) coinciden con el bloque score.

Devuelve {"ok": bool, "checks": [{name, passed, detail, critical}]}.
"""

import re

from pypdf import PdfReader

from .text_utils import normalize

# Nombres de KOLs de plantillas/ejemplos previos que NUNCA deben aparecer en un
# entregable real. Si alguno se cuela, es contaminacion de plantilla.
# (Ampliable: cada vez que se detecte una fuga, se anade aqui.)
DEFAULT_BLOCKLIST = [
    "Jesus San Miguel",     # homonimo clasico (Pamplona) — no debe filtrarse
    "John Doe",
    "Jane Smith",
    "Nombre Apellido",
]


def _leer_pdf_texto(pdf_path):
    reader = PdfReader(pdf_path)
    paginas = reader.pages
    texto = "\n".join(p.extract_text() or "" for p in paginas)
    return len(paginas), texto


def _check(name, passed, detail, critical=True):
    return {"name": name, "passed": bool(passed), "detail": detail,
            "critical": critical}


def verify_deliverables(profile, html_path, pdf_path, blocklist=None):
    """Ejecuta todas las comprobaciones y devuelve el informe."""
    if blocklist is None:
        blocklist = DEFAULT_BLOCKLIST

    checks = []
    ident = profile["identity"]
    nombre = ident["full_name"]

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()
    n_paginas, pdf_texto = _leer_pdf_texto(pdf_path)

    html_norm = normalize(html)
    pdf_norm = normalize(pdf_texto)
    nombre_norm = normalize(nombre)

    # 1) PDF de 5 paginas.
    checks.append(_check(
        "5-page PDF", n_paginas == 5,
        f"{n_paginas} page(s)"))

    # 2) El nombre del KOL actual aparece en ambos entregables.
    checks.append(_check(
        "KOL name in the dashboard", nombre_norm in html_norm,
        f"«{nombre}»"))
    checks.append(_check(
        "KOL name in the PDF", nombre_norm in pdf_norm,
        f"«{nombre}»"))

    # 3) Ningun nombre de KOL previo (excluyendo el actual).
    # Un nombre de la blocklist puede aparecer legitimamente como COAUTOR del
    # KOL actual (p. ej. dos hematologos que firman juntos). Eso no es
    # contaminacion de plantilla: es un dato real del perfil, y marcarlo como
    # fuga seria un falso positivo que invalida un dossier correcto.
    legitimos = {normalize(c.get("nombre", ""))
                 for c in (profile.get("perfil_cientifico", {})
                           .get("colaboradores") or [])}

    fugas = []
    for prev in blocklist:
        pn = normalize(prev)
        if not pn or pn == nombre_norm:
            continue
        if any(pn in coautor for coautor in legitimos if coautor):
            continue        # coautor real, no fuga
        if pn in html_norm or pn in pdf_norm:
            fugas.append(prev)
    checks.append(_check(
        "0 names from previous KOLs", not fugas,
        "no leaks" if not fugas else f"leaks: {', '.join(fugas)}"))

    # 4) PMIDs bien formados (solo digitos).
    pmids = [it.get("pmid", "") for it in profile["publications"]["items"]]
    pmids_malos = [p for p in pmids if not re.fullmatch(r"\d+", str(p))]
    checks.append(_check(
        "PMIDs bien formados", not pmids_malos,
        f"{len(pmids)} PMIDs" if not pmids_malos
        else f"malformados: {pmids_malos[:5]}"))

    # 5) NCTs bien formados (si hay ensayos).
    if profile.get("trials"):
        ncts = [it.get("nct", "") for it in profile["trials"]["items"]]
        ncts_malos = [n for n in ncts if not re.fullmatch(r"NCT\d{8}", str(n))]
        checks.append(_check(
            "NCTs bien formados", not ncts_malos,
            f"{len(ncts)} NCTs" if not ncts_malos
            else f"malformados: {ncts_malos[:5]}"))

    # 6) Coherencia del badge con el score (evita cifras heredadas).
    badge = ident.get("badge", {})
    sc = profile.get("score", {})
    coherente = (badge.get("score") == sc.get("total")
                 and badge.get("tier") == sc.get("tier"))
    checks.append(_check(
        "Badge consistent with the score", coherente,
        f"badge {badge.get('score')}/{badge.get('tier')} vs "
        f"score {sc.get('total')}/{sc.get('tier')}"))

    ok = all(c["passed"] for c in checks if c["critical"])
    return {"ok": ok, "checks": checks, "pdf_pages": n_paginas}
