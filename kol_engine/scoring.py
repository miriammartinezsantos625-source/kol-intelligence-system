"""
scoring — KOL Score /100 y asignacion de Tier.

Rubric transparente (pesos que suman 100). Cada componente es explicable ante
un MSL; nada es una caja negra.

    publicaciones          40   volumen y autoria (primer/ultimo autor pesan)
    ensayos                20   ensayos clinicos verificados por localizacion
    influencia             15   actividad reciente y diversidad de revistas
    relevancia_terapeutica 15   encaje con el area de interes
    crm                    10   historial de interacciones (hoy placeholder)

Tier:  >=70 -> Tier 1   |   40-69 -> Tier 2   |   <40 -> Tier 3

El score se normaliza sobre los componentes que REALMENTE se han podido medir.
Sin integracion CRM, ese componente no se puede puntuar: si contara igualmente
en el denominador, el maximo alcanzable seria 90 y todo KOL perderia 10 puntos
invisibles sobre un marcador que dice "/100". Lo mismo si ClinicalTrials.gov no
responde: no se puede penalizar 20 puntos por algo que no se ha mirado.

`breakdown` sigue dando los puntos brutos de cada componente sobre su peso
original (explicable ante un MSL); `excluded` dice cuales no entran y por que.
"""

PESOS = {
    "publications": 40,
    "trials": 20,
    "influence": 15,
    "therapeutic_relevance": 15,
    "crm": 10,
}


def _clamp(valor, maximo):
    return int(round(min(valor, maximo)))


def compute_score(pub_stats, trials, specialty=None, crm_interactions=0,
                  trials_available=True):
    """Calcula el score a partir de metricas ya limpias.

    pub_stats: {verified_count, recent_5y, first_last_author_count,
                unique_journals}
    trials:    None  o  {"verified_count": N, ...}
    trials_available: False si ClinicalTrials.gov no respondio. Entonces el
                componente no se puntua NI cuenta en el denominador, porque
                un fallo de red no es merito ni demerito del KOL.
    """
    verified = pub_stats.get("verified_count", 0)
    recent = pub_stats.get("recent_5y", 0)
    first_last = pub_stats.get("first_last_author_count", 0)
    journals = pub_stats.get("unique_journals", 0)

    # --- Publicaciones (40) ---
    # ~30 papers con buena autoria satura el componente.
    pub_score = _clamp(verified * 0.8 + first_last * 1.2, PESOS["publications"])

    # --- Ensayos (20) --- 4+ ensayos verificados saturan.
    n_trials = trials["verified_count"] if trials else 0
    trials_score = _clamp(n_trials * 5, PESOS["trials"])

    # --- Influencia (15) --- actividad reciente + variedad de revistas.
    influence_score = _clamp(recent * 0.6 + journals * 0.4, PESOS["influence"])

    # --- Relevancia terapeutica (15) ---
    if specialty:
        tr_score = 12 + (3 if recent > 0 else 0)
    else:
        tr_score = 8
    tr_score = _clamp(tr_score, PESOS["therapeutic_relevance"])

    # --- CRM (10) --- sin integracion real: 0 = primera toma de contacto.
    crm_score = _clamp(min(crm_interactions * 2, PESOS["crm"]), PESOS["crm"])

    breakdown = {
        "publications": pub_score,
        "trials": trials_score,
        "influence": influence_score,
        "therapeutic_relevance": tr_score,
        "crm": crm_score,
    }

    # --- Que componentes cuentan en el denominador ---
    excluded = {}
    medibles = ["publications", "influence", "therapeutic_relevance"]

    if trials_available:
        medibles.append("trials")
    else:
        excluded["trials"] = ("ClinicalTrials.gov did not answer: what could "
                              "not be checked cannot be scored.")

    if crm_interactions > 0:
        medibles.append("crm")
    else:
        excluded["crm"] = ("No CRM integration: 0 interactions on record. "
                           "It neither scores nor penalises.")

    maximo = sum(PESOS[k] for k in medibles)
    bruto = sum(breakdown[k] for k in medibles)
    total = int(round(bruto / maximo * 100)) if maximo else 0

    if total >= 70:
        tier = "Tier 1"
    elif total >= 40:
        tier = "Tier 2"
    else:
        tier = "Tier 3"

    return {
        "total": total,
        "tier": tier,
        "breakdown": breakdown,
        "counted": medibles,
        "excluded": excluded,
        "raw_points": bruto,
        "max_points": maximo,
    }
