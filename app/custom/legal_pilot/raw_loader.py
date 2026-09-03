"""
app/custom/legal_pilot/raw_loader.py

The pilot project's `load_raw_records()`, following
app/custom/_template/raw_loader.py's pattern.

A real deployment would parse an actual Bulletin Officiel / legal-text
source here. Its job is validating genericity against a realistic
field set and a corpus large enough to exercise every declared filter
meaningfully (multiple document types, multiple authorities, multiple
statuses, overlapping date ranges, cross-references) -- not shipping a
production ingestion pipeline. Swap this function's body for real
extraction logic when this project moves from "pilot" to "real
deployment"; nothing else in this package, app/core/, or app/api/ needs
to change either way.

Field names in `metadata` match this project's config.yaml `filters:`
declarations exactly (document_type, publication_date, promulgation_date,
issuing_authority, legal_status, title). `subject`, `jurisdiction`, and
`cross_references` are also included on every record even though they
aren't declared as filters in config.yaml -- under the default
`unknown_field_policy="passthrough"` (app/core/schema/metadata_types.py)
they pass through untyped rather than being rejected, which is itself a
useful thing for this pilot to demonstrate: a project can carry metadata
it displays or stores without being forced to make every field
filterable.
"""
from __future__ import annotations

from typing import Any

_SAMPLE_RECORDS: list[dict[str, Any]] = [
    {
        "id": "legal_text_0001",
        "text": (
            "Dahir portant loi relatif a la protection des donnees a caractere "
            "personnel. Le texte fixe les obligations des responsables de "
            "traitement, les droits des personnes concernees et institue une "
            "autorite nationale de controle chargee de veiller au respect de "
            "la loi."
        ),
        "metadata": {
            "title": "Dahir portant loi n. 1-09-15 relatif a la protection des donnees a caractere personnel",
            "promulgation_date": "2009-02-18",
            "publication_date": "2009-03-05",
            "document_type": "dahir",
            "issuing_authority": "roi_du_maroc",
            "legal_status": "en_vigueur",
            "subject": "protection des donnees",
            "jurisdiction": "national",
            "cross_references": ["legal_text_0007"],
        },
    },
    {
        "id": "legal_text_0002",
        "text": (
            "Decret fixant les conditions et les modalites de passation des "
            "marches publics par les administrations de l'Etat. Le texte "
            "precise les seuils applicables, les procedures d'appel d'offres "
            "et les regles de publicite et de mise en concurrence."
        ),
        "metadata": {
            "title": "Decret n. 2-12-349 relatif aux marches publics",
            "promulgation_date": "2013-03-20",
            "publication_date": "2013-04-04",
            "document_type": "decret",
            "issuing_authority": "chef_du_gouvernement",
            "legal_status": "modifie",
            "subject": "marches publics",
            "jurisdiction": "national",
            "cross_references": ["legal_text_0009"],
        },
    },
    {
        "id": "legal_text_0003",
        "text": (
            "Loi relative a la lutte contre la corruption, instituant une "
            "instance nationale de probite, de prevention et de lutte contre "
            "la corruption dotee de prerogatives d'enquete et de saisine du "
            "parquet."
        ),
        "metadata": {
            "title": "Loi n. 46-19 portant reorganisation de l'Instance Nationale de la Probite",
            "promulgation_date": "2021-07-14",
            "publication_date": "2021-08-02",
            "document_type": "loi",
            "issuing_authority": "parlement",
            "legal_status": "en_vigueur",
            "subject": "lutte contre la corruption",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0004",
        "text": (
            "Arrete du ministre de l'interieur fixant la liste des pieces "
            "justificatives exigees pour la delivrance de la carte nationale "
            "d'identite electronique, ainsi que les delais de traitement des "
            "demandes."
        ),
        "metadata": {
            "title": "Arrete du ministre de l'interieur n. 1234-19 relatif a la CNIE",
            "promulgation_date": "2019-05-10",
            "publication_date": "2019-06-01",
            "document_type": "arrete",
            "issuing_authority": "ministere_interieur",
            "legal_status": "en_vigueur",
            "subject": "etat civil",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0005",
        "text": (
            "Dahir promulguant la loi organique relative aux regions, "
            "definissant leurs competences propres, partagees et transferees, "
            "ainsi que les modalites d'election et de fonctionnement des "
            "conseils regionaux."
        ),
        "metadata": {
            "title": "Dahir n. 1-15-83 portant promulgation de la loi organique n. 111-14 relative aux regions",
            "promulgation_date": "2015-07-07",
            "publication_date": "2015-07-23",
            "document_type": "dahir",
            "issuing_authority": "roi_du_maroc",
            "legal_status": "en_vigueur",
            "subject": "regionalisation avancee",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0006",
        "text": (
            "Decret modifiant les dispositions relatives a la nomenclature "
            "des pieces justificatives des depenses publiques, dans un "
            "objectif de simplification administrative et de "
            "dematerialisation."
        ),
        "metadata": {
            "title": "Decret n. 2-22-431 modifiant le decret relatif aux pieces justificatives des depenses publiques",
            "promulgation_date": "2023-01-09",
            "publication_date": "2023-01-26",
            "document_type": "decret",
            "issuing_authority": "chef_du_gouvernement",
            "legal_status": "en_vigueur",
            "subject": "finances publiques",
            "jurisdiction": "national",
            "cross_references": ["legal_text_0002"],
        },
    },
    {
        "id": "legal_text_0007",
        "text": (
            "Decret d'application de la loi relative a la protection des "
            "donnees a caractere personnel, precisant les modalites de "
            "declaration prealable, les formulaires types et les delais "
            "d'instruction des dossiers."
        ),
        "metadata": {
            "title": "Decret n. 2-09-165 pris pour l'application de la loi n. 09-08",
            "promulgation_date": "2009-05-21",
            "publication_date": "2009-06-18",
            "document_type": "decret",
            "issuing_authority": "chef_du_gouvernement",
            "legal_status": "en_vigueur",
            "subject": "protection des donnees",
            "jurisdiction": "national",
            "cross_references": ["legal_text_0001"],
        },
    },
    {
        "id": "legal_text_0008",
        "text": (
            "Loi relative au code du travail dans sa partie consacree aux "
            "relations individuelles, fixant les regles applicables au "
            "contrat de travail, a la duree legale du travail et aux conges "
            "payes."
        ),
        "metadata": {
            "title": "Loi n. 65-99 relative au Code du travail",
            "promulgation_date": "2003-05-08",
            "publication_date": "2003-06-06",
            "document_type": "loi",
            "issuing_authority": "parlement",
            "legal_status": "modifie",
            "subject": "droit du travail",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0009",
        "text": (
            "Arrete du chef du gouvernement fixant les seuils de passation "
            "des marches publics par appel d'offres ouvert, ainsi que les "
            "modalites de publication des avis sur le portail des marches "
            "publics."
        ),
        "metadata": {
            "title": "Arrete du chef du gouvernement n. 20-14 fixant les seuils des marches publics",
            "promulgation_date": "2014-03-13",
            "publication_date": "2014-04-02",
            "document_type": "arrete",
            "issuing_authority": "chef_du_gouvernement",
            "legal_status": "abroge",
            "subject": "marches publics",
            "jurisdiction": "national",
            "cross_references": ["legal_text_0002"],
        },
    },
    {
        "id": "legal_text_0010",
        "text": (
            "Dahir portant loi organique relative a la loi de finances, "
            "fixant les principes budgetaires, les modalites de "
            "preparation, de vote et d'execution du budget de l'Etat."
        ),
        "metadata": {
            "title": "Dahir n. 1-15-62 portant promulgation de la loi organique n. 130-13 relative a la loi de finances",
            "promulgation_date": "2015-06-02",
            "publication_date": "2015-06-18",
            "document_type": "dahir",
            "issuing_authority": "roi_du_maroc",
            "legal_status": "en_vigueur",
            "subject": "finances publiques",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0011",
        "text": (
            "Decret relatif a l'organisation de la profession de comptable "
            "agree, fixant les conditions d'acces a la profession, les "
            "modalites d'inscription au tableau et les obligations "
            "deontologiques."
        ),
        "metadata": {
            "title": "Decret n. 2-89-582 relatif a la profession de comptable agree",
            "promulgation_date": "1993-01-08",
            "publication_date": "1993-02-17",
            "document_type": "decret",
            "issuing_authority": "chef_du_gouvernement",
            "legal_status": "abroge",
            "subject": "professions reglementees",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
    {
        "id": "legal_text_0012",
        "text": (
            "Arrete conjoint fixant les conditions d'octroi des "
            "autorisations d'exploitation des etablissements classes, dans "
            "une perspective de simplification des procedures "
            "administratives pour les investisseurs."
        ),
        "metadata": {
            "title": "Arrete conjoint n. 3025-20 relatif aux etablissements classes",
            "promulgation_date": "2020-10-15",
            "publication_date": "2020-11-05",
            "document_type": "arrete",
            "issuing_authority": "ministere_industrie",
            "legal_status": "en_vigueur",
            "subject": "investissement",
            "jurisdiction": "national",
            "cross_references": [],
        },
    },
]


def load_raw_records() -> list[dict[str, Any]]:
    return _SAMPLE_RECORDS
