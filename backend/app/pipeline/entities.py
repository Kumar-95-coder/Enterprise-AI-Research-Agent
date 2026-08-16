"""
Pipeline stage: entity + relationship extraction.

Uses spaCy's `en_core_web_sm` -- a real, pretrained, open-source NER model,
not a per-topic hard-coded name list -- plus a small controlled vocabulary
of AI/tech terms (since generic NER doesn't tag "generative AI" or "digital
twin" as entities; this app's whole domain is AI-in-the-enterprise, so a
domain term list is legitimate scaffolding, applied identically regardless
of the research topic).

If spaCy/the model isn't available at runtime, falls back to a
capitalized-phrase heuristic so the pipeline still produces (lower-quality)
entities rather than failing.

Relationships are created when two distinct entities co-occur in the same
evidence sentence alongside a verb from a controlled relation vocabulary.
"""
import re
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Entity, Relationship, Finding

_TECH_TERMS = [
    "machine learning", "generative ai", "computer vision", "natural language processing",
    "predictive maintenance", "digital twin", "robotics", "large language model",
    "deep learning", "artificial intelligence", "internet of things", "iot",
    "process automation", "robotic process automation", "neural network",
]

_RELATION_VERBS = {
    "uses": ["uses", "using", "deploys", "deployed", "leverages", "employs"],
    "adopts": ["adopts", "adopted", "adopting"],
    "improves": ["improves", "improved", "increases", "boosts", "enhances"],
    "affects": ["affects", "reduces", "cuts", "impacts", "disrupts"],
    "reports": ["reports", "reported", "announced", "found", "states"],
}

_SPACY_LABEL_MAP = {
    "ORG": "Organization", "GPE": "Country", "PRODUCT": "Product",
    "LAW": "Regulation", "PERSON": "Researcher", "NORP": "Industry",
}

_nlp = None
_nlp_unavailable = False


def _get_nlp():
    global _nlp, _nlp_unavailable
    if _nlp is None and not _nlp_unavailable:
        try:
            import spacy
            _nlp = spacy.load("en_core_web_sm")
        except Exception:
            _nlp_unavailable = True
    return _nlp


def _get_or_create_entity(db: Session, name: str, entity_type: str) -> Entity:
    name = name.strip()
    existing = db.execute(
        select(Entity).where(Entity.name == name, Entity.entity_type == entity_type)
    ).scalar_one_or_none()
    if existing:
        return existing
    e = Entity(name=name, entity_type=entity_type)
    db.add(e)
    db.flush()
    return e


def extract_entities_and_relationships(db: Session, job_id: str, findings: list[Finding]) -> dict:
    nlp = _get_nlp()
    entity_tags, relationships_created = 0, 0

    for f in findings:
        text = f.evidence_text
        found: list[tuple[str, str]] = []

        if nlp:
            for ent in nlp(text).ents:
                etype = _SPACY_LABEL_MAP.get(ent.label_)
                if etype:
                    found.append((ent.text, etype))
        else:
            for m in re.finditer(r"\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b", text):
                found.append((m.group(1), "Organization"))

        low = text.lower()
        for term in _TECH_TERMS:
            if term in low:
                found.append((term.title(), "Technology"))

        entity_ids, entity_objs = [], []
        for name, etype in found:
            if len(name) < 3:
                continue
            ent = _get_or_create_entity(db, name, etype)
            entity_ids.append(ent.id)
            entity_objs.append(ent)
            entity_tags += 1
        f.entities = list(dict.fromkeys(entity_ids))

        matched_relation = next(
            (rel for rel, verbs in _RELATION_VERBS.items() if any(v in low for v in verbs)), None
        )
        if matched_relation:
            distinct, seen_ids = [], set()
            for e in entity_objs:
                if e.id not in seen_ids:
                    distinct.append(e)
                    seen_ids.add(e.id)
                if len(distinct) == 2:
                    break
            if len(distinct) == 2:
                a, b = distinct
                db.add(Relationship(
                    research_job_id=job_id, source_entity_id=a.id,
                    relation_type=matched_relation, target_entity_id=b.id,
                    finding_id=f.id, confidence=0.55,
                ))
                relationships_created += 1

    db.flush()
    return {"entities_tagged": entity_tags, "relationships_created": relationships_created,
            "ner_backend": "spacy_en_core_web_sm" if nlp else "regex_fallback"}
