"""
candidatos — ¿quien es este medico? Agrupa por centro ANTES de perfilar.

Por que existe
--------------
La interfaz pedia dos datos: el nombre Y donde trabaja. Pero el centro es
justo lo que muchas veces no se sabe — es parte de lo que se quiere averiguar.
Peor: exigirlo de entrada obliga a acertar a ciegas, y si se acierta mal el
filtro de afiliacion descarta al KOL entero.

Este modulo invierte el flujo. Se busca en PubMed SOLO por el nombre (sin
filtro de afiliacion), se mira desde que instituciones publica cada persona que
responde a ese nombre, y esos centros se devuelven como candidatos para que la
persona elija. Ahi es donde se separan los homonimos de verdad: dos autores
'Martinez Lopez E' distintos aparecen como dos centros distintos, con su ciudad
y su numero de papers al lado.

Lo que este modulo NO hace: decidir. Agrupar afiliaciones no desambigua a
nadie por si solo — un mismo medico puede publicar desde tres centros a la vez
(hospital + universidad + instituto de investigacion), y dos homonimos pueden
compartir ciudad. La eleccion la hace la persona; aqui solo se dibuja el mapa.
Quien desambigua de verdad sigue siendo `pubmed_agent.filter_homonyms`, ya con
el centro elegido.

Honestidad de las cifras
------------------------
`papers` es cuantos papers DE LA MUESTRA analizada llevan esa afiliacion, no
la obra completa del autor. La muestra son los mas recientes (PubMed asigna
PMIDs crecientes en el tiempo, asi que ordenar por PMID descendente es ordenar
por novedad). Se dice explicitamente en el resultado (`papers_analizados` y
`total_pubmed`) para que la interfaz pueda mostrarlo sin fingir exhaustividad.
"""

import logging

from . import centros, disambiguator, pubmed_agent
from .text_utils import contains_term, normalize

logger = logging.getLogger(__name__)

# Cuantos PMIDs se piden y cuantos se descargan enteros. Buscar candidatos es
# un paso INTERMEDIO: tiene que responder en segundos, no traerse la obra
# completa (eso ya lo hace el pipeline despues, con el centro ya elegido).
MAX_PMIDS_BUSQUEDA = 300
MAX_PAPERS_ANALIZADOS = 120

# RAICES que identifican a una INSTITUCION dentro de una afiliacion.
# 'Servicio de Oncologia, Hospital 12 de Octubre, Madrid, Spain' -> el trozo
# que nos interesa es el que lleva 'hospital', no el servicio ni la ciudad.
#
# Son raices y no palabras completas a proposito: las afiliaciones vienen en
# todos los idiomas y cada uno declina la misma palabra a su manera
# ('institut', 'instituto', 'institute', 'institutet'; 'universidad',
# 'universitat', 'university', 'universitario'). Comparando por palabra
# entera, 'Karolinska Institutet' no se reconocia como institucion y el
# candidato se perdia entero.
INSTITUCION_RAICES = (
    "hospital", "hospitalar", "clinic", "institut", "universi", "centro",
    "centre", "center", "fundaci", "foundation", "consorci", "complej",
    "complex", "ciber", "cnio", "cnic", "isglobal", "idibaps", "incliva",
    "vhio", "iis", "nhs",
)

# Trozos que son una UNIDAD dentro del centro, no el centro. Si el segmento
# empieza por una de estas, no sirve como etiqueta aunque lleve 'universitario'
# dentro ('Servicio de Oncologia del Hospital Universitario...').
UNIDAD_CLAVES = [
    "department", "departament", "departamento", "dept", "servicio", "servei",
    "service", "unidad", "unitat", "unit", "division", "seccion", "section",
    "laboratorio", "laboratory", "lab", "grupo", "group", "programa",
    "program", "area", "catedra", "chair",
    # Una facultad o escuela es una parte de su universidad, no un centro
    # aparte: si se acepta como etiqueta, el mismo profesor sale repartido en
    # 'Facultad de Medicina', 'Faculty of Medicine' y 'Facultat de Medicina'.
    "facultad", "facultat", "facultade", "faculty", "escuela", "escola",
    "school", "college", "colegio",
]

# Marcas de que el segmento es una DIRECCION POSTAL, no un centro. Sin esto,
# 'One Amgen Center Drive' se colaba como institucion por la palabra 'center'.
DIRECCION_CLAVES = [
    "drive", "street", "road", "avenue", "boulevard", "blvd", "calle",
    "avenida", "avda", "carrer", "suite", "box", "floor",
]

# Palabras que NO distinguen a un centro de otro: sobran en la clave de grupo.
# Son las que hacen que 'University of Valencia', 'Universitat de Valencia' y
# 'Universidad de Valencia' parezcan tres sitios distintos siendo uno.
PALABRAS_VACIAS = {
    "de", "del", "la", "el", "los", "las", "of", "the", "and", "i", "y", "e",
    "for", "in", "at", "on", "d", "l", "research", "investigacion",
    "investigacio", "biomedical", "biomedica", "biomedicas", "health",
    "salud", "sanitaria", "sanitario", "sciences", "science", "ciencias",
    "medicine", "medicina", "biomedicine", "group", "grupo", "foundation",
    "fundacion", "fundacio",
}

# Cada raiz institucional pertenece a una FAMILIA. La familia entra en la
# clave de grupo para que 'Hospital de Valencia' y 'Universidad de Valencia'
# no se fundan al quedarse ambos en la palabra 'valencia'.
FAMILIAS = {
    "hospital": "hospital", "hospitalar": "hospital", "clinic": "clinica",
    "institut": "instituto", "universi": "universidad", "centro": "centro",
    "centre": "centro", "center": "centro", "fundaci": "fundacion",
    "foundation": "fundacion",
}


def _limpiar_afiliacion(texto):
    """Quita la coletilla de contacto que PubMed pega al final.

    'Hospital X, Madrid, Spain. Electronic address: a@b.es' -> sin la direccion.
    El correo no aporta y ensucia la etiqueta que se enseña al usuario.
    """
    if not texto:
        return ""
    limpio = texto.strip()
    for marca in ("Electronic address:", "electronic address:", "Email:",
                  "E-mail:", "email:"):
        if marca in limpio:
            limpio = limpio.split(marca)[0]
    # Un token con arroba es un correo suelto; fuera.
    limpio = " ".join(t for t in limpio.split() if "@" not in t)
    return limpio.strip(" .,;")


def _segmentos(afiliacion):
    """Parte una afiliacion en sus trozos separados por coma."""
    return [s.strip() for s in afiliacion.split(",") if s.strip()]


def _es_unidad(segmento):
    """True si el segmento nombra un servicio/departamento, no un centro."""
    palabras = normalize(segmento).split()
    return bool(palabras) and palabras[0] in UNIDAD_CLAVES


def _raiz_institucional(segmento):
    """La primera raiz institucional del segmento, o None.

    Por raiz y no por palabra entera: ver el comentario de INSTITUCION_RAICES.
    """
    for palabra in normalize(segmento).split():
        for raiz in INSTITUCION_RAICES:
            if palabra.startswith(raiz):
                return raiz
    return None


def _es_direccion(segmento):
    """True si el segmento es una direccion postal ('One Amgen Center Drive')."""
    palabras = normalize(segmento).split()
    return any(p in DIRECCION_CLAVES for p in palabras)


def _clave_canonica(segmento, raiz):
    """Clave de grupo estable frente al idioma y a los adornos del nombre.

    'University of Valencia', 'Universitat de València' y 'Universidad de
    Valencia' son el mismo sitio escrito en tres idiomas. La clave se queda
    con la FAMILIA del centro (universidad) y con las palabras que de verdad
    lo distinguen (valencia), y descarta el resto:

        'University of Valencia'      -> 'universidad valencia'
        'Universitat de València'     -> 'universidad valencia'
        'Hospital Clínico de Valencia'-> 'hospital clinico valencia'

    Si al quitar el relleno no queda nada distintivo, se usa el segmento
    entero: mejor un grupo de mas que fundir dos centros distintos.
    """
    familia = FAMILIAS.get(raiz, raiz)
    distintivas = sorted({
        p for p in normalize(segmento).split()
        if p not in PALABRAS_VACIAS and not p.startswith(INSTITUCION_RAICES)
    })
    if not distintivas:
        return normalize(segmento)
    return f"{familia} {' '.join(distintivas)}"


def _centro_de_una(afiliacion):
    """De UNA afiliacion, saca (clave de grupo, etiqueta visible, ciudad).

    Dos estrategias, en orden:

    1. **Catalogo** (`centros.CENTROS`): si el texto menciona un centro
       conocido, la clave de grupo es la del catalogo. Esto es lo que hace que
       'Hospital Universitari i Politecnic La Fe' y 'IIS La Fe' caigan en el
       MISMO candidato en vez de en dos: para quien elige son el mismo sitio.
    2. **Palabra institucional**: el primer segmento que nombre un hospital,
       instituto o universidad y no sea un servicio interno.

    Devuelve None si no se reconoce ningun centro (afiliaciones que son solo
    'Madrid, Spain', o solo un departamento).
    """
    texto = _limpiar_afiliacion(afiliacion)
    if not texto:
        return None
    segmentos = _segmentos(texto)

    # --- 1. Catalogo de centros conocidos ---
    # Se recorre CENTROS por fuera (no los segmentos) para respetar su orden
    # de especificidad, igual que hace centros._ciudad_por_catalogo.
    for claves, ciudad in centros.CENTROS:
        for clave in claves:
            if contains_term(texto, clave):
                etiqueta = next((s for s in segmentos
                                 if contains_term(s, clave)), texto)
                return {"clave": normalize(claves[0]),
                        "etiqueta": etiqueta, "ciudad": ciudad}

    # --- 2. Cualquier centro no catalogado ---
    for segmento in segmentos:
        if _es_unidad(segmento) or _es_direccion(segmento):
            continue
        raiz = _raiz_institucional(segmento)
        if raiz:
            return {"clave": _clave_canonica(segmento, raiz),
                    "etiqueta": segmento,
                    "ciudad": centros.deducir_ciudad(texto)}

    return None


def _centro_de_afiliacion(afiliacion):
    """Un autor puede firmar con varias afiliaciones ('A | B'): se queda con
    la primera que sea un centro reconocible.

    Contarlas todas inflaria el recuento (el mismo paper apareceria en dos
    candidatos) y repartiria a una sola persona entre varias fichas.
    """
    for trozo in (afiliacion or "").split("|"):
        centro = _centro_de_una(trozo)
        if centro:
            return centro
    return None


def nombre_de_autor(autor):
    """Nombre completo tal y como lo escribe PubMed: 'Elías Martínez-López'.

    Es la forma CANONICA del nombre, y por eso importa: quien busca escribe
    'elias martinez lopez' (sin tildes, en minusculas) porque es mas comodo,
    pero el dossier no puede salir asi. La query ya ignora tildes y mayusculas
    (ver disambiguator._query_autor); el nombre bonito lo pone PubMed.
    """
    fore = (autor.get("fore") or "").strip()
    last = (autor.get("last") or "").strip()
    return f"{fore} {last}".strip()


def _mismo_nombre_de_pila(uno, otro):
    """True si los dos nombres pueden ser de la MISMA persona.

    'T San-Miguel' y 'Teresa San-Miguel' son compatibles: una es la firma
    abreviada de la otra. 'Erika Martínez-López' y 'Elías Martínez-López' no:
    comparten apellido e inicial, que es justo lo que la busqueda por autor no
    distingue, pero son dos personas.
    """
    palabras_uno = normalize(uno).split()
    palabras_otro = normalize(otro).split()
    if not palabras_uno or not palabras_otro:
        return True
    pila_uno, pila_otro = palabras_uno[0], palabras_otro[0]
    # Una inicial suelta no contradice a nadie que empiece por esa letra.
    if len(pila_uno) == 1 or len(pila_otro) == 1:
        return pila_uno[0] == pila_otro[0]
    return pila_uno == pila_otro


def _nombre_canonico(formas):
    """De un Counter {nombre: veces}, la forma que se enseña.

    Gana la mas repetida CON nombre de pila completo: 'T San-Miguel' puede ser
    la mas frecuente y aun asi no sirve para identificar a nadie.
    """
    if not formas:
        return None
    completas = {n: c for n, c in formas.items()
                 if len(normalize(n).split()[0]) > 1} if formas else {}
    fuente = completas or formas
    return max(fuente.items(), key=lambda kv: kv[1])[0]


def _anio(entrada):
    try:
        return int(str(entrada.get("anio") or "")[:4])
    except (TypeError, ValueError):
        return None


def agrupar_por_centro(entradas):
    """Agrupa entradas {afiliacion, anio, titulo} por centro. Funcion PURA.

    Devuelve la lista de candidatos ordenada por numero de papers (desc) y,
    a igualdad, por lo reciente que sea el ultimo paper: quien publica hoy
    desde ahi es mas probable que sea su sitio actual.

    Cada candidato:
        {clave, etiqueta, ciudad, papers, primer_anio, ultimo_anio, ejemplo}
    """
    grupos = {}
    for entrada in entradas:
        centro = _centro_de_afiliacion(entrada.get("afiliacion"))
        if not centro:
            continue
        g = grupos.setdefault(centro["clave"], {
            "clave": centro["clave"], "ciudad": centro["ciudad"],
            "papers": 0, "anios": [], "etiquetas": {}, "ejemplo": None,
            "nombres": {},
        })
        nombre_autor = (entrada.get("nombre_autor") or "").strip()
        if nombre_autor:
            g["nombres"][nombre_autor] = g["nombres"].get(nombre_autor, 0) + 1
        g["papers"] += 1
        # La etiqueta que se enseña es la forma MAS REPETIDA, no la primera:
        # una firma rara de un solo paper no debe bautizar al grupo.
        etiqueta = centro["etiqueta"]
        g["etiquetas"][etiqueta] = g["etiquetas"].get(etiqueta, 0) + 1
        if not g["ciudad"] and centro["ciudad"]:
            g["ciudad"] = centro["ciudad"]
        anio = _anio(entrada)
        if anio:
            g["anios"].append(anio)
        if not g["ejemplo"] and entrada.get("titulo"):
            g["ejemplo"] = entrada["titulo"]

    candidatos = []
    for g in grupos.values():
        anios = sorted(g["anios"])
        etiqueta = max(g["etiquetas"].items(), key=lambda kv: kv[1])[0]
        canonico = _nombre_canonico(g["nombres"])
        # Otras personas que firman desde el mismo centro con ese apellido e
        # inicial. No es un detalle: la busqueda por autor NO distingue nombres
        # de pila, asi que aqui es donde se ve que 'Erika' y 'Elías' no son la
        # misma persona aunque PubMed los devuelva juntos.
        otros = sorted(
            ((n, c) for n, c in g["nombres"].items()
             if canonico and not _mismo_nombre_de_pila(n, canonico)),
            key=lambda nc: -nc[1])
        candidatos.append({
            "clave": g["clave"],
            "etiqueta": etiqueta,
            "nombre": canonico,
            "otros_nombres": [n for n, _ in otros],
            "ciudad": g["ciudad"],
            "papers": g["papers"],
            "primer_anio": anios[0] if anios else None,
            "ultimo_anio": anios[-1] if anios else None,
            "ejemplo": g["ejemplo"],
        })
    candidatos.sort(key=lambda c: (-c["papers"], -(c["ultimo_anio"] or 0)))
    return candidatos


def _autor_objetivo(paper, surname, inicial):
    """El autor del paper que responde al nombre buscado, o None.

    Reutiliza los mismos criterios que el filtro de homonimos
    (`pubmed_agent._surname_coincide` / `_inicial_coincide`) para que la
    pantalla de candidatos y el analisis posterior hablen del mismo autor.
    """
    for autor in paper.get("authors", []):
        if (pubmed_agent._surname_coincide(autor.get("last", ""), surname)
                and pubmed_agent._inicial_coincide(autor.get("initials", ""),
                                                   inicial)):
            return autor
    return None


def buscar_candidatos(nombre, surname=None, max_pmids=MAX_PMIDS_BUSQUEDA,
                      max_papers=MAX_PAPERS_ANALIZADOS, use_cache=True):
    """Busca en PubMed solo por el nombre y devuelve los centros candidatos.

    Devuelve:
        {nombre, surname, initial, query, total_pubmed, papers_analizados,
         sin_afiliacion, candidatos: [...]}

    `total_pubmed` es lo que PubMed dice que existe con ese nombre;
    `papers_analizados` lo que realmente se ha mirado. La interfaz debe
    enseñar ambos: prometer un recuento completo sobre una muestra seria
    exactamente el tipo de cifra inventada que este proyecto no admite.
    """
    estrategia = disambiguator.build_strategy(nombre, surname=surname)
    query = estrategia["query_used"]
    pmids, total = pubmed_agent.search_pmids_with_total(
        query, max_papers=max_pmids, use_cache=use_cache)

    # PubMed asigna PMIDs crecientes en el tiempo: ordenar por PMID
    # descendente es quedarse con lo mas reciente, que es lo que dice donde
    # trabaja HOY. Los no numericos (no deberia haberlos) van al final.
    pmids = sorted(pmids, key=lambda p: int(p) if str(p).isdigit() else -1,
                   reverse=True)[:max_papers]
    papers = pubmed_agent.fetch_papers(pmids, use_cache=use_cache) if pmids else []

    entradas, sin_afiliacion = [], 0
    for paper in papers:
        autor = _autor_objetivo(paper, estrategia["surname"],
                                estrategia["initial"])
        if autor is None:
            continue
        afiliacion = (autor.get("affiliation") or "").strip()
        if not afiliacion:
            sin_afiliacion += 1
            continue
        entradas.append({"afiliacion": afiliacion, "anio": paper.get("year"),
                         "titulo": paper.get("title"),
                         "nombre_autor": nombre_de_autor(autor)})

    candidatos = agrupar_por_centro(entradas)
    logger.info("candidates for %s: %d centres over %d papers analysed "
                "(%d en PubMed)", nombre, len(candidatos), len(papers), total)

    return {
        "nombre": nombre,
        "surname": estrategia["surname"],
        "initial": estrategia["initial"],
        "query": query,
        "total_pubmed": total,
        "papers_analizados": len(papers),
        "sin_afiliacion": sin_afiliacion,
        "candidatos": candidatos,
    }
