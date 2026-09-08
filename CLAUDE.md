# CLAUDE.md — KOL Intelligence System (engine)

> Claude Code reads this file **when it opens the project**. It summarises what
> this is, the rules the code MUST honour, and how to run it.
>
> Note on language: this document and the README are in English; the code,
> comments and user-facing strings are in Spanish, and the deliverables are
> written in Spanish on purpose (the users are MSLs working with Spanish
> hospitals). Do not "fix" that inconsistency without being asked.

## What it is (30-second summary)

A **KOL** (Key Opinion Leader) is a leading physician or researcher in a
therapeutic area. An **MSL** (Medical Science Liaison, working for a pharma
company) prepares meetings with those KOLs and needs a **pre-visit dossier**.

From **just a doctor's name**, this app builds a 360° KOL profile and two
deliverables derived from a single source of truth (`kol_profile.json`):

1. An interactive **HTML dashboard** (6 tabs).
2. A printable **PDF dossier** (5 pages).

Neither the city nor the specialty is ever asked for: the **city** is derived
from the institution (`centros.py`) and the **specialty** is inferred from the
MeSH descriptors and the department recorded in the doctor's own publications
(`perfil_cientifico.py`).

It queries real public sources: **PubMed** (publications),
**ClinicalTrials.gov** (trials), **Europe PMC** (metrics). It computes a
**KOL Score /100** → Tier 1/2/3.

The central challenge of the domain is **homonyms** (real case: "San Miguel").
Honesty comes first: **"0 verified trials" is a valid result**, not a failure.

## Web flow: two screens, not one

Screen 1 asks for **the name only**, with no example placeholder.
`kol_engine/candidatos.py` searches PubMed with no affiliation filter, groups
the author's affiliations by centre, and screen 2 shows those centres (papers,
city, year range) so the user can pick the right one. Requiring the institution
up front was wrong: it is precisely what the user often does not know.

The name may be typed without accents and in lower case — the query already
ignored them — and the name displayed and used in the dossier is PubMed's
**canonical** form (`candidatos.nombre_de_autor`). Each card warns when someone
else at that centre signs with the same surname and initial. Real case:
`Martinez Lopez E` returns Erika (Guadalajara), Emma (Murcia) and Elías (Peset).

The CLI (`kol.py`) still takes both name and institution.

## Hard rules (the code guarantees these; they are NOT optional)

- **Homonyms**: post-search filtering as a tested function, logging how many
  papers were excluded and why.
- **Trials verified by location**: every NCT is checked against the KOL's city
  and institution. If none verifies → `trials = None` → the "0 verified trials"
  block.
- **The city does not verify, it only widens**: location terms are split into
  *strong* ones (from the centre's name: `cnio`, `peset`) and *weak* ones (the
  city). A paper matching only on the city stays **unverified**, not confirmed —
  sharing Madrid identifies nobody. When the institution is unknown, the city
  does verify, with low confidence.
- **The author query goes WITHOUT quotes**: PubMed indexes the initials of
  *every* given name (`Sepulveda-Sanchez JM`). Quoted, it demands an exact match
  and lost whole KOLs; unquoted, PubMed only truncates.
- **In the PDF, font size belongs to the STYLE, never to a `<font size>` inside
  the text**: leading is computed from the style and is what reserves the row
  height. A `<font size=18>` over a 10pt style draws 18pt digits on a 12pt line
  and the number escapes its cell (this happened with three-digit KPIs: 222
  publications for Martí-Bonmatí, with the table rule crossing the digits).
  Guarded by
  `test_pdf_cabe.py::test_ningun_estilo_tiene_el_interlineado_mas_corto_que_su_letra`.
- **The PDF always fits in 5 pages**: page 4 is measured and adjusted
  (`_pagina4_ajustada`) instead of trusting fixed caps.
- **Europe PMC exposes two different metrics — never conflate them**:
  - The **name-level aggregate** (`get_metrics`) is ALWAYS `NO VERIFICADO`: it
    mixes homonyms in.
  - The **h-index of the disambiguated set** (`get_verified_metrics`) IS
    published: it fetches per-paper citations for the PMIDs the filter already
    attributed to this KOL and computes the h-index here. Bounded to the
    filtered set, it is attributable.
- **Never report as checked what was never looked at**: if ClinicalTrials.gov
  fails, `trials_result["error"]` records it, the note says `NO COMPROBADO`, and
  the component drops out of the score's denominator. A network failure is not
  the KOL's fault.
- **The score is normalised over what is measurable**: CRM does not score while
  there is no integration, so it does not count in the denominator either (if it
  did, the real ceiling would be 90 behind a badge that reads `/100`).
- **Coverage, never truncate in silence**: `analyze()` returns `coverage` with
  the real PubMed total. If the set is truncated, say so: the biography, the
  starting year and the yearly average describe only that subset.
- **Cache with a TTL** (`KOL_CACHE_TTL_DAYS`, 7 days): with no expiry the
  dossier projected a freshness it did not have. `cache_utils.prune()` clears it
  at the start of every pipeline.
- **Every write is ATOMIC** (temp file + `os.replace`): cache, JSON, dashboard
  and PDF. Flask is multi-threaded; writing in place, a reader saw half-written
  files and accepted them (measured: 22 reads out of 100).
- **An empty cache file is a failure, not an answer.** `read()` returns `None`
  for empty content: `""` passed the `is None` check and blew up in
  `json.loads()` on every run until it expired.
- **`_parse_articles` RAISES `RespuestaInvalida`** when the XML cannot be read,
  instead of returning `[]`. A truncated XML made the KOL look like they had no
  published work. `fetch_papers` drops the cache entry and retries fresh once
  before propagating.
- **`_peticion` retries network errors too** (ConnectionError/Timeout), not just
  429, and spaces requests at 3/s (`_esperar_turno`).
- **Logging instead of silence**: the engine uses `logging`. The web app
  configures it with `KOL_LOG_LEVEL`; the CLI with `-v`.
- **`kol.py` does NOT use `runner.run_pipeline`** (it duplicates the pipeline so
  it can narrate each step). Any behavioural change in the runner must be
  mirrored there — it bit us once already: the CLI still reported a "VALID
  result" while ClinicalTrials was down.
- **`verify.py`'s blocklist ignores real co-authors**: a listed name that signs
  alongside the current KOL is not template contamination.
- **Accents**: PubMed queries go WITHOUT accents; outputs WITH accents.
  Guarded by `tests/test_tildes.py`, which walks the JSON, the PDF and the
  dashboard looking for misspelled Spanish words.
- **Nothing invented**: with no evidence for a city, a specialty or a research
  line, return `None` and let the deliverable say so. A derived value is always
  labelled as such ("inferida", "deducida del centro").
- **Agreement**: counts are written with matching number ("2 revisiones
  sistemáticas", not "2 revisión sistemática").
- **Single source of truth**: the dashboard and the PDF both derive from
  `kol_profile.json`, never separately.
- **Final verification (step 9)**: an automated test, not a checklist.
- **Every screen carries the footer** "creado por Miriam Martínez Santos, PhD"
  (constant `AUTORA` in `app.py`). The dashboard and the PDF do NOT carry it yet.

## How to run it

```bash
pip install -r requirements.txt

# Basic use: name and where they work
python kol.py "Dra. Teresa San-Miguel" "Hospital Universitari i Politècnic La Fe"

# Web interface (name first, then pick the centre)
python3 app.py     # http://127.0.0.1:5001

# Flags: --solo-json  --solo-dashboard  --solo-pdf  --no-cache
# --ciudad / --especialidad only to FORCE a value; they are derived by default.
# --orcid is the only input that raises confidence to "high".
```

Output lands in `output/`: `kol_profile_{Name}.json`,
`KOL_Dashboard_{Name}.html`, `KOL_Dossier_{Name}.pdf`, plus a console summary.

## Build status

- [x] **Phase 0** — Scaffold (structure, requirements, CLAUDE/README, stubs).
- [x] **Phase 1** — Critical core: `disambiguator.py`, `pubmed_agent.py`,
      `test_homonym_filter.py` (the San Miguel case). ← the heart of the system.
- [x] **Phase 2** — `clinicaltrials_agent.py` (verification by location, the
      "0 trials" case), `europepmc_agent.py` (UNVERIFIED metrics),
      `scoring.py` (/100 + Tier), `profile.py` → `kol_profile.json`. Location
      matching on whole WORDS (`text_utils.contains_term`) so 'fe' is not
      confused with 'Tenerife'.
- [x] **Phase 3** — Rendering from the JSON: `dashboard.py` +
      `templates/dashboard_template.html` (self-contained, embedded KOL_DATA)
      and `pdf.py` (5-page dossier with reportlab). CLI gained
      `--solo-dashboard` / `--solo-pdf` to rebuild from an existing JSON.
- [x] **Phase 4** — `verify.py` (step 9 automated: 5 pages, current name
      present, 0 names from previous KOLs, well-formed PMIDs/NCTs, coherent
      badge) wired into `kol.py` (runs at the end; exit 3 on failure).
- [x] **Phase 5** — `kol-intelligence-system` skill created: `SKILL.md` (at the
      project root and in `~/.claude/skills/`) invokes the CLI and interprets
      the JSON/console output instead of improvising the engine.
- [x] **Phase 6** — *A dossier that actually talks about the doctor.*
      - `centros.py`: derives the city from the centre's name (catalogue of
        Spanish hospitals + written city + mentioned city). When in doubt,
        `None`.
      - `pubmed_agent`: extracts **MeSH** terms, keywords and publication
        types, which used to be discarded while parsing the XML.
      - `perfil_cientifico.py`: infers specialty (the **department** in the
        affiliation outranks the MeSH count), department, research lines,
        co-authors, career span and evidence types. Writes the "who they are"
        paragraph shared by the PDF and the dashboard.
      - `profile._briefing` rewritten: talking points derived from their real
        data, not a fixed template.
      - PDF: cover with department and field; page 2 with "who they are"; page
        4, which used to hold only "0 trials" and half a blank sheet, is now the
        scientific profile. Dashboard: "Scientific profile" and "Who they are"
        tabs.

### Audit (1 Sep 2026) — 5 bugs fixed

The two serious ones, both now covered by the hard rules above:

1. PubMed silently truncated at 200 papers. Tabernero lost 70% of his work and
   his dossier claimed he had "published since 2022" (really: 1993). It now
   pages up to 1,000 and `analysis["coverage"]` reports the real total.
2. A ClinicalTrials.gov outage was published as "0 verified trials (valid
   result)". It is now marked NOT CHECKED and drops out of the score.

Also in that pass: the score was renormalised over measurable components (the
real ceiling had been 90/100 because CRM never scored), the cache gained a
7-day TTL, and `_slug` normalises the case of the name.

## Tests

```bash
python -m pytest tests/ -v
```

**148 tests, none of which touch the network.** The key ones:

- `test_homonym_filter.py` — the filter must not drag in the homonym Jesús F.
  San-Miguel (Pamplona) when the KOL is from Valencia, nor confirm a homonym
  who merely shares a city (the María Blasco / CNIO case).
- `test_pdf_cabe.py` — the dossier fits in 5 pages with 3 papers and with 400.
- `test_tildes.py` — no Spanish word left unaccented in the deliverables.
- `test_disambiguator.py` — the author query goes unquoted (the Sepúlveda
  Sánchez case: 2 papers found versus 48 real ones).
