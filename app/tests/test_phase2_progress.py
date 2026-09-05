import pytest
from app.models import WatchEntry, MediaItem
from app.services.progress import (
    start_watching,
    reset_progress,
    complete,
    calculate_next_episode,
    mark_next_episode_watched,
    ProgressDomainError,
    STATUS_IN_PROGRESS,
    STATUS_WATCHED,
    STATUS_WANT_TO_WATCH,
)


def test_start_and_reset_progress():
    entry = WatchEntry(status=STATUS_WANT_TO_WATCH, last_watched_season=None, last_watched_episode=None)

    start_watching(entry)
    assert entry.status == STATUS_IN_PROGRESS
    assert entry.last_watched_season is None
    assert entry.last_watched_episode is None

    entry.last_watched_season = 1
    entry.last_watched_episode = 4
    reset_progress(entry)
    assert entry.status == STATUS_WANT_TO_WATCH
    assert entry.last_watched_season is None
    assert entry.last_watched_episode is None


def test_next_episode_calculation_ignores_season_zero():
    # Season 0 (Specials) with 10 eps, Season 1 with 8 eps, Season 2 with 8 eps
    season_map = {0: 10, 1: 8, 2: 8}

    # Brand new -> starts at S1E1 (not Season 0)
    assert calculate_next_episode(None, None, season_map) == (1, 1)

    # Mid-season increment
    assert calculate_next_episode(1, 4, season_map) == (1, 5)

    # Season boundary rollover
    assert calculate_next_episode(1, 8, season_map) == (2, 1)

    # Series finale reached
    assert calculate_next_episode(2, 8, season_map) is None


def test_mark_next_episode_watched_and_auto_finale():
    media = MediaItem(media_type="tv", total_seasons=2, total_episodes=4)
    entry = WatchEntry(status=STATUS_IN_PROGRESS, last_watched_season=None, last_watched_episode=None)
    season_map = {1: 2, 2: 2}

    # Mark S1E1
    mark_next_episode_watched(entry, media, season_map)
    assert entry.last_watched_season == 1
    assert entry.last_watched_episode == 1
    assert entry.status == STATUS_IN_PROGRESS

    # Mark S1E2 -> rolls to S1E2
    mark_next_episode_watched(entry, media, season_map)
    assert entry.last_watched_season == 1
    assert entry.last_watched_episode == 2

    # Mark S2E1
    mark_next_episode_watched(entry, media, season_map)
    assert entry.last_watched_season == 2
    assert entry.last_watched_episode == 1

    # Mark S2E2 (Finale) -> Auto-transitions to WATCHED
    mark_next_episode_watched(entry, media, season_map)
    assert entry.last_watched_season == 2
    assert entry.last_watched_episode == 2
    assert entry.status == STATUS_WATCHED


def test_unreleased_episode_blocking():
    media = MediaItem(media_type="tv")
    entry = WatchEntry(status=STATUS_IN_PROGRESS, last_watched_season=1, last_watched_episode=1)
    season_map = {1: 3}

    with pytest.raises(ProgressDomainError):
        mark_next_episode_watched(entry, media, season_map, next_ep_air_date="2099-01-01")
