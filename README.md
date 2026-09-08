# KOL Intelligence System

Type **a doctor's name**. Nothing else. You get a 360° profile of that *Key
Opinion Leader* (KOL) and two deliverables ready for a *Medical Science
Liaison* (MSL) visit:

- 📊 an interactive **HTML dashboard** (6 tabs)
- 📄 a printable **PDF dossier** (5 pages)

You are never asked for anything the system can work out on its own. The
**city** is derived from the institution, and the **specialty**, the
**department**, the **research lines** and the **co-authors** are read from the
doctor's own publications. Everything inferred is labelled as such.

The data comes from real public sources — **PubMed**, **ClinicalTrials.gov**
and **Europe PMC** — and is condensed into a **KOL Score /100** with its Tier.

## Why it is hard

Two doctors can share a surname and an initial. The central problem of the
domain is **homonym disambiguation**, and it is where most of this codebase
goes: the search is filtered against the KOL's affiliation and city, every
excluded paper is logged with its reason, and a paper that matches only on the
city is marked **unverified** rather than confirmed — sharing a city does not
identify anyone.

The second principle is honesty. **"0 verified trials" is a valid result**, not
a failure — and it is kept strictly apart from "NOT CHECKED", which is what you
get when ClinicalTrials.gov itself is down.

## Installation

```bash
pip install -r requirements.txt
```

Requirements: Python 3.10+ and an internet connection. The APIs are public and
need no key (PubMed E-utilities accepts an optional `api_key` for a higher rate
limit).

## Usage — web interface (the easy way)

```bash
python3 app.py
# open http://127.0.0.1:5001
```

Two steps, because the institution is often the very thing you do not know:

1. **You type only the name.** Accents and capitals are optional.
2. **You pick the institution** from the centres where that author actually
   publishes — each one shown with its paper count, city and year range. If
   someone else at that centre signs with the same surname and initial, the
   card warns you.

Then it generates the dashboard and links the PDF. Underneath it runs the same
engine as the CLI (`kol_engine/runner.py`).

## Usage — command line

```bash
# Basic: name and where they work
python kol.py "Dra. Teresa San-Miguel" "Hospital La Fe"

# With ORCID (the only input that raises confidence to "high")
python kol.py "Dra. Teresa San-Miguel" "Hospital La Fe" \
    --orcid 0000-0001-2345-6789
```

### Flags

| Flag               | What it does                                              |
|--------------------|-----------------------------------------------------------|
| `--orcid`          | Unique author identifier: confidence becomes **high**     |
| `--city`           | Forces the city (derived from the institution by default) |
| `--specialty`      | Forces the field (inferred from their papers by default)  |
| `--surname`        | Explicit surname, for compound given names                |
| `--json-only`      | Generates only `kol_profile.json` (to review first)       |
| `--dashboard-only` | Rebuilds the HTML from an existing JSON                   |
| `--pdf-only`       | Rebuilds the PDF from an existing JSON                    |
| `--no-cache`       | Forces fresh API calls                                    |

## Language

Everything the tool produces — the web interface, the dashboard, the PDF
dossier and the CLI — is in English. The source data it quotes is not
translated and never will be: Spanish hospital and department names, city
names and the titles of Spanish-language papers appear exactly as their
sources record them. Inside the code, comments and identifiers are in
Spanish; that is deliberate and documented in `CLAUDE.md`.

## Layout

```
.
├── app.py            # web interface (Flask)
├── kol.py            # entry point (CLI)
├── kol_engine/       # the engine (one responsibility per module)
├── templates/        # dashboard template
├── cache/            # raw API responses (auditable, 7-day TTL)
├── output/           # generated deliverables
└── tests/            # 148 tests, incl. the real "San Miguel" case
```

The dashboard and the PDF both derive from a single source of truth,
`kol_profile.json` — never built independently of each other.

## Tests

```bash
python3 -m pytest -q
```

**148 tests, none of which touch the network.** The key ones:

- `test_homonym_filter.py` — the filter must not drag in the homonym Jesús F.
  San-Miguel (Pamplona) when the KOL is from Valencia, nor confirm a homonym
  who merely shares a city (the María Blasco / CNIO case).
- `test_pdf_cabe.py` — the dossier fits in 5 pages with 3 papers and with 400.
- `test_disambiguator.py` — the author query must go **unquoted** (the Sepúlveda
  Sánchez case: 2 papers found versus 48 real ones).
- `test_tildes.py` — no Spanish word left unaccented in the deliverables.

## Known limits (honesty by design)

- **Homonyms**: common surnames contaminate searches. The system filters by
  affiliation/city and **logs what it excluded**. False positives and negatives
  are still possible.
- **Trials**: if none verifies against the KOL's location, the report says
  **"0 verified trials"** — a correct result, not an error. If instead
  ClinicalTrials.gov does not answer, it says **"NOT CHECKED"**. These are
  different things and the dossier never conflates them.
- **h-index**: the published figure is computed over the **already
  disambiguated set** — per-paper citation counts from Europe PMC over the
  PMIDs attributed to this KOL. That is stricter than Scopus or Web of Science,
  which do not filter homonyms. Europe PMC's own name-level aggregate is still
  shown, marked **UNVERIFIED**, for contrast.
- **Coverage**: if a KOL has more publications than the cap (`--retmax`, 1000
  by default), the dashboard warns that the starting year, the yearly average
  and the totals describe only the analysed subset. It never truncates in
  silence.
- **KOL Score**: normalised over the components that could actually be
  measured. With no CRM integration that component neither scores nor
  penalises, so 100 stays genuinely reachable.
- **Inferred specialty**: derived from the department in their affiliation and
  from MeSH descriptors. It is labelled *inferred* with a confidence level;
  override it with `--especialidad`.
- **Derived city**: comes from a catalogue of Spanish hospitals. If the centre
  is not listed and no city is mentioned, nothing is derived — better that than
  placing the KOL in the wrong city and poisoning the homonym filter.
- **Compound given names**: "María Teresa García" can be split in the wrong
  place when guessing where the given name ends. Fix it with `--apellidos`.
- **CRM and congresses**: no real integration yet; they return honest
  placeholders (interactions = 0, "first contact").

## Status

**Complete (phases 0–6).** It builds the deliverables from a name, disambiguates
homonyms, derives city and specialty, describes the doctor's scientific profile
and verifies its own output automatically. See `CLAUDE.md` for the phase-by-phase
detail and for the hard rules the code must honour.

---

Created by **Miriam Martínez Santos, PhD**.
