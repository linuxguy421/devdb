import logging
import os
from typing import Any, Dict, List
import httpx
from dotenv import load_dotenv

# Force .env values into environment variables
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
        """Dynamically evaluate API key across settings, os.getenv, and dotenv."""
        if self._override_api_key:
            return self._override_api_key

        if settings:
            key = getattr(settings, "TMDB_API_KEY", None) or getattr(settings, "tmdb_api_key", None)
            if key:
                return str(key)

        return os.getenv("TMDB_API_KEY", "") or os.getenv("tmdb_api_key", "")

    async def get_details(self, tmdb_id: int, media_type: str = "movie") -> Dict[str, Any]:
        """Fetch title details by TMDB ID and media type including credits."""
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
        """Fetch details and format them specifically for watched cards and edit modals."""
        raw_data = await self.get_details(tmdb_id, media_type)

        # Extract director(s) for movies or creators for TV shows
        crew = raw_data.get("credits", {}).get("crew", [])
        directors = [c["name"] for c in crew if c.get("job") == "Director"]
        if not directors and "created_by" in raw_data:
            directors = [creator.get("name") for creator in raw_data.get("created_by", [])]
        director_str = ", ".join(directors) if directors else "N/A"

        # Extract top 3 cast members
        cast = raw_data.get("credits", {}).get("cast", [])
        actor_str = ", ".join([c["name"] for c in cast[:3]]) if cast else "N/A"

        # Extract rating
        vote_avg = raw_data.get("vote_average")
        rating_str = f"{round(vote_avg, 1)}" if vote_avg is not None else "N/A"

        return {
            "title": raw_data.get("title") or raw_data.get("name") or f"Title #{tmdb_id}",
            "director": director_str,
            "actors": actor_str,
            "imdb_rating": rating_str,
            "poster_path": raw_data.get("poster_path"),
            "overview": raw_data.get("overview", "No description available."),
        }

    async def get_trending(self, time_window: str = "week") -> List[Dict[str, Any]]:
        """Fetch trending movies for the dashboard shelf."""
        key = self.api_key
        if not key:
            logger.warning("TMDB_API_KEY is not configured or empty.")
            return []

        endpoint = f"{self.base_url}/trending/movie/{time_window}"
        params = {"api_key": key}

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(endpoint, params=params, timeout=10.0)
                if response.status_code == 200:
                    data = response.json()
                    results = []
                    for item in data.get("results", []):
                        poster_path = item.get("poster_path")
                        release_date = item.get("release_date") or item.get("first_air_date") or ""
                        results.append(
                            {
                                "id": item.get("id"),
                                "title": item.get("title") or item.get("name") or "Untitled",
                                "poster_url": f"{self.image_base_url}{poster_path}" if poster_path else None,
                                "media_type": item.get("media_type", "movie"),
                                "release_year": release_date[:4] if release_date else "",
                            }
                        )
                    return results
                logger.error(f"TMDB Trending API returned HTTP {response.status_code}: {response.text}")
            except httpx.HTTPError as e:
                logger.error(f"TMDB get_trending connection error: {e}")

        return []

    async def search_multi(self, query: str) -> Dict[str, Any]:
        """Search movies, TV shows, and people via TMDB multi-search."""
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

    async def search_titles(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        res = await self.search_multi(query)
        return res.get("results", [])

    async def search(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        return await self.search_titles(query, page)


# Exported instances for all router imports
tmdb_service = TMDBService()
tmdb_client = tmdb_service
