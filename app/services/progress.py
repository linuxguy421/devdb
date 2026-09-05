from datetime import date, datetime, timezone
from typing import Dict, Any, Optional, Tuple
from app.models import WatchEntry, MediaItem

STATUS_WANT_TO_WATCH = "want_to_watch"
STATUS_IN_PROGRESS = "in_progress"
STATUS_WATCHED = "watched"


class ProgressDomainError(Exception):
    """Raised when an invalid status transition or progress operation is attempted."""
    pass


def start_watching(entry: WatchEntry) -> WatchEntry:
    """Transitions entry to 'in_progress'. Resets TV cursors to None/None."""
    entry.status = STATUS_IN_PROGRESS
    entry.last_watched_season = None
    entry.last_watched_episode = None
    return entry


def reset_progress(entry: WatchEntry) -> WatchEntry:
    """Resets entry back to 'want_to_watch' and clears progress cursors."""
    entry.status = STATUS_WANT_TO_WATCH
    entry.last_watched_season = None
    entry.last_watched_episode = None
    return entry


def complete(entry: WatchEntry) -> WatchEntry:
    """Explicitly marks an entry as fully watched."""
    entry.status = STATUS_WATCHED
    return entry


def calculate_next_episode(
    last_season: Optional[int],
    last_episode: Optional[int],
    season_episode_counts: Dict[int, int]
) -> Optional[Tuple[int, int]]:
    """
    Determines the next (season, episode) tuple based on current cursor state and season map.
    Explicitly ignores Season 0 (specials).
    Returns None if the series is complete.
    """
    # Filter out Season 0
    valid_seasons = sorted([s for s in season_episode_counts.keys() if s > 0])
    if not valid_seasons:
        return None

    # Brand new entry (hasn't watched S01E01 yet)
    if last_season is None or last_episode is None:
        first_season = valid_seasons[0]
        return (first_season, 1) if season_episode_counts.get(first_season, 0) > 0 else None

    # Current season has remaining episodes
    current_season_episodes = season_episode_counts.get(last_season, 0)
    if last_episode < current_season_episodes:
        return (last_season, last_episode + 1)

    # Move to the next available season
    next_seasons = [s for s in valid_seasons if s > last_season]
    if next_seasons:
        next_season = next_seasons[0]
        return (next_season, 1) if season_episode_counts.get(next_season, 0) > 0 else None

    # No remaining episodes across any season -> Series Complete
    return None


def mark_next_episode_watched(
    entry: WatchEntry,
    media_item: MediaItem,
    season_episode_counts: Dict[int, int],
    next_ep_air_date: Optional[str] = None
) -> WatchEntry:
    """
    Advances TV progress cursor by 1 episode. Auto-completes entry to 'watched'
    if the completed episode was the series finale.
    """
    if media_item.media_type != "tv":
        raise ProgressDomainError("Cannot increment episode progress on a movie.")

    if entry.status != STATUS_IN_PROGRESS:
        entry.status = STATUS_IN_PROGRESS

    # Unreleased next episode check
    if next_ep_air_date:
        try:
            air_d = date.fromisoformat(next_ep_air_date)
            if air_d > datetime.now(timezone.utc).date():
                raise ProgressDomainError(f"Next episode has not aired yet (Airs {next_ep_air_date}).")
        except ValueError:
            pass

    next_target = calculate_next_episode(
        entry.last_watched_season,
        entry.last_watched_episode,
        season_episode_counts
    )

    if next_target is None:
        # Reached the end of available episodes
        entry.status = STATUS_WATCHED
        return entry

    target_season, target_episode = next_target
    entry.last_watched_season = target_season
    entry.last_watched_episode = target_episode

    # Check if this newly marked episode is the final episode of the final season
    subsequent_target = calculate_next_episode(
        entry.last_watched_season,
        entry.last_watched_episode,
        season_episode_counts
    )
    if subsequent_target is None:
        entry.status = STATUS_WATCHED

    return entry
