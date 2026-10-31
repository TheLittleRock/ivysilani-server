import re
import logging
from typing import Optional, Dict, Any, List
import httpx
from app.db import crud

logger = logging.getLogger("tmdb_service")

class TMDBService:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_POSTER = "https://image.tmdb.org/t/p/w600_and_h900_bestv2"
    IMAGE_BASE_BACKDROP = "https://image.tmdb.org/t/p/original"

    def __init__(self):
        self._cache: Dict[str, Any] = {}

    def get_api_key(self) -> str:
        key = crud.get_setting("tmdb_api_key", "2f453df93e1dd76ca1e176029a0f9baf")
        return key.strip() if key else ""

    def _clean_title(self, title: str) -> str:
        """Odstraní doplňkové texty z názvu pro lepší vyhledání v TMDB (např. 'ČT', čísla sérií)."""
        t = re.sub(r"\s*[\(\[].*?[\)\]]", "", title)
        t = re.sub(r"\s*-\s*.*$", "", t)
        t = re.sub(r"\s+\d+\.\s*série.*$", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+[IVXLC]+\.\s*řada.*$", "", t, flags=re.IGNORECASE)
        return t.strip()

    async def search(self, title: str, year: Optional[str] = None, show_type: str = "movie") -> Optional[Dict[str, Any]]:
        api_key = self.get_api_key()
        if not api_key:
            return None

        clean = self._clean_title(title)
        cache_key = f"search_{clean}_{year}_{show_type}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                params = {
                    "api_key": api_key,
                    "query": clean,
                    "language": "cs-CZ",
                    "include_adult": "false"
                }
                if year and year.isdigit() and len(year) == 4:
                    if show_type == "movie":
                        params["primary_release_year"] = year
                    else:
                        params["first_air_date_year"] = year

                endpoint = "/search/movie" if show_type == "movie" else "/search/tv"
                r = await client.get(f"{self.BASE_URL}{endpoint}", params=params)
                
                # Pokud specifický typ nic nenašel, zkusíme multi search
                results = []
                if r.status_code == 200:
                    results = r.json().get("results", [])
                
                if not results:
                    params_multi = {"api_key": api_key, "query": clean, "language": "cs-CZ", "include_adult": "false"}
                    r_multi = await client.get(f"{self.BASE_URL}/search/multi", params=params_multi)
                    if r_multi.status_code == 200:
                        results = [item for item in r_multi.json().get("results", []) if item.get("media_type") in ["movie", "tv"]]

                if not results:
                    self._cache[cache_key] = None
                    return None

                best = results[0]
                media_type = best.get("media_type") or ("movie" if show_type == "movie" else "tv")
                tmdb_id = str(best["id"])

                # Získání IMDb ID přes external_ids
                imdb_id = None
                try:
                    ext_r = await client.get(f"{self.BASE_URL}/{media_type}/{tmdb_id}/external_ids", params={"api_key": api_key})
                    if ext_r.status_code == 200:
                        imdb_id = ext_r.json().get("imdb_id")
                except Exception as e:
                    logger.debug(f"Error fetching external IDs for {tmdb_id}: {e}")

                poster_path = best.get("poster_path")
                backdrop_path = best.get("backdrop_path")

                res = {
                    "tmdb_id": tmdb_id,
                    "imdb_id": imdb_id,
                    "title": best.get("title") or best.get("name"),
                    "original_title": best.get("original_title") or best.get("original_name"),
                    "overview": best.get("overview", ""),
                    "poster_url": f"{self.IMAGE_BASE_POSTER}{poster_path}" if poster_path else None,
                    "backdrop_url": f"{self.IMAGE_BASE_BACKDROP}{backdrop_path}" if backdrop_path else None,
                    "media_type": media_type,
                    "vote_average": best.get("vote_average", 0.0),
                    "release_date": best.get("release_date") or best.get("first_air_date", "")
                }
                self._cache[cache_key] = res
                return res

        except Exception as e:
            logger.warning(f"TMDB search failed for '{title}': {e}")
            return None

    async def get_by_imdb_id(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        api_key = self.get_api_key()
        if not api_key or not imdb_id:
            return None

        cache_key = f"imdb_{imdb_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                params = {
                    "api_key": api_key,
                    "external_source": "imdb_id",
                    "language": "cs-CZ"
                }
                r = await client.get(f"{self.BASE_URL}/find/{imdb_id}", params=params)
                if r.status_code != 200:
                    return None
                data = r.json()
                movie_results = data.get("movie_results", [])
                tv_results = data.get("tv_results", [])
                
                item = None
                media_type = "movie"
                if movie_results:
                    item = movie_results[0]
                    media_type = "movie"
                elif tv_results:
                    item = tv_results[0]
                    media_type = "tv"
                
                if not item:
                    self._cache[cache_key] = None
                    return None

                poster_path = item.get("poster_path")
                backdrop_path = item.get("backdrop_path")
                res = {
                    "tmdb_id": str(item["id"]),
                    "imdb_id": imdb_id,
                    "title": item.get("title") or item.get("name"),
                    "original_title": item.get("original_title") or item.get("original_name"),
                    "overview": item.get("overview", ""),
                    "poster_url": f"{self.IMAGE_BASE_POSTER}{poster_path}" if poster_path else None,
                    "backdrop_url": f"{self.IMAGE_BASE_BACKDROP}{backdrop_path}" if backdrop_path else None,
                    "media_type": media_type
                }
                self._cache[cache_key] = res
                return res
        except Exception as e:
            logger.warning(f"TMDB find by IMDb ID failed for {imdb_id}: {e}")
            return None

    async def enrich_show_metadata(self, show: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Vyhledá pořad na TMDB a uloží nalezené tmdb_id, imdb_id a plakáty do DB."""
        if not show:
            return None

        show_id = show["id"]
        # Pokud již má tmdb_id a imdb_id, vrátíme stávající
        if show.get("tmdb_id") and show.get("imdb_id"):
            return {
                "tmdb_id": show["tmdb_id"],
                "imdb_id": show["imdb_id"],
                "poster_url": show.get("tmdb_poster"),
                "backdrop_url": show.get("tmdb_backdrop")
            }

        tmdb_data = await self.search(
            title=show["title"],
            year=show.get("year"),
            show_type=show.get("show_type", "movie")
        )
        if tmdb_data:
            crud.update_show_tmdb(
                show_id=show_id,
                tmdb_id=tmdb_data.get("tmdb_id", ""),
                imdb_id=tmdb_data.get("imdb_id", ""),
                tmdb_poster=tmdb_data.get("poster_url", "") or "",
                tmdb_backdrop=tmdb_data.get("backdrop_url", "") or ""
            )
            return tmdb_data

        return None

tmdb_service = TMDBService()
