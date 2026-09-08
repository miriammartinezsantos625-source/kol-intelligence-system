"""
perfil_cientifico — responde a "¿QUIÉN es este médico?" con sus propios papers.

¿Por qué existe?
El dossier tenía el nombre del KOL, su hospital, un score y una lista de
títulos… pero no decía a qué se dedica. Y el dato ya estaba descargado: cada
registro de PubMed trae los descriptores **MeSH** (el vocabulario controlado con
que la NLM etiqueta a mano de qué trata cada artículo), la **afiliación
completa** del autor (que suele incluir su servicio hospitalario) y la lista de
**coautores**. Este módulo lo aprovecha para deducir, sin preguntar nada:

    especialidad          → de qué área es (antes había que teclearla)
    servicio              → su servicio/departamento, leído de la afiliación
    lineas_investigacion  → sus temas recurrentes, con nº de papers
    colaboradores         → con quién publica y cuántas veces
    trayectoria           → desde cuándo publica, ritmo, actividad reciente
    tipos_publicacion     → ensayos, revisiones, metaanálisis, guías

Todo es código PURO (sin red): recibe la lista de papers ya filtrados de
homónimos y devuelve dicts. Eso lo hace fácil de testear y garantiza que no
describimos a un homónimo.

Honestidad: cada bloque dice en qué evidencia se apoya y cuántos papers la
sostienen. Si no hay evidencia suficiente, devolvemos None y el entregable
escribe "no determinada" — nunca un dato inventado.
"""

import collections
import re

from .text_utils import normalize

# ----------------------------------------------------------------------
#  MeSH que no distinguen a nadie
# ----------------------------------------------------------------------
# La NLM añade "check tags" (Humans, Male, Adult...) y descriptores de
# metodología (Retrospective Studies...) a casi todo. Aparecen en el 90% de los
# papers, así que como "línea de investigación" no dicen nada. Fuera.
MESH_GENERICOS = {
    "humans", "male", "female", "adult", "aged", "middle aged", "child",
    "animals", "adolescent", "young adult", "aged 80 and over", "infant",
    "infant newborn", "child preschool", "mice", "rats", "pregnancy",
    "retrospective studies", "prospective studies", "follow up studies",
    "time factors", "reproducibility of results", "cohort studies",
    "case control studies", "cross sectional studies", "longitudinal studies",
    "sensitivity and specificity", "predictive value of tests",
    "severity of illness index", "risk factors", "risk assessment",
    "incidence", "prevalence", "registries", "surveys and questionnaires",
    "spain", "europe", "united states", "age factors", "sex factors",
    "reproducibility", "double blind method", "single blind method",
    "logistic models", "multivariate analysis", "proportional hazards models",
    "kaplan meier estimate", "statistics nonparametric", "odds ratio",
    "treatment outcome", "prognosis", "disease free survival",
    "survival rate", "survival analysis", "recurrence", "comorbidity",
    "hospitals", "hospitalization", "length of stay", "tertiary care centers",
    "cell line tumor", "cell line", "cells cultured", "immunohistochemistry",
    "gene expression profiling", "polymerase chain reaction", "biomarkers tumor",
    "dna methylation", "in situ hybridization fluorescence",
    "postoperative complications", "adolescent", "aging",
}


# ----------------------------------------------------------------------
#  Catálogo de especialidades
# ----------------------------------------------------------------------
# Cada especialidad se reconoce por PATRONES (subcadenas normalizadas) que
# pueden aparecer en un MeSH o en el nombre de la revista. Un paper puede votar
# a varias; gana la que más votos reúne.
#
# Los patrones se comparan sobre texto normalizado (sin tildes, minúsculas),
# así que se escriben así: 'cirugia', no 'cirugía'.
ESPECIALIDADES = [
    ("Medical oncology", [
        "neoplasm", "carcinoma", "antineoplastic", "chemotherapy", "oncolog",
        "tumor", "tumour", "cancer", "immunotherapy", "metastas", "sarcoma",
        "melanoma",
    ]),
    ("Haematology", [
        "hematolog", "haematolog", "leukemia", "leukaemia", "lymphoma",
        "myeloma", "anemia", "thrombo", "hemostas", "blood", "bone marrow",
        "transplantation hematopoietic", "coagulation",
    ]),
    ("General and digestive surgery", [
        "surgical procedures digestive", "colorectal surg", "colectomy",
        "appendectomy", "cholecystectomy", "laparoscop", "surg endosc",
        "gastrointestinal surg", "hernia", "mesenteric", "anastomo",
        "surgery digestive", "surgical oncolog", "abdominal surg",
        # formas con las que se nombra el SERVICIO en las afiliaciones
        "general and digestive surgery", "digestive surgery",
        "cirugia general y del aparato digestivo", "cirugia digestiva",
        "cirugia general",
    ]),
    ("Surgery", [
        "surgical procedures operative", "surg", "operative", "reconstruction",
        "postoperative", "intraoperative", "surgeons",
    ]),
    ("Gastroenterology", [
        "gastroenterol", "hepatolog", "liver", "hepatic", "pancrea",
        "inflammatory bowel", "crohn", "colitis", "gastric", "intestinal",
        "esophag", "oesophag", "colon", "rectum", "biliary", "cirrhosis",
    ]),
    ("Cardiology", [
        "cardiolog", "heart", "cardiac", "myocard", "coronary", "arrhythmi",
        "atrial fibrillation", "hypertension", "cardiovascular", "aortic",
        "echocardiograph", "heart failure",
    ]),
    ("Neurology", [
        "neurolog", "brain", "nervous system", "stroke", "epilep",
        "parkinson", "alzheimer", "multiple sclerosis", "dementia",
        "neurodegener", "migraine", "neuromuscular",
    ]),
    ("Neurosurgery", [
        "neurosurg", "craniotomy", "glioblastoma", "brain neoplasm",
        "intracranial",
    ]),
    ("Pathology", [
        "patholog", "histolog", "immunohistochem", "biopsy", "cytolog",
        "biomarkers tumor",
    ]),
    ("Ophthalmology", [
        "ophthalmol", "retina", "retinal", "uveitis", "macular", "glaucoma",
        "cornea", "cataract", "vitreo", "eye disease", "visual acuity",
        "intravitreal",
    ]),
    ("Dermatology", [
        "dermatolog", "skin disease", "psoriasis", "dermatitis", "cutaneous",
        "acne", "alopecia", "hidradenitis",
    ]),
    ("Respiratory medicine", [
        "pulmon", "respiratory tract", "lung disease", "asthma", "copd",
        "pulmonary disease chronic", "bronch", "thorax", "sleep apnea",
        "cystic fibrosis",
    ]),
    ("Endocrinology and nutrition", [
        "endocrin", "diabetes", "thyroid", "obesity", "insulin", "metabolic",
        "pituitary", "adrenal", "osteoporosis", "lipid", "nutrition",
    ]),
    ("Rheumatology", [
        "rheumat", "arthritis", "lupus", "spondyl", "autoimmune disease",
        "connective tissue disease", "gout", "fibromyalgia",
    ]),
    ("Infectious diseases", [
        "infectious disease", "infection", "antibacterial", "antiviral",
        "hiv", "hepatitis", "tuberculosis", "covid", "sars cov", "sepsis",
        "antimicrobial", "vaccin", "microbiolog",
    ]),
    ("Nephrology", [
        "kidney", "renal", "nephrolog", "dialysis", "glomerul",
        "kidney transplantation",
    ]),
    ("Urology", [
        "urolog", "prostat", "bladder", "urinary", "kidney calculi",
        "endourol", "lithotripsy",
    ]),
    ("Obstetrics and gynaecology", [
        "gynecol", "obstetric", "pregnancy complications", "uterine",
        "ovarian", "endometri", "cervix", "fertility", "breast neoplasm",
    ]),
    ("Paediatrics", [
        "pediatr", "paediatr", "infant premature", "neonat", "childhood",
    ]),
    ("Psychiatry", [
        "psychiatr", "depress", "schizophren", "bipolar", "anxiety",
        "mental disorder", "psychotropic", "addiction", "substance related",
    ]),
    ("Orthopaedics and traumatology", [
        "orthoped", "fracture", "arthroplasty", "joint", "spine", "bone",
        "musculoskeletal", "tendon", "knee", "hip",
    ]),
    ("Anaesthesiology", [
        "anesthes", "anaesthes", "analgesi", "sedation", "pain management",
        "critical care", "intensive care",
    ]),
    ("Internal medicine", [
        "internal medicine", "primary health care", "general practice",
        "family practice",
    ]),
    ("Radiology and diagnostic imaging", [
        "radiolog", "tomography", "magnetic resonance imaging", "ultrasonograph",
        "radiograph", "nuclear medicine", "positron emission",
    ]),
    ("Pharmacy and pharmacology", [
        "pharmacolog", "pharmacokinet", "pharmac", "drug therapy",
        "drug related side effects", "clinical pharmacy",
    ]),
    ("Genetics and molecular biology", [
        "genetic", "genom", "mutation", "gene expression", "microrna",
        "epigenet", "sequencing", "molecular biology",
    ]),
    ("Public health and epidemiology", [
        "public health", "epidemiolog", "health policy", "screening",
        "mass screening", "health services",
    ]),
]

# Términos que aparecen tan a menudo que, si una especialidad SOLO se sostiene
# en ellos, la señal es demasiado débil (p.ej. 'surg' en cualquier paper que
# mencione una operación de paso).
_PATRONES_DEBILES = {"surg", "operative", "blood", "bone", "joint", "infection"}


def _texto_del_paper(paper):
    """Todo el texto temático de un paper, normalizado y en una sola cadena.

    Junta MeSH + palabras clave + revista + título. Los MeSH 'major topic'
    (los temas centrales) se repiten para que pesen el doble en el recuento.
    """
    piezas = []
    piezas.extend(paper.get("mesh", []))
    piezas.extend(paper.get("mesh_major", []))   # repetidos a propósito: peso x2
    piezas.extend(paper.get("keywords", []))
    piezas.append(paper.get("journal", ""))
    piezas.append(paper.get("title", ""))
    return normalize(" | ".join(p for p in piezas if p))


def _especialidad_por_texto(texto):
    """Especialidad que mejor describe un texto suelto (p.ej. un servicio).

    Puede encajar en varias ("Department of General and Digestive Surgery"
    activa tanto "Cirugía" como "Cirugía general y del aparato digestivo").
    Gana la del patrón MÁS LARGO, que es siempre la más específica: 'general
    and digestive surgery' (29 car.) describe mejor que 'surg' (4).

    Devuelve (nombre, patron) o (None, None).
    """
    t = normalize(texto or "")
    if not t:
        return (None, None)
    mejor_nombre, mejor_patron = None, ""
    for nombre, patrones in ESPECIALIDADES:
        for patron in patrones:
            if patron in t and len(patron) > len(mejor_patron):
                mejor_nombre, mejor_patron = nombre, patron
    return (mejor_nombre, mejor_patron or None)


def inferir_especialidad(papers, minimo=2, servicio_texto=None):
    """Deduce el área del KOL a partir del contenido de sus papers.

    Cada paper vota por las especialidades cuyos patrones aparecen en su
    texto temático. Gana la más votada, siempre que la sostengan al menos
    `minimo` papers.

    Si además conocemos su SERVICIO (leído de la afiliación), ese dato manda:
    es la propia declaración del médico sobre a qué se dedica, mientras que los
    MeSH describen temas sueltos. Un cirujano digestivo que publica sobre
    cáncer de colon no es un oncólogo médico, y solo el servicio lo distingue.
    Aun así exigimos que al menos `minimo` papers respalden esa área: si el
    servicio dice una cosa y sus papers no la sostienen, volvemos al recuento.

    Devuelve {'nombre', 'papers_que_la_sostienen', 'total_papers',
              'confianza', 'origen_señal', 'alternativas'} o None.
    """
    if not papers:
        return None

    votos = collections.Counter()
    fuertes = collections.Counter()  # votos que NO vienen solo de patrones débiles
    for paper in papers:
        texto = _texto_del_paper(paper)
        for nombre, patrones in ESPECIALIDADES:
            encontrados = [p for p in patrones if p in texto]
            if encontrados:
                votos[nombre] += 1
                if any(p not in _PATRONES_DEBILES for p in encontrados):
                    fuertes[nombre] += 1

    if not votos:
        return None

    # Ordena por votos fuertes primero, luego por votos totales. Así una
    # especialidad apoyada en señales específicas gana a otra que solo aparece
    # de refilón.
    candidatas = sorted(votos, key=lambda n: (fuertes[n], votos[n]), reverse=True)
    mejor = candidatas[0]
    origen_senal = "publications"

    # El servicio del KOL desempata, si sus papers lo respaldan.
    por_servicio, _ = _especialidad_por_texto(servicio_texto)
    if por_servicio and fuertes[por_servicio] >= minimo and por_servicio != mejor:
        candidatas = [por_servicio] + [c for c in candidatas if c != por_servicio]
        mejor = por_servicio
        origen_senal = "department"

    if fuertes[mejor] < minimo:
        return None

    total = len(papers)
    cobertura = fuertes[mejor] / total
    if cobertura >= 0.5:
        confianza = "high"
    elif cobertura >= 0.25:
        confianza = "medium"
    else:
        confianza = "low"

    return {
        "nombre": mejor,
        "papers_que_la_sostienen": fuertes[mejor],
        "total_papers": total,
        "confianza": confianza,
        "origen_senal": origen_senal,
        "alternativas": [
            {"nombre": n, "papers": fuertes[n]}
            for n in candidatas[1:4] if fuertes[n] >= minimo
        ],
    }


# ----------------------------------------------------------------------
#  Líneas de investigación
# ----------------------------------------------------------------------

def lineas_investigacion(papers, top=8, minimo=2):
    """Temas recurrentes del KOL: los MeSH más frecuentes, sin los genéricos.

    Devuelve [{'tema', 'papers', 'principal'}], ordenado por frecuencia.
    'principal' indica que la NLM lo marcó como major topic en algún paper:
    es un tema CENTRAL de su trabajo, no una mención de paso.
    """
    if not papers:
        return []

    cuenta = collections.Counter()
    es_major = set()
    ultimo = {}          # tema -> año del paper más reciente que lo trata
    for paper in papers:
        anio = _anio(paper)
        # set(): un mismo MeSH no cuenta dos veces dentro del mismo paper.
        for termino in set(paper.get("mesh", [])):
            if normalize(termino) in MESH_GENERICOS:
                continue
            cuenta[termino] += 1
            ultimo[termino] = max(ultimo.get(termino, 0), anio)
        for termino in set(paper.get("mesh_major", [])):
            if normalize(termino) not in MESH_GENERICOS:
                es_major.add(termino)

    lineas = []
    for tema, n in cuenta.most_common(top * 3):
        if n < minimo:
            continue
        lineas.append({"tema": tema, "papers": n, "principal": tema in es_major,
                       "recurrente": True, "ultimo_anio": ultimo.get(tema, 0)})
        if len(lineas) >= top:
            break

    # Un KOL puede tener una obra tematicamente dispersa: ningun MeSH se repite
    # y la lista sale vacia. Eso no significa que no sepamos de que escribe.
    # Completamos con los "major topics" (los temas que la NLM marco como
    # CENTRALES de cada articulo), aunque solo aparezcan una vez, y los
    # marcamos como no recurrentes para no exagerar la senal.
    if len(lineas) < 3:
        ya = {l["tema"] for l in lineas}
        # Orden por ACTUALIDAD, no alfabético: al MSL le sirve más saber sobre
        # qué escribe ahora que qué empieza por A.
        sueltos = sorted(es_major - ya,
                         key=lambda t: (-ultimo.get(t, 0), -cuenta[t], t))
        for tema in sueltos[:top - len(lineas)]:
            lineas.append({"tema": tema, "papers": cuenta[tema],
                           "principal": True, "recurrente": False,
                           "ultimo_anio": ultimo.get(tema, 0)})

    # Los recurrentes primero, luego los centrales; a igualdad, más papers y
    # más recientes arriba.
    lineas.sort(key=lambda l: (l["recurrente"], l["principal"], l["papers"],
                               l["ultimo_anio"]), reverse=True)
    return lineas


# ----------------------------------------------------------------------
#  Servicio / departamento (de la afiliación del propio autor)
# ----------------------------------------------------------------------

# La afiliación viene como "Departamento, Centro, Ciudad, País". El primer
# trozo suele ser el servicio. Reconocemos el trozo por estas palabras.
_PISTAS_SERVICIO = (
    "servicio", "departamento", "department", "unidad", "unit", "servei",
    "division", "divisió", "section", "seccion", "área", "area", "institute",
    "instituto", "laboratory", "laboratorio", "grupo", "group", "cátedra",
    "school", "facultad", "faculty",
)

# Ruido que no queremos como "servicio".
_NO_SERVICIO = ("hospital", "university", "universidad", "universitat",
                "universitario", "centro de salud", "foundation", "fundación")


def servicio(papers, minimo=1):
    """Servicio/departamento más frecuente en la afiliación del propio KOL.

    Lee `matched_affiliation` (la afiliación del autor identificado como el
    KOL, que pone `filter_homonyms`), parte por comas y se queda con el primer
    trozo que parezca un servicio.

    Devuelve {'nombre', 'papers'} o None.
    """
    cuenta = collections.Counter()
    for paper in papers:
        afiliacion = paper.get("matched_affiliation") or ""
        for bloque in afiliacion.split("|"):       # varias afiliaciones
            for trozo in bloque.split(","):
                t = trozo.strip()
                if not t or len(t) < 6:
                    continue
                tn = normalize(t)
                if any(r in tn for r in _NO_SERVICIO):
                    continue
                if any(p in tn for p in _PISTAS_SERVICIO):
                    cuenta[t] += 1
                    break     # solo el primer servicio de cada afiliación
    if not cuenta:
        return None
    nombre, n = cuenta.most_common(1)[0]
    if n < minimo:
        return None
    return {"nombre": nombre, "papers": n}


# ----------------------------------------------------------------------
#  Red de colaboración
# ----------------------------------------------------------------------

def colaboradores(papers, surname, top=8, minimo=2):
    """Coautores con los que más publica (excluyendo al propio KOL).

    Devuelve [{'nombre', 'papers'}]. Útil para el MSL: son las personas con
    las que ya tiene relación de trabajo, y posibles puertas de entrada.
    """
    propio = set(normalize(surname).split())
    cuenta = collections.Counter()
    for paper in papers:
        vistos = set()
        for autor in paper.get("authors", []):
            apellido = autor.get("last", "")
            if not apellido:
                continue
            # Salta al propio KOL.
            if propio and propio.issubset(set(normalize(apellido).split())):
                continue
            iniciales = autor.get("initials", "")
            nombre = f"{apellido} {iniciales}".strip()
            if nombre in vistos:
                continue
            vistos.add(nombre)
            cuenta[nombre] += 1
    return [{"nombre": n, "papers": c}
            for n, c in cuenta.most_common(top) if c >= minimo]


# ----------------------------------------------------------------------
#  Trayectoria temporal
# ----------------------------------------------------------------------

def _anio(paper):
    try:
        return int(str(paper.get("year", ""))[:4])
    except (ValueError, TypeError):
        return 0


def trayectoria(papers, anio_actual):
    """Desde cuándo publica, hasta cuándo, y su ritmo.

    Devuelve {'primer_anio', 'ultimo_anio', 'anios_activo', 'por_anio',
              'media_anual', 'activo'} o None si no hay años válidos.

    'activo' = ha publicado en los últimos 3 años. Para un MSL importa: un KOL
    que publicó mucho hace 15 años y nada desde entonces no es el mismo
    interlocutor que uno en plena producción.
    """
    anios = [_anio(p) for p in papers]
    anios = [a for a in anios if a > 1900]
    if not anios:
        return None

    primer, ultimo = min(anios), max(anios)
    por_anio = collections.Counter(anios)
    span = max(1, ultimo - primer + 1)
    return {
        "primer_anio": primer,
        "ultimo_anio": ultimo,
        "anios_activo": span,
        "por_anio": [{"anio": a, "papers": por_anio[a]}
                     for a in range(primer, ultimo + 1)],
        "media_anual": round(len(anios) / span, 1),
        "activo": ultimo >= anio_actual - 3,
    }


# ----------------------------------------------------------------------
#  Tipos de publicación
# ----------------------------------------------------------------------

# PubMed etiqueta cada artículo con su tipo. Estos son los que le importan a
# un MSL: distinguen a alguien que genera evidencia de alguien que la revisa.
# Cada tipo lleva su forma en singular y en plural: escribir "2 revisión
# sistemática" en un dossier que va a leer un médico queda descuidado, y el
# plural en castellano no se saca con una regla de una línea (metaanálisis es
# invariable, guía de práctica clínica pluraliza solo la primera palabra).
_TIPOS_INTERESANTES = {
    "Randomized Controlled Trial": ("Randomised controlled trial",
                                    "randomised controlled trials"),
    "Clinical Trial": ("Clinical trial", "clinical trials"),
    "Clinical Trial, Phase I": ("Phase I clinical trial",
                                "phase I clinical trials"),
    "Clinical Trial, Phase II": ("Phase II clinical trial",
                                 "phase II clinical trials"),
    "Clinical Trial, Phase III": ("Phase III clinical trial",
                                  "phase III clinical trials"),
    "Multicenter Study": ("Multicentre study", "multicentre studies"),
    "Meta-Analysis": ("Meta-analysis", "meta-analyses"),
    "Systematic Review": ("Systematic review", "systematic reviews"),
    "Review": ("Review", "reviews"),
    "Practice Guideline": ("Clinical practice guideline",
                           "clinical practice guidelines"),
    "Guideline": ("Guideline", "guidelines"),
    "Observational Study": ("Observational study", "observational studies"),
    "Case Reports": ("Case report", "case reports"),
    "Editorial": ("Editorial", "editorials"),
    "Comment": ("Comment", "comments"),
}


def tipos_publicacion(papers):
    """Recuento de tipos de publicación, con el nombre en español.

    Devuelve [{'tipo', 'papers', 'texto'}] ordenado de más a menos. `texto` ya
    trae el número y el sustantivo concordados ("2 revisiones sistemáticas"),
    para que ni el PDF ni el dashboard ni el briefing tengan que pluralizar
    cada uno por su cuenta.
    """
    cuenta = collections.Counter()
    plurales = {}
    for paper in papers:
        for pt in set(paper.get("pubtypes", [])):
            etiquetas = _TIPOS_INTERESANTES.get(pt)
            if etiquetas:
                singular, plural = etiquetas
                cuenta[singular] += 1
                plurales[singular] = plural
    return [{"tipo": t, "papers": n,
             "texto": f"{n} {t.lower() if n == 1 else plurales[t]}"}
            for t, n in cuenta.most_common()]



# ----------------------------------------------------------------------
#  Resumen narrativo ("quién es", en una frase)
# ----------------------------------------------------------------------

def resumen(especialidad, serv, tray, lineas, pub_stats):
    """Un párrafo que responde "¿quién es este médico?" en lenguaje llano.

    Vive aquí, y no en el PDF, para que el dossier y el dashboard digan
    exactamente lo mismo (regla de la fuente de verdad única). Solo afirma lo
    que se sostiene en datos: si falta una pieza, la frase la omite en vez de
    rellenarla.
    """
    frases = []

    area = (especialidad or {}).get("nombre")
    if area and serv:
        frases.append(f"Works in {serv['nombre']}; their published work "
                      f"places them in {area.lower()}.")
    elif area:
        frases.append(f"Their published work places them in {area.lower()}.")
    elif serv:
        frases.append(f"Works in {serv['nombre']}.")

    if tray:
        estado = ("and is still publishing" if tray["activo"]
                  else f"though their latest indexed publication is from "
                       f"{tray['ultimo_anio']}")
        n_anios = tray["anios_activo"]
        span = f"{n_anios} year" + ("" if n_anios == 1 else "s")
        frases.append(
            f"Publishing since {tray['primer_anio']} ({span}, "
            f"{tray['media_anual']} papers/year on average) {estado}.")

    n_lidera = pub_stats.get("first_last_author_count", 0)
    n_total = pub_stats.get("count", 0)
    if n_total:
        if n_lidera == 0:
            frases.append(
                f"Across the {n_total} verified paper{'' if n_total == 1 else 's'} "
                "they always sign in a "
                "middle position: they take part in large groups rather than "
                "leading a line of their own.")
        else:
            frases.append(
                f"They lead as first or last author on {n_lidera} of "
                f"{n_total} paper{'' if n_total == 1 else 's'}.")

    recurrentes = [l for l in (lineas or []) if l.get("recurrente")][:3]
    if recurrentes:
        frases.append("Recurring topics: "
                      + ", ".join(l["tema"] for l in recurrentes) + ".")
    else:
        # Sin temas repetidos: obra dispersa. Decirlo, en vez de disfrazar tres
        # temas sueltos de "líneas de investigación".
        sueltos = [l["tema"] for l in (lineas or [])][:3]
        if sueltos:
            frases.append(
                "No topic repeats across their work: they publish on varied "
                "subjects. Most recently, " + ", ".join(sueltos) + ".")

    if not frases:
        return ("There are not enough verified publications to describe their "
                "scientific profile. Worth confirming the data with the KOL "
                "directly, or supplying their ORCID.")
    return " ".join(frases)


# ----------------------------------------------------------------------
#  Ensamblado
# ----------------------------------------------------------------------

def construir(papers, surname, anio_actual, especialidad_declarada=None,
              pub_stats=None):
    """Devuelve el bloque `perfil_cientifico` completo del kol_profile.json.

    `papers` son los papers YA filtrados de homónimos (verificados +
    sin verificar), tal cual los devuelve pubmed_agent.filter_homonyms.

    Si Miriam declaró una especialidad a mano, esa manda (`origen: declarada`);
    si no, se infiere de los papers (`origen: inferida`).
    """
    serv = servicio(papers)
    inferida = inferir_especialidad(
        papers, servicio_texto=(serv or {}).get("nombre"))

    if especialidad_declarada:
        esp = {
            "nombre": especialidad_declarada,
            "origen": "declared",
            "confianza": "high",
            "detalle": "Specialty supplied manually.",
        }
        if inferida and normalize(inferida["nombre"]) != normalize(especialidad_declarada):
            esp["inferida_de_papers"] = inferida["nombre"]
    elif inferida:
        esp = {
            "nombre": inferida["nombre"],
            "origen": "inferred",
            "confianza": inferida["confianza"],
            "detalle": (
                f"Matches the department recorded in their affiliation, and "
                f"{inferida['papers_que_la_sostienen']} of "
                f"{inferida['total_papers']} publications support it."
                if inferida["origen_senal"] == "department" else
                f"Derived from the MeSH descriptors and journals of their "
                f"publications: {inferida['papers_que_la_sostienen']} of "
                f"{inferida['total_papers']} fit this field."
            ),
            "alternativas": inferida["alternativas"],
        }
    else:
        esp = {
            "nombre": None,
            "origen": "undetermined",
            "confianza": "low",
            "detalle": ("There are not enough publications to derive the field "
                        "reliably."),
        }

    lineas = lineas_investigacion(papers)
    tray = trayectoria(papers, anio_actual)

    return {
        "especialidad": esp,
        "servicio": serv,
        "lineas_investigacion": lineas,
        "colaboradores": colaboradores(papers, surname),
        "trayectoria": tray,
        "tipos_publicacion": tipos_publicacion(papers),
        "resumen": resumen(esp, serv, tray, lineas, pub_stats or {}),
    }
