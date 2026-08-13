from scripts.send_cross_confirmation import build_matches


def test_cross_confirmation_only_matches_same_symbol():
    stocks = {
        "stocks": [
            {"symbol": "AAA", "score": 80, "stage": "IGNITION"},
            {"symbol": "BBB", "score": 75, "stage": "IGNITION"},
        ]
    }
    options = {
        "contracts": [
            {"symbol": "AAA", "contract_symbol": "AAA1", "score": 70, "flow_momentum_score": 80},
            {"symbol": "CCC", "contract_symbol": "CCC1", "score": 90, "flow_momentum_score": 95},
        ]
    }
    matches = build_matches(stocks, options)
    assert [row["symbol"] for row in matches] == ["AAA"]
