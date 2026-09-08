"""
Test del h-index calculado sobre el set YA desambiguado.

El h-index agregado de Europe PMC mezcla homonimos y por eso se marca
NO VERIFICADO. Este otro se calcula sobre los papers que el filtro ya ha
atribuido al KOL, asi que si es atribuible.
"""

import pytest

from kol_engine.europepmc_agent import get_verified_metrics, hindex


@pytest.mark.parametrize("citas, esperado", [
    ([], 0),
    ([0, 0, 0], 0),
    ([1], 1),
    ([10, 10, 10], 3),
    ([5, 4, 3, 2, 1], 3),
    ([27, 16, 15, 12, 9, 5, 5, 4, 3, 3, 1, 0, 0], 5),
    ([100], 1),
])
def test_hindex(citas, esperado):
    assert hindex(citas) == esperado


def test_hindex_no_depende_del_orden():
    assert hindex([3, 1, 5, 0, 2]) == hindex([5, 3, 2, 1, 0])


def test_un_paper_muy_citado_no_infla_el_hindex():
    """h-index mide consistencia, no un exito puntual."""
    assert hindex([5000, 1, 0]) == 1


def test_sin_pmids_devuelve_none():
    assert get_verified_metrics([]) is None
    assert get_verified_metrics(None) is None


def test_pmids_no_numericos_se_descartan():
    assert get_verified_metrics(["no-es-un-pmid", ""]) is None


def test_papers_sin_citas_conocidas_cuentan_como_cero(monkeypatch):
    """Omitirlos reduciria el denominador e inflaria el h-index."""
    from kol_engine import europepmc_agent

    # Europe PMC solo conoce 2 de los 5 papers.
    monkeypatch.setattr(europepmc_agent, "_citas_de_lote",
                        lambda pmids, use_cache=True: {"1": 9, "2": 8})

    m = get_verified_metrics(["1", "2", "3", "4", "5"])
    assert m["papers_evaluados"] == 5
    assert m["papers_encontrados"] == 2
    assert m["hindex"] == 2          # [9,8,0,0,0]
    assert m["citations"] == 17


def test_fallo_de_red_no_rompe_el_pipeline(monkeypatch):
    from kol_engine import europepmc_agent

    def revienta(pmids, use_cache=True):
        raise ConnectionError("Europe PMC caído")

    monkeypatch.setattr(europepmc_agent, "_citas_de_lote", revienta)
    assert get_verified_metrics(["1", "2"]) is None
