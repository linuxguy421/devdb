import time
from typing import Any, Dict, List, Optional, Tuple
import httpx

from app.config import settings


class TTLCache:
    """Lightweight thread-safe in-memory cache with expiration support."""
    def __init__(self, default_ttl: int = 3600):
        self._store: Dict[str, Tuple[float, Any]] = {}
        self.default_ttl = default_ttl

    def get(self, key: str) -> Optional[Any]:
        if key in self._store:
            expires_at, data = self._store[key]
            if time.time() < expires_at:
                return data
            del self._store[key]  # Expired
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        ttl_val = ttl if ttl is not None else self.default_ttl
        self._store[key] = (time.time() + ttl_val, value)


class TMDBService:
    def __init__(self):
        self.api_key = settings.TMDB_API_KEY
        self.base_url = "https://api.themoviedb.org/3"
        self.cache = TTLCache(default_ttl=3600)  # Default 1 hour TTL

    def _make_cache_key(self, endpoint: str, params: Dict[str, Any]) -> str:
        """Generates a stable cache key from endpoint and query parameters."""
        filtered_params = {k: v for k, v in params.items() if k != "api_key"}
        sorted_items = sorted(filtered_params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_items)
        return f"{endpoint}?{param_str}"

    async def _get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> Dict[str, Any]:
        if params is None:
            params = {}
        params["api_key"] = self.api_key

        cache_key = self._make_cache_key(endpoint, params)
        cached_res = self.cache.get(cache_key)
        if cached_res is not None:
            return cached_res

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}{endpoint}", params=params)
            if response.status_code == 200:
                data = response.json()
                self.cache.set(cache_key, data, ttl=ttl)
                return data
            return {}

    async def search_multi(self, query: str) -> Dict[str, Any]:
        # Cache search queries for 1 hour
        return await self._get("/search/multi", {"query": query}, ttl=3600)

    async def discover_titles(
        self,
        media_type: str = "movie",
        sort_by: str = "popularity.desc",
        genre_id: Optional[int] = None,
        year_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        endpoint = f"/discover/{media_type}"
        params: Dict[str, Any] = {"sort_by": sort_by}

        if genre_id:
            params["with_genres"] = genre_id

        if year_filter:
            if year_filter.startswith("decade_"):
                dec = int(year_filter.replace("decade_", "").replace("s", ""))
                date_key_gte = "primary_release_date.gte" if media_type == "movie" else "first_air_date.gte"
                date_key_lte = "primary_release_date.lte" if media_type == "movie" else "first_air_date.lte"
                params[date_key_gte] = f"{dec}-01-01"
                params[date_key_lte] = f"{dec + 9}-12-31"
            elif year_filter.isdigit():
                year_key = "primary_release_year" if media_type == "movie" else "first_air_date_year"
                params[year_key] = year_filter

        # Cache discover feeds for 1 hour
        return await self._get(endpoint, params, ttl=3600)

    async def get_trending(self, time_window: str = "week") -> List[Dict[str, Any]]:
        """Trending movies & TV shows for the homepage rail."""
        window = time_window if time_window in ("day", "week") else "week"
        # Refresh a few times a day rather than caching for the full hour like
        # discover/search, since this is meant to look current on the homepage.
        data = await self._get(f"/trending/all/{window}", ttl=3600 * 3)
        return data.get("results", [])

    async def get_formatted_details(self, tmdb_id: int, media_type: str) -> Dict[str, Any]:
        target_type = media_type if media_type in ("movie", "tv") else "movie"

        # Media details & cast rarely change, so cache raw response for 24 hours (86,400s)
        raw_data = await self._get(
            f"/{target_type}/{tmdb_id}",
            {"append_to_response": "credits,external_ids"},
            ttl=86400,
        )

        if not raw_data:
            return {}

        credits = raw_data.get("credits", {})
        crew = credits.get("crew", [])
        cast_raw = credits.get("cast", [])

        director = next((m["name"] for m in crew if m.get("job") == "Director"), None)
        created_by = [c["name"] for c in raw_data.get("created_by", [])] if "created_by" in raw_data else []

        formatted_cast = [
            {
                "name": member.get("name"),
                "character": member.get("character", ""),
                "profile_path": member.get("profile_path"),
            }
            for member in cast_raw[:12]
        ]

        external_ids = raw_data.get("external_ids", {})
        imdb_id = raw_data.get("imdb_id") or external_ids.get("imdb_id")

        runtime = raw_data.get("runtime")
        if not runtime and raw_data.get("episode_run_time"):
            runtimes = raw_data.get("episode_run_time")
            runtime = runtimes[0] if runtimes else None

        return {
            "id": raw_data.get("id"),
            "title": raw_data.get("title") or raw_data.get("name"),
            "original_title": raw_data.get("original_title") or raw_data.get("original_name"),
            "overview": raw_data.get("overview"),
            "poster_path": raw_data.get("poster_path"),
            "backdrop_path": raw_data.get("backdrop_path"),
            "release_date": raw_data.get("release_date") or raw_data.get("first_air_date"),
            "status": raw_data.get("status"),
            "tagline": raw_data.get("tagline"),
            "vote_average": raw_data.get("vote_average"),
            "vote_count": raw_data.get("vote_count"),
            "popularity": raw_data.get("popularity"),
            "runtime": runtime,
            "number_of_seasons": raw_data.get("number_of_seasons"),
            "number_of_episodes": raw_data.get("number_of_episodes"),
            "genres": raw_data.get("genres", []),
            "budget": raw_data.get("budget", 0),
            "revenue": raw_data.get("revenue", 0),
            "imdb_id": imdb_id,
            "original_language": raw_data.get("original_language"),
            "production_companies": [c.get("name") for c in raw_data.get("production_companies", [])],
            "networks": [n.get("name") for n in raw_data.get("networks", [])] if "networks" in raw_data else [],
            "cast": formatted_cast,
            "director": director,
            "created_by": created_by,
        }


tmdb_service = TMDBService()
