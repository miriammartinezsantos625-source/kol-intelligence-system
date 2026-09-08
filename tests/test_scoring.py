"""
Test de scoring: rubric /100 y asignacion de Tier.
"""

from kol_engine.scoring import compute_score


def _stats(verified, recent, first_last, journals):
    return {"verified_count": verified, "recent_5y": recent,
            "first_last_author_count": first_last, "unique_journals": journals}


def test_perfil_alto_es_tier1():
    sc = compute_score(_stats(39, 20, 11, 30), trials=None,
                       specialty="Neuropatologia")
    assert sc["total"] >= 70
    assert sc["tier"] == "Tier 1"


def test_perfil_medio_es_tier2():
    sc = compute_score(_stats(10, 5, 5, 8),
                       trials={"verified_count": 2}, specialty="Oncologia")
    assert 40 <= sc["total"] < 70
    assert sc["tier"] == "Tier 2"


def test_perfil_bajo_es_tier3():
    sc = compute_score(_stats(2, 0, 0, 1), trials=None, specialty=None)
    assert sc["total"] < 40
    assert sc["tier"] == "Tier 3"


def test_sin_ensayos_el_componente_es_cero():
    sc = compute_score(_stats(20, 10, 8, 15), trials=None, specialty="X")
    assert sc["breakdown"]["trials"] == 0


def test_ningun_componente_supera_su_maximo():
    sc = compute_score(_stats(999, 999, 999, 999),
                       trials={"verified_count": 999}, specialty="X")
    assert sc["breakdown"]["publications"] <= 40
    assert sc["breakdown"]["trials"] <= 20
    assert sc["breakdown"]["influence"] <= 15
    assert sc["total"] <= 100


# ----------------------------------------------------------------------
#  Normalizacion sobre componentes medibles (auditoria)
# ----------------------------------------------------------------------

def test_el_maximo_alcanzable_es_100_de_verdad():
    """Antes el techo real era 90: CRM valia 10 puntos que nadie podia sacar,
    asi que todo KOL perdia 10 puntos invisibles sobre un marcador '/100'."""
    sc = compute_score(_stats(999, 999, 999, 999),
                       trials={"verified_count": 999}, specialty="X")
    assert sc["total"] == 100
    assert sc["tier"] == "Tier 1"


def test_crm_no_cuenta_si_no_hay_integracion():
    sc = compute_score(_stats(20, 10, 8, 15),
                       trials={"verified_count": 2}, specialty="X")
    assert "crm" in sc["excluded"]
    assert "crm" not in sc["counted"]
    assert sc["max_points"] == 90


def test_crm_si_cuenta_cuando_hay_interacciones():
    sc = compute_score(_stats(20, 10, 8, 15), trials={"verified_count": 2},
                       specialty="X", crm_interactions=3)
    assert "crm" not in sc["excluded"]
    assert sc["max_points"] == 100


def test_fallo_de_clinicaltrials_no_penaliza():
    """Un fallo de red no es demerito del KOL: el componente sale del
    denominador en vez de restar 20 puntos y bajarle de Tier."""
    stats = _stats(30, 12, 10, 20)
    caido = compute_score(stats, None, specialty="X", trials_available=False)
    sin_ensayos = compute_score(stats, None, specialty="X")

    assert "trials" in caido["excluded"]
    assert caido["max_points"] == 70          # 100 - trials(20) - crm(10)
    assert caido["total"] > sin_ensayos["total"]


def test_breakdown_sigue_dando_puntos_brutos():
    """El desglose debe seguir siendo explicable ante un MSL."""
    sc = compute_score(_stats(10, 5, 5, 8), trials={"verified_count": 2},
                       specialty="Oncologia")
    assert set(sc["breakdown"]) == {"publications", "trials", "influence",
                                    "therapeutic_relevance", "crm"}
    assert sc["raw_points"] == sum(sc["breakdown"][k] for k in sc["counted"])
