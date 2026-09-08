"""
text_utils — utilidades de texto compartidas.

Toda la desambiguacion de homonimos compara nombres y afiliaciones. Para que
"Valéncia", "VALENCIA" y "valencia" cuenten como iguales, normalizamos:
quitamos tildes, pasamos a minusculas y convertimos guiones en espacios.

Regla dura del proyecto: las QUERIES a PubMed van SIN tildes; los OUTPUTS
(dashboard, PDF) van CON tildes. Por eso `strip_accents` se usa al construir
queries y al comparar, nunca al mostrar.
"""

import re
import unicodedata


def strip_accents(text):
    """Devuelve el texto sin tildes ni diacriticos.

    'Teresa San-Miguel Valéncia' -> 'Teresa San-Miguel Valencia'
    Usa la descomposicion Unicode (NFD): separa la letra de su tilde y luego
    descarta las marcas (categoria 'Mn' = Mark, nonspacing).
    """
    if not text:
        return ""
    descompuesto = unicodedata.normalize("NFD", text)
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def normalize(text):
    """Forma canonica para COMPARAR textos (no para mostrar).

    - sin tildes
    - en minusculas
    - toda la puntuacion (comas, puntos, guiones, /) convertida en espacios
    - multiples espacios colapsados a uno solo

    Asi 'San-Miguel', 'San Miguel' y 'san  miguel' comparan como iguales
    ('san miguel'), y 'Valencia,' pasa a ser la palabra 'valencia' (clave para
    la comparacion por palabra completa en contains_term).
    """
    if not text:
        return ""
    sin_tildes = strip_accents(text).lower()
    # Cualquier cosa que no sea letra/numero/espacio -> espacio.
    solo_alfanum = re.sub(r"[^a-z0-9 ]+", " ", sin_tildes)
    return " ".join(solo_alfanum.split())  # colapsa espacios repetidos


def contains_term(text, term):
    """True si `term` aparece en `text` como PALABRA completa (no subcadena).

    Evita falsos positivos como que 'fe' (de 'La Fe') coincida dentro de
    'Tenerife'. Truco: rodear ambos de espacios y buscar la subcadena
    ' fe ' dentro de ' ... tenerife ... ' -> no coincide; ' ... la fe ... '
    -> si coincide. Funciona igual para terminos de varias palabras.
    """
    if not text or not term:
        return False
    texto = f" {normalize(text)} "
    palabra = f" {normalize(term)} "
    return palabra in texto


def matches_any(text, terms):
    """True si alguno de los `terms` aparece como palabra completa en `text`.
    Devuelve el termino que coincidio, o None."""
    for t in terms:
        if contains_term(text, t):
            return t
    return None
