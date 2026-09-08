"""
Test de candidatos — del nombre a los centros, sin preguntar donde trabaja.

Lo que se protege aqui es la pantalla que separa homonimos: se busca solo por
el nombre y se enseñan los centros desde los que publica cada quien. Si esta
agrupacion miente (parte a una persona en tres fichas, o funde a dos medicos
distintos en una), la eleccion posterior tambien miente, y con ella el dossier
entero.

Todo lo de aqui es la MITAD PURA: no toca la red.
"""

from kol_engine import candidatos


# ----------------------------------------------------------------------
#  De una afiliacion al centro
# ----------------------------------------------------------------------

def test_saca_el_centro_y_no_el_servicio():
    """'Servicio de X, Hospital Y' -> el centro es el hospital, no el servicio."""
    centro = candidatos._centro_de_afiliacion(
        "Servicio de Oncología Médica, Hospital Universitario 12 de Octubre, "
        "Madrid, Spain")
    assert centro["ciudad"] == "Madrid"
    assert "12 de Octubre" in centro["etiqueta"]


def test_el_catalogo_funde_las_formas_del_mismo_centro():
    """'Politècnic La Fe' e 'IIS La Fe' son el mismo sitio para quien elige.

    Sin esta fusion, un solo medico saldria partido en dos candidatos y
    parecerian dos personas distintas.
    """
    a = candidatos._centro_de_afiliacion(
        "Hospital Universitari i Politècnic La Fe, Valencia, Spain")
    b = candidatos._centro_de_afiliacion(
        "Instituto de Investigación Sanitaria La Fe, Valencia, Spain")
    assert a["clave"] == b["clave"]


def test_centro_no_catalogado_tambien_se_reconoce():
    """El catalogo no cubre el mundo: basta con que nombre una institucion."""
    centro = candidatos._centro_de_afiliacion(
        "Department of Neurology, Karolinska Institutet, Stockholm, Sweden")
    assert "Karolinska" in centro["etiqueta"]


def test_afiliacion_sin_centro_no_inventa():
    """'Madrid, Spain' a secas no es un centro: mejor None que adivinar."""
    assert candidatos._centro_de_afiliacion("Madrid, Spain") is None
    assert candidatos._centro_de_afiliacion("") is None


def test_quita_el_correo_de_la_etiqueta():
    """PubMed pega la direccion de contacto; no debe salir en pantalla."""
    centro = candidatos._centro_de_afiliacion(
        "Hospital Doctor Peset, Valencia, Spain. Electronic address: a@b.es")
    assert "@" not in centro["etiqueta"]
    assert centro["ciudad"] == "Valencia"


def test_varias_afiliaciones_cuentan_una_sola_vez():
    """Un autor que firma con dos centros no puede contar en los dos.

    Contarlo dos veces inflaria el recuento y repartiria a una persona entre
    varias fichas.
    """
    centro = candidatos._centro_de_afiliacion(
        "Hospital Doctor Peset, Valencia, Spain | "
        "Universitat de València, Valencia, Spain")
    assert centro is not None
    assert "Peset" in centro["etiqueta"]


# ----------------------------------------------------------------------
#  Agrupacion
# ----------------------------------------------------------------------

def _entrada(afiliacion, anio, titulo="Un paper"):
    return {"afiliacion": afiliacion, "anio": anio, "titulo": titulo}


def test_agrupa_dos_homonimos_en_dos_candidatos():
    """El caso que justifica la pantalla: mismo nombre, dos sitios."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("Hospital Doctor Peset, Valencia, Spain", "2024"),
        _entrada("Hospital Doctor Peset, Valencia, Spain", "2023"),
        _entrada("Hospital 12 de Octubre, Madrid, Spain", "2020"),
    ])
    assert len(grupos) == 2
    # Ordenados por numero de papers: primero el que mas publica.
    assert grupos[0]["papers"] == 2
    assert grupos[0]["ciudad"] == "Valencia"
    assert grupos[1]["ciudad"] == "Madrid"


def test_el_rango_de_anios_sale_de_los_papers():
    grupos = candidatos.agrupar_por_centro([
        _entrada("Hospital Doctor Peset, Valencia, Spain", "2015"),
        _entrada("Hospital Doctor Peset, Valencia, Spain", "2024"),
        _entrada("Hospital Doctor Peset, Valencia, Spain", ""),
    ])
    assert grupos[0]["primer_anio"] == 2015
    assert grupos[0]["ultimo_anio"] == 2024
    assert grupos[0]["papers"] == 3  # el que no tiene año sigue contando


def test_la_etiqueta_es_la_forma_mas_repetida():
    """Una firma rara de un solo paper no debe bautizar al grupo."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("Hospital Universitario Doctor Peset, Valencia, Spain", "2024"),
        _entrada("Hospital Universitario Doctor Peset, Valencia, Spain", "2023"),
        _entrada("Hosp. Dr. Peset, Valencia, Spain", "2010"),
    ])
    assert len(grupos) == 1
    assert grupos[0]["etiqueta"] == "Hospital Universitario Doctor Peset"


def test_a_igualdad_de_papers_gana_el_mas_reciente():
    """Donde publica HOY es mas informativo que donde publicaba en 2005."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("Hospital 12 de Octubre, Madrid, Spain", "2005"),
        _entrada("Hospital Doctor Peset, Valencia, Spain", "2024"),
    ])
    assert grupos[0]["ciudad"] == "Valencia"


def test_sin_entradas_no_hay_candidatos():
    """Cero candidatos es un resultado valido, no un fallo."""
    assert candidatos.agrupar_por_centro([]) == []
    assert candidatos.agrupar_por_centro([_entrada("Madrid, Spain", "2024")]) == []


# ----------------------------------------------------------------------
#  Ruido que ensuciaba la pantalla (casos reales de 'Teresa San-Miguel')
# ----------------------------------------------------------------------

def test_una_direccion_postal_no_es_un_centro():
    """'One Amgen Center Drive' es una calle: colaba por la palabra 'center'."""
    assert candidatos._centro_de_afiliacion(
        "One Amgen Center Drive, Thousand Oaks, CA, USA") is None


def test_la_facultad_no_sustituye_a_la_universidad():
    """Una facultad es parte de su universidad, no un centro aparte.

    Aceptandola, el mismo profesor salia repartido en 'Facultad de Medicina',
    'Faculty of Medicine' y 'Facultat de Medicina i Odontologia'.
    """
    centro = candidatos._centro_de_afiliacion(
        "Faculty of Medicine and Odontology, University of Valencia, "
        "Valencia, Spain")
    assert "University of Valencia" == centro["etiqueta"]


def test_el_idioma_no_parte_a_la_misma_universidad():
    """Tres idiomas, un solo sitio: tienen que caer en el mismo candidato."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("University of Valencia, Valencia, Spain", "2024"),
        _entrada("Universitat de València, Valencia, Spain", "2023"),
        _entrada("Universidad de Valencia, Valencia, Spain", "2022"),
    ])
    assert len(grupos) == 1
    assert grupos[0]["papers"] == 3


def test_la_familia_evita_fundir_centros_distintos():
    """Mismo apellido de ciudad, distinta clase de centro: NO son lo mismo."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("Universidad de Salamanca, Salamanca, Spain", "2024"),
        _entrada("Hospital de Salamanca, Salamanca, Spain", "2024"),
    ])
    assert len(grupos) == 2


def test_una_escuela_suelta_no_es_un_centro():
    """'Medical School' sin universidad detras no identifica ningun sitio."""
    assert candidatos._centro_de_afiliacion("Medical School, Valencia, Spain") \
        is None


def test_una_palabra_repetida_no_crea_un_candidato_nuevo():
    """'University of Valencia Valencia' es el mismo sitio, mal escrito."""
    grupos = candidatos.agrupar_por_centro([
        _entrada("University of Valencia, Valencia, Spain", "2024"),
        _entrada("University of Valencia Valencia, Spain", "2021"),
    ])
    assert len(grupos) == 1


# ----------------------------------------------------------------------
#  El nombre que se enseña lo pone PubMed, no quien escribe
# ----------------------------------------------------------------------

def _entrada_con_nombre(nombre_autor, afiliacion="Hospital Doctor Peset, "
                                                 "Valencia, Spain", anio="2024"):
    return {"afiliacion": afiliacion, "anio": anio, "titulo": "Un paper",
            "nombre_autor": nombre_autor}


def test_el_nombre_sale_con_tildes_aunque_se_escriba_sin_ellas():
    """Se busca 'elias martinez lopez'; el dossier dice 'Elías Martínez-López'."""
    grupos = candidatos.agrupar_por_centro([
        _entrada_con_nombre("Elías Martínez-López"),
        _entrada_con_nombre("Elías Martínez-López"),
    ])
    assert grupos[0]["nombre"] == "Elías Martínez-López"


def test_la_firma_abreviada_no_gana_al_nombre_completo():
    """'T San-Miguel' puede ser la mas frecuente y no identifica a nadie."""
    grupos = candidatos.agrupar_por_centro([
        _entrada_con_nombre("T San-Miguel"),
        _entrada_con_nombre("T San-Miguel"),
        _entrada_con_nombre("Teresa San-Miguel"),
    ])
    assert grupos[0]["nombre"] == "Teresa San-Miguel"
    # Y la abreviatura NO se denuncia como otra persona: es la misma.
    assert grupos[0]["otros_nombres"] == []


def test_avisa_de_quien_comparte_apellido_e_inicial():
    """Caso real: 'Martinez Lopez E' devuelve a Erika, Emilio, Emma y Elías.

    La busqueda por autor no distingue nombres de pila. Si en el mismo centro
    firma otra persona con esa inicial, hay que decirlo o sus papers se
    atribuyen al KOL equivocado.
    """
    grupos = candidatos.agrupar_por_centro([
        _entrada_con_nombre("Erika Martínez-López"),
        _entrada_con_nombre("Erika Martínez-López"),
        _entrada_con_nombre("Elías Martínez-López"),
    ])
    assert grupos[0]["nombre"] == "Erika Martínez-López"
    assert grupos[0]["otros_nombres"] == ["Elías Martínez-López"]


def test_nombre_de_autor_junta_pila_y_apellido():
    assert candidatos.nombre_de_autor(
        {"fore": "Teresa", "last": "San-Miguel"}) == "Teresa San-Miguel"
    assert candidatos.nombre_de_autor({"fore": "", "last": "San-Miguel"}) \
        == "San-Miguel"
