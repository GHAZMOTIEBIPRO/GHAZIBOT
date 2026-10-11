from options_radar.free_feed_validation import classify_http_response, validate_csv_feed, source_metadata


def test_access_denied():
    assert classify_http_response(403, 'text/html', 'blocked').reason == 'access_denied'


def test_html_is_not_csv():
    assert not validate_csv_feed(200, 'text/csv', '<html>blocked</html>', ('symbol',)).accepted


def test_csv_headers_and_rows():
    assert validate_csv_feed(200, 'text/csv', 'symbol,volume\nABC,2\n', ('symbol',)).accepted
    assert not validate_csv_feed(200, 'text/csv', 'other,volume\nABC,2\n', ('symbol',)).accepted


def test_no_synthetic_quote_timestamp():
    record = source_metadata(provider='occ', source_url='https://example.org', observed_at='2026-10-11T00:00:00Z')
    assert record['quote_timestamp'] is None
    assert record['execution_grade'] is False
