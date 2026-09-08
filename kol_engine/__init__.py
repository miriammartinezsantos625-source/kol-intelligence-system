"""
kol_engine — motor del KOL Intelligence System.

Este paquete contiene toda la logica del sistema. Cada modulo tiene una
responsabilidad unica (ver el brief, seccion 3):

    disambiguator      -> construye la query de PubMed y estima la confianza
    pubmed_agent       -> busca papers y filtra homonimos (con log)
    clinicaltrials_agent -> verifica ensayos por localizacion
    europepmc_agent    -> metricas academicas (marcadas NO VERIFICADO)
    scoring            -> KOL Score /100 + Tier
    profile            -> ensambla todo en kol_profile.json (fuente de verdad)
    dashboard          -> kol_profile.json -> HTML 5 pestanas
    pdf                -> kol_profile.json -> PDF 5 paginas
    verify             -> Paso 9 automatizado (verificacion final)

Principio rector: TODO deriva de kol_profile.json. El dashboard y el PDF
nunca se generan de forma independiente.
"""

__version__ = "0.1.0"
