"""
Test de clinicaltrials_agent: matching de investigador y verificacion por
localizacion (funciones puras, sin red).

Caso central: los ensayos de 'San Miguel' en Valencia son de Jesús San Miguel
(Pamplona), NO de Teresa. El sistema debe verificar 0.
"""

from kol_engine.clinicaltrials_agent import _official_coincide, verify_trials


def _study(nct, official_name, official_aff, city, role="PRINCIPAL_INVESTIGATOR"):
    return {"protocolSection": {
        "identificationModule": {"nctId": nct, "briefTitle": "Estudio " + nct},
        "designModule": {"phases": ["PHASE2"]},
        "contactsLocationsModule": {
            "overallOfficials": [{"name": official_name,
                                  "affiliation": official_aff, "role": role}],
            "locations": [{"facility": "Hospital", "city": city,
                           "country": "Spain"}],
        }}}


# ---- _official_coincide ----

def test_official_rechaza_homonimo_por_inicial():
    # Jesús (J) no es Teresa (T), aunque compartan apellido.
    assert _official_coincide("Jesús San Miguel Izquierdo", "San-Miguel", "T") \
        is False


def test_official_acepta_nombre_correcto():
    assert _official_coincide("Teresa San-Miguel", "San-Miguel", "T") is True


def test_official_rechaza_solo_apellido():
    # Sin nombre de pila no se puede confirmar la identidad -> se rechaza.
    assert _official_coincide("San Miguel", "San-Miguel", "T") is False


# ---- verify_trials ----

LOC = ["valencia", "fe"]


def test_verifica_ensayo_de_teresa_en_valencia():
    studies = [_study("NCT00000001", "Teresa San-Miguel",
                      "Hospital La Fe", "Valencia")]
    verificados, log = verify_trials(studies, "San-Miguel", "T", LOC)
    assert log["verified_count"] == 1
    assert verificados[0]["nct"] == "NCT00000001"


def test_excluye_ensayo_de_jesus_en_pamplona():
    studies = [_study("NCT00000002", "Jesús San Miguel",
                      "Clinica Universidad de Navarra", "Pamplona")]
    verificados, log = verify_trials(studies, "San-Miguel", "T", LOC)
    assert log["verified_count"] == 0


def test_no_confunde_fe_con_tenerife():
    # Teresa como investigadora, pero la sede es Tenerife: 'fe' NO debe casar.
    studies = [_study("NCT00000003", "Teresa San-Miguel",
                      "Hospital de Canarias", "Santa Cruz de Tenerife")]
    verificados, log = verify_trials(studies, "San-Miguel", "T", ["fe"])
    assert log["verified_count"] == 0
