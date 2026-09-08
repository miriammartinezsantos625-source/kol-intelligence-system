"""
Test del perfil cientifico — el bloque que responde "quien es este medico".

Se apoya en datos que PubMed ya devolvia y que antes se tiraban: descriptores
MeSH, afiliacion completa del autor y coautores. Todo el modulo es puro, asi
que estos tests no tocan la red.

Lo que se protege aqui:
  - el SERVICIO del KOL manda sobre el recuento de MeSH al elegir area
  - no se llama "linea de investigacion" a un tema que aparece una sola vez
  - los MeSH genericos (Humans, Male...) nunca son un tema
  - sin evidencia, se devuelve None en vez de inventar
"""

from kol_engine import perfil_cientifico as pc


def _paper(anio, mesh=(), major=(), journal="J Test", titulo="T",
           afiliacion="", autores=(), pubtypes=()):
    """Paper minimo con la forma que produce pubmed_agent.filter_homonyms."""
    return {
        "pmid": "1", "title": titulo, "journal": journal, "year": str(anio),
        "mesh": list(mesh), "mesh_major": list(major), "keywords": [],
        "pubtypes": list(pubtypes),
        "matched_affiliation": afiliacion,
        "authors": [{"last": a, "initials": "X", "affiliation": "",
                     "orcid": "", "fore": ""} for a in autores],
    }


# ----------------------------------------------------------------------
#  Especialidad
# ----------------------------------------------------------------------

def test_el_servicio_manda_sobre_el_recuento_de_mesh():
    """Un cirujano digestivo que publica de cancer NO es oncologo medico.

    Sus MeSH votan 'Oncología médica' tanto o mas que cirugia; solo el servicio
    que consta en su afiliacion desempata bien. Este es justo el caso real de
    Elias Martinez Lopez.
    """
    afil = "Department of General and Digestive Surgery, Hospital Doctor Peset"
    papers = [
        _paper(2025, mesh=["Colorectal Neoplasms", "Colectomy"], afiliacion=afil),
        _paper(2024, mesh=["Colonic Neoplasms", "Laparoscopy"], afiliacion=afil),
        _paper(2023, mesh=["Rectal Neoplasms", "Anastomosis, Surgical"],
               afiliacion=afil),
    ]
    esp = pc.inferir_especialidad(papers, servicio_texto=afil)
    assert esp["nombre"] == "General and digestive surgery"
    assert esp["origen_senal"] == "department"


def test_sin_servicio_decide_el_recuento():
    papers = [
        _paper(2025, mesh=["Retinal Diseases", "Macular Degeneration"]),
        _paper(2024, mesh=["Uveitis", "Eye Diseases"]),
        _paper(2023, mesh=["Glaucoma"]),
    ]
    esp = pc.inferir_especialidad(papers)
    assert esp["nombre"] == "Ophthalmology"
    assert esp["origen_senal"] == "publications"


def test_el_servicio_no_manda_si_los_papers_no_lo_respaldan():
    """Si el servicio dice una cosa y su obra otra, gana la obra.

    Evita que un cargo administrativo en la afiliacion tape a que se dedica.
    """
    papers = [
        _paper(2025, mesh=["Retinal Diseases"]),
        _paper(2024, mesh=["Uveitis"]),
        _paper(2023, mesh=["Glaucoma"]),
    ]
    esp = pc.inferir_especialidad(papers, servicio_texto="Department of Cardiology")
    assert esp["nombre"] == "Ophthalmology"


def test_sin_papers_no_hay_especialidad():
    assert pc.inferir_especialidad([]) is None


def test_un_solo_paper_no_basta_para_declarar_area():
    """Con `minimo=2`, un paper suelto no define la especialidad de nadie."""
    assert pc.inferir_especialidad([_paper(2025, mesh=["Glaucoma"])]) is None


# ----------------------------------------------------------------------
#  Lineas de investigacion
# ----------------------------------------------------------------------

def test_los_mesh_genericos_no_son_temas():
    """'Humans' y 'Male' salen en casi todos los papers: no distinguen a nadie."""
    papers = [_paper(2025, mesh=["Humans", "Male", "Glioblastoma"]),
              _paper(2024, mesh=["Humans", "Female", "Glioblastoma"])]
    temas = [l["tema"] for l in pc.lineas_investigacion(papers)]
    assert "Glioblastoma" in temas
    assert "Humans" not in temas and "Male" not in temas


def test_un_tema_repetido_es_linea_recurrente():
    papers = [_paper(2025, mesh=["Glioblastoma"]),
              _paper(2024, mesh=["Glioblastoma"]),
              _paper(2023, mesh=["Glioblastoma"])]
    linea = pc.lineas_investigacion(papers)[0]
    assert linea["tema"] == "Glioblastoma"
    assert linea["papers"] == 3
    assert linea["recurrente"] is True
    assert linea["ultimo_anio"] == 2025


def test_obra_dispersa_da_temas_no_recurrentes_y_por_actualidad():
    """Si ningun tema se repite, se listan los centrales, del mas reciente.

    Antes la lista salia vacia y el dossier dejaba un hueco; ahora dice la
    verdad ('no repite tema') pero sigue informando.
    """
    papers = [_paper(2016, mesh=["Appendicitis"], major=["Appendicitis"]),
              _paper(2025, mesh=["Crohn Disease"], major=["Crohn Disease"])]
    lineas = pc.lineas_investigacion(papers)
    assert [l["recurrente"] for l in lineas] == [False, False]
    assert lineas[0]["tema"] == "Crohn Disease"   # el mas reciente primero


# ----------------------------------------------------------------------
#  Servicio, coautores, trayectoria
# ----------------------------------------------------------------------

def test_servicio_se_lee_de_la_afiliacion_del_propio_kol():
    afil = "Department of Pathology, Hospital La Fe, Valencia, Spain"
    papers = [_paper(2025, afiliacion=afil), _paper(2024, afiliacion=afil)]
    assert pc.servicio(papers)["nombre"] == "Department of Pathology"


def test_servicio_ignora_el_nombre_del_hospital():
    """'Hospital La Fe' es el centro, no el servicio."""
    papers = [_paper(2025, afiliacion="Hospital La Fe, Valencia, Spain")]
    assert pc.servicio(papers) is None


def test_colaboradores_excluye_al_propio_kol():
    papers = [_paper(2025, autores=["San-Miguel", "Megias", "Navarro"]),
              _paper(2024, autores=["San-Miguel", "Megias"])]
    nombres = [c["nombre"] for c in pc.colaboradores(papers, "San-Miguel")]
    assert any("Megias" in n for n in nombres)
    assert not any("San-Miguel" in n for n in nombres)


def test_trayectoria_marca_inactivo():
    """Un KOL que no publica desde hace mas de 3 anios no es 'activo'."""
    papers = [_paper(2010), _paper(2012)]
    t = pc.trayectoria(papers, anio_actual=2026)
    assert t["primer_anio"] == 2010 and t["ultimo_anio"] == 2012
    assert t["activo"] is False
    # El eje temporal cubre todos los anios, incluidos los vacios.
    assert [a["anio"] for a in t["por_anio"]] == [2010, 2011, 2012]
    assert t["por_anio"][1]["papers"] == 0


def test_trayectoria_sin_anios_validos():
    assert pc.trayectoria([_paper("")], anio_actual=2026) is None


def test_tipos_publicacion_se_traducen():
    papers = [_paper(2025, pubtypes=["Meta-Analysis", "Journal Article"])]
    tipos = pc.tipos_publicacion(papers)
    assert tipos[0]["tipo"] == "Meta-analysis" and tipos[0]["papers"] == 1
    # 'Journal Article' lo lleva todo: no aporta nada, no se lista.
    assert all(t["tipo"] != "Journal Article" for t in tipos)


def test_tipos_publicacion_concuerdan_en_numero():
    """'2 systematic review' es justo lo que no debe salir en un dossier."""
    papers = [_paper(2025, pubtypes=["Systematic Review"]),
              _paper(2024, pubtypes=["Systematic Review"]),
              _paper(2023, pubtypes=["Observational Study"])]
    textos = {t["texto"] for t in pc.tipos_publicacion(papers)}
    assert "2 systematic reviews" in textos
    assert "1 observational study" in textos


def test_el_plural_no_es_anadir_una_s():
    """El plural va en la tabla, no en una regla ingenua.

    En castellano el caso era "metaanálisis" (invariable); en ingles es
    "meta-analyses", que tampoco sale de anadir una s. El motivo del test
    sigue siendo el mismo.
    """
    papers = [_paper(2025, pubtypes=["Meta-Analysis"]),
              _paper(2024, pubtypes=["Meta-Analysis"])]
    assert pc.tipos_publicacion(papers)[0]["texto"] == "2 meta-analyses"


def test_resumen_no_inventa_cuando_no_hay_datos():
    r = pc.resumen(None, None, None, [], {})
    assert "not enough verified publications" in r.lower()
