import asyncio

from app.core.logging import logger
from ddgs import DDGS


class WebSearchService:
    def __init__(self, max_results: int):
        self.max_limit = max_results

    def _sync_search(self, query: str, limit: int) -> list[dict]:
        with DDGS() as search:
            results = search.text(query, max_results=limit)
            return [
                {
                    "title": r.get("title"),
                    "url": r.get(""),
                    "snippet": r.get("snippet"),
                }
                for r in results
            ]

    def _sync_search_images(self, query: str, limit: int) -> list[dict]:
        with DDGS() as search:
            result = search.images(query, max_results=limit)
            return [
                {
                    "title": r.get("title"),
                    "image_url": r.get("image"),
                    "thumbnail": r.get("thumbnail"),
                    "source": r.get("url"),
                }
                for r in result
            ]

    async def async_search(self, query: str, limit: int | None = None) -> list[dict]:
        limit = limit or self.max_limit
        logger.info("WebSearchService: searching text query=%r limit=%d", query, limit)
        try:
            return await asyncio.to_thread(self._sync_search, query, limit)
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return [{"error": "Поиск временно недоступен", "details": str(e)}]

    async def async_search_images(self, query: str, limit: int | None = None) -> list[dict]:
        limit = limit or self.max_limit
        logger.info("WebSearchService: searching image query=%r limit=%d", query, limit)
        try:
            return await asyncio.to_thread(self._sync_search_images, query, limit)
        except Exception as e:
            logger.error("Web search failed: %s", e)
            return [{"error": "Поиск изображений временно недоступен", "details": str(e)}]