from jobpipe.textutil import find_quote, html_to_text, normalise_for_match, sha256_text


def test_html_to_text_handles_escaped_greenhouse_content():
    raw = ("&lt;p&gt;Pay &amp;amp; benefits&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Python&lt;/li&gt;"
           "&lt;li&gt;SQL&lt;/li&gt;&lt;/ul&gt;")
    assert html_to_text(raw, escaped=True) == "Pay & benefits\n\n- Python\n- SQL"


def test_html_to_text_breaks_and_spacing():
    assert html_to_text("<div>Line one<br>Line   two</div>") == "Line one\nLine two"


def test_normalise_for_match_flattens_case_quotes_dashes_and_spaces():
    text = "  Must hold\u00a0\u201cAustralian\u201d   citizenship \u2013 NV1 "
    assert normalise_for_match(text) == 'must hold "australian" citizenship - nv1'


def test_find_quote_maps_back_to_the_original_span():
    text = "About us\n\nYou must hold Australian\n citizenship and an NV1 clearance."
    span = find_quote(text, "must hold australian citizenship")
    assert span is not None
    start, end = span
    assert text[start:end] == "must hold Australian\n citizenship"


def test_find_quote_handles_curly_quotes_and_dashes():
    text = "We offer a \u201cflexible\u201d hybrid model \u2013 3 days in the office."
    assert find_quote(text, 'a "flexible" hybrid model - 3 days') is not None


def test_find_quote_returns_none_when_missing_or_empty():
    assert find_quote("Sydney office", "Melbourne office") is None
    assert find_quote("Sydney office", "   ") is None


def test_sha256_text():
    assert sha256_text("abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
