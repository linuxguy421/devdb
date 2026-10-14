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
        release_date="2021-01-01",
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


def test_comfort_can_follow_a_clear_movie_or_tv_preference():
    watched = [
        entry(media(media_type="movie", genres="Drama"), 8),
        entry(media(media_type="movie", genres="Comedy"), 7),
        entry(media(media_type="movie", genres="Thriller"), 9),
        entry(media(media_type="tv", genres="Drama"), 6),
    ]
    movie_pick = _score_candidate(
        entry(media(media_type="movie", genres="Drama", title="Movie Pick")),
        watched,
        set(),
        "comfort",
    )
    tv_pick = _score_candidate(
        entry(media(media_type="tv", genres="Drama", title="TV Pick")),
        watched,
        set(),
        "comfort",
    )
    assert movie_pick.score > tv_pick.score
    assert any("usual movies preference" in reason for reason in movie_pick.reasons)


def test_format_preference_is_not_used_with_tiny_history():
    watched = [
        entry(media(media_type="movie", genres="Drama"), 8),
        entry(media(media_type="movie", genres="Drama"), 7),
    ]
    movie_pick = _score_candidate(
        entry(media(media_type="movie", genres="Drama", title="Movie Pick")),
        watched,
        set(),
        "comfort",
    )
    tv_pick = _score_candidate(
        entry(media(media_type="tv", genres="Drama", title="TV Pick")),
        watched,
        set(),
        "comfort",
    )
    assert movie_pick.score == tv_pick.score



def test_watchlist_source_implements_candidate_source_contract():
    from app.services.watch_recommendations import CandidateSource, WantToWatchSource

    assert issubclass(WantToWatchSource, CandidateSource)


def test_watchlist_source_filters_missing_media_and_length():
    import asyncio

    from app.services.watch_recommendations import WantToWatchSource

    entries = [
        entry(media(runtime=90, title="Short")),
        entry(media(runtime=170, title="Long")),
        entry(None),
    ]

    class Result:
        def scalars(self):
            return self

        def all(self):
            return entries

    class FakeDB:
        async def execute(self, statement):
            return Result()

    result = asyncio.run(
        WantToWatchSource().fetch(
            FakeDB(),
            user_id=1,
            media_type="all",
            length="short",
            exclude_entry_id=None,
        )
    )
    assert len(result) == 1
    assert result[0].media.title == "Short"
    assert result[0].source == "want_to_watch"
    assert result[0].entry is entries[0]



def test_tmdb_discovery_source_normalizes_and_skips_titles_already_in_my_media(monkeypatch):
    import asyncio

    from app.services import tmdb
    from app.services.watch_recommendations import TMDBDiscoverySource

    async def fake_discover_titles(media_type="movie", sort_by="popularity.desc", **kwargs):
        if media_type == "movie":
            return {
                "results": [
                    {
                        "id": 10,
                        "title": "Already Saved",
                        "overview": "Existing",
                        "genre_ids": [18],
                        "vote_average": 8.1,
                    },
                    {
                        "id": 11,
                        "title": "New Discovery",
                        "overview": "Fresh",
                        "genre_ids": [878, 12],
                        "vote_average": 7.9,
                        "poster_path": "/poster.jpg",
                    },
                ]
            }
        return {"results": []}

    monkeypatch.setattr(tmdb.tmdb_service, "discover_titles", fake_discover_titles)

    class Result:
        def all(self):
            return [(10, "movie")]

    class FakeDB:
        async def execute(self, statement):
            return Result()

    candidates = asyncio.run(
        TMDBDiscoverySource().fetch(
            FakeDB(),
            user_id=7,
            media_type="movie",
            length="any",
            exclude_entry_id=None,
        )
    )

    assert len(candidates) == 1
    assert candidates[0].source == "tmdb_discovery"
    assert candidates[0].entry is None
    assert candidates[0].media.tmdb_id == 11
    assert candidates[0].media.title == "New Discovery"
    assert candidates[0].media.genres == "Science Fiction, Adventure"


def test_discovery_candidates_allow_unknown_runtime_when_length_is_filtered(monkeypatch):
    import asyncio

    from app.services import tmdb
    from app.services.watch_recommendations import TMDBDiscoverySource

    async def fake_discover_titles(media_type="movie", sort_by="popularity.desc", **kwargs):
        return {
            "results": [
                {
                    "id": 99,
                    "title": "Unknown Runtime",
                    "genre_ids": [35],
                    "vote_average": 7.0,
                }
            ]
        } if media_type == "movie" else {"results": []}

    monkeypatch.setattr(tmdb.tmdb_service, "discover_titles", fake_discover_titles)

    class Result:
        def all(self):
            return []

    class FakeDB:
        async def execute(self, statement):
            return Result()

    candidates = asyncio.run(
        TMDBDiscoverySource().fetch(
            FakeDB(),
            user_id=7,
            media_type="movie",
            length="short",
            exclude_entry_id=None,
        )
    )
    assert len(candidates) == 1
    assert candidates[0].media.runtime is None



def test_genre_rating_and_release_era_filters_are_applied():
    from app.services.watch_recommendations import _matches_candidate_filters

    candidate = media(
        genres="Comedy, Drama",
        vote_average=7.8,
        release_date="2018-06-12",
    )
    assert _matches_candidate_filters(candidate, "Comedy", 7.0, "decade_2010s")
    assert not _matches_candidate_filters(candidate, "Horror", 7.0, "decade_2010s")
    assert not _matches_candidate_filters(candidate, "Comedy", 8.0, "decade_2010s")
    assert not _matches_candidate_filters(candidate, "Comedy", 7.0, "decade_2020s")
    assert _matches_candidate_filters(candidate, "any", 0, "any")


def test_buddy_candidate_includes_recommender_and_note_in_reasons():
    from app.services.watch_recommendations import WatchCandidate

    candidate = WatchCandidate(
        media=media(title="Buddy Pick", vote_average=7.2),
        source="buddies",
        recommendation_names=["alex"],
        recommendation_notes=["Great twist ending"],
    )
    pick = _score_candidate(candidate, [], set(), "comfort")

    assert any("Recommended by alex" in reason for reason in pick.reasons)
    assert any("Great twist ending" in reason for reason in pick.reasons)
    assert pick.source == "buddies"


def test_tmdb_discovery_blends_popular_and_hidden_gem_pools(monkeypatch):
    import asyncio

    from app.services import tmdb
    from app.services.watch_recommendations import TMDBDiscoverySource

    calls = []

    async def fake_discover_titles(**kwargs):
        calls.append(kwargs)
        if kwargs["sort_by"] == "popularity.desc":
            return {"results": [
                {"id": 1, "title": "Popular", "genre_ids": [18], "vote_average": 7.4},
                {"id": 2, "title": "Overlap", "genre_ids": [18], "vote_average": 8.1},
            ]}
        return {"results": [
            {"id": 2, "title": "Overlap", "genre_ids": [18], "vote_average": 8.1},
            {"id": 3, "title": "Hidden Gem", "genre_ids": [18], "vote_average": 8.7},
        ]}

    class Result:
        def all(self):
            return []

    class FakeDB:
        async def execute(self, statement):
            return Result()

    monkeypatch.setattr(tmdb.tmdb_service, "discover_titles", fake_discover_titles)
    candidates = asyncio.run(
        TMDBDiscoverySource().fetch(
            FakeDB(),
            user_id=1,
            media_type="movie",
            length="any",
            exclude_entry_id=None,
        )
    )

    assert [candidate.media.title for candidate in candidates] == [
        "Popular", "Overlap", "Hidden Gem"
    ]
    assert [call["sort_by"] for call in calls] == [
        "popularity.desc", "vote_average.desc"
    ]
    assert calls[1]["min_vote_count"] == 100

