"""Assistant IA eStage MEF — backend précis, concis et traçable.

Les réponses prioritaires proviennent des fichiers JSON locaux. Si une clé API
est configurée, NVIDIA puis le fournisseur secondaire peuvent reformuler le
brouillon factuel. Ce prototype ne consulte pas les candidatures réelles eStage.
"""
from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("estage-mef-ia")

app = FastAPI(
    title="Assistant IA eStage MEF — Prototype",
    version="2.2.0",
    description=(
        "Assistant d'information et d'orientation non connecté "
        "aux candidatures réelles eStage."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------- Lecture des données -----------------------------

def load_json(filename: str, default: Any = None) -> Any:
    path = DATA_DIR / filename

    if not path.exists():
        if default is not None:
            logger.info("Fichier facultatif absent : %s", filename)
            return default

        raise FileNotFoundError(
            f"Fichier requis introuvable : {path}"
        )

    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            return json.load(stream)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"JSON invalide dans {filename}, "
            f"ligne {exc.lineno}: {exc.msg}"
        ) from exc


def collection(filename: str, *keys: str) -> list[dict[str, Any]]:
    data = load_json(filename, default=[])

    if isinstance(data, list):
        return [
            item for item in data
            if isinstance(item, dict)
        ]

    if isinstance(data, dict):
        for key in keys:
            if isinstance(data.get(key), list):
                return [
                    item for item in data[key]
                    if isinstance(item, dict)
                ]

    return []


def unique(values: list[Any]) -> list[Any]:
    result = []
    seen = set()

    for value in values:
        if isinstance(value, (dict, list)):
            marker = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
            )
        else:
            marker = str(value)

        if marker not in seen:
            seen.add(marker)
            result.append(value)

    return result


def merge_record(
    old: dict[str, Any],
    new: dict[str, Any],
) -> dict[str, Any]:
    result = dict(old)

    replace_lists = {
        "services",
        "services_ids",
        "sources_ids",
        "source_ids",
        "attributions",
        "domaines_intervention",
        "profils_formation_pertinents",
        "competences_pertinentes",
        "mots_cles",
        "metiers_associes",
    }

    for key, value in new.items():
        if key in replace_lists and isinstance(value, list):
            result[key] = list(value)

        elif (
            isinstance(value, list)
            and isinstance(result.get(key), list)
        ):
            result[key] = unique(result[key] + value)

        elif value is not None and value != "":
            result[key] = value

        elif key not in result:
            result[key] = value

    if new.get("mission_resume"):
        result["mission"] = new["mission_resume"]

    return result


def merge_by_id(
    *groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = {}
    order = []

    for group in groups:
        for raw in group:
            item = dict(raw)
            item_id = str(item.get("id") or "").strip()

            if not item_id:
                item_id = f"__sans_id_{len(order)}"
                item["id"] = item_id

            if item_id not in records:
                records[item_id] = item
                order.append(item_id)

            else:
                records[item_id] = merge_record(
                    records[item_id],
                    item,
                )

    return [records[item_id] for item_id in order]


STRUCTURES = merge_by_id(
    collection("structures.json", "structures", "items"),
    collection("structures_2026.json", "structures", "items"),
)

STRUCTURES = [
    item for item in STRUCTURES
    if item.get("id") not in {
        "dgb-demo",
        "dgb-legacy-placeholder",
    }
    and not str(
        item.get("source_status", "")
    ).lower().startswith("deprecated")
    and "placeholder" not in str(
        item.get("id", "")
    ).lower()
]

SERVICES = collection(
    "services_2026.json",
    "services",
    "items",
)

PROFILES = collection(
    "profils_competences.json",
    "profils",
    "profiles",
    "items",
)

SOURCES = collection(
    "sources.json",
    "sources",
    "items",
)

FAQ = merge_by_id(
    collection("faq.json", "faq", "items"),
    collection("faq_phase2.json", "faq", "items"),
)

PROCEDURES = merge_by_id(
    collection("procedures.json", "procedures", "items"),
    collection("procedures_phase2.json", "procedures", "items"),
)

INTENTS = collection(
    "intents_questions.json",
    "intentions",
    "intents",
    "items",
)

PARCOURS = collection(
    "parcours.json",
    "parcours",
    "items",
)

OFFRES = collection(
    "offres_stage.json",
    "offres",
    "items",
)

DOSSIERS_DEMO = collection(
    "demo_dossiers.json",
    "dossiers",
    "items",
)

GLOSSAIRE = load_json("glossaire.json", default={})

INFORMATIONS_GENERALES = load_json(
    "informations_generales.json",
    default={},
)

MATCHING_RULES = load_json(
    "matching_rules.json",
    default={},
)

CHAMPS_STATUTS = load_json(
    "champs_et_statuts.json",
    default={},
)

TESTS_ACCEPTATION = load_json(
    "tests_acceptation.json",
    default={},
)

if not isinstance(GLOSSAIRE, dict):
    GLOSSAIRE = {}

if not isinstance(INFORMATIONS_GENERALES, dict):
    INFORMATIONS_GENERALES = {}


STRUCTURES_BY_ID = {
    str(item["id"]): item
    for item in STRUCTURES
    if item.get("id")
}

SERVICES_BY_ID = {
    str(item["id"]): item
    for item in SERVICES
    if item.get("id")
}

SOURCES_BY_ID = {
    str(item["id"]): item
    for item in SOURCES
    if item.get("id")
}


# ----------------------------- Modèles API ----------------------------------

class ChatMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    history: Optional[list[dict[str, Any]]] = None


class ProfileInput(BaseModel):
    formation: Optional[str] = ""
    specialite: Optional[str] = ""
    niveau: Optional[str] = ""
    competences: list[str] = Field(default_factory=list)
    domaines_interet: list[str] = Field(default_factory=list)
    objectifs: Optional[str] = ""


# -------------------------- Normalisation texte -----------------------------

STOPWORDS = {
    "avec", "dans", "pour", "les", "des", "une", "mon", "mes",
    "vous", "votre", "vos", "est", "suis", "sont", "que", "qui",
    "quoi", "comment", "faire", "peux", "peut", "etre", "chez",
    "vers", "plus", "moins", "quelle", "quelles", "quel", "quels",
    "moi", "sur", "par", "aux", "au", "du", "de", "la", "le",
    "et", "ou", "mef", "profil", "structure", "structures",
    "service", "services", "stage", "stages", "pourquoi", "je",
    "un", "en", "ce", "cette", "cet", "il", "elle", "me", "ma",
}


def normalize_text(value: Any) -> str:
    text = str(value or "").lower()
    text = text.replace("’", "'").replace("œ", "oe")
    text = unicodedata.normalize("NFKD", text)

    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = (
        text.replace("-", " ")
        .replace("–", " ")
        .replace("—", " ")
    )

    text = re.sub(r"[^a-z0-9\s+#/]", " ", text)

    return re.sub(r"\s+", " ", text).strip()


def tokens(value: Any) -> set[str]:
    return {
        word
        for word in re.split(
            r"[^a-z0-9]+",
            normalize_text(value),
        )
        if len(word) > 2 and word not in STOPWORDS
    }


def has(text: str, phrase: str) -> bool:
    target = normalize_text(phrase)

    return bool(target) and (
        f" {target} " in f" {normalize_text(text)} "
    )


def is_demo(item: dict[str, Any]) -> bool:
    status = normalize_text(
        item.get("source_status")
        or item.get("status")
        or ""
    )

    return bool(item.get("demo_data")) or any(
        flag in status
        for flag in (
            "demo data",
            "not found",
            "deprecated",
            "non verifie",
            "non confirme",
            "requires direct confirmation",
            "requires_direct_confirmation",
            "a verifier",
        )
    )


def sources_for(
    record: dict[str, Any],
    limit: int = 2,
) -> list[dict[str, Any]]:
    ids = (
        record.get("sources_ids")
        or record.get("source_ids")
        or []
    )

    return [
        SOURCES_BY_ID[str(source_id)]
        for source_id in ids
        if str(source_id) in SOURCES_BY_ID
    ][:limit]


def source_lines(
    record: dict[str, Any],
    limit: int = 2,
) -> list[str]:
    return [
        f"Source : {source.get('titre', source['url'])} — {source['url']}"
        for source in sources_for(record, limit)
        if source.get("url")
    ]


def expand_structure(
    item: dict[str, Any],
) -> dict[str, Any]:
    result = dict(item)

    service_ids = {
        str(value)
        for value in (item.get("services_ids") or [])
    }

    services = [
        service
        for service in SERVICES
        if (
            str(service.get("structure_id", ""))
            == str(item.get("id", ""))
        )
        or str(service.get("id", "")) in service_ids
    ]

    result["services_details"] = services

    names = [
        value
        for value in (item.get("services") or [])
        if isinstance(value, str) and value
    ]

    names.extend(
        str(service["nom"])
        for service in services
        if service.get("nom")
    )

    result["services_affichage"] = unique(names)
    result["sources_details"] = sources_for(item, 4)

    return result


def find_structure(message: str) -> Optional[dict[str, Any]]:
    for item in sorted(
        STRUCTURES,
        key=lambda record: len(
            normalize_text(record.get("nom", ""))
        ),
        reverse=True,
    ):
        if item.get("nom") and has(
            message,
            str(item["nom"]),
        ):
            return item

    matches = []

    for item in STRUCTURES:
        aliases = (
            [item.get("nom_court", ""), item.get("id", "")]
            + list(item.get("alias") or [])
        )

        for alias in aliases:
            if alias and has(message, str(alias)):
                matches.append(
                    (len(normalize_text(alias)), item)
                )

    return (
        max(matches, key=lambda value: value[0])[1]
        if matches
        else None
    )


# ----------------------------- Orientation ----------------------------------

def profile_text(profile: ProfileInput) -> str:
    return " ".join([
        profile.formation or "",
        profile.specialite or "",
        profile.niveau or "",
        " ".join(profile.competences),
        " ".join(profile.domaines_interet),
        profile.objectifs or "",
    ]).strip()


def split_profile_name(name: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"[/|,;]", name or "")
        if part.strip()
    ]


def matched_profile_families(
    text: str,
) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    profile_ids: set[str] = set()
    query_tokens = tokens(text)
    matched_profiles = []

    for profile in PROFILES:
        phrases = split_profile_name(
            str(profile.get("nom", ""))
        )

        phrases.extend(
            str(value)
            for value in (profile.get("synonymes") or [])
            if value
        )

        match = any(
            has(text, phrase)
            for phrase in phrases
        )

        if not match:
            family_tokens = (
                set().union(*(tokens(value) for value in phrases))
                if phrases
                else set()
            )

            match = len(family_tokens & tokens(text)) >= 2

        if match:
            if profile.get("id"):
                profile_ids.add(str(profile["id"]))

            matched_profiles.append(profile)
            query_tokens.update(tokens(" ".join(phrases)))
            query_tokens.update(
                tokens(" ".join(profile.get("competences") or []))
            )

    return profile_ids, query_tokens, matched_profiles


def recommendation_data(
    profile: ProfileInput,
    limit: int = 3,
) -> list[dict[str, Any]]:
    raw = profile_text(profile)

    profile_ids, query_tokens, profile_families = (
        matched_profile_families(raw)
    )

    if not query_tokens:
        return []

    ranked = []

    for structure in STRUCTURES:
        sid = str(structure.get("id", ""))

        if (
            sid == "mef"
            or sid.startswith("port-")
            or is_demo(structure)
        ):
            continue

        score = 0
        reasons = []
        priority_rank = None

        for family in profile_families:
            targets = [
                str(value)
                for value in (
                    family.get("structures_recommandees") or []
                )
            ]

            if sid in targets:
                rank = targets.index(sid)

                priority_rank = (
                    rank
                    if priority_rank is None
                    else min(priority_rank, rank)
                )

        if priority_rank is not None:
            score += max(25, 65 - 7 * priority_rank)
            reasons.append(
                "missions associées au profil sélectionné"
            )

        for field, label in (
            ("profils_formation_pertinents", "formation"),
            ("competences_pertinentes", "compétence"),
            ("domaines_intervention", "domaine"),
            ("mots_cles", "activité"),
        ):
            hits = []

            for value in structure.get(field) or []:
                if not isinstance(value, str) or not value.strip():
                    continue

                overlap = tokens(value) & query_tokens
                exact = has(raw, value)

                if (
                    exact
                    or len(overlap) >= 2
                    or bool(
                        overlap
                        & {
                            "python",
                            "sql",
                            "pytorch",
                            "tensorflow",
                            "ml",
                        }
                    )
                ):
                    hits.append(value)

            if hits:
                factor = (
                    5
                    if field in {
                        "profils_formation_pertinents",
                        "competences_pertinentes",
                    }
                    else 3
                )

                score += min(12, len(hits) * factor)
                reasons.extend(
                    f"{label} : {value}"
                    for value in hits[:2]
                )

        related_services = [
            service
            for service in SERVICES
            if (
                str(service.get("structure_id", "")) == sid
                or str(service.get("id", ""))
                in {
                    str(value)
                    for value in (
                        structure.get("services_ids") or []
                    )
                }
            )
        ]

        service_ranked = []

        for service in related_services:
            service_text = " ".join([
                str(service.get("nom", "")),
                str(service.get("missions_resume", "")),
                " ".join(service.get("mots_cles") or []),
                " ".join(
                    service.get("profils_formation_pertinents") or []
                ),
                " ".join(
                    service.get("competences_pertinentes") or []
                ),
                " ".join(service.get("synonymes") or []),
            ])

            overlap = len(
                tokens(service_text) & query_tokens
            )

            if overlap >= 2:
                service_ranked.append((overlap, service))

        service_ranked.sort(
            key=lambda pair: pair[0],
            reverse=True,
        )

        services = unique([
            str(service.get("nom"))
            for _, service in service_ranked[:2]
            if service.get("nom")
        ])

        if services:
            score += min(15, len(services) * 5)

        if score <= 0:
            continue

        display_name = (
            structure.get("nom_court")
            or structure.get("nom")
            or sid
        )

        if (
            display_name == "Pôle informatique"
            and structure.get("portefeuille")
        ):
            display_name = (
                f"Pôle informatique — "
                f"{structure['portefeuille']}"
            )

        ranked.append({
            "id": sid,
            "nom": structure.get("nom", sid),
            "nom_court": display_name,
            "type_structure": structure.get("type_structure"),
            "score": min(score, 95),
            "raisons": unique(reasons)[:3],
            "services_cibles": services,
            "source_status": (
                structure.get("source_status")
                or structure.get("status")
            ),
            "niveau_confiance": (
                structure.get("niveau_confiance")
                or structure.get("confiance")
            ),
            "sources": sources_for(structure, 1),
            "note_orientation": structure.get("note_orientation"),
        })

    ranked.sort(
        key=lambda item: (
            item["score"],
            bool(item["services_cibles"]),
        ),
        reverse=True,
    )

    result = []
    seen = set()

    for item in ranked:
        key = normalize_text(item["nom_court"])

        if key in seen:
            continue

        seen.add(key)
        result.append(item)

        if len(result) >= max(1, min(limit, 3)):
            break

    return result


# --------------------------- Détection d'intention ---------------------------

def find_exact_faq(
    message: str,
) -> Optional[dict[str, Any]]:
    query = normalize_text(message)
    matches = []

    for item in FAQ:
        candidates = (
            [item.get("question")]
            if item.get("question")
            else []
        ) + list(item.get("variantes") or [])

        if any(
            normalize_text(candidate) == query
            for candidate in candidates
            if candidate
        ):
            matches.append(item)

    return (
        max(
            matches,
            key=lambda item: len(
                item.get("sources_ids") or []
            ),
        )
        if matches
        else None
    )


def has_profile_orientation(message: str) -> bool:
    profile_terms = (
        "intelligence artificielle",
        "machine learning",
        "apprentissage automatique",
        "data science",
        "data analyst",
        "business intelligence",
        "informatique",
        "python",
        "developpeur",
        "genie logiciel",
        "cybersecurite",
        "statistiques",
        "comptabilite",
        "economie",
        "droit",
        "finance",
        "gestion de projet",
        "bases de donnees",
        "etudiant en",
        "ma formation",
        "mes competences",
        "mon profil",
        "licence",
        "master",
        "ia",
        "deep learning",
    )

    orientation_terms = (
        "quelles structures",
        "quelle structure",
        "correspondent a mon profil",
        "correspond a mon profil",
        "correspond a ma formation",
        "structure adaptee a mon profil",
        "ou faire mon stage",
        "trouver mon stage",
        "je cherche un stage",
        "je recherche un stage",
        "je veux faire un stage",
        "oriente moi",
        "recommande",
        "recommandation",
        "ou puis je postuler",
        "ou pourrais je postuler",
        "ou puis je etre utile",
        "par ou commencer",
    )

    excluded = (
        "document a fournir",
        "documents a fournir",
        "piece a fournir",
        "pieces a fournir",
        "conditions d eligibilite",
        "date limite",
        "verifier mon dossier",
        "suivre mon dossier",
        "statut de ma candidature",
        "mot de passe",
        "probleme technique",
        "offre active",
        "offres de stage",
        "lettre de motivation",
        "mon cv",
        "curriculum vitae",
        "entretien",
    )

    return (
        any(has(message, term) for term in profile_terms)
        and any(has(message, term) for term in orientation_terms)
        and not any(has(message, term) for term in excluded)
    )


def detect_intent(message: str) -> str:
    text = normalize_text(message)

    # Priorité aux demandes d'orientation personnalisée.
    if has_profile_orientation(message):
        return "orientation"

    # Suivi de dossier : ne jamais inventer un statut réel.
    if any(has(text, term) for term in (
        "verifier mon dossier",
        "ou en est mon dossier",
        "ou en est ma candidature",
        "suivre mon dossier",
        "suivre ma demande",
        "statut de ma candidature",
        "statut de mon dossier",
        "ma candidature est elle acceptee",
        "mon dossier est il complet",
        "ma demande a t elle bien ete recue",
        "numero de dossier",
        "reference de candidature",
        "quels documents manquent a mon dossier",
        "pourquoi ma demande est elle incomplete",
    )):
        return "verifier_dossier"

    # Problèmes techniques.
    if any(has(text, term) for term in (
        "mot de passe",
        "probleme de connexion",
        "code de verification",
        "code otp",
        "je ne recois pas le code",
        "televerser mon cv",
        "fichier pdf refuse",
        "formulaire ne se soumet pas",
        "page ne s ouvre pas",
        "site ne s ouvre pas",
        "erreur apres l envoi",
        "page reste bloquee",
        "probleme technique",
        "connexion internet interrompue",
        "bouton ne fonctionne pas",
        "je n arrive pas a me connecter",
    )):
        return "assistance_technique"

    # Détection des questions de procédure.
    asks_procedure_explicitly = any(has(text, term) for term in (
        "quels documents",
        "quel document",
        "quels sont les documents",
        "quels sont les pieces",
        "documents obligatoires",
        "documents requis",
        "documents a fournir",
        "documents a preparer",
        "document a preparer",
        "pieces a fournir",
        "pieces a preparer",
        "quels papiers",
        "quelles sont les etapes",
        "etapes a suivre",
        "etapes a suivre sur la plateforme",
        "conditions d eligibilite",
        "conditions pour effectuer un stage",
        "date limite pour deposer",
        "comment deposer",
        "comment postuler",
        "comment faire une demande",
        "etapes pour deposer",
        "procedure de candidature",
        "combien de temps faut il pour obtenir une reponse",
        "modifier une demande",
        "annuler une candidature",
        "frais de candidature",
        "duree du stage",
        "convention de stage",
        "attestation de scolarite",
        "suis je eligible",
        "formats de fichiers acceptes",
    ))

    procedure_context = any(has(text, term) for term in (
        "estage",
        "plateforme",
        "demande de stage",
        "candidature",
        "deposer",
        "postuler",
        "stage au mef",
        "stage mef",
    ))

    mentions_documents_or_steps = any(has(text, term) for term in (
        "document",
        "documents",
        "piece",
        "pieces",
        "etape",
        "etapes",
        "formulaire",
    ))

    if (
        asks_procedure_explicitly
        or (
            procedure_context
            and mentions_documents_or_steps
        )
    ):
        return "procedure"

    # Préparation de candidature.
    if any(has(text, term) for term in (
        "lettre de motivation",
        "rediger une lettre",
        "relire ma lettre",
        "mon cv",
        "curriculum vitae",
        "preparer mon cv",
        "exemple de cv",
        "portfolio",
        "github",
        "preparer un entretien",
        "questions d entretien",
        "sujet de memoire",
        "projet de memoire",
        "formuler mes objectifs",
        "presenter mes projets",
        "valoriser mes projets",
        "adapter ma candidature",
        "preparer ma candidature",
    )):
        return "preparation_candidature"

    # Offres de stage.
    if any(has(text, term) for term in (
        "offres de stage",
        "offre de stage actuellement",
        "offre active",
        "offres disponibles",
        "quelles offres sont disponibles",
        "offre remuneree",
        "cette offre est elle ouverte",
        "date limite de cette offre",
        "offre pour un stagiaire",
        "postuler a cette offre",
        "offres disponibles en informatique",
        "annonce encore ouverte",
        "y a t il actuellement des offres",
    )):
        return "offre_stage"

    # Exploration des structures et du ministère.
    if any(has(text, term) for term in (
        "explorer le mef",
        "organisation du mef",
        "organigramme",
        "que fait le mef",
        "quelles sont les structures",
        "quelles structures composent",
        "quelle est la mission",
        "quelles sont les missions",
        "parle moi de",
        "presente le mef",
        "difference entre les impots et les douanes",
        "que signifie",
        "quel est le role de",
        "quelle est la source officielle",
        "pourquoi cette information est fiable",
    )):
        return "explorer"

    stage_seeking = any(has(text, term) for term in (
        "stage",
        "faire un stage",
        "cherche un stage",
        "recherche un stage",
        "trouve un stage",
    ))

    profile_terms = (
        "data science",
        "data analyst",
        "analyse de donnees",
        "machine learning",
        "intelligence artificielle",
        "python",
        "genie logiciel",
        "informatique",
        "cybersecurite",
        "statistiques",
        "comptabilite",
        "economie",
        "droit",
        "finance",
        "gestion de projet",
        "bases de donnees",
        "apprentissage automatique",
    )

    if stage_seeking and any(
        has(text, term) for term in profile_terms
    ):
        return "orientation"

    # Intentions chargées depuis le fichier JSON.
    for item in INTENTS:
        if any(
            has(text, example)
            for example in (item.get("exemples") or [])
            if example
        ):
            identifier = normalize_text(
                str(item.get("id", ""))
                + " "
                + str(item.get("label", ""))
            )

            if "dossier" in identifier or "suivi" in identifier:
                return "verifier_dossier"

            if "technique" in identifier or "assistance" in identifier:
                return "assistance_technique"

            if "procedure" in identifier:
                return "procedure"

            if "offre" in identifier:
                return "offre_stage"

            if (
                "preparation" in identifier
                or "candidature" in identifier
            ):
                return "preparation_candidature"

            if (
                "orientation" in identifier
                or "trouver mon stage" in identifier
            ):
                return "orientation"

            if "explorer" in identifier:
                return "explorer"

    # Catégorie de la FAQ exacte, si disponible.
    exact = find_exact_faq(message)

    if exact:
        category = normalize_text(
            exact.get("categorie", "")
        )

        if "trouver mon stage" in category:
            return "orientation"

        if "procedure" in category:
            return "procedure"

        if "explorer" in category:
            return "explorer"

        if "dossier" in category:
            return "verifier_dossier"

        if "offre" in category:
            return "offre_stage"

        if "technique" in category:
            return "assistance_technique"

        if "candidature" in category:
            return "preparation_candidature"

    if (
        find_structure(message)
        and "stage" not in text
        and "postuler" not in text
    ):
        return "explorer"

    return "general"


# -------------------------------- FAQ ----------------------------------------

def best_faq(
    message: str,
    category: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    query = tokens(message)
    ranked = []

    for item in FAQ:
        if (
            category
            and normalize_text(item.get("categorie", ""))
            != normalize_text(category)
        ):
            continue

        candidates = (
            [item.get("question")]
            if item.get("question")
            else []
        ) + list(item.get("variantes") or [])

        q_tokens = (
            set().union(
                *(tokens(value) for value in candidates if value)
            )
            if candidates
            else set()
        )

        score = (
            len(query & q_tokens)
            + len(
                query
                & tokens(" ".join(item.get("mots_cles") or []))
            )
        )

        if any(
            has(message, candidate)
            for candidate in candidates
            if candidate
        ):
            score += 50

        if score:
            ranked.append((
                score,
                len(item.get("sources_ids") or []),
                item,
            ))

    ranked.sort(
        key=lambda row: (row[0], row[1]),
        reverse=True,
    )

    return ranked[0][2] if ranked else None


# ----------------------------- Réponses --------------------------------------

def answer_orientation(message: str) -> str:
    profile = ProfileInput(
        formation=message,
        specialite=message,
        objectifs=message,
    )

    recos = recommendation_data(profile, 3)

    if not recos:
        return (
            "Pour te conseiller précisément, indique ta formation, "
            "ton niveau d'études, deux ou trois compétences "
            "que tu maîtrises et le sujet que tu aimerais travailler. "
            "Je comparerai ensuite ces éléments aux missions documentées."
        )

    is_ai = any(has(message, term) for term in (
        "intelligence artificielle",
        "machine learning",
        "apprentissage automatique",
        "deep learning",
        "data science",
        "data analyst",
        "ia",
    ))

    if is_ai:
        intro = (
            "Pour ton profil en intelligence artificielle, "
            "je regarderais d'abord les services liés aux données, "
            "à l'interopérabilité et aux solutions numériques :"
        )
    else:
        intro = (
            "Au regard de ta formation et de tes compétences, "
            "voici les pistes que je te conseille d'examiner :"
        )

    lines = [intro]

    for item in recos:
        lines.append(f"\n**{item['nom_court']}**")

        structure = STRUCTURES_BY_ID.get(
            str(item["id"]),
            {},
        )

        relevant_services = []

        for service in SERVICES:
            if (
                str(service.get("structure_id", ""))
                != str(item["id"])
            ):
                continue

            service_text = " ".join([
                str(service.get("nom", "")),
                str(service.get("missions_resume", "")),
                " ".join(service.get("mots_cles") or []),
                " ".join(
                    service.get("profils_formation_pertinents") or []
                ),
                " ".join(
                    service.get("competences_pertinentes") or []
                ),
                " ".join(service.get("synonymes") or []),
            ])

            if is_ai:
                specific_topics = (
                    "gouvernance des donnees",
                    "interopérabilité",
                    "solutions digitales",
                    "archives numeriques",
                    "analyse de donnees",
                    "systemes d information",
                    "applications",
                    "decisionnel",
                    "machine learning",
                    "data science",
                    "statistiques",
                    "suivi evaluation",
                    "performance des projets",
                )

                semantic = any(
                    has(service_text, topic)
                    for topic in specific_topics
                )

                overlap = len(
                    tokens(message) & tokens(service_text)
                )

                if semantic or overlap >= 2:
                    relevant_services.append((
                        overlap + (3 if semantic else 0),
                        service,
                    ))

            else:
                overlap = len(
                    tokens(message) & tokens(service_text)
                )

                if overlap >= 2:
                    relevant_services.append(
                        (overlap, service)
                    )

        relevant_services.sort(
            key=lambda pair: pair[0],
            reverse=True,
        )

        service_names = unique([
            str(service.get("nom"))
            for _, service in relevant_services[:2]
            if service.get("nom")
        ])

        if service_names:
            lines.append(
                "Je commencerais par "
                + " et ".join(
                    f"**{name}**"
                    for name in service_names
                )
                + "."
            )

            service = relevant_services[0][1]
            mission = str(
                service.get("missions_resume") or ""
            ).strip()

            if mission:
                lines.append(mission)

        else:
            note = str(
                structure.get("note_orientation") or ""
            ).strip()

            if note:
                note = re.split(
                    r"(?i)cela ne prouve|offre de stage|"
                    r"disponibilit[eé] d'un stage",
                    note,
                )[0].strip(" .;")

                lines.append(note + ".")

        for source in item.get("sources", [])[:1]:
            if source.get("url"):
                lines.append(
                    f"Référence : "
                    f"{source.get('titre', 'source documentaire')} "
                    f"— {source['url']}"
                )

    lines.append(
        "Ces pistes sont fondées sur les missions documentées, "
        "pas sur la disponibilité d'un poste. "
        "Elles ne garantissent pas qu'une offre est ouverte "
        "ni qu'une candidature sera acceptée."
    )

    return "\n".join(lines)


def answer_explore(message: str) -> str:
    item = find_structure(message)

    if not item:
        ministry = INFORMATIONS_GENERALES.get(
            "ministere",
            {},
        )

        name = (
            ministry.get("nom")
            if isinstance(ministry, dict)
            else None
        )

        return (
            f"{name or 'Le MEF'} couvre plusieurs domaines "
            "des finances publiques. "
            "Indique une structure ou un domaine précis "
            "(informatique, impôts, trésor, budget, dette "
            "ou suivi-évaluation) pour obtenir une réponse ciblée."
        )

    expanded = expand_structure(item)

    lines = [
        f"**{item.get('nom')}**",
        str(
            item.get("mission_resume")
            or item.get("mission")
            or item.get("description")
            or "La mission détaillée n'est pas renseignée "
            "dans les informations disponibles."
        ),
    ]

    domains = item.get("domaines_intervention") or []

    if domains:
        lines.append(
            "Domaines principaux : "
            + ", ".join(str(value) for value in domains[:5])
            + "."
        )

    services = expanded.get("services_details") or []
    query_tokens = tokens(message)
    ranked_services = []

    for service in services:
        service_text = " ".join([
            str(service.get("nom", "")),
            str(service.get("missions_resume", "")),
            " ".join(service.get("mots_cles") or []),
            " ".join(
                service.get("profils_formation_pertinents") or []
            ),
            " ".join(
                service.get("competences_pertinentes") or []
            ),
        ])

        overlap = len(
            query_tokens & tokens(service_text)
        )

        if overlap:
            ranked_services.append((overlap, service))

    ranked_services.sort(
        key=lambda pair: pair[0],
        reverse=True,
    )

    chosen = (
        [item for _, item in ranked_services[:3]]
        if ranked_services
        else services[:3]
    )

    names = [
        str(item.get("nom"))
        for item in chosen
        if item.get("nom")
    ]

    if names:
        lines.append(
            "Services pertinents documentés : "
            + "; ".join(names)
            + "."
        )

    lines.append(
        "Statut de la source : "
        + str(
            item.get("source_status")
            or item.get("status")
            or "non précisé"
        )
        + "."
    )

    if is_demo(item):
        lines.append(
            "Attention : cette fiche est marquée "
            "comme non vérifiée ou donnée de démonstration."
        )

    lines.extend(source_lines(item, 2))

    return "\n\n".join(lines)


def procedure_by_id(*ids: str) -> Optional[dict[str, Any]]:
    for wanted in ids:
        for item in PROCEDURES:
            if item.get("id") == wanted:
                return item

    return None


def answer_procedure(message: str) -> str:
    text = normalize_text(message)

    estage = procedure_by_id(
        "proc-estage-real",
        "proc-estage-generique",
    )

    status = normalize_text(
        (estage or {}).get("source_status", "")
    )

    unverified = any(
        value in status
        for value in (
            "requires direct confirmation",
            "requires_direct_confirmation",
            "not found",
            "non confirme",
            "demo data",
        )
    )

    if (
        estage
        and not unverified
        and (
            estage.get("etapes")
            or estage.get("documents_requis")
            or estage.get("conditions_eligibilite")
        )
    ):
        lines = [
            str(estage.get("titre", "Procédure eStage"))
        ]

        lines.extend(
            f"{number}. {step}"
            for number, step in enumerate(
                estage.get("etapes") or [],
                1,
            )
        )

        documents = estage.get("documents_requis") or []

        if documents:
            lines.append(
                "Documents indiqués : "
                + ", ".join(str(value) for value in documents)
                + "."
            )

        lines.append(
            "Vérifie les instructions actuelles sur la plateforme "
            "officielle avant d'envoyer ta demande."
        )

        return "\n".join(lines)

    # Les exigences eStage ne sont pas confirmées.
    # Les conseils pratiques doivent rester séparés des faits officiels.

    asks_documents = any(has(text, term) for term in (
        "document",
        "documents",
        "piece",
        "pieces",
        "fournir",
        "joindre",
        "attestation",
        "pdf",
        "preparer",
    ))

    asks_steps = any(has(text, term) for term in (
        "etape",
        "etapes",
        "comment deposer",
        "comment postuler",
        "comment faire une demande",
        "plateforme",
        "formulaire",
        "procedure",
        "suivre",
    ))

    asks_estage = any(has(text, term) for term in (
        "estage",
        "plateforme",
        "demande de stage",
        "stage au mef",
        "candidature",
    ))

    if asks_estage and (asks_documents or asks_steps):
        parts = []

        if asks_documents:
            parts.append(
                "**Documents à préparer "
                "(liste indicative, non officielle)**\n"
                "Tu peux préparer un CV à jour, une attestation "
                "de scolarité ou d'inscription, une pièce d'identité, "
                "et tes relevés de notes ou diplômes si tu en disposes. "
                "Prépare une lettre de motivation uniquement si elle "
                "est demandée par l'avis ou le formulaire. "
                "**Cette liste ne confirme pas les pièces obligatoires "
                "d'eStage** : n'envoie que les documents explicitement "
                "demandés sur la plateforme ou dans un avis officiel."
            )

        if asks_steps:
            parts.append(
                "**Étapes prudentes à suivre**\n"
                "1. Ouvre la plateforme eStage MEF : "
                "https://estage-mef-front.vercel.app/\n"
                "2. Lis les consignes et l'avis correspondant "
                "à ta demande.\n"
                "3. Renseigne les champs réellement affichés "
                "et joins uniquement les pièces requises.\n"
                "4. Relis les informations avant de valider l'envoi.\n"
                "5. Conserve la confirmation ou la référence du "
                "dossier si la plateforme en affiche une.\n\n"
                "Le formulaire et ses étapes exactes n'ont pas été "
                "confirmés dans les sources de ce prototype ; "
                "suis en priorité les instructions affichées "
                "sur la plateforme."
            )

        parts.append(
            "**Statut de l'information : à confirmer directement.** "
            "Le prototype n'est pas connecté à l'API eStage et ne peut "
            "pas garantir la liste des pièces, les étapes réelles "
            "ou la réception d'une candidature."
        )

        return "\n\n".join(parts)

    if any(has(text, term) for term in (
        "documents",
        "document",
        "piece",
        "pieces",
        "fournir",
        "joindre",
        "attestation",
        "pdf",
    )):
        return (
            "La liste des pièces obligatoires propres à eStage "
            "n'est pas confirmée dans cette base. "
            "Suis la liste affichée dans le formulaire ou dans "
            "l'avis officiel correspondant. "
            "Ne considère pas une procédure observée pour l'ASIN "
            "comme une preuve des exigences eStage."
        )

    if (
        has(text, "asin")
        or has(
            text,
            "agence des systemes d information et du numerique",
        )
    ):
        asin = procedure_by_id(
            "proc-asin-observee",
            "proc-candidature-type-observee",
        )

        if asin:
            lines = [
                str(asin.get("titre", "Procédure observée pour l'ASIN"))
            ]

            lines.extend(
                f"{number}. {step}"
                for number, step in enumerate(
                    asin.get("etapes") or [],
                    1,
                )
            )

            documents = (
                asin.get("documents_requis")
                or asin.get("documents_observes")
                or []
            )

            if documents:
                lines.append(
                    "Pièces citées par ces avis ASIN : "
                    + ", ".join(str(value) for value in documents)
                    + "."
                )

            lines.append(
                "Cette procédure concerne les avis ASIN concernés ; "
                "elle ne doit pas être généralisée à eStage."
            )

            lines.extend(source_lines(asin, 2))

            return "\n".join(lines)

    return str(
        (estage or {}).get("message_si_information_absente")
        or (estage or {}).get("reponse_de_secours")
        or (
            "Les étapes exactes de candidature eStage ne sont pas "
            "confirmées. Consulte les consignes affichées directement "
            "sur la plateforme officielle."
        )
    )


def answer_dossier(message: str) -> str:
    for dossier in DOSSIERS_DEMO:
        reference = str(dossier.get("id", ""))

        if reference and has(message, reference):
            return (
                "**DÉMONSTRATION — DOSSIER FICTIF**\n\n"
                f"Référence : {reference}\n"
                f"Statut simulé : "
                f"{dossier.get('statut', 'non renseigné')}\n"
                f"Date de dépôt simulée : "
                f"{dossier.get('date_depot', 'non renseignée')}\n"
                f"Structure demandée : "
                f"{dossier.get('structure_demandee', 'non renseignée')}\n\n"
                f"{dossier.get('message', 'Ce dossier est fictif et n’est pas connecté à eStage.')}"
            )

    return (
        "Je ne peux pas consulter une candidature réelle : "
        "ce prototype n'est pas connecté à l'API eStage. "
        "Connecte-toi à la plateforme officielle pour vérifier "
        "le statut et contacte le support qui y est indiqué "
        "en cas de problème. "
        "Ne partage pas ici ton mot de passe, ton code de vérification "
        "ni tes documents personnels."
    )


def answer_offers() -> str:
    active = [
        item for item in OFFRES
        if (
            item.get("actif") is True
            and item.get("statut_verification")
            in {"ouverture_verifiee", "active_verifiee"}
        )
    ]

    if not active:
        return (
            "Le catalogue local ne contient aucune offre marquée "
            "comme active et vérifiée. Cela ne signifie pas qu'aucune "
            "offre n'existe sur eStage : ce prototype ne récupère pas "
            "automatiquement les annonces. Consulte la plateforme et "
            "l'avis officiel de la structure, en vérifiant la date "
            "limite et le lien de candidature."
        )

    lines = [
        "Voici les offres locales marquées comme actives et vérifiées :"
    ]

    for item in active[:5]:
        title = (
            item.get("intitule")
            or item.get("titre")
            or "Offre sans titre"
        )

        structure = (
            item.get("structure")
            or item.get("structure_nom")
            or "structure non précisée"
        )

        deadline = (
            item.get("date_limite")
            or "date limite non renseignée"
        )

        url = (
            item.get("lien_officiel")
            or item.get("url_officiel")
            or "lien non renseigné"
        )

        lines.append(
            f"- **{title}** — {structure} ; {deadline} ; {url}."
        )

    lines.append(
        "Confirme l'offre sur sa page officielle avant de postuler."
    )

    return "\n".join(lines)


def answer_technical(message: str) -> str:
    text = normalize_text(message)

    if any(has(text, term) for term in (
        "mot de passe",
        "connexion",
        "connecter",
        "code otp",
        "code de verification",
    )):
        return (
            "Vérifie l'identifiant et l'adresse e-mail associés "
            "au compte, puis utilise la procédure officielle "
            "de récupération si eStage la propose. "
            "Si le problème persiste, relève le message d'erreur "
            "et contacte le support indiqué sur la plateforme. "
            "Ne partage jamais ton mot de passe ni un code "
            "de vérification."
        )

    if any(has(text, term) for term in (
        "pdf",
        "fichier",
        "televerser",
        "cv",
        "piece jointe",
    )):
        return (
            "Vérifie que le fichier s'ouvre correctement et respecte "
            "le format et la taille demandés par le formulaire. "
            "Les limites exactes ne sont pas documentées dans cette "
            "base. Si le fichier est toujours refusé, note l'erreur "
            "puis contacte le support de la plateforme. "
            "Ne joins pas de document personnel à cette conversation."
        )

    return (
        "Indique la page concernée, l'action effectuée et le message "
        "d'erreur exact. Vérifie les champs obligatoires et évite "
        "de cliquer plusieurs fois sur Envoyer si la demande a "
        "peut-être déjà été transmise. "
        "Ne partage ni mot de passe, ni code OTP, ni document personnel."
    )


def answer_preparation(message: str) -> str:
    text = normalize_text(message)

    if any(has(text, term) for term in (
        "lettre",
        "motivation",
        "rediger",
        "modele",
    )):
        return (
            "Pour une lettre de motivation, utilise quatre parties :\n"
            "1. **Ton profil** : formation, niveau et demande de stage.\n"
            "2. **Ton intérêt pour la structure** : une mission vérifiée "
            "en lien avec ton sujet.\n"
            "3. **Ce que tu apportes** : deux ou trois compétences "
            "illustrées par des projets réels.\n"
            "4. **Ton objectif** : ce que tu veux apprendre et "
            "une conclusion polie.\n\n"
            "Pour une version personnalisée, indique ta formation, "
            "la structure visée, ton sujet et un ou deux projets."
        )

    if any(has(text, term) for term in (
        "cv",
        "curriculum vitae",
        "portfolio",
        "github",
    )):
        return (
            "Pour ton CV, présente ta formation, les compétences "
            "réellement maîtrisées, tes projets, tes expériences, "
            "les langues et les liens utiles. Pour chaque projet, "
            "précise le problème, ton rôle, les outils et le résultat. "
            "Distingue les projets académiques des expériences "
            "professionnelles et n'invente pas de compétences."
        )

    if any(has(text, term) for term in (
        "entretien",
        "interview",
    )):
        return (
            "Prépare une présentation de 60 à 90 secondes, deux projets "
            "concrets et des exemples de problèmes résolus. Pour chaque "
            "projet, explique ton rôle, les outils, le résultat et les "
            "limites. Consulte les missions de la structure à partir "
            "d'une source fiable. Un entretien n'est pas garanti pour "
            "chaque candidature."
        )

    return (
        "Précise si tu veux travailler ton CV, ta lettre de motivation, "
        "ton sujet de stage ou la préparation d'un éventuel entretien."
    )


def answer_general(message: str) -> str:
    item = find_exact_faq(message) or best_faq(message)

    if item:
        short_answer = str(
            item.get("reponse_courte") or ""
        ).strip()

        full_answer = str(
            item.get("reponse") or ""
        ).strip()

        # Évite les réponses courtes qui s'arrêtent en plein milieu
        # d'une phrase : utiliser alors la réponse complète.
        short_is_complete = bool(
            re.search(
                r"[.!?…][\"»')\]]?\s*$",
                short_answer,
            )
        )

        if short_answer and (
            short_is_complete or not full_answer
        ):
            answer = short_answer
        else:
            answer = (
                full_answer
                or short_answer
                or "La réponse n'est pas renseignée."
            )

        if item.get("source_status"):
            answer += (
                f"\n\nStatut de l'information : "
                f"{item['source_status']}."
            )

        lines = source_lines(item, 2)

        if lines:
            answer += "\n\n" + "\n".join(lines)

        return answer

    return (
        "Je peux t'aider à trouver une structure adaptée, comprendre "
        "les démarches documentées, explorer le MEF, examiner les "
        "offres enregistrées, préparer ta candidature ou expliquer "
        "le suivi simulé. Pose une question précise ; si une "
        "information officielle manque, je te le dirai."
    )


def answer_for_intent(
    message: str,
    intent: str,
) -> str:
    if intent == "orientation":
        return answer_orientation(message)

    if intent == "explorer":
        return answer_explore(message)

    if intent == "procedure":
        return answer_procedure(message)

    if intent == "verifier_dossier":
        return answer_dossier(message)

    if intent == "offre_stage":
        return answer_offers()

    if intent == "assistance_technique":
        return answer_technical(message)

    if intent == "preparation_candidature":
        return answer_preparation(message)

    return answer_general(message)


# ----------------------- Génération optionnelle -----------------------------

SYSTEM_PROMPT = """
Tu es un assistant qui accompagne les candidats à un stage au MEF du Bénin.
Réponds en français naturel, directement à la question, sans digression.
Limite la réponse à deux courts paragraphes ou trois puces maximum.
Ne parle pas de JSON, de base de données, de score interne ou de gabarit.
Reformule uniquement les informations factuelles fournies dans le brouillon.
N'invente aucune structure, mission, offre ouverte, pièce obligatoire, date limite, règle ou procédure.
Ne présente pas une procédure ASIN comme la procédure eStage.
Ne prétends jamais avoir consulté un dossier réel : le prototype n'est pas connecté à l'API eStage.
Si une information manque, dis-le simplement et précisément.
""".strip()


def call_openai_compatible(
    prompt: str,
    api_key: str,
    base_url: str,
    model: str,
    timeout: float,
    provider: str,
) -> Optional[str]:
    if not api_key:
        logger.info(
            "%s non configuré ; réponse locale utilisée si nécessaire.",
            provider,
        )
        return None

    try:
        import requests

        response = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}"
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT,
                    },
                    {
                        "role": "user",
                        "content": prompt,
                    },
                ],
                "temperature": 0.15,
                "max_tokens": 350,
            },
            timeout=timeout,
        )

        if (
            response.status_code in {401, 403, 408, 429}
            or response.status_code >= 500
        ):
            logger.warning(
                "%s indisponible : HTTP %s",
                provider,
                response.status_code,
            )
            return None

        response.raise_for_status()
        data = response.json()

        answer = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content")
        )

        return (
            answer.strip()
            if isinstance(answer, str) and answer.strip()
            else None
        )

    except Exception as exc:
        logger.warning(
            "%s indisponible (%s).",
            provider,
            type(exc).__name__,
        )
        return None


def call_nvidia(prompt: str) -> Optional[str]:
    return call_openai_compatible(
        prompt=prompt,
        api_key=os.environ.get("NVIDIA_API_KEY", ""),
        base_url=os.environ.get(
            "NVIDIA_BASE_URL",
            "https://integrate.api.nvidia.com/v1",
        ),
        model=os.environ.get(
            "NVIDIA_MODEL",
            "deepseek-v4.1-flash",
        ),
        timeout=float(
            os.environ.get("NVIDIA_TIMEOUT_SECONDS", "12")
        ),
        provider="NVIDIA",
    )


def call_secondary_llm(prompt: str) -> Optional[str]:
    return call_openai_compatible(
        prompt=prompt,
        api_key=os.environ.get("LLM_API_KEY", ""),
        base_url=os.environ.get(
            "LLM_BASE_URL",
            "https://api.groq.com/openai/v1",
        ),
        model=os.environ.get(
            "LLM_MODEL",
            "llama-3.1-8b-instant",
        ),
        timeout=float(
            os.environ.get("LLM_TIMEOUT_SECONDS", "15")
        ),
        provider="LLM secondaire",
    )


def build_answer(
    message: str,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    intent = detect_intent(message)

    draft = answer_for_intent(message, intent)

    profile = ProfileInput(
        formation=message,
        specialite=message,
        objectifs=message,
    )

    recommendations = (
        recommendation_data(profile, 3)
        if intent == "orientation"
        else []
    )

    # Ne jamais transmettre un statut de dossier à un modèle génératif.
    if intent == "verifier_dossier":
        return (
            draft,
            "gabarit_local",
            intent,
            recommendations,
        )

    prompt = (
        f"Question du candidat :\n{message}\n\n"
        f"Besoin identifié : {intent}\n\n"
        f"Brouillon factuel :\n{draft}\n\n"
        "Reformule en français naturel, précis et concis. "
        "Réponds uniquement à la question. "
        "Ne mentionne pas les scores internes. "
        "Ne dépasse pas trois recommandations. "
        "N'ajoute aucun fait absent du brouillon et conserve "
        "les réserves importantes."
    )

    generated = call_nvidia(prompt)

    if generated:
        return (
            generated,
            "nvidia",
            intent,
            recommendations,
        )

    generated = call_secondary_llm(prompt)

    if generated:
        return (
            generated,
            "llm_secondaire",
            intent,
            recommendations,
        )

    return (
        draft,
        "gabarit_local",
        intent,
        recommendations,
    )


def compact_recommendations(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "id": item.get("id"),
            "nom": item.get("nom"),
            "nom_court": item.get("nom_court"),
            "raisons": item.get("raisons", [])[:2],
            "services_cibles": (
                item.get("services_cibles", [])[:2]
            ),
            "source_status": item.get("source_status"),
            "sources": item.get("sources", [])[:1],
        }
        for item in items[:3]
    ]


# -------------------------------- Routes -------------------------------------

@app.get("/")
def root():
    return {
        "application": "Assistant IA eStage MEF — Prototype",
        "status": "ok",
        "documentation": "/docs",
        "connexion_estage_reelle": False,
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "structures_chargees": len(STRUCTURES),
        "services_charges": len(SERVICES),
        "faq_chargees": len(FAQ),
        "procedures_chargees": len(PROCEDURES),
        "profils_charges": len(PROFILES),
        "sources_chargees": len(SOURCES),
        "offres_chargees": len(OFFRES),
        "dossiers_demo_charges": len(DOSSIERS_DEMO),
        "nvidia_configure": bool(
            os.environ.get("NVIDIA_API_KEY")
        ),
        "llm_secondaire_configure": bool(
            os.environ.get("LLM_API_KEY")
        ),
        "connexion_estage_reelle": False,
        "contexte_general_charge": bool(
            INFORMATIONS_GENERALES
        ),
    }


@app.get("/api/contexte")
def get_context():
    return INFORMATIONS_GENERALES


@app.get("/api/structures")
def get_structures():
    return [
        expand_structure(item)
        for item in STRUCTURES
    ]


@app.get("/api/structures/{structure_id}")
def get_structure(structure_id: str):
    item = STRUCTURES_BY_ID.get(structure_id)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Structure non trouvée",
        )

    return expand_structure(item)


@app.get("/api/services")
def get_services(
    structure_id: Optional[str] = None,
):
    if structure_id:
        return [
            item
            for item in SERVICES
            if str(item.get("structure_id", "")) == structure_id
        ]

    return SERVICES


@app.get("/api/services/{service_id}")
def get_service(service_id: str):
    item = SERVICES_BY_ID.get(service_id)

    if not item:
        raise HTTPException(
            status_code=404,
            detail="Service non trouvé",
        )

    result = dict(item)

    parent = STRUCTURES_BY_ID.get(
        str(item.get("structure_id", ""))
    )

    result["structure"] = (
        parent.get("nom")
        if parent
        else None
    )

    result["sources_details"] = sources_for(item, 3)

    return result


@app.get("/api/faq")
def get_faq():
    return FAQ


@app.get("/api/procedures")
def get_procedures():
    return PROCEDURES


@app.get("/api/sources")
def get_sources():
    return SOURCES


@app.get("/api/profils")
def get_profiles():
    return PROFILES


@app.get("/api/parcours")
def get_parcours():
    return PARCOURS


@app.get("/api/intents")
def get_intents():
    return INTENTS


@app.get("/api/offres")
def get_offers():
    return {
        "offres": OFFRES,
        "nombre": len(OFFRES),
        "note": (
            "Le catalogue local n'est pas un flux officiel en temps réel."
        ),
    }


@app.get("/api/glossaire")
def get_glossary():
    return GLOSSAIRE


@app.get("/api/dossiers/demo/{reference}")
def get_demo_dossier(reference: str):
    item = next(
        (
            dossier
            for dossier in DOSSIERS_DEMO
            if normalize_text(dossier.get("id", ""))
            == normalize_text(reference)
        ),
        None,
    )

    if not item:
        raise HTTPException(
            status_code=404,
            detail=(
                "Référence de démonstration inconnue ; "
                "aucun dossier réel ne peut être consulté."
            ),
        )

    return {
        "demo_data": True,
        "avertissement": (
            "DOSSIER FICTIF — non connecté à eStage."
        ),
        "dossier": item,
    }


@app.post("/api/recommend")
def recommend(profile: ProfileInput):
    return {
        "recommandations": recommendation_data(profile, 3),
        "note": (
            "Les scores sont indicatifs et ne garantissent "
            "ni offre ni acceptation."
        ),
    }


@app.post("/api/chat")
def chat(payload: ChatMessage):
    message = payload.message.strip()

    answer, source, intent, recommendations = build_answer(
        message
    )

    return {
        "reponse": answer,
        "structures_citees": compact_recommendations(
            recommendations
        ),
        "intention_detectee": intent,
        "source_reponse": source,
        "connexion_estage_reelle": False,
    }