"""
pdf — kol_profile.json -> dossier PDF de 5 paginas (estilo editorial Excelia).

Paginas:
  1. Portada            (nombre, servicio, area, tier, score, fuentes)
  2. Resumen ejecutivo  (quien es, KPIs, desglose de score, desambiguacion)
  3. Publicaciones      (tabla + revistas)
  4. Perfil cientifico  (lineas, colaboradores, actividad, ensayos, metricas)
  5. Briefing pre-visita

Se genera desde el perfil (misma fuente de verdad que el dashboard).
"""

import logging
import os
import tempfile

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageBreak, PageTemplate,
                                Paragraph, Spacer, Table, TableStyle)

from .profile import _slug

# ---- Paleta Excelia ----
NAVY = colors.HexColor("#0B1929")
TEAL = colors.HexColor("#2DDAAC")
CORAL = colors.HexColor("#C47A5C")
BLUE = colors.HexColor("#8AAFC8")
CREAM = colors.HexColor("#F7F5F1")
LINE = colors.HexColor("#e3ded5")
MUTED = colors.HexColor("#5b6b7a")
WHITE = colors.white

logger = logging.getLogger(__name__)

MAXES = {"publications": 40, "trials": 20, "influence": 15,
         "therapeutic_relevance": 15, "crm": 10}
NICE = {"publications": "Publications", "trials": "Trials",
        "influence": "Influence", "therapeutic_relevance": "Therap. relevance",
        "crm": "CRM"}


# ----------------------------------------------------------------------
#  Estilos
# ----------------------------------------------------------------------

def _styles():
    ss = getSampleStyleSheet()
    st = {}
    st["h1"] = ParagraphStyle("h1", parent=ss["Title"], textColor=NAVY,
                              fontSize=22, spaceAfter=6, alignment=TA_LEFT)
    st["h2"] = ParagraphStyle("h2", parent=ss["Heading2"], textColor=NAVY,
                              fontSize=15, spaceBefore=6, spaceAfter=8)
    st["body"] = ParagraphStyle("body", parent=ss["BodyText"], fontSize=10,
                                textColor=NAVY, leading=14)
    st["muted"] = ParagraphStyle("muted", parent=st["body"], textColor=MUTED,
                                 fontSize=9, leading=12)
    st["cell"] = ParagraphStyle("cell", parent=st["body"], fontSize=8.5,
                                leading=11)
    st["cellh"] = ParagraphStyle("cellh", parent=st["cell"], textColor=MUTED,
                                 fontName="Helvetica-Bold", fontSize=8)
    st["unver"] = ParagraphStyle("unver", parent=st["body"], textColor=CORAL,
                                 fontName="Helvetica-Bold")
    return st


# ----------------------------------------------------------------------
#  Cabecera / pie (paginas 2-5) y portada (pagina 1)
# ----------------------------------------------------------------------

def _cover(canvas, doc):
    """Pagina 1: portada a sangre en navy."""
    c = canvas
    w, h = A4
    c.saveState()
    c.setFillColor(NAVY)
    c.rect(0, 0, w, h, fill=1, stroke=0)

    # Circulo con iniciales
    cx, cy, r = w / 2, h - 6 * cm, 1.5 * cm
    c.setFillColor(TEAL)
    c.circle(cx, cy, r, fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(cx, cy - 9, doc.kol["identity"]["initials"])

    ident = doc.kol["identity"]
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 24)
    c.drawCentredString(cx, cy - 3 * cm, ident["header_name"])
    c.setFillColor(BLUE)
    c.setFont("Helvetica", 13)
    linea2 = " · ".join(filter(None, [ident["institution"], ident["city"]]))
    c.drawCentredString(cx, cy - 3.9 * cm, linea2)

    # El servicio sale de la afiliacion de sus propios papers; la especialidad
    # se deduce de sus MeSH. Si son inferidos, se dice — nunca se presenta un
    # dato deducido como si lo hubiera declarado el KOL.
    y = cy - 4.6 * cm
    if ident.get("service"):
        c.setFillColor(WHITE)
        c.setFont("Helvetica", 11)
        c.drawCentredString(cx, y, ident["service"])
        y -= 0.65 * cm
    if ident.get("specialty"):
        c.setFillColor(TEAL)
        c.setFont("Helvetica-Bold", 12)
        sufijo = (" (inferred from their publications)"
                  if ident.get("specialty_origin") == "inferred" else "")
        c.drawCentredString(cx, y, ident["specialty"] + sufijo)

    # Tarjeta de score
    badge = ident["badge"]
    c.setFillColor(TEAL)
    c.roundRect(cx - 3.5 * cm, cy - 8.3 * cm, 7 * cm, 2.4 * cm, 10,
                fill=1, stroke=0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(cx, cy - 7.4 * cm, f"{badge['score']}/100")
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(cx, cy - 8.0 * cm, badge["tier"])

    # Pie de portada
    v = doc.kol["verification_note"]
    c.setFillColor(BLUE)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(cx, 2.4 * cm, "Sources: " + " · ".join(v["sources"]))
    c.drawCentredString(cx, 1.9 * cm,
                        f"Generated on {v['date']} · KOL Intelligence System")
    c.restoreState()


def _header_footer(canvas, doc):
    """Paginas 2-5: banda de cabecera + pie con nº de pagina."""
    c = canvas
    w, h = A4
    c.saveState()
    # Banda superior
    c.setFillColor(NAVY)
    c.rect(0, h - 1.6 * cm, w, 1.6 * cm, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(2 * cm, h - 1.05 * cm, doc.kol["identity"]["header_name"])
    c.setFillColor(TEAL)
    c.setFont("Helvetica-Bold", 9)
    c.drawRightString(w - 2 * cm, h - 1.05 * cm,
                      f"{doc.kol['identity']['badge']['tier']} · "
                      f"{doc.kol['identity']['badge']['score']}/100")
    # Pie
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8)
    c.drawString(2 * cm, 1.1 * cm, "KOL Intelligence System")
    c.drawRightString(w - 2 * cm, 1.1 * cm, f"Page {doc.page}")
    c.restoreState()


# ----------------------------------------------------------------------
#  Bloques de contenido (flowables)
# ----------------------------------------------------------------------

# Cuerpo y interlineado de cada mitad del KPI. El interlineado (`leading`) va
# aparte del tamaño a proposito: es la altura de la linea, y es lo que reserva
# la fila de la tabla. Si se queda corto, el numero se sale de su celda.
KPI_VALOR_PT, KPI_VALOR_LEADING = 18, 21
KPI_ETIQUETA_PT, KPI_ETIQUETA_LEADING = 8, 10


def _kpi_table(pairs):
    """Fila de KPIs como tabla (valor grande arriba, etiqueta debajo)."""
    est_valor, est_etiqueta = _kpi_styles()
    vals = [Paragraph(f"<b>{v}</b>", est_valor) for v, _ in pairs]
    lbls = [Paragraph(l, est_etiqueta) for _, l in pairs]
    t = Table([vals, lbls], colWidths=[(17 * cm) / len(pairs)] * len(pairs))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        # Solo separadores VERTICALES: el numero y su etiqueta son una sola
        # cosa, y una raya entre ambos los partia en dos.
        ("LINEAFTER", (0, 0), (-2, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, 0), 9),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 1),
        ("TOPPADDING", (0, -1), (-1, -1), 0),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 9),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def _kpi_styles():
    """Estilos del valor y de la etiqueta de un KPI.

    El tamaño va en el ESTILO, no en una etiqueta <font> dentro del texto: el
    interlineado se calcula desde el estilo, asi que un <font size=18> sobre un
    estilo de 10pt dibujaba digitos de 18pt en una linea de 12. El numero se
    salia de su fila y la raya horizontal de la tabla le cruzaba por la base
    (visto en el dossier de Luis Martí-Bonmatí, con KPIs de tres cifras).
    """
    valor = ParagraphStyle(
        "kpi_valor", fontName="Helvetica", fontSize=KPI_VALOR_PT,
        leading=KPI_VALOR_LEADING, textColor=NAVY, alignment=TA_LEFT)
    etiqueta = ParagraphStyle(
        "kpi_etiqueta", fontName="Helvetica", fontSize=KPI_ETIQUETA_PT,
        leading=KPI_ETIQUETA_LEADING, textColor=MUTED, alignment=TA_LEFT)
    return valor, etiqueta


def _breakdown_table(breakdown, st, excluidos=()):
    rows = [[Paragraph("Component", st["cellh"]),
             Paragraph("Points", st["cellh"]),
             Paragraph("Max", st["cellh"])]]
    for k, v in breakdown.items():
        # Un componente excluido no se ha podido medir: no suma ni resta, y
        # el PDF debe decirlo en vez de mostrar un 0 que parece un suspenso.
        if k in excluidos:
            valor, maximo = "not scored", "—"
        else:
            valor, maximo = str(v), str(MAXES.get(k, ""))
        rows.append([Paragraph(NICE.get(k, k), st["cell"]),
                     Paragraph(valor, st["cell"]),
                     Paragraph(maximo, st["cell"])])
    t = Table(rows, colWidths=[9 * cm, 4 * cm, 4 * cm])
    t.setStyle(_table_style())
    return t


def _table_style(header=True):
    cmds = [
        ("BACKGROUND", (0, 0), (-1, -1), WHITE),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if header:
        cmds.append(("LINEBELOW", (0, 0), (-1, 0), 1, NAVY))
    return TableStyle(cmds)


def esc_tipo(t):
    """'2 revisiones sistemáticas' con el número en negrita."""
    numero, resto = t["texto"].split(" ", 1)
    return f"<b>{numero}</b> {resto}"


def _tabla_simple(titulo_izq, titulo_der, filas, st, anchos=(11 * cm, 6 * cm)):
    """Tabla de dos columnas con cabecera, para listas cortas (tema/nº)."""
    rows = [[Paragraph(titulo_izq, st["cellh"]),
             Paragraph(titulo_der, st["cellh"])]]
    for izq, der in filas:
        rows.append([Paragraph(str(izq), st["cell"]),
                     Paragraph(str(der), st["cell"])])
    t = Table(rows, colWidths=list(anchos))
    t.setStyle(_table_style())
    return t


def _sparkline_anios(por_anio, st):
    """Actividad por año, dibujada con barras de texto.

    Un gráfico de verdad exigiría otra dependencia; con bloques Unicode se lee
    igual de bien en un dossier impreso y no añade peso al proyecto.
    """
    if not por_anio:
        return []
    maximo = max(p["papers"] for p in por_anio) or 1
    filas = []
    for p in por_anio:
        n = p["papers"]
        barra = "█" * int(round(8 * n / maximo)) if n else "·"
        filas.append((str(p["anio"]),
                      f'<font color="#2DDAAC">{barra}</font> {n or ""}'))
    # Dos columnas de años, para que 10 años no ocupen media página.
    mitad = (len(filas) + 1) // 2
    izq, der = filas[:mitad], filas[mitad:]
    der += [("", "")] * (len(izq) - len(der))
    rows = [[Paragraph(a, st["cell"]), Paragraph(b, st["cell"]),
             Paragraph(c, st["cell"]), Paragraph(d, st["cell"])]
            for (a, b), (c, d) in zip(izq, der)]
    t = Table(rows, colWidths=[1.6 * cm, 6.9 * cm, 1.6 * cm, 6.9 * cm])
    t.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    return [t]


def _bullets(items, st, symbol="•", color="#2DDAAC"):
    out = []
    for it in items:
        out.append(Paragraph(
            f'<font color="{color}"><b>{symbol}</b></font>&nbsp;&nbsp;{it}',
            st["body"]))
        out.append(Spacer(1, 3))
    return out


# Niveles de recorte de la pagina 4, de menos a mas agresivo. Cada tupla es
# (nº lineas, nº coautores, nº anios de actividad, nº ensayos).
NIVELES_P4 = [
    (6, 6, 20, 6),
    (5, 5, 14, 5),
    (5, 4, 10, 4),
    (4, 4, 8, 4),
    (4, 3, 6, 3),
    (3, 3, 0, 3),     # 0 = se omite el bloque de actividad
    (3, 0, 0, 2),     # y despues los coautores
]


def _alto_total(flowables, ancho, alto):
    """Altura que ocuparian estos flowables en un marco de ancho x alto.

    reportlab expone `wrap(ancho, alto)`: cada elemento devuelve el espacio que
    necesita. Sumandolos sabemos si la pagina cabe ANTES de generar el PDF, en
    vez de descubrirlo contando paginas despues.

    Ojo: `wrap` devuelve solo la altura DIBUJADA. El aire que los estilos ponen
    alrededor no entra ahi, y hay que pedirlo con getSpaceBefore()/After() —
    NO leyendo `f.spaceBefore`, que en un Paragraph siempre vale 0 porque el
    espaciado vive en su estilo, no en el objeto. Ese despiste dejaba la cuenta
    2,7 cm corta (unos 4 titulos) y la pagina desbordaba igual.
    """
    total = 0
    for f in flowables:
        try:
            total += f.wrap(ancho, alto)[1]
            total += f.getSpaceBefore() + f.getSpaceAfter()
        except (AttributeError, TypeError, ValueError) as e:
            # Un flowable que no sabe medirse no bloquea nada, pero se anota:
            # si esto pasa mucho, el ajuste a 5 paginas esta midiendo de menos.
            logger.debug("flowable no medible (%s): %s", type(f).__name__, e)
            continue
    return total


def _pagina4_ajustada(kol, sci, st):
    """Devuelve la pagina 4 con el mayor detalle que quepa en una hoja."""
    ancho = A4[0] - 4 * cm                     # margenes izq. + der.
    alto = A4[1] - 2.2 * cm - 1.8 * cm         # margenes sup. + inf.
    # Un centimetro de colchon: la medida es muy buena pero no exacta al punto
    # (saltos de linea dentro de una celda, redondeos), y quedarse corto cuesta
    # una pagina entera de mas.
    disponible = alto - 1 * cm
    for nivel in NIVELES_P4:
        bloques = _pagina4(kol, sci, st, *nivel)
        if _alto_total(bloques, ancho, alto) <= disponible:
            return bloques
    return bloques          # el ultimo nivel es el minimo posible


def _pagina4(kol, sci, st, n_lineas, n_colabs, n_anios, n_ensayos):
    """Contenido de la pagina 4 con los topes indicados."""
    story = [Paragraph("Scientific profile", st["h1"]), Spacer(1, 6)]

    lineas = sci.get("lineas_investigacion") or []
    if lineas and n_lineas:
        recurrentes = [l for l in lineas if l.get("recurrente")]
        if recurrentes:
            story.append(Paragraph("Research lines", st["h2"]))
            story.append(Paragraph(
                "Topics they <b>return to</b> across their work: a line of "
                "research, not a one-off paper.", st["muted"]))
        else:
            story.append(Paragraph("Topics covered", st["h2"]))
            story.append(Paragraph(
                "No descriptor repeats across their publications: a "
                "thematically scattered body of work. Most recent topics listed.",
                st["muted"]))
        story.append(Spacer(1, 4))
        story.append(_tabla_simple(
            "Topic (MeSH descriptor)", "Papers · latest",
            [(l["tema"], f"{l['papers']} · {l['ultimo_anio'] or '—'}")
             for l in lineas[:n_lineas]], st, anchos=(12 * cm, 5 * cm)))
        story.append(Spacer(1, 12))

    tipos = sci.get("tipos_publicacion") or []
    if tipos:
        story.append(Paragraph("Type of evidence produced", st["h2"]))
        story.append(Paragraph(
            " · ".join(esc_tipo(t) for t in tipos[:6]), st["body"]))
        story.append(Spacer(1, 12))

    colabs = sci.get("colaboradores") or []
    if colabs and n_colabs:
        story.append(Paragraph("Frequent co-authors", st["h2"]))
        story.append(_tabla_simple(
            "Co-author", "Joint papers",
            [(c["nombre"], c["papers"]) for c in colabs[:n_colabs]], st,
            anchos=(12 * cm, 5 * cm)))
        story.append(Spacer(1, 12))

    tray = sci.get("trayectoria") or {}
    if tray.get("por_anio") and n_anios:
        anios = tray["por_anio"][-n_anios:]
        titulo = "Activity by year"
        if len(anios) < len(tray["por_anio"]):
            titulo += f" (last {len(anios)})"
        story.append(Paragraph(titulo, st["h2"]))
        story.extend(_sparkline_anios(anios, st))
        story.append(Spacer(1, 8))

    m = kol["metrics_unverified"]
    mv = kol.get("metrics_verified")
    if mv:
        # h-index calculado sobre el set ya filtrado de homonimos: atribuible.
        nota_metricas = (
            f" · <b>h-index {mv['hindex']}</b> and <b>"
            f"{mv['citations']:,}" + "</b> citations, computed "
            f"over the {mv['papers_evaluados']} papers already filtered for "
            "homonyms (not over a search by name).")
    else:
        nota_metricas = (
            f" · h-index and citations (Europe PMC): <font color='#C47A5C'><b>"
            f"{m['hindex_europepmc']}</b></font>, not disambiguated — the "
            "reliable figures are on the previous page.")

    story.append(Paragraph("Clinical trials and metrics", st["h2"]))
    if not kol["trials"]:
        story.append(Paragraph(
            "<b>0 verified trials</b> against the KOL's location. A valid "
            "result: no ClinicalTrials.gov study under this surname was "
            "confirmed in their city or institution, so no work by possible "
            "homonyms is attributed to them." + nota_metricas,
            st["muted"]))
    else:
        rows = [[Paragraph("NCT", st["cellh"]), Paragraph("Title", st["cellh"]),
                 Paragraph("Phase", st["cellh"]), Paragraph("Role", st["cellh"])]]
        for tr in kol["trials"]["items"][:n_ensayos]:
            rows.append([Paragraph(tr["nct"], st["cell"]),
                         Paragraph(tr["title"][:70], st["cell"]),
                         Paragraph(tr["phase"], st["cell"]),
                         Paragraph(tr["role"], st["cell"])])
        t = Table(rows, colWidths=[3 * cm, 8 * cm, 3 * cm, 3 * cm], repeatRows=1)
        t.setStyle(_table_style())
        story.append(t)
        restantes = len(kol["trials"]["items"]) - n_ensayos
        cola = (f"… and {restantes} more trial(s) (see dashboard). "
                if restantes > 0 else "")
        story.append(Spacer(1, 5))
        story.append(Paragraph(cola + nota_metricas.lstrip(" ·"), st["muted"]))
    return story


def _story(kol, st):
    story = []
    ident = kol["identity"]
    pub = kol["publications"]
    sc = kol["score"]
    nTrials = kol["trials"]["verified_count"] if kol["trials"] else 0

    # La portada la pinta _cover; empezamos rompiendo a la pagina 2.
    story.append(PageBreak())

    # ---- Pagina 2: Resumen ejecutivo ----
    story.append(Paragraph("Executive summary", st["h1"]))
    story.append(Spacer(1, 6))

    # "Quien es": la frase viene del perfil (fuente de verdad unica), no se
    # redacta aqui, para que dashboard y PDF digan exactamente lo mismo.
    sci = kol.get("perfil_cientifico") or {}
    if sci.get("resumen"):
        story.append(Paragraph("Who they are", st["h2"]))
        story.append(Paragraph(sci["resumen"], st["body"]))
        esp = sci.get("especialidad") or {}
        if esp.get("origen") == "inferred":
            story.append(Spacer(1, 3))
            story.append(Paragraph(
                f"Field <b>inferred</b> (confidence: {esp.get('confianza', '—')}). "
                + esp.get("detalle", ""), st["muted"]))
        story.append(Spacer(1, 12))

    story.append(_kpi_table([
        (pub["verified_count"], "Verified pubs."),
        (pub["recent_5y"], "Recent (5 yrs)"),
        (len(pub["journals"]), "Journals"),
        (nTrials, "Verified trials"),
        (pub["excluded_count"], "Homonyms excl."),
    ]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("KOL Score breakdown", st["h2"]))
    story.append(_breakdown_table(sc["breakdown"], st,
                                  excluidos=sc.get("excluded", {})))
    story.append(Spacer(1, 6))
    story.append(Paragraph(f"<b>Total: {sc['total']}/100 — {sc['tier']}</b>",
                           st["body"]))
    story.append(Spacer(1, 16))
    story.append(Paragraph("Disambiguation", st["h2"]))
    story.append(Paragraph(
        f"Confidence: <b>{kol['disambiguation']['confidence'].upper()}</b>",
        st["body"]))
    story.append(Paragraph(kol["disambiguation"]["notes"], st["muted"]))

    # ---- Pagina 3: Publicaciones ----
    story.append(PageBreak())
    story.append(Paragraph("Publications", st["h1"]))
    story.append(Spacer(1, 8))
    rows = [[Paragraph("Year", st["cellh"]), Paragraph("Title", st["cellh"]),
             Paragraph("Journal", st["cellh"]), Paragraph("Authorship", st["cellh"])]]
    for it in pub["items"][:12]:
        titulo = it["title"][:95] + ("…" if len(it["title"]) > 95 else "")
        rows.append([Paragraph(str(it["year"]), st["cell"]),
                     Paragraph(titulo, st["cell"]),
                     Paragraph(it["journal"][:28], st["cell"]),
                     Paragraph(it["author_position"], st["cell"])])
    t = Table(rows, colWidths=[1.3 * cm, 9.7 * cm, 4 * cm, 2 * cm], repeatRows=1)
    t.setStyle(_table_style())
    story.append(t)
    if len(pub["items"]) > 12:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"… and {len(pub['items']) - 12} more publication(s) "
            "(see dashboard).", st["muted"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Journals", st["h2"]))
    story.append(Paragraph(" · ".join(pub["journals"][:22]) or "—", st["muted"]))

    # ---- Pagina 4: Perfil cientifico ----
    # Antes esta pagina solo tenia "0 ensayos" y dos "NO VERIFICADO": media
    # hoja en blanco. Ahora lleva lo que de verdad describe al KOL.
    #
    # Cuanto contenido cabe depende del KOL: uno con 5 lineas de investigacion
    # de nombre largo, 14 ensayos y 20 anios de actividad no cabe donde cabe
    # otro con 13 papers. Poner topes fijos "a ojo" no funcionaba (Tabernero y
    # San Miguel se iban a 6 paginas y verify.py tumbaba la entrega), asi que
    # _pagina4 se construye con varios niveles de recorte y aqui se MIDE cual
    # es el primero que cabe de verdad.
    story.append(PageBreak())
    story.extend(_pagina4_ajustada(kol, sci, st))

    # ---- Pagina 5: Briefing ----
    story.append(PageBreak())
    story.append(Paragraph("Pre-visit briefing", st["h1"]))
    story.append(Spacer(1, 8))
    b = kol["briefing"]
    story.append(Paragraph("Talking points", st["h2"]))
    story.extend(_bullets(b["talking_points"], st))
    story.append(Spacer(1, 8))
    story.append(Paragraph("Do", st["h2"]))
    story.extend(_bullets(b["do"], st, symbol="✓", color="#0a7a5c"))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Avoid", st["h2"]))
    story.extend(_bullets(b["dont"], st, symbol="✕", color="#a24e2b"))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Checklist", st["h2"]))
    story.extend(_bullets(b["checklist"], st))
    return story


# ----------------------------------------------------------------------
#  Punto de entrada
# ----------------------------------------------------------------------

def render_pdf(profile, output_dir):
    """Genera KOL_Dossier_{Nombre}.pdf y devuelve su ruta."""
    os.makedirs(output_dir, exist_ok=True)
    slug = _slug(profile["identity"]["full_name"])
    ruta = os.path.join(output_dir, f"KOL_Dossier_{slug}.pdf")
    # Se construye en un temporal y se renombra al final: si el build falla a
    # medias, nadie se queda con un PDF truncado en output/ creyendo que vale.
    fd, tmp = tempfile.mkstemp(dir=output_dir, suffix=".pdf.tmp")
    os.close(fd)

    doc = BaseDocTemplate(tmp, pagesize=A4,
                          leftMargin=2 * cm, rightMargin=2 * cm,
                          topMargin=2.2 * cm, bottomMargin=1.8 * cm,
                          title=f"KOL Dossier — {profile['identity']['full_name']}")
    doc.kol = profile  # accesible desde los callbacks de pagina

    frame = Frame(doc.leftMargin, doc.bottomMargin,
                  doc.width, doc.height, id="body")
    # Pagina 1 usa _cover; el resto _header_footer.
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[frame], onPage=_cover),
        PageTemplate(id="content", frames=[frame], onPage=_header_footer),
    ])

    st = _styles()
    story = _story(profile, st)
    # Forzar que a partir de la pagina 2 se use la plantilla 'content'.
    story.insert(0, _SwitchTo("content"))
    try:
        doc.build(story)
        os.replace(tmp, ruta)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info("PDF dossier generated: %s", ruta)
    return ruta


# Flowable invisible que cambia de plantilla de pagina en el siguiente salto.
from reportlab.platypus import NextPageTemplate as _NPT


def _SwitchTo(template_id):
    return _NPT(template_id)
