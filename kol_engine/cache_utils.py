"""
cache_utils — cache simple en disco para respuestas de APIs.

Guardar las respuestas crudas cumple dos objetivos del brief:
  1. Reproducibilidad (#4): re-ejecutar un KOL da el mismo resultado.
  2. Auditabilidad: queda constancia exacta de lo que devolvio cada API.

Con CADUCIDAD (TTL). Sin ella, un perfil regenerado meses despues devolvia los
mismos datos viejos mientras el pie del dossier estampaba la fecha de hoy: el
documento aparentaba una frescura que no tenia. Pasado el TTL la entrada se
ignora y se vuelve a consultar la API; el fichero se conserva para auditoria.

El TTL se puede ajustar con la variable de entorno KOL_CACHE_TTL_DAYS
(0 = sin caducidad, comportamiento antiguo).
"""

import hashlib
import logging
import os
import tempfile
import time

logger = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")

# Los datos bibliometricos se mueven despacio; una semana es un compromiso
# razonable entre no machacar las APIs y no servir un dossier caducado.
DEFAULT_TTL_DAYS = 7


def ttl_segundos():
    """TTL efectivo en segundos. 0 o negativo = sin caducidad."""
    try:
        dias = float(os.getenv("KOL_CACHE_TTL_DAYS", DEFAULT_TTL_DAYS))
    except (TypeError, ValueError):
        dias = DEFAULT_TTL_DAYS
    return dias * 86400


def esta_caducada(ruta, ahora=None):
    """True si la entrada existe pero es mas vieja que el TTL."""
    limite = ttl_segundos()
    if limite <= 0 or not os.path.exists(ruta):
        return False
    ahora = ahora if ahora is not None else time.time()
    return (ahora - os.path.getmtime(ruta)) > limite


def cache_path(prefix, clave):
    """Ruta de cache determinista a partir de un prefijo y una clave."""
    h = hashlib.md5(clave.encode("utf-8")).hexdigest()[:12]
    return os.path.join(CACHE_DIR, f"{prefix}_{h}.txt")


def read(ruta, use_cache=True):
    """Contenido cacheado, o None si no existe, no se usa, esta caduco o vacio.

    Un fichero VACIO se trata como fallo de cache, no como respuesta valida:
    una escritura interrumpida (Ctrl-C, disco lleno) dejaba un fichero de 0
    bytes que pasaba el `is None` y luego reventaba en json.loads() en cada
    ejecucion hasta que caducara.
    """
    if not (use_cache and os.path.exists(ruta)):
        return None
    if esta_caducada(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            contenido = f.read()
    except OSError as e:
        logger.warning("unreadable cache %s: %s", ruta, e)
        return None
    if not contenido.strip():
        logger.warning("empty cache entry, discarded and re-fetched: %s", ruta)
        return None
    return contenido


def write(ruta, contenido):
    """Escribe de forma ATOMICA (temporal + rename).

    Flask sirve peticiones en varios hilos: dos perfiles a la vez sobre la
    misma consulta se pisaban a media escritura y un lector podia leer el
    fichero truncado (medido: 22 de 100 lecturas) y darlo por bueno.
    `os.replace` es atomico dentro del mismo sistema de ficheros, asi que un
    lector ve o el contenido viejo entero o el nuevo entero, nunca la mitad.
    """
    carpeta = os.path.dirname(ruta) or "."
    os.makedirs(carpeta, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
        os.replace(tmp, ruta)
    except BaseException:
        # Nunca dejar el .tmp tirado si algo falla a medias.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# Nombre expresivo para usarla fuera de la cache (entregables).
escritura_atomica = write


def prune(max_age_days=None):
    """Borra entradas de cache mas viejas que el TTL. Devuelve cuantas borro.

    Sin esto la carpeta crece indefinidamente con respuestas que ya nadie
    va a usar (ya caducaron, asi que solo ocupan disco).
    """
    limite = (max_age_days * 86400) if max_age_days else ttl_segundos()
    if limite <= 0 or not os.path.isdir(CACHE_DIR):
        return 0
    ahora = time.time()
    borrados = 0
    for nombre in os.listdir(CACHE_DIR):
        ruta = os.path.join(CACHE_DIR, nombre)
        try:
            if os.path.isfile(ruta) and (ahora - os.path.getmtime(ruta)) > limite:
                os.unlink(ruta)
                borrados += 1
        except OSError:
            continue
    if borrados:
        logger.info("cache: %d expired entries removed", borrados)
    return borrados
