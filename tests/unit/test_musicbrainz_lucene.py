from app.metadata.musicbrainz import escape_lucene


def test_escape_lucene_hostile_filename_chars() -> None:
    assert escape_lucene('AC/DC: "Live" (1991)') == 'AC\\/DC\\: \\"Live\\" \\(1991\\)'
