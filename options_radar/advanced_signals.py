from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


_DILUTION_FORMS = {"S-1", "S-1/A", "S-3", "S-3/A", "424B3", "424B5", "424B7", "EFFECT"}
_STANDARD_OCC = re.compile(
    r"^(?P<root>[A-Z]{1,6})(?P<date>\d{6})(?P<side>[CP])(?P<strike>\d{8})$"
)


@dataclass(frozen=True)
class EventEnrichment:
    score: int
    category: str
    evidence: str
    event_value: float | None = None
    confidence: float = 0.5
    purpose: str = ""


def _clean_number(value: str | None) -> float | None:
    if not value:
        return None
    raw = re.sub(r"[^0-9.\-]", "", value)
    if raw in {"", ".", "-"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _first_text(element: ET.Element, names: tuple[str, ...]) -> str:
    for node in element.iter():
        local = node.tag.rsplit("}", 1)[-1]
        if local in names and node.text:
            return node.text.strip()
    return ""


def parse_form4_transactions(raw: str) -> EventEnrichment | None:
    """Parse open-market Form 4 transactions and calculate disclosed value.

    Only transaction code P (open-market purchase) and S (open-market sale) are
    directional. Awards, option exercises, gifts and tax withholding are ignored.
    """

    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None

    purchases: list[float] = []
    sales: list[float] = []
    purchase_shares = 0.0
    sale_shares = 0.0
    owner_role = ""

    officer_title = _first_text(root, ("officerTitle",))
    if officer_title:
        owner_role = officer_title
    elif _first_text(root, ("isDirector",)).lower() == "1":
        owner_role = "Director"
    elif _first_text(root, ("isTenPercentOwner",)).lower() == "1":
        owner_role = "10% Owner"

    for transaction in root.iter():
        if transaction.tag.rsplit("}", 1)[-1] != "nonDerivativeTransaction":
            continue
        code = _first_text(transaction, ("transactionCode",)).upper()
        if code not in {"P", "S"}:
            continue
        shares = _clean_number(_first_text(transaction, ("transactionShares", "value")))
        # transactionShares contains a nested value; find it explicitly to avoid
        # accidentally picking a price or ownership amount.
        shares = None
        price = None
        for node in transaction.iter():
            local = node.tag.rsplit("}", 1)[-1]
            if local == "transactionShares":
                shares = _clean_number(_first_text(node, ("value",)))
            elif local == "transactionPricePerShare":
                price = _clean_number(_first_text(node, ("value",)))
        if shares is None or shares <= 0:
            continue
        value = shares * price if price is not None and price >= 0 else None
        if code == "P":
            purchase_shares += shares
            if value is not None:
                purchases.append(value)
        else:
            sale_shares += shares
            if value is not None:
                sales.append(value)

    purchase_value = sum(purchases)
    sale_value = sum(sales)
    if purchase_shares <= 0 and sale_shares <= 0:
        return None

    role = f"; {owner_role}" if owner_role else ""
    if purchase_value > 0 and purchase_value >= sale_value:
        score = 12
        if purchase_value >= 100_000:
            score = 16
        if purchase_value >= 500_000:
            score = 20
        if purchase_value >= 2_000_000:
            score = 23
        return EventEnrichment(
            score=score,
            category="Insider open-market purchase",
            evidence=(
                f"Form 4 code P; purchase ${purchase_value:,.0f}; "
                f"{purchase_shares:,.0f} shares{role}"
            ),
            event_value=purchase_value,
            confidence=0.95,
            purpose="open_market_purchase",
        )

    if sale_value > 0:
        score = -8
        if sale_value >= 500_000:
            score = -12
        if sale_value >= 2_000_000:
            score = -16
        return EventEnrichment(
            score=score,
            category="Insider open-market sale",
            evidence=(
                f"Form 4 code S; sale ${sale_value:,.0f}; "
                f"{sale_shares:,.0f} shares{role}"
            ),
            event_value=sale_value,
            confidence=0.9,
            purpose="open_market_sale",
        )
    return None


def classify_13d_purpose(text: str) -> EventEnrichment:
    normalized = re.sub(r"\s+", " ", text.lower())
    activist = (
        "nominate" in normalized and "board" in normalized,
        "replace" in normalized and "director" in normalized,
        "strategic alternatives" in normalized,
        "potential transaction" in normalized,
        "acquisition of control" in normalized,
        "merger" in normalized or "acquisition" in normalized or "tender offer" in normalized,
        "engage with" in normalized and "board" in normalized,
    )
    if any(activist):
        return EventEnrichment(
            score=18,
            category="Active/strategic Schedule 13D",
            evidence="Item 4 indicates board, control, transaction or strategic activity",
            confidence=0.85,
            purpose="active_or_control",
        )
    if "investment purposes" in normalized and (
        "no present intention" in normalized
        or "not acquired" in normalized and "changing or influencing control" in normalized
    ):
        return EventEnrichment(
            score=7,
            category="Passive investment Schedule 13D",
            evidence="Item 4 describes investment purpose without current control intent",
            confidence=0.75,
            purpose="passive_investment",
        )
    return EventEnrichment(
        score=11,
        category="Schedule 13D — purpose requires review",
        evidence="Beneficial owner crossed the Schedule 13D threshold; Item 4 ambiguous",
        confidence=0.55,
        purpose="unclear_13d",
    )


def _extract_currency_amounts(text: str) -> list[float]:
    multipliers = {"thousand": 1_000, "million": 1_000_000, "billion": 1_000_000_000}
    values: list[float] = []
    pattern = re.compile(
        r"\$\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(thousand|million|billion)?",
        flags=re.I,
    )
    for match in pattern.finditer(text):
        amount = float(match.group(1).replace(",", ""))
        multiplier = multipliers.get((match.group(2) or "").lower(), 1)
        values.append(amount * multiplier)
    return values


def classify_dilution(form: str, text: str) -> EventEnrichment | None:
    normalized = re.sub(r"\s+", " ", text.lower())
    if form.upper() not in _DILUTION_FORMS and not any(
        phrase in normalized
        for phrase in (
            "at-the-market offering",
            "registered direct offering",
            "public offering",
            "equity distribution agreement",
            "sales agreement prospectus",
        )
    ):
        return None

    category = "Shelf registration — potential dilution"
    score = -10
    confidence = 0.65
    if "at-the-market" in normalized or "equity distribution agreement" in normalized:
        category, score, confidence = "Active ATM offering", -24, 0.95
    elif "registered direct offering" in normalized:
        category, score, confidence = "Registered direct offering", -25, 0.95
    elif "public offering" in normalized or "underwritten offering" in normalized:
        category, score, confidence = "Public equity offering", -23, 0.9
    elif form.upper().startswith("424B"):
        category, score, confidence = "Prospectus supplement — dilution review", -18, 0.85
    elif form.upper().startswith("S-1"):
        category, score, confidence = "S-1 registration — dilution risk", -16, 0.8
    elif form.upper().startswith("S-3"):
        category, score, confidence = "S-3 shelf — potential dilution", -12, 0.75

    amounts = _extract_currency_amounts(text)
    event_value = max(amounts) if amounts else None
    evidence = f"Form {form}; {category}"
    if event_value is not None:
        evidence += f"; disclosed amount up to ${event_value:,.0f}"
        if event_value >= 100_000_000:
            score = min(score, -25)
    return EventEnrichment(
        score=score,
        category=category,
        evidence=evidence,
        event_value=event_value,
        confidence=confidence,
        purpose="dilution",
    )


def enrich_sec_event(form: str, raw_text: str) -> EventEnrichment | None:
    upper = form.upper()
    if upper == "4":
        return parse_form4_transactions(raw_text)
    if upper.startswith("SC 13D"):
        return classify_13d_purpose(raw_text)
    return classify_dilution(upper, raw_text)


def is_standard_occ_contract(contract_symbol: Any, underlying_symbol: Any) -> bool:
    contract = str(contract_symbol or "").upper().replace(" ", "")
    underlying = str(underlying_symbol or "").upper().replace("-", "")
    match = _STANDARD_OCC.fullmatch(contract)
    if not match:
        return False
    root = match.group("root")
    # Adjusted contracts frequently use a numeric suffix in the root or a root
    # that no longer equals the deliverable's current underlying symbol.
    return root == underlying and root.isalpha()
