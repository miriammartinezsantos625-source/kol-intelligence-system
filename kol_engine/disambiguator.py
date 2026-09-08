"""
disambiguator — construye la estrategia de busqueda para un KOL.

A partir de nombre + institucion (+ ciudad, pais, ORCID, especialidad),
produce:

    query_used       -> la cadena que se enviara a PubMed (SIN tildes)
    location_terms   -> lista de terminos para verificar afiliaciones
                        (ej. ['valencia', 'la fe']); la usa el filtro de
                        homonimos en pubmed_agent
    surname          -> apellido del autor, normalizado para comparar
    initial          -> inicial del nombre de pila (ej. 'T')
    confidence       -> 'alta' | 'media' | 'baja'
    notes            -> explicacion legible de por que se eligio esta query

La confianza depende de cuantas senales tenemos para distinguir homonimos:
    - ORCID presente                      -> alta   (identificador unico)
    - afiliacion/ciudad presente          -> media
    - solo nombre                         -> baja
"""

from .text_utils import strip_accents, normalize

# Titulos y tratamientos que quitamos del nombre antes de parsear.
TITULOS = {
    "dr", "dra", "dr.", "dra.", "prof", "prof.", "profa", "profa.",
    "doctor", "doctora", "mr", "mrs", "ms", "phd", "md",
}

# Palabras vacias frecuentes en nombres de institucion: no sirven para
# distinguir a nadie, asi que no las usamos como terminos de localizacion.
STOPWORDS_INSTITUCION = {
    "hospital", "universitari", "universitario", "universitaria", "university",
    "clinic", "clinica", "clinico", "institut", "instituto", "institute",
    "centro", "center", "de", "i", "y", "and", "of", "the", "el", "la", "los",
    "las", "del", "general", "regional", "nacional", "politecnic", "politecnico",
    "fundacion", "foundation", "servicio", "department", "departamento",
    # tratamientos y genericos que aparecen en nombres de centros
    "doctor", "dr", "prof", "profesor", "don", "dona", "sr", "sra",
    "provincial", "comarcal", "salud", "health", "medico", "medical",
}


def _es_inicial(token):
    """True si el token es una inicial suelta ('F.', 'J', 'M.')."""
    return len(token.strip(".")) == 1


def parse_name(full_name):
    """Separa un nombre completo en (apellido, inicial_del_nombre).

    Heuristica adaptada a nombres ESPAÑOLES (dos apellidos):
      - quita titulos ('Dra.', 'Prof.', ...) y las iniciales sueltas ('F.')
      - el PRIMER token de palabra aporta la inicial del nombre de pila
      - con 3+ tokens de palabra, los DOS ULTIMOS son el apellido compuesto
        (caso 'Elias Martinez Lopez' -> 'Martinez Lopez'); con 2, el ultimo
      - los apellidos con guion ('San-Miguel') se mantienen enteros

    'Dra. Teresa San-Miguel'   -> ('San-Miguel', 'T')
    'Jesús F. San-Miguel'      -> ('San-Miguel', 'J')
    'Elias Martinez Lopez'     -> ('Martinez Lopez', 'E')

    Limitacion: en nombres de pila compuestos de 3 palabras ('Maria Teresa
    Garcia') puede confundir la 2ª palabra con un apellido. Solucion: pasar el
    apellido explicito (parametro `surname` de build_strategy).
    """
    tokens = full_name.replace(",", " ").split()
    # Descarta titulos (comparando sin tildes/mayusculas).
    tokens = [t for t in tokens if strip_accents(t).lower().strip(".") not in
              {x.strip(".") for x in TITULOS}]
    # Separa las iniciales sueltas (p.ej. 'F.') de las palabras.
    palabras = [t for t in tokens if not _es_inicial(t)]
    if not palabras:
        return ("", "")
    inicial = strip_accents(palabras[0])[0].upper()
    if len(palabras) == 1:
        return (palabras[0], "")          # un solo token: apellido sin nombre
    if len(palabras) >= 3:
        apellido = " ".join(palabras[-2:])  # dos apellidos (español)
    else:
        apellido = palabras[-1]
    return (apellido, inicial)


def _terminos_localizacion(institution, city):
    """Extrae terminos para verificar afiliaciones, separados por FUERZA.

    De 'Hospital Universitari i Politècnic La Fe' + 'Valencia' saca
    fuertes=['la','fe'] y debiles=['valencia'], descartando palabras genericas
    ('hospital', 'universitari', ...).

    ¿Por que separarlos? Porque no valen lo mismo. Que la afiliacion diga
    'CNIO' identifica un centro concreto; que diga 'Madrid' solo dice que
    trabaja en una ciudad de tres millones de habitantes. Tratarlos igual
    metia homonimos: buscando a Maria Blasco (CNIO) entraba otra M. Blasco
    nefrologa de Madrid, y sus 17 papers "verificados" eran de otra persona.

    Asi que la ciudad sirve para AMPLIAR la busqueda (que no se escape ningun
    paper) pero no basta para VERIFICAR: un paper que solo casa con la ciudad
    se queda en 'sin verificar', que es exactamente lo que es.

    Devuelve (todos, fuertes).
    """
    fuertes, debiles = [], []
    if city:
        debiles.append(normalize(city))
    if institution:
        for palabra in normalize(institution).split():
            if palabra not in STOPWORDS_INSTITUCION and len(palabra) > 1:
                fuertes.append(palabra)

    def _sin_duplicados(lista):
        vistos = []
        for t in lista:
            if t and t not in vistos:
                vistos.append(t)
        return vistos

    fuertes = _sin_duplicados(fuertes)
    debiles = [d for d in _sin_duplicados(debiles) if d not in fuertes]

    # Si NO conocemos la institucion, la ciudad es lo unico que tenemos: en ese
    # caso si vale para verificar (con la confianza baja que le corresponde).
    if not fuertes:
        return (debiles, debiles)
    return (fuertes + debiles, fuertes)


def _query_autor(apellido, inicial):
    """Fragmento de query de PubMed para el autor, SIN tildes y SIN comillas.

    PubMed indexa autores como 'Apellido(s) II', donde II son las iniciales de
    TODOS sus nombres de pila: Juan Manuel Sepulveda Sanchez esta indexado como
    'Sepulveda-Sanchez JM', no como 'Sepulveda-Sanchez J'.

    Por eso la busqueda va SIN comillas. Entrecomillada, PubMed exige
    coincidencia exacta y 'Sepulveda-Sanchez J'[Author] devuelve 2 resultados;
    sin comillas, PubMed trunca las iniciales el solo y devuelve 64. Es la
    diferencia entre perder a un KOL entero y encontrarlo. La precision no la
    pone la query, la pone el filtrado de homonimos posterior.

    Los apellidos compuestos pueden estar con espacio o con guion, asi que
    pedimos ambas variantes con OR:
        (Martinez Lopez E[Author] OR Martinez-Lopez E[Author])
    """
    ap = strip_accents(apellido)
    con_espacios = " ".join(ap.replace("-", " ").split())
    con_guion = con_espacios.replace(" ", "-")
    formas = {con_espacios, con_guion}  # set: no duplica si es de una palabra
    partes = [f"{f} {inicial}".strip() + "[Author]" for f in sorted(formas)]
    return "(" + " OR ".join(partes) + ")"


def build_strategy(full_name, institution=None, city=None, country=None,
                   orcid=None, specialty=None, surname=None):
    """Punto de entrada. Devuelve un dict con la estrategia de busqueda.

    Si se pasa `surname` explicito, se usa ese apellido (util cuando el nombre
    es ambiguo, p.ej. nombres de pila compuestos). Si no, se infiere del
    nombre con parse_name. Ver el docstring del modulo para el contrato.
    """
    apellido_auto, inicial = parse_name(full_name)
    apellido = surname.strip() if surname else apellido_auto
    location_terms, strong_terms = _terminos_localizacion(institution, city)

    notas = []

    # --- Rama 1: tenemos ORCID -> maxima confianza ---
    if orcid:
        query = f"{orcid}[auid]"
        confidence = "alta"
        notas.append(
            f"Se usa el ORCID {orcid} como identificador único de autor "
            "([auid]); es la señal más fiable contra homónimos."
        )
        notas.append(
            "Aun así, el filtrado por afiliación se aplica como red de "
            "seguridad."
        )
    else:
        # --- Rama 2/3: construimos por nombre (+ afiliacion si la hay) ---
        query = _query_autor(apellido, inicial)
        if location_terms:
            filtro_afil = " OR ".join(
                f'"{t}"[Affiliation]' for t in location_terms
            )
            query = f"{query} AND ({filtro_afil})"
            confidence = "media"
            notas.append(
                "Sin ORCID: se combina nombre de autor con filtro de "
                f"afiliación ({', '.join(location_terms)}). El filtrado de "
                "homónimos posterior refina el resultado."
            )
            debiles = [t for t in location_terms if t not in strong_terms]
            if debiles:
                notas.append(
                    f"«{', '.join(debiles)}» amplía la búsqueda pero no basta "
                    "para verificar: un paper que solo coincida ahí queda como "
                    "«sin verificar», no como confirmado."
                )
        else:
            confidence = "baja"
            notas.append(
                "Solo se dispone del nombre (sin ORCID ni institución/ciudad). "
                "Alto riesgo de homónimos; el resultado debe revisarse a mano."
            )

    if specialty:
        notas.append(
            f"Especialidad declarada: {specialty} (contexto, no se añade a la "
            "query para no perder papers)."
        )

    return {
        "full_name": full_name,
        "surname": apellido,
        "initial": inicial,
        "query_used": query,
        "location_terms": location_terms,
        "strong_terms": strong_terms,
        "orcid": orcid,
        "confidence": confidence,
        "notes": " ".join(notas),
    }
