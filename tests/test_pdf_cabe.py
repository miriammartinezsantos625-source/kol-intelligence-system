"""
Test de que el dossier SIEMPRE cabe en 5 paginas.

verify.py exige 5 paginas exactas, asi que un desbordamiento no es un detalle
estetico: tumba la entrega entera (exit 3). La pagina 4 (perfil cientifico) es
la que mas varia entre KOLs — uno con 13 papers y otro con 200, 14 ensayos y
20 anios de actividad no ocupan lo mismo.

Poner topes fijos "a ojo" no funcionaba: cada vez que se ajustaban para un KOL,
otro se desbordaba. Ahora `_pagina4_ajustada` MIDE la altura y elige el nivel de
detalle que cabe. Este test lo comprueba en los dos extremos.
"""

from pypdf import PdfReader

from kol_engine import disambiguator, pdf, profile


def _perfil(n_papers, n_ensayos, n_anios):
    """Perfil sintetico del tamano pedido (build_profile es puro, sin red)."""
    est = disambiguator.build_strategy(
        "Dra. Teresa San-Miguel", institution="Hospital La Fe", city="Valencia")
    papers = []
    for i in range(n_papers):
        anio = 2026 - (i % n_anios)
        papers.append({
            "pmid": str(10000000 + i),
            "title": ("Estudio muy largo sobre glioblastoma multiforme y su "
                      "manejo quirurgico en pacientes de edad avanzada " + str(i)),
            "journal": f"Journal of Very Long Names {i % 25}",
            "year": str(anio), "author_position": "primera",
            "mesh": ["Glioblastoma", "Brain Neoplasms", "Mutation",
                     "Neoplasm Recurrence, Local", "Meningeal Neoplasms",
                     "Antineoplastic Combined Chemotherapy Protocols"],
            "mesh_major": ["Glioblastoma", "Brain Neoplasms"],
            "keywords": [], "pubtypes": ["Review", "Meta-Analysis"],
            "matched_affiliation": "Department of Pathology, Hospital La Fe",
            "authors": [
                {"last": "San-Miguel", "initials": "T", "fore": "Teresa",
                 "affiliation": "", "orcid": ""}
            ] + [{"last": f"Coautor-De-Apellido-Largo{j}", "initials": "AB",
                  "fore": "", "affiliation": "", "orcid": ""} for j in range(8)],
        })
    analysis = {"verified": papers, "unverified": [], "excluded": [],
                "log": {"excluded_count": 0, "excluded_reasons": {}}}
    trials = None
    if n_ensayos:
        trials = {"trials": {"verified_count": n_ensayos, "items": [
            {"nct": f"NCT{20000000 + i}",
             "title": "Ensayo clinico internacional multicentrico de nombre "
                      "extenso para un farmaco en investigacion",
             "phase": "PHASE3", "role": "Principal Investigator",
             "location": "Valencia"} for i in range(n_ensayos)]}, "log": {}}
    else:
        trials = {"trials": None, "log": {}}
    metrics = {"hindex_europepmc": "NO VERIFICADO", "citations": "NO VERIFICADO",
               "epmc_raw_hits": 10, "note": "x"}
    return profile.build_profile(
        "Dra. Teresa San-Miguel", "Hospital La Fe", "Valencia", "España",
        None, None, est, analysis, trials, metrics)


def _paginas(perfil, tmp_path):
    return len(PdfReader(pdf.render_pdf(perfil, str(tmp_path))).pages)


def test_kol_pequeno_cabe_en_5_paginas(tmp_path):
    assert _paginas(_perfil(n_papers=3, n_ensayos=0, n_anios=2), tmp_path) == 5


def test_kol_prolifico_con_muchos_ensayos_cabe_en_5_paginas(tmp_path):
    """Caso real: Josep Tabernero — 197 papers y 14 ensayos se iban a 6 hojas."""
    assert _paginas(_perfil(n_papers=200, n_ensayos=14, n_anios=25),
                    tmp_path) == 5


def test_caso_extremo_cabe_en_5_paginas(tmp_path):
    """Mucho mas de lo que da de si un KOL real: el ajuste debe aguantar."""
    assert _paginas(_perfil(n_papers=400, n_ensayos=40, n_anios=40),
                    tmp_path) == 5


def test_el_ajuste_conserva_el_maximo_detalle_que_quepa(tmp_path):
    """Un KOL pequeno no debe salir recortado: si cabe todo, se enseña todo."""
    perfil = _perfil(n_papers=3, n_ensayos=0, n_anios=2)
    texto = "\n".join(p.extract_text() or ""
                      for p in PdfReader(pdf.render_pdf(perfil, str(tmp_path))).pages)
    assert "Coautores habituales" in texto
    assert "Actividad por año" in texto


# ----------------------------------------------------------------------
#  Que el texto quepa en su fila, no solo el dossier en sus 5 paginas
# ----------------------------------------------------------------------

def test_ningun_estilo_tiene_el_interlineado_mas_corto_que_su_letra():
    """El `leading` reserva la altura de la fila. Si es menor que el cuerpo de
    letra, el texto se sale de su celda.

    Paso de verdad: los KPIs se dibujaban con `<font size=18>` dentro de un
    estilo de 10pt, cuyo interlineado era 12. Con un KOL de tres cifras (222
    publicaciones, caso Luis Martí-Bonmatí) los números se salían de su fila y
    la raya de la tabla les cruzaba por la base.
    """
    estilos = list(pdf._styles().items()) + [
        ("kpi_valor", pdf._kpi_styles()[0]),
        ("kpi_etiqueta", pdf._kpi_styles()[1]),
    ]
    for nombre, estilo in estilos:
        assert estilo.leading >= estilo.fontSize, (
            f"el estilo «{nombre}» dibuja letra de {estilo.fontSize}pt en una "
            f"línea de {estilo.leading}pt: el texto se saldrá de su celda")


def test_los_kpis_de_tres_cifras_no_ensanchan_la_tabla():
    """La fila de KPIs mide siempre 17 cm, con 0 o con 222 publicaciones."""
    ancho = lambda pares: sum(pdf._kpi_table(pares)._argW)
    pequenos = [("0", "Publicaciones verif."), ("0", "Ensayos verif.")]
    grandes = [("222", "Publicaciones verif."), ("152", "Ensayos verif.")]
    assert round(ancho(pequenos), 2) == round(ancho(grandes), 2)
