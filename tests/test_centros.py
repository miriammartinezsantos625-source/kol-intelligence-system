"""
Test de centros — deduccion de la ciudad a partir del centro de trabajo.

Es lo que permite pedir solo DOS datos (nombre + donde trabaja) sin perder
desambiguacion: la ciudad es un termino de localizacion de primer orden.

Regla que se protege aqui: ante la duda, NO inventar. Deducir mal la ciudad
mete al KOL en el hospital equivocado y contamina el filtro de homonimos, que
es peor que no deducir nada.
"""

from kol_engine import centros


def test_deduce_por_catalogo():
    """Un centro conocido da su ciudad sin que nadie la escriba."""
    assert centros.deducir_ciudad("Hospital Doctor Peset") == "Valencia"
    assert centros.deducir_ciudad("Hospital Universitari i Politècnic La Fe") \
        == "Valencia"
    assert centros.deducir_ciudad("Hospital 12 de Octubre") == "Madrid"
    assert centros.deducir_ciudad("Clínica Universidad de Navarra") == "Pamplona"


def test_deduce_la_ciudad_escrita_a_mano():
    """Si la ciudad viene pegada al centro, se lee de ahi."""
    assert centros.deducir_ciudad("Hospital La Fe, Valencia") == "Valencia"
    assert centros.deducir_ciudad("Hospital Clínico (Granada)") == "Granada"


def test_deduce_ciudad_mencionada():
    """Un centro desconocido en una ciudad conocida sigue dando la ciudad."""
    assert centros.deducir_ciudad("Centro de Salud de Albacete") == "Albacete"


def test_no_inventa_ciudad():
    """Sin senal, devuelve None: el sistema sigue con los terminos del centro."""
    assert centros.deducir_ciudad("Centro de salud del pueblo") is None
    assert centros.deducir_ciudad("") is None
    assert centros.deducir_ciudad(None) is None


def test_no_confunde_ciudad_dentro_de_otra_palabra():
    """La comparacion es por PALABRA completa, como en el filtro de homonimos.

    'Leon' no debe salir de 'Leonardo', ni 'Lugo' de 'Lugones'.
    """
    assert centros.deducir_ciudad("Instituto Leonardo Torres") is None


def test_limpiar_centro_quita_la_ciudad_pegada():
    """La portada no debe decir 'Hospital La Fe, Valencia · Valencia'."""
    assert centros.limpiar_centro("Hospital La Fe, Valencia") == "Hospital La Fe"
    assert centros.limpiar_centro("Hospital Clínico (Granada)") == "Hospital Clínico"
    # Si la coma no separa una ciudad, no se toca nada.
    assert centros.limpiar_centro("Hospital Clínico, Servicio de Cardiología") \
        == "Hospital Clínico, Servicio de Cardiología"
