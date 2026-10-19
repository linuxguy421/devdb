import hashlib

from app.api_keys.service import generate_api_key
from app.scrobble.schemas import NormalizedScrobble


def test_generated_api_key_is_unique_and_stored_as_hash_material():
    raw_key, prefix, key_hash = generate_api_key()
    another_key, another_prefix, another_hash = generate_api_key()

    assert raw_key.startswith("ddb_live_")
    assert len(raw_key) >= 40
    assert prefix == raw_key[:16]
    assert key_hash == hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    assert raw_key != another_key
    assert prefix != another_prefix
    assert key_hash != another_hash


def test_normalized_scrobble_can_use_header_auth_without_body_token():
    payload = NormalizedScrobble(
        media_identifier={"source": "tmdb", "value": "550"},
        media_type="movie",
        progress_percent=20,
        event_type="start",
    )
    assert payload.user_token is None
