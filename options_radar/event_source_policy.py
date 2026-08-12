from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SourcePolicy:
    family: str
    tier: str
    rank: int
    official: bool
    primary: bool
    attention_only: bool
    independent_confirmation: bool
    note_ar: str


# Event evidence hierarchy. A screening/attention source can nominate a symbol,
# but it cannot establish the underlying catalyst by itself.
SOURCE_POLICIES: tuple[tuple[tuple[str, ...], SourcePolicy], ...] = (
    (
        ("sec edgar", "edgar", "sec.gov", "sec full-text", "sec precision"),
        SourcePolicy(
            family="sec",
            tier="A_OFFICIAL",
            rank=100,
            official=True,
            primary=True,
            attention_only=False,
            independent_confirmation=True,
            note_ar="إفصاح رسمي منشور عبر SEC/EDGAR",
        ),
    ),
    (
        ("drugs@fda", "openfda", "fda.gov", " fda", "fda "),
        SourcePolicy(
            family="fda",
            tier="A_OFFICIAL",
            rank=100,
            official=True,
            primary=True,
            attention_only=False,
            independent_confirmation=True,
            note_ar="مصدر FDA رسمي",
        ),
    ),
    (
        ("nasdaq trader", "nasdaqtrader"),
        SourcePolicy(
            family="nasdaq_trader",
            tier="A_OFFICIAL",
            rank=98,
            official=True,
            primary=True,
            attention_only=False,
            independent_confirmation=True,
            note_ar="بيانات تشغيل سوق رسمية من Nasdaq Trader",
        ),
    ),
    (
        ("clinicaltrials.gov", "clinicaltrials"),
        SourcePolicy(
            family="clinicaltrials",
            tier="B_OFFICIAL_REGISTRY",
            rank=88,
            official=True,
            primary=False,
            attention_only=False,
            independent_confirmation=True,
            note_ar="سجل حكومي رسمي للدراسة؛ تحديث السجل لا يثبت وحده نجاح النتيجة",
        ),
    ),
    (
        ("investor relations", "company ir", "issuer release", "company press release"),
        SourcePolicy(
            family="issuer",
            tier="B_ISSUER_PRIMARY",
            rank=86,
            official=False,
            primary=True,
            attention_only=False,
            independent_confirmation=True,
            note_ar="إفصاح أولي صادر من الشركة ويحتاج مطابقة الجهة الرسمية عندما يكون الحدث تنظيميًا",
        ),
    ),
    (
        ("reuters", "associated press", "dow jones", "bloomberg"),
        SourcePolicy(
            family="independent_news",
            tier="C_CONFIRMATION",
            rank=74,
            official=False,
            primary=False,
            attention_only=False,
            independent_confirmation=True,
            note_ar="تأكيد صحفي مستقل؛ ليس بديلًا عن الإفصاح الرسمي",
        ),
    ),
    (
        ("benzinga", "finnhub", "alpha vantage", "yahoo finance", "yahoo"),
        SourcePolicy(
            family="news_aggregator",
            tier="C_AGGREGATOR",
            rank=58,
            official=False,
            primary=False,
            attention_only=False,
            independent_confirmation=False,
            note_ar="مزود/مجمّع أخبار مفيد للاكتشاف السريع ولا يثبت السبب وحده",
        ),
    ),
    (
        ("finviz",),
        SourcePolicy(
            family="finviz",
            tier="D_ATTENTION",
            rank=34,
            official=False,
            primary=False,
            attention_only=True,
            independent_confirmation=False,
            note_ar="فرز واهتمام سوقي فقط؛ لا يثبت المحفز",
        ),
    ),
    (
        ("reddit",),
        SourcePolicy(
            family="reddit",
            tier="D_ATTENTION",
            rank=28,
            official=False,
            primary=False,
            attention_only=True,
            independent_confirmation=False,
            note_ar="تسارع نقاش اجتماعي فقط؛ لا يثبت صحة الخبر",
        ),
    ),
    (
        ("twitter", "x.com", " x ", "x api"),
        SourcePolicy(
            family="x",
            tier="D_ATTENTION",
            rank=28,
            official=False,
            primary=False,
            attention_only=True,
            independent_confirmation=False,
            note_ar="تسارع نقاش اجتماعي فقط؛ لا يثبت صحة الخبر",
        ),
    ),
    (
        ("stocktwits",),
        SourcePolicy(
            family="stocktwits",
            tier="D_ATTENTION",
            rank=26,
            official=False,
            primary=False,
            attention_only=True,
            independent_confirmation=False,
            note_ar="اهتمام متداولين فقط؛ لا يثبت المحفز",
        ),
    ),
)

DEFAULT_POLICY = SourcePolicy(
    family="unknown_secondary",
    tier="C_UNVERIFIED",
    rank=48,
    official=False,
    primary=False,
    attention_only=False,
    independent_confirmation=False,
    note_ar="مصدر غير مصنف؛ يحتاج تأكيد أولي/رسمي",
)

REGULATORY_DECISION_CATEGORIES = {
    "FDA_APPROVAL",
    "FDA_CRL",
    "FDA_HOLD_LIFTED",
    "FDA_BREAKTHROUGH",
    "FDA_FAST_TRACK",
    "FDA_ORPHAN_DRUG",
    "FDA_PRIORITY_REVIEW",
    "FDA_RMAT",
    "FDA_CLINICAL_HOLD",
}

# A registry record can prove that a study exists or that its registry record changed,
# but not that a claimed positive/negative clinical readout is true.
CLINICAL_OUTCOME_CATEGORIES = {"TRIAL_POSITIVE", "TRIAL_FAILED"}


def classify_source(source: Any, url: Any = "") -> SourcePolicy:
    text = f" {str(source or '').strip().lower()} {str(url or '').strip().lower()} "
    for markers, policy in SOURCE_POLICIES:
        if any(marker in text for marker in markers):
            return policy
    return DEFAULT_POLICY


def event_source_evidence(row: dict[str, Any]) -> dict[str, Any]:
    policy = classify_source(row.get("source"), row.get("url"))
    category = str(row.get("category_normalized") or row.get("category") or "").upper()

    can_establish_cause = policy.primary or policy.tier == "A_OFFICIAL"
    verification_state = "OFFICIAL_CONFIRMED" if policy.tier == "A_OFFICIAL" else "UNCONFIRMED"

    if policy.family == "clinicaltrials":
        can_establish_cause = category not in CLINICAL_OUTCOME_CATEGORIES
        verification_state = "OFFICIAL_REGISTRY_ONLY"

    if policy.family == "issuer":
        verification_state = "ISSUER_PRIMARY"
        if category in REGULATORY_DECISION_CATEGORIES:
            # The company can report a regulatory event, but the strongest state is
            # reserved for SEC/FDA confirmation.
            verification_state = "ISSUER_CLAIM_NEEDS_REGULATOR_CONFIRMATION"

    if policy.attention_only:
        can_establish_cause = False
        verification_state = "ATTENTION_ONLY"
    elif not policy.primary and not policy.official:
        can_establish_cause = False
        verification_state = "SECONDARY_CONFIRMATION_ONLY"

    return {
        "source_family": policy.family,
        "source_tier": policy.tier,
        "source_rank": policy.rank,
        "source_official": policy.official,
        "source_primary": policy.primary,
        "attention_only": policy.attention_only,
        "independent_confirmation_eligible": policy.independent_confirmation,
        "can_establish_cause": can_establish_cause,
        "verification_state": verification_state,
        "source_policy_note_ar": policy.note_ar,
    }


def cluster_evidence_summary(members: list[dict[str, Any]]) -> dict[str, Any]:
    enriched: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for member in members:
        evidence = event_source_evidence(member)
        enriched.append((member, evidence))

    families = list(dict.fromkeys(evidence["source_family"] for _, evidence in enriched))
    official_families = list(
        dict.fromkeys(
            evidence["source_family"]
            for _, evidence in enriched
            if evidence["source_tier"] == "A_OFFICIAL"
        )
    )
    issuer_families = list(
        dict.fromkeys(
            evidence["source_family"]
            for _, evidence in enriched
            if evidence["source_tier"] == "B_ISSUER_PRIMARY"
        )
    )
    attention_families = list(
        dict.fromkeys(
            evidence["source_family"]
            for _, evidence in enriched
            if evidence["attention_only"]
        )
    )
    independent_families = list(
        dict.fromkeys(
            evidence["source_family"]
            for _, evidence in enriched
            if evidence["independent_confirmation_eligible"]
            and not evidence["attention_only"]
        )
    )
    cause_families = list(
        dict.fromkeys(
            evidence["source_family"]
            for _, evidence in enriched
            if evidence["can_establish_cause"]
        )
    )

    official_confirmed = bool(official_families)
    issuer_primary = bool(issuer_families)
    primary_cause_eligible = bool(cause_families)
    attention_only = bool(enriched) and all(evidence["attention_only"] for _, evidence in enriched)

    if official_confirmed:
        state = "OFFICIAL_CONFIRMED"
    elif issuer_primary:
        state = "ISSUER_PRIMARY_AWAITING_OFFICIAL_CROSSCHECK"
    elif attention_only:
        state = "ATTENTION_ONLY"
    else:
        state = "UNCONFIRMED_SECONDARY"

    return {
        "verification_state": state,
        "official_confirmed": official_confirmed,
        "issuer_primary": issuer_primary,
        "primary_cause_eligible": primary_cause_eligible,
        "attention_only": attention_only,
        "source_families": families,
        "official_source_families": official_families,
        "issuer_source_families": issuer_families,
        "attention_source_families": attention_families,
        "cause_source_families": cause_families,
        "independent_confirmation_families": independent_families,
        "independent_confirmation_count": len(independent_families),
    }
