from __future__ import annotations

from datetime import datetime, timezone

import pytest

from scripts import build_nasdaq_listed as nl
from scripts import build_symbol_directory as sd
from tests.test_symbol_directory import SHA, csv_text

NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
HEADER = "Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares"


def listed(rows: int = 2600, extra: list[str] | None = None, footer: bool = True) -> str:
    lines = [HEADER]
    for i in range(rows):
        sym = "".join(chr(65 + (i // 26 ** k) % 26) for k in range(4))
        lines.append(f"{sym}|Company {i} Inc. - Common Stock|S|N|N|100|N|N")
    lines += extra or []
    if footer:
        lines.append("File Creation Time: 1027202608:01|||||||")
    return "\n".join(lines) + "\n"


EXTRA = [
    "GOOGL|Alphabet Inc. - Class A Common Stock|Q|N|N|100|N|N",
    "GOOG|Alphabet Inc. - Class C Capital Stock|Q|N|N|100|N|N",
    "QQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N",
    "ZZZW|Zeta Holdings Corp - Warrant|S|N|N|100|N|N",
    "ZZZT|NASDAQ TEST STOCK|G|Y|N|100|N|N",
    "DEFC|Deficient Co - Common Stock|S|N|D|100|N|N",
    "BNKR|Broke Corp - Ordinary Shares|S|N|Q|100|N|N",
]


def test_counts_keep_securities_companies_etfs_and_tests_apart():
    report = nl.build(listed(extra=EXTRA), NOW)
    c = report["counts"]
    assert c["test_issues_excluded"] == 1
    assert c["etfs"] == 1
    assert c["securities"] == 2600 + 6
    assert c["other_securities"] == 1           # the warrant; GOOG's "Class C Capital Stock" is equity
    assert c["equity_securities"] == 2600 + 4   # GOOGL, GOOG, DEFC, BNKR
    assert c["companies"] == 2600 + 3           # Alphabet counted once
    assert report["file_created_at"] == "2026-10-27T12:01:00+00:00"   # 08:01 New York (EDT) from the footer
    assert "notwithstanding Nasdaq Terms of Services" in report["source"]["notice"]


def test_share_classes_of_one_issuer_count_as_one_company():
    rows = [*EXTRA[:2], "GOOGX|Alphabet Inc. - Class B Common Stock|Q|N|N|100|N|N"]
    report = nl.build(listed(extra=rows), NOW)
    # Three Alphabet classes: three equity securities, one company.
    assert report["counts"]["equity_securities"] - report["counts"]["companies"] == 2


def test_status_flags_first_seen_only_after_tracking_starts():
    first = nl.build(listed(extra=EXTRA), NOW)
    flags = {f["symbol"]: f for f in first["status_flags"]}
    assert set(flags) == {"DEFC", "BNKR"}
    assert flags["DEFC"]["first_seen_at"] is None and flags["DEFC"]["first_seen_basis"] == "BEFORE_TRACKING"
    later = NOW.replace(day=28)
    second = nl.build(listed(extra=[*EXTRA, "NEWD|New Deficient Inc. - Common Stock|S|N|E|100|N|N"]), later, first)
    flags2 = {f["symbol"]: f for f in second["status_flags"]}
    assert flags2["NEWD"]["first_seen_at"] == later.isoformat() and flags2["NEWD"]["first_seen_basis"] == "THIS_RUN"
    assert flags2["DEFC"]["first_seen_at"] is None
    assert second["tracking_since"] == NOW.isoformat()


@pytest.mark.parametrize("text", [listed(rows=100), listed(footer=False), "Bad|Header\n"])
def test_rejects_unexpected_files(text):
    with pytest.raises(nl.FileRejected):
        nl.build(text, NOW)


def test_only_the_granted_product_is_requested():
    gates = nl._gates()
    assert gates.product_allowed("nasdaqtrader_nasdaq_listed")
    assert not gates.product_allowed("nasdaqtrader_other_listed")
    assert "otherlisted" in gates.PRODUCT_UNRESOLVED["nasdaqtrader_other_listed"]["url"]
    calls = []

    class Session:
        def get(self, url, **kw):
            calls.append(url)

            class R:
                text = listed()

                def raise_for_status(self):
                    return None
            return R()

    nl.fetch(Session())
    assert calls == ["https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"]


def test_sp500_directory_counts_companies_by_cik():
    text = csv_text(500)
    lines = text.splitlines()
    # Second share class of the first company: same CIK, new symbol.
    first = lines[1].split(",")
    lines.append(",".join(["ZZZZ", *first[1:]]))
    report = sd.build("\n".join(lines) + "\n", {"sha": SHA, "date": "x"}, NOW)
    assert report["counts"] == {"securities": 501, "companies": 500}
