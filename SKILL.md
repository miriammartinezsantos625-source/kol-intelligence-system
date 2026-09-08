---
name: kol-intelligence-system
description: Genera inteligencia 360° sobre un Key Opinion Leader (KOL) médico a partir de solo su nombre e institución, para que un Medical Science Liaison (MSL) prepare una visita científica. Ejecuta una aplicación Python real (determinista y auditable) que consulta PubMed, ClinicalTrials.gov y Europe PMC, desambigua homónimos, deduce la ciudad del centro y la especialidad de los propios papers del médico, calcula un KOL Score /100 con su Tier, y produce dos entregables desde una única fuente de verdad (kol_profile.json): un dashboard HTML de 6 pestañas y un dossier PDF de 5 páginas. Usar cuando Miriam diga 'prepara un dossier de KOL', 'perfil de <médico>', 'inteligencia KOL', 'briefing pre-visita', 'analiza al Dr./Dra. <nombre>', 'KOL de <institución>', o cualquier petición de perfilar a un médico/investigador de referencia para una farmacéutica.
---

# KOL Intelligence System — orquestador

## ¿Qué hace esta skill?

Un **KOL** (Key Opinion Leader) es un médico o investigador de referencia en un
área terapéutica. Un **MSL** (Medical Science Liaison de una farmacéutica)
prepara reuniones con esos KOLs y necesita un **dossier pre-visita**: quién es,
qué ha publicado, en qué ensayos participa, su perfil de influencia, y puntos de
conversación y precauciones.

Esta skill **NO improvisa el análisis**: invoca una aplicación Python real y
testeada (`02_Motor_KOL/kol.py`) que hace todo el trabajo de forma determinista,
y luego **interpreta y presenta** sus resultados. El motor ya garantiza en
código las reglas difíciles (desambiguación de homónimos, verificación de
ensayos por localización, métricas honestas); la skill solo las respeta al leer
la salida.

> El reto central del dominio son los **homónimos** (caso real: "San Miguel").
> La honestidad prima: **"0 verified trials" es un resultado válido**, no un
> fallo.

---

## PASO 1 — Recoger los datos del KOL

Solo hacen falta **dos**: el nombre del médico y **dónde trabaja**. No pidas
más: la ciudad se deduce del centro y la especialidad se infiere de sus propias
publicaciones.

| Dato | Obligatorio | Flag CLI |
|---|---|---|
| Nombre | ✅ | (posicional) |
| Dónde trabaja (hospital/centro) | ✅ | (posicional) |
| ORCID | opcional — lo **único** que sube la confianza a «alta» | `--orcid` |
| Ciudad | solo para forzarla | `--city` |
| Especialidad | solo para forzarla | `--specialty` |
| Apellido(s) | solo si el nombre de pila es compuesto | `--surname` |

Si Miriam solo da el nombre, sin centro, avísale de que la confianza será
**baja** y habrá riesgo de homónimos. Si el nombre de pila es compuesto
(«María Teresa García»), pásale el apellido con `--surname`.

---

## PASO 2 — Ejecutar el motor (CLI)

Ruta del motor (en el repo publicado, el motor está en la RAÍZ; en el
checkout local cuelga de `02_Motor_KOL/`):
`~/Documents/Claude/Projects/INDUSTRIA FARMACEUTICA/kol-intelligence-system/02_Motor_KOL`

Ejecuta (ajustando los datos):

```bash
cd ~/"Documents/Claude/Projects/INDUSTRIA FARMACEUTICA/kol-intelligence-system/02_Motor_KOL"
python3 kol.py "Dra. Teresa San-Miguel" "Hospital Universitari i Politècnic La Fe"
```

Flags útiles:
- `--orcid` — el único dato que sube la confianza a «alta».
- `--json-only` — genera solo `kol_profile.json` (para revisar antes de renderizar).
- `--dashboard-only` / `--pdf-only` — regenera un entregable desde un JSON existente.
- `--no-cache` — fuerza llamadas frescas a las APIs.

Miriam suele usar la **interfaz web** (`python3 app.py` → http://127.0.0.1:5001),
que pide esos mismos dos campos. Por debajo llama al mismo motor.

**Interpreta el código de salida:**
- `0` → todo OK, verificación final pasada.
- `2` → error de red consultando PubMed (reintentar o avisar).
- `3` → la **verificación final falló** (revisar el informe del "Paso 9" en la
  consola antes de entregar nada).

---

## PASO 3 — Leer los resultados

El motor imprime en consola: confianza de desambiguación, nº de papers
antes/después de filtrar, ensayos verificados, KOL Score/Tier, y el informe de
verificación. La fuente de verdad completa está en:

`02_Motor_KOL/output/kol_profile_{Nombre}.json`

Si necesitas datos concretos (publicaciones, ensayos, briefing), **lee ese
JSON**; no reconstruyas las cifras a mano. Entregables generados:

- `output/KOL_Dashboard_{Nombre}.html` — dashboard interactivo de 6 pestañas
  (Summary, Scientific profile, Publications, Trials, Pre-visit briefing,
  Competitive intelligence).
- `output/KOL_Dossier_{Nombre}.pdf` — dossier imprimible de 5 páginas.

> Para VER el dashboard en el navegador en macOS: la extensión de Chrome no abre
> `file://`. Sírvelo con `python3 -m http.server` desde `output/` (evita el
> puerto 8765) y abre `http://127.0.0.1:<puerto>/KOL_Dashboard_{Nombre}.html`.

---

## PASO 4 — Presentar a Miriam

Resume en el chat, con honestidad:

1. **Confianza** de la desambiguación (`high` / `medium` / `low`) y por qué.
2. **Publicaciones**: verificadas / sin verificar / excluidas (homónimos).
   «Sin verificar» incluye los papers que solo coinciden con la **ciudad** y no
   con la institución: son probables, no confirmados. No los presentes como
   verificados.
3. **Ensayos**: nº verificados — y si son 0, dilo como resultado válido, no como
   fallo ("no se atribuye trabajo de posibles homónimos"). Distínguelo de
   `NOT CHECKED`, que es que ClinicalTrials.gov no respondió.
4. **Quién es**: el párrafo de `perfil_cientifico.resumen` (servicio, área,
   trayectoria, si lidera o solo participa, sus temas). Es lo que más le
   interesa a un MSL antes de entrar a la visita.
5. **Qué se ha deducido y qué se ha declarado**: si la ciudad se dedujo del
   centro o la especialidad se infirió de los papers, **dilo**, con su nivel de
   confianza. Nunca presentes un dato inferido como declarado.
6. **KOL Score /100 y Tier**, con una frase del desglose.
7. **Métricas de Europe PMC**: recuérdalas como **NOT VERIFIED**.
8. **Rutas** de los dos entregables.
9. Si `verify.py` marcó algún ✗, **no presentes el resultado como definitivo**:
   explica qué comprobación falló.

---

## Reglas duras (las garantiza el motor; respétalas al interpretar)

- **Homónimos**: el filtrado ya está hecho y logueado; no re-incluyas papers
  excluidos.
- **Ensayos**: si el JSON trae `trials: null`, es "0 verified trials"
  (válido).
- **Europe PMC**: h-index y citas son **NOT VERIFIED** — nunca los presentes
  como cifras fiables.
- **Una sola fuente de verdad**: dashboard y PDF salen del mismo
  `kol_profile.json`. No inventes ni edites cifras en los entregables.
- **Nada inventado**: si el motor no pudo deducir la ciudad, la especialidad o
  una línea de investigación, devuelve `None` y el entregable lo dice. No
  rellenes tú ese hueco.
- **Líneas de investigación**: solo se llaman así si el tema se REPITE. Si el
  JSON las marca `recurrente: false`, son temas sueltos de una obra dispersa —
  preséntalos como tales.
- **Idioma**: los entregables se redactan en INGLÉS. Lo único que sigue en
  castellano es el dato de origen citado tal cual (nombres de hospital y
  servicio, ciudades, títulos de papers españoles), y eso SÍ lleva tildes:
  si ves una palabra castellana sin tilde en un entregable, es un bug. Las
  queries a PubMed, en cambio, van siempre sin tildes.

---

## Si algo falla

- Sin resultados / confianza baja → pide a Miriam más datos (ciudad, ORCID).
- Error de red (exit 2) → reintenta; si persiste, avisa.
- Verificación fallida (exit 3) → muestra el informe del Paso 9 y no entregues.
- Para depurar el motor: `cd 02_Motor_KOL && python3 -m pytest tests/ -v`
  (148 tests, ninguno toca la red).
