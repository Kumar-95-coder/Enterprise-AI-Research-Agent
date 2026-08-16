"""
Pipeline stage: evidence extraction, classification, and claim clustering.

Splits each source's stored content into candidate evidence sentences,
scores them for "claim-like" signal (quantifiers, comparative/causal verbs),
assigns each to the best-matching sub-question and an enterprise category,
and estimates confidence / evidence strength / a signed polarity used
downstream for contradiction detection.

Then clusters findings within the same sub-question into explicit Claim
records via TF-IDF similarity -- this is the Claim -> Evidence -> Source
chain the assignment requires to be queryable and traceable.

This stage is heuristic/pattern-based (topic-agnostic patterns, not
per-topic hard-coding) rather than deep semantic understanding -- swapping
LLM_PROVIDER to a real model materially improves nuance here without
changing anything downstream. See docs/architecture.md.
"""
import re
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Source, Finding, SubQuestion, Claim, ClaimFinding
from app.vectorstore.tfidf_store import TfidfVectorStore
from app.config import get_settings

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")

_SIGNAL_WORDS = [
    "reduc", "increas", "improv", "decreas", "adopt", "deploy", "achiev", "sav",
    "cut", "drive", "enable", "accelerat", "report", "found", "show", "estimat",
    "grow", "fail", "struggl", "risk", "cost", "invest", "roi", "percent", "%",
]

_NEGATIVE_CUES = ["fail", "struggl", "lack", "few organiz", "rarely", "did not", "didn't",
                  "no measurable", "risk", "concern", "barrier", "challeng", "expensive",
                  "decreas", "cut ", "lower", "slow", "resist", "skeptic"]
_POSITIVE_CUES = ["improv", "increas", "boost", "accelerat", "gain", "success",
                  "adopt", "sav", "reduc", "efficien", "grow", "benefit", "measurable"]

# Strong negation-scope phrases: when these appear, the sentence is negative
# even if it also contains positive-vocabulary words in the same breath
# ("failed to achieve *measurable savings*"). A bag-of-cues count alone
# can't see that "measurable savings" is the object being negated rather
# than an independent positive signal -- these phrases short-circuit that.
_STRONG_NEGATION_PHRASES = [
    "fail to achieve", "failed to achieve", "failed to deliver", "failed to get",
    "struggled to", "struggled with", "unable to achieve", "did not achieve",
    "didn't achieve", "no measurable", "zero measurable", "zero return",
    "achieved zero", "without measurable",
]

_CATEGORY_KEYWORDS = {
    "Technology": ["technology", "ai ", "machine learning", "algorithm", "model", "software", "platform", "computer vision", "generative"],
    "Market": ["market", "industry", "sector", "competit"],
    "Operations": ["operation", "process", "workflow", "production", "supply chain", "maintenance"],
    "Strategy": ["strategy", "roadmap", "initiative", "priorit"],
    "Financial Impact": ["cost", "revenue", "roi", "saving", "budget", "$", "%", "spend"],
    "Customer Impact": ["customer", "client", "satisfaction", "experience"],
    "Workforce": ["worker", "employee", "job", "workforce", "talent", "skill", "labor"],
    "Risk": ["risk", "vulnerab", "threat", "failure", "exposure"],
    "Regulation": ["regulat", "compliance", "law", "policy", "standard"],
    "Security": ["security", "cyber", "breach", "privacy"],
    "Implementation": ["implement", "deploy", "rollout", "pilot", "integrat"],
    "Adoption": ["adopt", "usage", "uptake", "penetrat"],
    "ROI": ["roi", "return on investment", "payback"],
    "Forecast": ["forecast", "expect", "projected", "will grow", "by 20"],
    "Case Study": ["case study", "for example", "one manufacturer", "one company", "pilot program"],
}


def _sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if len(s.strip()) > 25]


def _is_candidate(sentence: str) -> bool:
    low = sentence.lower()
    return any(sig in low for sig in _SIGNAL_WORDS)


def _classify_category(sentence: str) -> str:
    low = sentence.lower()
    best, best_score = "General", 0
    for cat, kws in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in kws if kw in low)
        if score > best_score:
            best, best_score = cat, score
    return best


def _best_sub_question(sentence: str, sub_questions: list[SubQuestion]):
    if not sub_questions:
        return None
    low = sentence.lower()
    scored = []
    for sq in sub_questions:
        kws = re.findall(r"[a-z]{4,}", sq.text.lower())
        score = sum(1 for kw in kws if kw in low)
        scored.append((score, sq))
    scored.sort(key=lambda x: -x[0])
    return scored[0][1] if scored[0][0] > 0 else sub_questions[0]


def _polarity(sentence: str) -> float:
    low = sentence.lower()
    if any(p in low for p in _STRONG_NEGATION_PHRASES):
        return -1.0
    pos = sum(1 for c in _POSITIVE_CUES if c in low)
    neg = sum(1 for c in _NEGATIVE_CUES if c in low)
    if pos == neg == 0:
        return 0.0
    return (pos - neg) / max(pos + neg, 1)


def _confidence_and_strength(sentence: str, source_quality: float):
    has_number = bool(re.search(r"\d", sentence))
    conf = 0.4 + 0.3 * has_number + 0.3 * source_quality
    conf = min(conf, 0.97)
    if conf >= 0.75 and has_number:
        strength = "strong"
    elif conf >= 0.55:
        strength = "moderate"
    else:
        strength = "weak"
    return round(conf, 2), strength


def extract_findings_for_source(db: Session, job_id: str, source: Source, sub_questions: list[SubQuestion]) -> list[Finding]:
    findings = []
    for sentence in _sentences(source.content):
        if not _is_candidate(sentence):
            continue
        sub_q = _best_sub_question(sentence, sub_questions)
        conf, strength = _confidence_and_strength(sentence, source.quality_score or 0.5)
        f = Finding(
            research_job_id=job_id,
            sub_question_id=sub_q.id if sub_q else None,
            source_id=source.id,
            evidence_text=sentence,
            context=source.title,
            category=_classify_category(sentence),
            confidence=conf,
            evidence_strength=strength,
            polarity=_polarity(sentence),
            date_hint=source.publication_date,
        )
        db.add(f)
        findings.append(f)
    db.flush()
    return findings


def cluster_claims(db: Session, job_id: str, findings: list[Finding]) -> list[Claim]:
    """Greedy TF-IDF-similarity clustering: findings within the same
    sub-question that are semantically close become one Claim, with each
    finding recorded as supporting or contradicting that claim based on
    polarity agreement."""
    threshold = get_settings().MIN_CLAIM_CLUSTER_SIMILARITY
    store = TfidfVectorStore()

    by_subq: dict = {}
    for f in findings:
        by_subq.setdefault(f.sub_question_id, []).append(f)

    all_claims: list[Claim] = []

    for sub_q_id, group in by_subq.items():
        clusters: list[dict] = []
        for f in group:
            best_cluster, best_sim = None, 0.0
            for c in clusters:
                sim = store.pairwise_similarity(f.evidence_text, c["rep_text"])
                if sim > best_sim:
                    best_cluster, best_sim = c, sim

            if best_cluster and best_sim >= threshold:
                stance = "supporting" if (f.polarity * best_cluster["polarity"] >= 0) else "contradicting"
                db.add(ClaimFinding(claim_id=best_cluster["claim"].id, finding_id=f.id, stance=stance))
                f.claim_id = best_cluster["claim"].id
                (best_cluster["supporting"] if stance == "supporting" else best_cluster["contradicting"]).append(f)
            else:
                claim = Claim(research_job_id=job_id, sub_question_id=sub_q_id,
                               statement=f.evidence_text, category=f.category)
                db.add(claim)
                db.flush()
                db.add(ClaimFinding(claim_id=claim.id, finding_id=f.id, stance="supporting"))
                f.claim_id = claim.id
                clusters.append({"claim": claim, "rep_text": f.evidence_text, "polarity": f.polarity,
                                  "supporting": [f], "contradicting": []})
                all_claims.append(claim)

        for c in clusters:
            claim = c["claim"]
            supporting, contradicting = c["supporting"], c["contradicting"]
            claim.supporting_count = len(supporting)
            claim.contradicting_count = len(contradicting)
            claim.neutral_count = 0
            src_ids = {f.source_id for f in supporting + contradicting}
            claim.distinct_source_count = len(src_ids)
            if src_ids:
                pubs = db.execute(select(Source.publisher).where(Source.id.in_(src_ids))).scalars().all()
                claim.distinct_publisher_count = len({p for p in pubs if p})
            claim.confidence = round(sum(f.confidence for f in supporting) / max(len(supporting), 1), 2)
            if contradicting:
                claim.agreement_level = "disputed"
            elif claim.distinct_source_count >= 2:
                claim.agreement_level = "strong_agreement"
            else:
                claim.agreement_level = "single_source"
            claim.evidence_strength = supporting[0].evidence_strength if supporting else "weak"

    db.flush()
    return all_claims
