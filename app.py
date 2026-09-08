#!/usr/bin/env python3
"""
app.py — interfaz web del KOL Intelligence System.

Levanta una web local con un formulario: escribes nombre + institucion, pulsas
"Generar" y te muestra el dashboard del KOL con enlaces al PDF y al JSON.

Uso:
    cd 02_Motor_KOL
    python3 app.py
    # abre http://127.0.0.1:5001 en el navegador

Por debajo llama a kol_engine.runner (la MISMA logica que el CLI).
"""

import logging
import os
import traceback

from flask import (Flask, redirect, render_template_string, request,
                   send_from_directory, url_for)

from kol_engine import candidatos, runner

OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "output"))

app = Flask(__name__)

# ---- Estilo Excelia compartido por las paginas ----
BASE_CSS = """
  :root{--navy:#0B1929;--teal:#2DDAAC;--coral:#C47A5C;--blue:#8AAFC8;
        --cream:#F7F5F1;--muted:#5b6b7a;--line:#e3ded5}
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,
       Arial,sans-serif;background:var(--cream);color:var(--navy);line-height:1.5}
  .top{background:var(--navy);color:#fff;padding:20px}
  .top h1{margin:0;font-size:20px}
  .top .sub{color:var(--blue);font-size:13px}
  .wrap{max-width:760px;margin:36px auto;padding:0 20px}
  .card{background:#fff;border:1px solid var(--line);border-radius:14px;
        padding:28px;box-shadow:0 1px 3px rgba(0,0,0,.04)}
  label{display:block;font-weight:600;font-size:13px;margin:14px 0 5px}
  input{width:100%;padding:11px 12px;border:1px solid var(--line);
        border-radius:9px;font-size:15px}
  input:focus{outline:none;border-color:var(--teal)}
  /* El ejemplo tiene que leerse como pista, nunca como texto ya escrito:
     mas claro que el gris por defecto del navegador y en cursiva. */
  input::placeholder{color:#9aa7b2;opacity:1;font-style:italic}
  .row{display:flex;gap:14px}.row>div{flex:1}
  .hint{color:var(--muted);font-size:12px;margin-top:4px}
  button{margin-top:22px;background:var(--teal);color:var(--navy);border:none;
        padding:13px 22px;border-radius:22px;font-size:15px;font-weight:700;
        cursor:pointer;width:100%}
  button:hover{filter:brightness(1.05)}
  .req{color:var(--coral)}
  details{margin:18px 0 6px;border-top:1px solid var(--line);padding-top:12px}
  summary{cursor:pointer;font-size:13px;color:var(--muted);font-weight:600}
  details[open] summary{margin-bottom:6px}
"""

AUTORA = "Miriam Martínez Santos, PhD"

# Pie de autoria. Va en TODAS las pantallas, tambien en la de error: si algo
# falla, la firma sigue siendo la misma.
FOOTER = """
<div class="pie">KOL Intelligence System · created by """ + AUTORA + """</div>
"""

FOOTER_CSS = """
  .pie{max-width:1160px;margin:34px auto 26px;padding:16px 20px 0;
       border-top:1px solid var(--line);color:var(--muted);font-size:12px;
       text-align:center}
"""

# El overlay ("Buscando…", "Generando…") lo comparten las dos pantallas.
OVERLAY_CSS = """
  #overlay{display:none;position:fixed;inset:0;background:rgba(11,25,41,.92);
        color:#fff;align-items:center;justify-content:center;flex-direction:column;
        text-align:center;padding:20px;z-index:9}
  .spin{width:46px;height:46px;border:4px solid rgba(255,255,255,.25);
        border-top-color:var(--teal);border-radius:50%;animation:s 1s linear
        infinite;margin-bottom:18px}
  @keyframes s{to{transform:rotate(360deg)}}
"""

FORM_PAGE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KOL Intelligence System</title><style>""" + BASE_CSS + FOOTER_CSS + OVERLAY_CSS + """
</style></head><body>
<div class="top"><h1>KOL Intelligence System</h1>
  <div class="sub">360° profile of a medical Key Opinion Leader</div></div>
<div class="wrap"><div class="card">
  <form method="POST" action="/buscar"
        onsubmit="document.getElementById('overlay').style.display='flex'">
    <label>Doctor's name <span class="req">*</span></label>
    <input name="nombre" required autofocus autocomplete="off">

    <button type="submit">Find doctor</button>
  </form>
</div></div>
""" + FOOTER + """
<div id="overlay"><div class="spin"></div>
  <div><b>Searching PubMed…</b><br>Finding which centres that name
  publishes from.</div></div>
</body></html>
"""

CANDIDATOS_PAGE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Which one? — {{ nombre }}</title>
<style>""" + BASE_CSS + FOOTER_CSS + OVERLAY_CSS + """
  .cand{display:flex;gap:14px;align-items:center;justify-content:space-between;
        border:1px solid var(--line);border-radius:12px;padding:16px 18px;
        margin-bottom:12px;background:#fff}
  .cand:hover{border-color:var(--teal)}
  .cand .nom{font-weight:700;font-size:15px}
  .cand .centro{font-size:14px;margin-top:2px}
  .cand .meta{color:var(--muted);font-size:13px;margin-top:3px}
  .cand .ojo{color:var(--coral);font-size:12px;margin-top:6px;max-width:52ch}
  .cand .ej{color:var(--muted);font-size:12px;margin-top:6px;font-style:italic}
  .cand form{margin:0}
  .cand button{margin:0;white-space:nowrap;width:auto;padding:10px 18px;
        font-size:14px}
  .n{background:var(--navy);color:#fff;border-radius:20px;padding:3px 11px;
     font-size:12px;font-weight:700;margin-right:8px}
  .aviso{background:#fff;border:1px solid var(--line);border-left:4px solid
        var(--coral);border-radius:10px;padding:14px 16px;margin-bottom:18px;
        font-size:13px;color:var(--muted)}
  .volver{display:inline-block;margin-top:6px;color:var(--muted);font-size:13px}
</style></head><body>
<div class="top"><h1>{{ nombre }}</h1>
  <div class="sub">Which one is it? Pick the centre where they work</div></div>
<div class="wrap">

  {% if candidatos %}
  <div class="aviso">
    These are the centres someone with that surname and initial signs from.
    <b>If there is more than one, it may be the same person at different
    stages, or different people</b> — which is why you pick. The name on each
    card is the one recorded in PubMed, so <b>it does not matter how you typed
    it</b>: the dossier will use the correct form. Based on the
    <b>{{ papers_analizados }}</b> most recent papers
    {% if total_pubmed > papers_analizados %}out of the <b>{{ total_pubmed }}</b>
    PubMed holds under that name{% endif %}.
  </div>

  {% for c in candidatos %}
  <div class="cand">
    <div>
      <div class="nom">{{ c.nombre or nombre }}</div>
      <div class="centro">{{ c.etiqueta }}</div>
      <div class="meta"><span class="n">{{ c.papers }}</span>
        {% if c.ciudad %}{{ c.ciudad }} · {% endif %}
        {% if c.primer_anio %}{{ c.primer_anio }}–{{ c.ultimo_anio }}{% endif %}
      </div>
      {% if c.otros_nombres %}
      <div class="ojo">{{ c.otros_nombres|join(', ') }} also signs from
        there — same surname and initial, but a <b>different person</b>:
        those papers are not theirs.</div>
      {% endif %}
      {% if c.ejemplo %}<div class="ej">«{{ c.ejemplo }}»</div>{% endif %}
    </div>
    <form method="POST" action="/generar"
          onsubmit="document.getElementById('overlay').style.display='flex'">
      <input type="hidden" name="nombre" value="{{ c.nombre or nombre }}">
      <input type="hidden" name="institucion" value="{{ c.etiqueta }}">
      <input type="hidden" name="apellidos" value="{{ apellidos or '' }}">
      <button type="submit">This is them</button>
    </form>
  </div>
  {% endfor %}
  {% else %}
  <div class="aviso">
    <b>PubMed returns no centre for that name.</b>
    {% if total_pubmed %}There are {{ total_pubmed }} papers with that surname
    and initial, but none carries a recognisable affiliation.{% else %}
    There are no papers with that surname and initial: check the spelling.
    {% endif %} You can type the centre by hand below.
  </div>
  {% endif %}

  {% if omitidos %}
  <div class="aviso"><b>{{ omitidos }}</b> further centres are omitted, all
    with fewer publications than those above. If the one you want is missing,
    type it by hand below.</div>
  {% endif %}

  <div class="card">
    <details {% if not candidatos %}open{% endif %}>
      <summary>None of these / type the centre by hand</summary>
      <form method="POST" action="/generar"
            onsubmit="document.getElementById('overlay').style.display='flex'">
        <input type="hidden" name="nombre" value="{{ nombre }}">
        <label>Where they work</label>
        <input name="institucion" autocomplete="off">
        <div class="hint">Leave it empty to analyse <b>with no centre</b>: it
          still works, but confidence will be <b>low</b> and homonyms may get
          mixed in.</div>
        <div class="row">
          <div><label>ORCID</label><input name="orcid" autocomplete="off">
            <div class="hint">The only input that raises confidence to
              «high».</div></div>
          <div><label>Surname(s)</label>
            <input name="apellidos" value="{{ apellidos or '' }}"
                   autocomplete="off">
            <div class="hint">Only if the given name is compound.</div></div>
        </div>
        <button type="submit">Generate profile</button>
      </form>
    </details>
    <a class="volver" href="/">← Search another name</a>
  </div>
</div>
""" + FOOTER + """
<div id="overlay"><div class="spin"></div>
  <div><b>Building profile…</b><br>Querying PubMed, ClinicalTrials.gov and
  Europe PMC. This can take a few seconds.</div></div>
</body></html>
"""

RESULT_PAGE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>KOL — {{ nombre }}</title><style>""" + BASE_CSS + FOOTER_CSS + """
  .bar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;
       justify-content:space-between}
  .chips{display:flex;gap:10px;flex-wrap:wrap}
  .chip{background:#fff;border:1px solid var(--line);border-radius:20px;
        padding:6px 14px;font-size:13px}
  .chip b{color:var(--navy)}
  .actions a{display:inline-block;text-decoration:none;background:var(--navy);
        color:#fff;padding:9px 16px;border-radius:20px;font-size:13px;
        font-weight:600;margin-left:8px}
  .actions a.ghost{background:#fff;color:var(--navy);border:1px solid var(--line)}
  .vok{color:#0a7a5c;font-weight:700}.vfail{color:#a2302b;font-weight:700}
  iframe{width:100%;height:1200px;border:1px solid var(--line);border-radius:14px;
         margin-top:18px;background:#fff}
  .wrapfull{max-width:1160px;margin:22px auto;padding:0 20px}
</style></head><body>
<div class="top"><div class="bar" style="max-width:1160px;margin:0 auto">
  <div><h1>{{ nombre }}</h1>
    <div class="sub">KOL Score {{ score }}/100 · {{ tier }} ·
      confidence {{ confidence }}</div></div>
  <div class="actions">
    <a class="ghost" href="/">← New analysis</a>
    <a href="/output/{{ pdf_name }}" download>Download PDF</a>
  </div>
</div></div>
<div class="wrapfull">
  <div class="chips">
    <span class="chip"><b>{{ pubs_ver }}</b> verified publications</span>
    <span class="chip"><b>{{ pubs_exc }}</b> homonyms excluded</span>
    <span class="chip"><b>{{ trials_txt }}</b></span>
    {% if area %}<span class="chip">Field: <b>{{ area }}</b>
      {% if area_inferida %}<i>(inferred)</i>{% endif %}</span>{% endif %}
    {% if ciudad %}<span class="chip">City: <b>{{ ciudad }}</b>
      {% if ciudad_deducida %}<i>(derived from the centre)</i>{% endif %}</span>{% endif %}
    <span class="chip">Verification:
      {% if vok %}<span class="vok">✓ OK</span>
      {% else %}<span class="vfail">✗ review</span>{% endif %}</span>
  </div>
  <iframe src="/output/{{ html_name }}" title="KOL dashboard"></iframe>
</div>
""" + FOOTER + """
</body></html>
"""

ERROR_PAGE = """
<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Error</title><style>""" + BASE_CSS + FOOTER_CSS + """</style></head><body>
<div class="top"><h1>Something went wrong</h1></div>
<div class="wrap"><div class="card">
  <p>Could not build the profile for <b>{{ nombre }}</b>.</p>
  <p class="hint">{{ error }}</p>
  <p>This is usually a connection problem with PubMed/ClinicalTrials. Try
     again in a few seconds.</p>
  <p><a href="/">← Back</a></p>
</div></div>
""" + FOOTER + """
</body></html>
"""


# Tope por campo. Holgado para cualquier nombre real, pero acota la query.
# Sin esto, los avisos del motor (caché corrupta, 429, red inestable) no se
# ven en ningún sitio: la app fallaba en silencio.
logging.basicConfig(
    level=os.getenv("KOL_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")

# Tope por campo. Holgado para cualquier nombre real, pero acota la query.
MAX_CAMPO = 120

# Fichas de centro que se enseñan. Mas abajo la cola es siempre de centros con
# uno o dos papers (congresos, colaboraciones sueltas, homónimos lejanos): no
# ayudan a elegir y alargan la pantalla. Se dice cuantos se omiten, nunca se
# esconden en silencio.
MAX_CANDIDATOS = 8


@app.route("/")
def index():
    return render_template_string(FORM_PAGE)


def _demasiado_largo(pares):
    """Etiquetas de los campos que pasan de MAX_CAMPO caracteres.

    Un nombre desmesurado genera una query gigante y PubMed responde 414.
    Mejor decirlo aqui que fallar contra la API con un error criptico.
    """
    return [etiqueta for etiqueta, valor in pares
            if len(valor or "") > MAX_CAMPO]


@app.route("/buscar", methods=["POST"])
def buscar():
    """Paso 1 -> paso 2: del nombre a los centros candidatos.

    Solo se pide el nombre. Aqui se busca en PubMed SIN filtro de afiliacion y
    se agrupan las afiliaciones del autor, para que la eleccion del centro la
    haga la persona viendo los datos en vez de adivinarlo antes de empezar.
    """
    f = request.form
    nombre = (f.get("nombre") or "").strip()
    if not nombre:
        return redirect(url_for("index"))

    apellidos = (f.get("apellidos") or "").strip() or None
    largos = _demasiado_largo([("name", nombre), ("surname", apellidos)])
    if largos:
        return render_template_string(
            ERROR_PAGE, nombre=nombre[:80],
            error=f"Field too long ({', '.join(largos)}): "
                  f"maximum {MAX_CAMPO} characters.")

    try:
        res = candidatos.buscar_candidatos(nombre, surname=apellidos)
    except Exception as e:
        traceback.print_exc()
        return render_template_string(ERROR_PAGE, nombre=nombre, error=str(e))

    encontrados = res["candidatos"]
    return render_template_string(
        CANDIDATOS_PAGE, nombre=nombre, apellidos=apellidos,
        candidatos=encontrados[:MAX_CANDIDATOS],
        omitidos=max(0, len(encontrados) - MAX_CANDIDATOS),
        papers_analizados=res["papers_analizados"],
        total_pubmed=res["total_pubmed"])


@app.route("/generar", methods=["POST"])
def generar():
    f = request.form
    nombre = (f.get("nombre") or "").strip()
    if not nombre:
        return redirect(url_for("index"))

    largos = _demasiado_largo(
        (("name", nombre), ("institution", f.get("institucion")),
         ("city", f.get("ciudad")), ("specialty", f.get("especialidad")),
         ("surname", f.get("apellidos")), ("ORCID", f.get("orcid"))))
    if largos:
        return render_template_string(
            ERROR_PAGE, nombre=nombre[:80],
            error=f"Field too long ({', '.join(largos)}): "
                  f"maximum {MAX_CAMPO} characters.")
    # El apellido se deduce del nombre completo (disambiguator.parse_name).
    # Solo se pasa explicito si Miriam lo ha escrito en ajustes avanzados,
    # que es lo que salva los nombres de pila compuestos.
    surname = (f.get("apellidos") or "").strip() or None
    campos = {k: (f.get(k) or "").strip() or None
              for k in ("institucion", "ciudad", "pais", "orcid", "especialidad")}
    try:
        res = runner.run_pipeline(nombre, surname=surname, **campos)
    except Exception as e:
        traceback.print_exc()
        return render_template_string(ERROR_PAGE, nombre=nombre, error=str(e))

    perfil = res["perfil"]
    trials = perfil["trials"]
    n_trials = trials["verified_count"] if trials else 0
    trials_txt = f"{n_trials} verified trial" + ("" if n_trials == 1 else "s")
    return render_template_string(
        RESULT_PAGE,
        nombre=perfil["identity"]["header_name"],
        score=perfil["score"]["total"], tier=perfil["score"]["tier"],
        confidence=perfil["disambiguation"]["confidence"],
        pubs_ver=perfil["publications"]["verified_count"],
        pubs_exc=perfil["publications"]["excluded_count"],
        trials_txt=trials_txt,
        vok=res["verify_report"]["ok"],
        area=perfil["identity"].get("specialty"),
        area_inferida=perfil["identity"].get("specialty_origin") == "inferida",
        ciudad=perfil["identity"].get("city"),
        ciudad_deducida=bool(res.get("ciudad_deducida")),
        html_name=os.path.basename(res["html_path"]),
        pdf_name=os.path.basename(res["pdf_path"]),
    )


@app.route("/output/<path:filename>")
def output_file(filename):
    """Sirve los entregables generados (HTML, PDF, JSON)."""
    return send_from_directory(OUTPUT_DIR, filename)


if __name__ == "__main__":
    print("\n  KOL Intelligence System — open:  http://127.0.0.1:5001\n")
    app.run(host="127.0.0.1", port=5001, debug=False)
