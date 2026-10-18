import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.scrobble.adapters import parse_jellyfin_payload, parse_plex_payload
from app.scrobble.schemas import NormalizedScrobble


TOKEN = "a" * 32


def test_normalized_schema_rejects_invalid_progress():
    with pytest.raises(ValidationError):
        NormalizedScrobble(
            user_token=TOKEN,
            media_identifier={"source": "tmdb", "value": "123"},
            media_type="movie",
            progress_percent=101,
            event_type="stop",
        )


def test_plex_nested_payload_maps_movie_and_progress():
    payload = {
        "Payload": {
            "event": "media.stop",
            "Metadata": {
                "type": "movie",
                "Guid": [{"id": "tmdb://550"}],
                "viewOffset": 90000,
                "duration": 100000,
            },
        }
    }
    result = parse_plex_payload(payload, TOKEN)
    assert result.media_identifier.source.value == "tmdb"
    assert result.media_identifier.value == "550"
    assert result.media_type.value == "movie"
    assert result.event_type.value == "stop"
    assert result.progress_percent == 90


def test_plex_supports_form_encoded_json_payload():
    payload = {
        "payload": '{"event":"media.pause","Metadata":{"type":"movie","Guid":[{"id":"imdb://tt0133093"}],"viewOffset":50,"duration":100}}'
    }
    result = parse_plex_payload(payload, TOKEN)
    assert result.media_identifier.source.value == "imdb"
    assert result.media_identifier.value == "tt0133093"
    assert result.event_type.value == "pause"
    assert result.progress_percent == 50


def test_jellyfin_maps_provider_ids_and_ticks():
    payload = {
        "NotificationType": "Playback Stop",
        "Item": {
            "Type": "Movie",
            "ProviderIds": {"Tmdb": "550"},
        },
        "PlaybackPositionTicks": 90,
        "RunTimeTicks": 100,
    }
    result = parse_jellyfin_payload(payload, TOKEN)
    assert result.media_identifier.value == "550"
    assert result.media_type.value == "movie"
    assert result.event_type.value == "stop"
    assert result.progress_percent == 90


def test_unsupported_webhook_event_is_rejected():
    with pytest.raises(HTTPException):
        parse_plex_payload(
            {"event": "media.rate", "Metadata": {"type": "movie", "Guid": ["tmdb://1"]}},
            TOKEN,
        )


def test_show_requires_season_and_episode_together():
    with pytest.raises(ValidationError):
        NormalizedScrobble(
            user_token=TOKEN,
            media_identifier={"source": "tmdb", "value": "1399"},
            media_type="show",
            season=1,
            progress_percent=50,
            event_type="pause",
        )
