import logging
import os
from typing import Any, Dict, List, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

try:
    from app.config import settings
except ImportError:
    settings = None

logger = logging.getLogger(__name__)


class TMDBService:
    def __init__(self, api_key: str | None = None):
        self._override_api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.image_base_url = "https://image.tmdb.org/t/p/w500"

    @property
    def api_key(self) -> str:
        if self._override_api_key:
            return self._override_api_key

        if settings:
            key = getattr(settings, "TMDB_API_KEY", None) or getattr(settings, "tmdb_api_key", None)
            if key:
                return str(key)

        return os.getenv("TMDB_API_KEY", "") or os.getenv("tmdb_api_key", "")

    async def discover_titles(
        self,
        media_type: str = "movie",
        sort_by: str = "popularity.desc",
        genre_id: Optional[int] = None,
        year_filter: Optional[str] = None,
        page: int = 1,
    ) -> Dict[str, Any]:
        """Fetch discovered titles using TMDB's discover API with decade and year range support."""
        key = self.api_key
        if not key:
            logger.warning("TMDB_API_KEY is not configured or empty.")
            return {"results": []}

        media_type = "movie" if media_type not in ["movie", "tv"] else media_type
        endpoint = f"{self.base_url}/discover/{media_type}"
        params = {
            "api_key": key,
            "sort_by": sort_by,
            "include_adult": "false",
            "language": "en-US",
            "page": page,
        }

        if genre_id:
            params["with_genres"] = str(genre_id)

        # Handle Decade vs Specific Year filtering
        if year_filter:
            if year_filter.startswith("decade_"):
                decade_raw = year_filter.replace("decade_", "").replace("s", "")
                if decade_raw.isdigit():
                    start_year = int(decade_raw)
                    end_year = start_year + 9
                    start_date = f"{start_year}-01-01"
                    end_date = f"{end_year}-12-31"

                    if media_type == "movie":
                        params["primary_release_date.gte"] = start_date
                        params["primary_release_date.lte"] = end_date
                    else:
                        params["first_air_date.gte"] = start_date
                        params["first_air_date.lte"] = end_date
            elif year_filter.isdigit():
                if media_type == "movie":
                    params["primary_release_year"] = year_filter
                else:
                    params["first_air_date_year"] = year_filter

        if "vote_average" in sort_by:
            params["vote_count.gte"] = 200

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(endpoint, params=params, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    for item in results:
                        item["media_type"] = media_type
                    return {"results": results}
                logger.error(f"TMDB Discover API returned HTTP {response.status_code}: {response.text}")
            except httpx.HTTPError as e:
                logger.error(f"TMDB Discover API connection error: {e}")

        return {"results": []}

    async def get_details(self, tmdb_id: int, media_type: str = "movie") -> Dict[str, Any]:
        key = self.api_key
        if not key:
            logger.warning("TMDB_API_KEY is not configured or empty.")
            return {
                "id": tmdb_id,
                "title": f"Title #{tmdb_id}",
                "name": f"Title #{tmdb_id}",
                "poster_path": None,
            }

        media_type = "movie" if media_type not in ["movie", "tv"] else media_type
        endpoint = f"{self.base_url}/{media_type}/{tmdb_id}"
        params = {"api_key": key, "append_to_response": "credits"}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(endpoint, params=params, timeout=10.0)
                if response.status_code == 200:
                    return response.json()
                logger.error(f"TMDB API returned HTTP {response.status_code}: {response.text}")
            except httpx.HTTPError as e:
                logger.error(f"TMDB get_details connection error: {e}")

        return {
            "id": tmdb_id,
            "title": f"Title #{tmdb_id}",
            "name": f"Title #{tmdb_id}",
            "poster_path": None,
        }

    async def get_formatted_details(self, tmdb_id: int, media_type: str = "movie") -> Dict[str, Any]:
        raw_data = await self.get_details(tmdb_id, media_type)

        crew = raw_data.get("credits", {}).get("crew", [])
        directors = [c["name"] for c in crew if c.get("job") == "Director"]
        if not directors and "created_by" in raw_data:
            directors = [creator.get("name") for creator in raw_data.get("created_by", [])]
        director_str = ", ".join(directors) if directors else "N/A"

        cast = raw_data.get("credits", {}).get("cast", [])
        actor_str = ", ".join([c["name"] for c in cast[:3]]) if cast else "N/A"

        vote_avg = raw_data.get("vote_average")
        rating_str = f"{round(vote_avg, 1)}" if vote_avg is not None else "N/A"

        release_date = raw_data.get("release_date") or raw_data.get("first_air_date") or ""
        release_year = release_date[:4] if release_date else ""

        return {
            "title": raw_data.get("title") or raw_data.get("name") or f"Title #{tmdb_id}",
            "director": director_str,
            "actors": actor_str,
            "imdb_rating": rating_str,
            "poster_path": raw_data.get("poster_path"),
            "overview": raw_data.get("overview", "No description available."),
            "year": release_year,
        }

    async def search_multi(self, query: str) -> Dict[str, Any]:
        if not query:
            return {"results": []}

        key = self.api_key
        if not key:
            logger.warning("TMDB_API_KEY is not configured or empty.")
            return {"results": []}

        endpoint = f"{self.base_url}/search/multi"
        params = {
            "api_key": key,
            "query": query,
            "include_adult": "false",
            "language": "en-US",
            "page": 1,
        }

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(
                    endpoint,
                    params=params,
                    headers={"accept": "application/json"},
                    timeout=10.0,
                )
                if response.status_code == 200:
                    return response.json()
                logger.error(f"TMDB API returned HTTP {response.status_code}: {response.text}")
            except httpx.HTTPError as e:
                logger.error(f"TMDB API connection error: {e}")

        return {"results": []}


tmdb_service = TMDBService()
