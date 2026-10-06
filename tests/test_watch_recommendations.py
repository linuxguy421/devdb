from types import SimpleNamespace

from app.services.watch_recommendations import _matches_length, _score_candidate


def media(**kwargs):
    defaults = dict(
        media_type="movie",
        runtime=120,
        total_episodes=None,
        genres=None,
        vote_average=None,
        title="Candidate",
        tmdb_id=1,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def entry(m, rating=None):
    return SimpleNamespace(media_item=m, rating=rating)


def test_length_filters_movies_by_runtime():
    assert _matches_length(media(runtime=90), "short")
    assert not _matches_length(media(runtime=90), "normal")
    assert _matches_length(media(runtime=120), "normal")
    assert _matches_length(media(runtime=170), "long")


def test_unknown_runtime_does_not_match_length_filter():
    assert not _matches_length(media(runtime=None), "short")
    assert _matches_length(media(runtime=None), "any")


def test_comfort_prefers_genres_the_user_rates_highly():
    watched = [
        entry(media(genres="Horror, Thriller"), 9),
        entry(media(genres="Horror"), 8),
        entry(media(genres="Drama"), 5),
    ]
    pick = _score_candidate(
        entry(media(genres="Horror", title="Horror Pick")),
        watched,
        set(),
        "comfort",
    )
    assert pick.score > 0
    assert any("Horror" in reason for reason in pick.reasons)


def test_new_rewards_unexplored_genre():
    watched = [
        entry(media(genres="Comedy"), 7),
        entry(media(genres="Comedy"), 8),
    ]
    pick = _score_candidate(
        entry(media(genres="Horror", title="New Pick")),
        watched,
        set(),
        "new",
    )
    assert pick.score >= 8
    assert any("outside your usual genres" in reason for reason in pick.reasons)


def test_buddy_recommendation_gets_a_meaningful_boost():
    candidate = entry(media(tmdb_id=42, media_type="movie", title="Buddy Pick"))
    plain = _score_candidate(candidate, [], set(), "comfort")
    recommended = _score_candidate(
        candidate,
        [],
        {(42, "movie")},
        "comfort",
    )
    assert recommended.score > plain.score
    assert any("buddy recommended" in reason.lower() for reason in recommended.reasons)


def test_high_tmdb_rating_can_contribute_without_dominating():
    candidate = entry(media(vote_average=9.0, title="Highly Rated"))
    pick = _score_candidate(candidate, [], set(), "comfort")
    assert pick.score <= 4
    assert any("TMDB rating" in reason for reason in pick.reasons)
