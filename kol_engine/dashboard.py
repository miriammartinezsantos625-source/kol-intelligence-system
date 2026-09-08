"""
dashboard — kol_profile.json -> HTML de 5 pestanas (self-contained).

El HTML incrusta el perfil como objeto JS (KOL_DATA) y el JavaScript de la
plantilla rellena la pagina desde ahi. Asi el dashboard NUNCA se desincroniza
del perfil: es la misma fuente de verdad.
"""

import json
import logging
import os

from .cache_utils import escritura_atomica
from .profile import _slug

logger = logging.getLogger(__name__)

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "templates",
                        "dashboard_template.html")
PLACEHOLDER = "__KOL_DATA__"


def render_dashboard(profile, output_dir):
    """Genera KOL_Dashboard_{Nombre}.html y devuelve su ruta."""
    with open(TEMPLATE, "r", encoding="utf-8") as f:
        plantilla = f.read()

    # json.dumps seguro para incrustar en <script>: escapamos '<' para que un
    # titulo con '</script>' no rompa la pagina.
    datos = json.dumps(profile, ensure_ascii=False).replace("<", "\\u003c")
    html = plantilla.replace(PLACEHOLDER, datos)

    os.makedirs(output_dir, exist_ok=True)
    slug = _slug(profile["identity"]["full_name"])
    ruta = os.path.join(output_dir, f"KOL_Dashboard_{slug}.html")
    escritura_atomica(ruta, html)
    logger.info("dashboard generated: %s", ruta)
    return ruta
