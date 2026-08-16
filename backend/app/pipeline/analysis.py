"""
Pipeline stage: contradiction detection.

A dedicated stage (per the assignment's explicit requirement) rather than
folding disagreement detection into claim clustering. Compares claim pairs
within the same sub-question: if they are topically related (TF-IDF
similarity above a floor -- otherwise they're just unrelated, not
contradictory) AND heuristically opposite in polarity, a Contradiction is
recorded with an inferred type and the specific finding/source pair that
grounds it.

Deliberately conservative: per the assignment's explicit warning, not every
difference is treated as a contradiction. Claims mentioning different
explicit years or regions are typed as different_time_period /
different_geography instead of a direct empirical conflict.
"""
import re
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models import Claim, Contradiction, ClaimFinding, Finding
from app.vectorstore.tfidf_store import TfidfVectorStore
from app.config import get_settings

_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_GEO_TERMS = [r"u\.?s\.?\b", r"united states", r"europe", r"\beu\b", r"china", r"asia", r"germany", r"india", r"\buk\b"]


def _infer_type(text_a: str, text_b: str) -> str:
    years_a, years_b = set(_YEAR_RE.findall(text_a)), set(_YEAR_RE.findall(text_b))
    if years_a and years_b and years_a != years_b:
        return "different_time_period"

    geo_a = {m.group(0).lower() for term in _GEO_TERMS for m in re.finditer(term, text_a, re.I)}
    geo_b = {m.group(0).lower() for term in _GEO_TERMS for m in re.finditer(term, text_b, re.I)}
    if geo_a and geo_b and geo_a.isdisjoint(geo_b):
        return "different_geography"

    if "forecast" in text_a.lower() or "forecast" in text_b.lower() or "expect" in (text_a + text_b).lower():
        return "forecast_disagreement"
    return "empirical_evidence_disagreement"


def _reason_for_type(ctype: str) -> str:
    return {
        "different_time_period": "The two findings reference different time periods, which may explain the divergent outcomes rather than a genuine conflict.",
        "different_geography": "The two findings reference different regions; regulatory and market conditions vary geographically.",
        "forecast_disagreement": "At least one side is a forward-looking projection rather than a measured outcome.",
        "empirical_evidence_disagreement": "Both sides report measured/observed outcomes yet disagree; this may reflect different methodologies, sample sizes, or definitions.",
    }.get(ctype, "Unclear -- insufficient context to determine the source of disagreement.")


def _claim_polarity(db: Session, claim_id: str) -> float:
    findings = db.execute(
        select(Finding).join(ClaimFinding, ClaimFinding.finding_id == Finding.id)
        .where(ClaimFinding.claim_id == claim_id)
    ).scalars().all()
    if not findings:
        return 0.0
    return sum(f.polarity for f in findings) / len(findings)


def detect_contradictions(db: Session, job_id: str, claims: list[Claim]) -> list[Contradiction]:
    settings = get_settings()
    by_subq: dict = {}
    for c in claims:
        by_subq.setdefault(c.sub_question_id, []).append(c)

    store = TfidfVectorStore()
    created = []

    for sub_q_id, group in by_subq.items():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                sim = store.pairwise_similarity(a.statement, b.statement)
                same_category = a.category == b.category and a.category != "General"
                # Two independent signals of "these claims are actually about
                # the same thing": literal lexical overlap (sim), or agreement
                # on the enterprise category classifier. Short, differently
                # -worded sentences on the same underlying topic (e.g. one
                # AI-ROI claim phrased around "adoption", another around
                # "financial value") often share very little vocabulary, so
                # category agreement is what actually pairs them correctly --
                # sim alone is too strict a gate for single-sentence claims.
                if not same_category and sim < settings.MIN_CONTRADICTION_SIMILARITY:
                    continue
                if sim < 0.02:
                    continue  # still require *some* nonzero relatedness

                pol_a, pol_b = _claim_polarity(db, a.id), _claim_polarity(db, b.id)
                if pol_a == 0 or pol_b == 0 or (pol_a > 0) == (pol_b > 0):
                    continue  # not opposite in direction -- not a contradiction

                finding_a = db.execute(
                    select(Finding).join(ClaimFinding, ClaimFinding.finding_id == Finding.id)
                    .where(ClaimFinding.claim_id == a.id).order_by(Finding.confidence.desc())
                ).scalars().first()
                finding_b = db.execute(
                    select(Finding).join(ClaimFinding, ClaimFinding.finding_id == Finding.id)
                    .where(ClaimFinding.claim_id == b.id).order_by(Finding.confidence.desc())
                ).scalars().first()
                if not finding_a or not finding_b or finding_a.source_id == finding_b.source_id:
                    continue

                ctype = _infer_type(a.statement, b.statement)
                polarity_divergence = min(abs(pol_a - pol_b) / 2, 1.0)
                relatedness = 0.5 if same_category else 0.0
                relatedness += min(sim / 0.15, 1.0) * 0.5
                confidence = round(min(0.4 * polarity_divergence + 0.6 * relatedness, 0.95), 2)
                relation_note = "shared enterprise category" if same_category else "lexical overlap"
                contradiction = Contradiction(
                    research_job_id=job_id,
                    claim_a_id=a.id, claim_b_id=b.id,
                    finding_a_id=finding_a.id, finding_b_id=finding_b.id,
                    source_a_id=finding_a.source_id, source_b_id=finding_b.source_id,
                    contradiction_type=ctype,
                    explanation=(f"Claim \"{a.statement[:140]}\" and claim \"{b.statement[:140]}\" "
                                 f"present opposing evidence for the same research angle "
                                 f"(matched via {relation_note}, topical similarity {sim:.2f})."),
                    confidence=confidence,
                    possible_reason=_reason_for_type(ctype),
                )
                db.add(contradiction)
                created.append(contradiction)

    db.flush()
    return created
