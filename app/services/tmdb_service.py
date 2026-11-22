import re
import unicodedata
import logging
from typing import Optional, Dict, Any, List, Set, Tuple
import httpx
from app.db import crud

logger = logging.getLogger("tmdb_service")

class TMDBService:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_POSTER = "https://image.tmdb.org/t/p/w600_and_h900_bestv2"
    IMAGE_BASE_BACKDROP = "https://image.tmdb.org/t/p/original"

    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._aligned_shows: Set[str] = set()

    def is_show_aligned(self, show_id: str) -> bool:
        return show_id in self._aligned_shows

    def mark_show_aligned(self, show_id: str):
        self._aligned_shows.add(show_id)

    def clear_aligned_shows_cache(self):
        self._aligned_shows.clear()

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

    def normalize_title(self, text: str, show_title: Optional[str] = None) -> str:
        """Normalizuje název epizody pro spolehlivé porovnání (bez diakritiky, malá písmena, bez názvu seriálu)."""
        if not text:
            return ""
        t = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("utf-8").lower()
        if show_title:
            st = unicodedata.normalize("NFKD", str(show_title)).encode("ascii", "ignore").decode("utf-8").lower()
            st_clean = re.sub(r"[^\w\s]", " ", st).strip()
            if st_clean:
                t = re.sub(re.escape(st_clean), " ", t)
                for word in st_clean.split():
                    if len(word) >= 4:
                        t = re.sub(r"\b" + re.escape(word) + r"\b", " ", t)
        t = re.sub(r"13\s*\.?\s*komnata", " ", t)
        t = re.sub(r"komisar\s+montalbano", " ", t)
        t = re.sub(r"pan\s+tau", " ", t)
        t = re.sub(r"dobrodruzstvi\s+kriminalistiky", " ", t)
        t = re.sub(r"nemocnice\s+na\s+kraji\s+mesta", " ", t)
        t = re.sub(r"[^\w\s]", " ", t)
        return " ".join(t.split())

    def _match_tokens(self, s1: str, s2: str, show_title: Optional[str] = None) -> bool:
        """Ověří shodu kmenů slov pro českou flexi (např. 'Tereza Pergnerová' vs 'Terezy Pergnerové')."""
        n1 = self.normalize_title(s1, show_title)
        n2 = self.normalize_title(s2, show_title)
        if not n1 or not n2:
            return False
        if n1 == n2 or n1 in n2 or n2 in n1:
            return True
        t1 = set(w[:4] for w in n1.split() if len(w) >= 3)
        t2 = set(w[:4] for w in n2.split() if len(w) >= 3)
        if not t1 or not t2:
            return False
        common = t1 & t2
        return len(common) >= min(len(t1), len(t2)) and len(common) >= 1

    async def get_tv_episodes(self, tmdb_id: str) -> List[Dict[str, Any]]:
        api_key = self.get_api_key()
        if not api_key or not tmdb_id:
            return []

        cache_key = f"tmdb_tv_episodes_{tmdb_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        episodes: List[Dict[str, Any]] = []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(f"{self.BASE_URL}/tv/{tmdb_id}", params={"api_key": api_key, "language": "cs-CZ"})
                if r.status_code != 200:
                    return []
                show_data = r.json()
                seasons = show_data.get("seasons", [])
                for s in seasons:
                    s_num = s.get("season_number")
                    if s_num == 0 and len(seasons) > 1:
                        continue
                    s_r = await client.get(
                        f"{self.BASE_URL}/tv/{tmdb_id}/season/{s_num}",
                        params={"api_key": api_key, "language": "cs-CZ"}
                    )
                    if s_r.status_code == 200:
                        s_data = s_r.json()
                        for ep in s_data.get("episodes", []):
                            episodes.append({
                                "season": s_num,
                                "episode": ep.get("episode_number"),
                                "name": ep.get("name") or "",
                                "norm_name": self.normalize_title(ep.get("name") or ""),
                                "air_date": ep.get("air_date") or "",
                                "overview": ep.get("overview") or "",
                                "still_path": ep.get("still_path") or ""
                            })
            self._cache[cache_key] = episodes
            return episodes
        except Exception as e:
            logger.warning(f"Error fetching TMDb episodes for tv {tmdb_id}: {e}")
            return []

    async def align_show_episodes(self, show_id: str, tmdb_id: Optional[str] = None) -> Dict[str, Any]:
        """Přeindexuje epizody seriálu podle TMDb sérií a čísel dílů."""
        show = crud.get_show_by_id(show_id)
        if not show:
            return {"status": "error", "message": f"Show {show_id} not found", "matched": 0}

        tid = tmdb_id or show.get("tmdb_id")
        if not tid:
            enrich = await self.enrich_show_metadata(show)
            if enrich:
                tid = enrich.get("tmdb_id")

        if not tid:
            return {"status": "no_tmdb", "message": f"No TMDb ID found for {show.get('title')}", "matched": 0}

        # Uložíme zjištěné TMDb ID přímo k záznamu pořadu, pokud dosud chybělo
        if tid and show.get("tmdb_id") != tid:
            crud.update_show_tmdb(show_id=show_id, tmdb_id=tid)

        self.mark_show_aligned(show_id)

        tmdb_eps = await self.get_tv_episodes(tid)
        if not tmdb_eps:
            return {"status": "no_tmdb_episodes", "message": f"No episodes on TMDb for {tid}", "matched": 0}

        tmdb_seasons = sorted(list(set(e["season"] for e in tmdb_eps)))
        if len(tmdb_seasons) <= 1:
            return {"status": "single_season_tmdb", "matched": 0}

        local_eps = crud.get_episodes_by_show(show_id)
        if not local_eps:
            return {"status": "no_local_episodes", "matched": 0}

        matched_count = 0
        used_tmdb: Set[Tuple[int, int]] = set()
        stitle = show.get("title", "")

        for ep in local_eps:
            ep_title = ep.get("title", "")
            norm_title = self.normalize_title(ep_title, stitle)
            best_match = None

            # a) Přesná shoda normalizovaného názvu
            for tm in tmdb_eps:
                key = (tm["season"], tm["episode"])
                if key in used_tmdb:
                    continue
                if tm["norm_name"] and tm["norm_name"] == norm_title:
                    best_match = tm
                    break

            # b) Token / stem match
            if not best_match:
                for tm in tmdb_eps:
                    key = (tm["season"], tm["episode"])
                    if key in used_tmdb:
                        continue
                    if self._match_tokens(ep_title, tm["name"], stitle):
                        best_match = tm
                        break

            if best_match:
                key = (best_match["season"], best_match["episode"])
                used_tmdb.add(key)
                crud.update_episode_season_and_number(
                    ep["id"],
                    season=best_match["season"],
                    episode_num=best_match["episode"]
                )
                matched_count += 1

        # Fallback: Pokud se nespárovalo dostatečně dílů podle názvu, ale počty sedí
        if matched_count < (len(local_eps) // 2) and abs(len(local_eps) - len(tmdb_eps)) <= 2:
            local_sorted = sorted(local_eps, key=lambda x: (x.get("episode_num", 0), x.get("id", "")))
            for idx, ep in enumerate(local_sorted):
                if idx < len(tmdb_eps):
                    tm = tmdb_eps[idx]
                    crud.update_episode_season_and_number(
                        ep["id"],
                        season=tm["season"],
                        episode_num=tm["episode"]
                    )
                    matched_count += 1

        logger.info(f"Aligned show '{show.get('title')}' ({show_id}) with TMDb {tid}: {matched_count}/{len(local_eps)} episodes mapped across {len(tmdb_seasons)} seasons.")
        return {
            "status": "ok",
            "show_id": show_id,
            "tmdb_id": tid,
            "matched": matched_count,
            "total": len(local_eps),
            "seasons": tmdb_seasons
        }

tmdb_service = TMDBService()
