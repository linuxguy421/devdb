from fastapi import HTTPException
import httpx

from app.config import settings
from app.scrobble.schemas import IdentifierSource, MediaIdentifier, ScrobbleMediaType


async def resolve_tmdb_identifier(
    identifier: MediaIdentifier,
    media_type: ScrobbleMediaType,
) -> int:
    """Resolve TMDB/IMDb/TVDB IDs to DevDB's canonical TMDB key."""
    if identifier.source == IdentifierSource.TMDB:
        return int(identifier.value)

    if not settings.TMDB_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="TMDB_API_KEY is required to resolve IMDb/TVDB identifiers",
        )

    external_source = {
        IdentifierSource.IMDB: "imdb_id",
        IdentifierSource.TVDB: "tvdb_id",
    }[identifier.source]
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                f"https://api.themoviedb.org/3/find/{identifier.value}",
                params={
                    "api_key": settings.TMDB_API_KEY,
                    "external_source": external_source,
                },
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="TMDB identifier lookup failed") from exc

    result_key = "movie_results" if media_type == ScrobbleMediaType.MOVIE else "tv_results"
    results = data.get(result_key) or []
    if not results or not results[0].get("id"):
        raise HTTPException(
            status_code=422,
            detail=f"Unable to resolve {identifier.source.value.upper()} identifier to a TMDB title",
        )
    return int(results[0]["id"])
