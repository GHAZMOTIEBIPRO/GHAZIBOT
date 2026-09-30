from scripts.send_three_path_alerts import key
def test_alert_key_is_stable():
    row={"symbol":"NVDA","contract":"NVDA251017C00150000","expiration":"2025-10-17","direction":"CALL"}
    assert key("LARGE_CAP_CONTRACT_SELECTION",row)==key("LARGE_CAP_CONTRACT_SELECTION",row)
