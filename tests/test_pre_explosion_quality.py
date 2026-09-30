from scripts.fast_explosion_scan_runner import rank_market

def test_early_candidate_has_earlyness_and_acceleration_fields():
    rows=[{"symbol":"EARLY","name":"Early Common Stock","lastsale":"4","marketCap":"50000000","volume":"2000000","pctchange":"6"}]
    ranked=rank_market(rows, news_events=[], structural={"EARLY":{"float_shares":2000000,"structural_score":90}})
    assert ranked
    c=ranked[0]
    assert hasattr(c,"institutional_earlyness")
    assert hasattr(c,"institutional_acceleration")
    assert c.institutional_earlyness >= 0
