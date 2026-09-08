"""
centros — deduce la CIUDAD a partir del nombre del centro de trabajo.

¿Por qué existe?
Para que Miriam solo tenga que escribir DOS cosas: el nombre del médico y
dónde trabaja. La ciudad es la señal más útil contra homónimos (entra en
`location_terms` y filtra afiliaciones), pero pedirla por separado es fricción
innecesaria: si el centro es "Hospital Doctor Peset", la ciudad es Valencia y
el sistema puede saberlo solo.

Tres estrategias, en orden:

  1. La ciudad viene escrita en el propio texto — "Hospital La Fe, Valencia"
     o "Hospital La Fe (Valencia)". Se lee y ya está.
  2. El centro está en el catálogo `CENTROS` de aquí abajo (hospitales
     españoles de referencia). Se busca por una palabra distintiva.
  3. El texto contiene el nombre de una ciudad española conocida.

Si ninguna funciona devolvemos None, y el sistema sigue como hasta ahora: con
los términos del propio nombre del centro ("peset", "fe"), que ya filtran
bastante. Deducir mal la ciudad sería peor que no deducirla, así que ante la
duda no inventamos.
"""

import re

from .text_utils import contains_term, normalize

# ----------------------------------------------------------------------
#  Catálogo de centros españoles de referencia
# ----------------------------------------------------------------------
# Cada entrada: (claves distintivas, ciudad).
# Las "claves" son palabras que identifican al centro SIN ambigüedad dentro de
# su ciudad. Deben ir sin tildes y en minúsculas (se comparan normalizadas).
# El orden importa: se devuelve la PRIMERA coincidencia, así que las claves
# más específicas van antes que las genéricas.
CENTROS = [
    # --- Valencia ---
    (["la fe", "politecnic la fe", "politecnico la fe"], "Valencia"),
    (["peset", "doctor peset"], "Valencia"),
    (["clinico universitario de valencia", "incliva"], "Valencia"),
    (["general universitario de valencia", "consorcio hospital general"], "Valencia"),
    (["arnau de vilanova"], "Valencia"),
    (["manises"], "Manises"),
    (["ribera salud", "hospital de la ribera", "alzira"], "Alzira"),
    (["iis la fe", "instituto de investigacion sanitaria la fe"], "Valencia"),
    (["catolica de valencia", "ucv"], "Valencia"),

    # --- Madrid ---
    (["12 de octubre", "doce de octubre"], "Madrid"),
    (["la paz", "idipaz"], "Madrid"),
    (["ramon y cajal", "irycis"], "Madrid"),
    (["gregorio maranon", "maranon"], "Madrid"),
    (["clinico san carlos"], "Madrid"),
    (["puerta de hierro"], "Majadahonda"),
    (["fundacion jimenez diaz", "jimenez diaz"], "Madrid"),
    (["la princesa"], "Madrid"),
    (["cnio"], "Madrid"),
    (["cnic"], "Madrid"),
    (["hm hospitales", "hm sanchinarro", "ciocc"], "Madrid"),
    (["quironsalud madrid"], "Madrid"),
    (["infanta sofia"], "San Sebastián de los Reyes"),
    (["severo ochoa"], "Leganés"),
    (["getafe"], "Getafe"),
    (["alcorcon"], "Alcorcón"),
    (["mostoles"], "Móstoles"),
    (["principe de asturias"], "Alcalá de Henares"),

    # --- Barcelona ---
    (["vall d hebron", "vall hebron", "vhio", "vhir"], "Barcelona"),
    (["clinic de barcelona", "idibaps"], "Barcelona"),
    (["sant pau", "santa creu i sant pau"], "Barcelona"),
    (["bellvitge", "idibell"], "L'Hospitalet de Llobregat"),
    (["ico", "institut catala d oncologia"], "L'Hospitalet de Llobregat"),
    (["sant joan de deu"], "Esplugues de Llobregat"),
    (["del mar", "imim"], "Barcelona"),
    (["germans trias", "can ruti"], "Badalona"),
    (["irb barcelona", "irsicaixa"], "Barcelona"),

    # --- Navarra / País Vasco ---
    (["clinica universidad de navarra", "cun", "cima"], "Pamplona"),
    (["complejo hospitalario de navarra"], "Pamplona"),
    (["cruces", "biocruces"], "Barakaldo"),
    (["donostia", "biodonostia"], "San Sebastián"),
    (["basurto"], "Bilbao"),
    (["txagorritxu", "araba"], "Vitoria-Gasteiz"),

    # --- Andalucía ---
    (["virgen del rocio", "ibis"], "Sevilla"),
    (["virgen macarena"], "Sevilla"),
    (["reina sofia", "imibic"], "Córdoba"),
    (["virgen de las nieves"], "Granada"),
    (["clinico san cecilio"], "Granada"),
    (["regional de malaga", "carlos haya", "ibima"], "Málaga"),
    (["virgen de la victoria"], "Málaga"),
    (["puerta del mar"], "Cádiz"),
    (["torrecardenas"], "Almería"),
    (["juan ramon jimenez"], "Huelva"),
    (["virgen de valme"], "Sevilla"),

    # --- Galicia / Asturias / Cantabria ---
    (["chuac", "a coruna", "inibic"], "A Coruña"),
    (["chus", "santiago de compostela", "idis"], "Santiago de Compostela"),
    (["alvaro cunqueiro", "vigo"], "Vigo"),
    (["hospital universitario central de asturias", "huca", "ispa"], "Oviedo"),
    (["marques de valdecilla", "idival"], "Santander"),

    # --- Castilla y León / Castilla-La Mancha / Extremadura ---
    (["clinico universitario de salamanca", "ibsal"], "Salamanca"),
    (["rio hortega", "clinico universitario de valladolid"], "Valladolid"),
    (["complejo asistencial de burgos"], "Burgos"),
    (["nacional de paraplejicos"], "Toledo"),
    (["complejo hospitalario de toledo"], "Toledo"),
    (["albacete"], "Albacete"),
    (["infanta cristina", "badajoz"], "Badajoz"),

    # --- Aragón / La Rioja / Murcia / Baleares / Canarias ---
    (["miguel servet", "iis aragon"], "Zaragoza"),
    (["lozano blesa"], "Zaragoza"),
    (["san pedro", "cibir"], "Logroño"),
    (["virgen de la arrixaca", "imib"], "Murcia"),
    (["morales meseguer"], "Murcia"),
    (["son espases", "idisba"], "Palma de Mallorca"),
    (["nuestra senora de candelaria"], "Santa Cruz de Tenerife"),
    (["hospital universitario de canarias"], "La Laguna"),
    (["doctor negrin", "negrin"], "Las Palmas de Gran Canaria"),

    # --- Cataluña (resto) / Comunidad Valenciana (resto) ---
    (["joan xxiii", "tarragona"], "Tarragona"),
    (["arnau de vilanova de lleida", "lleida"], "Lleida"),
    (["josep trueta", "girona", "idibgi"], "Girona"),
    (["general de alicante", "isabial"], "Alicante"),
    (["general de elche", "elche"], "Elche"),
    (["general de castellon", "castellon"], "Castellón de la Plana"),
]

# Ciudades españolas frecuentes, como última red (estrategia 3). Se comparan
# por palabra completa, así que 'leon' no coincide dentro de 'leonardo'.
CIUDADES = [
    "Madrid", "Barcelona", "Valencia", "Sevilla", "Zaragoza", "Málaga",
    "Murcia", "Palma de Mallorca", "Las Palmas de Gran Canaria", "Bilbao",
    "Alicante", "Córdoba", "Valladolid", "Vigo", "Gijón", "Granada",
    "A Coruña", "Vitoria-Gasteiz", "Elche", "Oviedo", "Badalona", "Cartagena",
    "Terrassa", "Jerez de la Frontera", "Sabadell", "Santa Cruz de Tenerife",
    "Pamplona", "Almería", "Alcalá de Henares", "San Sebastián", "Leganés",
    "Santander", "Castellón de la Plana", "Burgos", "Albacete", "Getafe",
    "Salamanca", "Logroño", "Huelva", "Marbella", "Lleida", "Tarragona",
    "León", "Cádiz", "Jaén", "Ourense", "Girona", "Lugo", "Cáceres",
    "Melilla", "Badajoz", "Toledo", "Manises", "Alzira", "Barakaldo",
    "Majadahonda", "La Laguna", "Santiago de Compostela",
    "L'Hospitalet de Llobregat", "Esplugues de Llobregat",
    "San Sebastián de los Reyes", "Alcorcón", "Móstoles",
]


def _ciudad_escrita(texto):
    """Estrategia 1: la ciudad viene tras una coma o entre paréntesis.

    'Hospital La Fe, Valencia'   -> 'Valencia'
    'Hospital La Fe (Valencia)'  -> 'Valencia'

    Solo se acepta si el trozo encontrado es una ciudad conocida: así
    'Servicio de Cardiología, Hospital X' no nos hace creer que la ciudad es
    'Hospital X'.
    """
    candidatos = []
    entre_parentesis = re.findall(r"\(([^)]+)\)", texto)
    candidatos.extend(entre_parentesis)
    if "," in texto:
        candidatos.append(texto.rsplit(",", 1)[1])

    for trozo in candidatos:
        trozo = trozo.strip()
        for ciudad in CIUDADES:
            if normalize(trozo) == normalize(ciudad):
                return ciudad
    return None


def _ciudad_por_catalogo(texto):
    """Estrategia 2: el centro está en el catálogo CENTROS."""
    for claves, ciudad in CENTROS:
        for clave in claves:
            if contains_term(texto, clave):
                return ciudad
    return None


def _ciudad_mencionada(texto):
    """Estrategia 3: el texto menciona una ciudad conocida en cualquier sitio.

    Las ciudades de nombre largo van primero para que 'Santiago de Compostela'
    gane a 'Santiago' si ambas encajasen.
    """
    por_longitud = sorted(CIUDADES, key=lambda c: -len(c))
    for ciudad in por_longitud:
        if contains_term(texto, ciudad):
            return ciudad
    return None


def deducir_ciudad(centro):
    """Devuelve la ciudad deducida del nombre del centro, o None.

    >>> deducir_ciudad("Hospital Doctor Peset")
    'Valencia'
    >>> deducir_ciudad("Hospital Universitari i Politècnic La Fe")
    'Valencia'
    >>> deducir_ciudad("Clínica Universidad de Navarra")
    'Pamplona'
    >>> deducir_ciudad("Centro de salud del pueblo") is None
    True
    """
    if not centro or not centro.strip():
        return None
    texto = centro.strip()
    return (_ciudad_escrita(texto)
            or _ciudad_por_catalogo(texto)
            or _ciudad_mencionada(texto))


def limpiar_centro(centro):
    """Quita la ciudad del final del nombre del centro, si venía pegada.

    'Hospital La Fe, Valencia' -> 'Hospital La Fe'
    Así la portada del dossier no repite 'Valencia · Valencia'.
    """
    if not centro:
        return ""
    texto = centro.strip()
    # Quita un '(Ciudad)' final.
    texto = re.sub(r"\s*\([^)]*\)\s*$", "", texto).strip()
    # Quita un ', Ciudad' final si esa parte es una ciudad conocida.
    if "," in texto:
        cabeza, cola = texto.rsplit(",", 1)
        if any(normalize(cola) == normalize(c) for c in CIUDADES):
            texto = cabeza.strip()
    return texto
