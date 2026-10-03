import json
from app.agent.tools import ToolRegistry
from app.handlers.web_search import WebSearchService
from app.agent.models import ToolContext, ToolResult
from app.tools.loader import load_schema
from app.core.errors import ToolArgumentsError
def register_web_search(registry: ToolRegistry, web_service: WebSearchService ):

    async def search_images(context: ToolContext, args: dict):
        query = args.get("query")
        max_results = args.get("max_results")
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentsError("search_images", "query must be a non-empty string")
        result = await web_service.async_search_images(query, max_results)
        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"images": result}, ensure_ascii=False)
        )

    async def web_search(context: ToolContext, args: dict):
        query = args.get("query")
        max_results = args.get("max_results", 3)
        if not isinstance(query, str) or not query.strip():
            raise ToolArgumentsError("web_search", "query must be a non-empty string")

        result = await web_service.async_search(query, max_results)

        return ToolResult(
            call_id=context.call_id,
            content=json.dumps({"results": result}, ensure_ascii=False)        )

    registry.register(
        "web_search",
        web_search,
        load_schema("web_search")
    )
    registry.register(
        "search_images",
        search_images,
        load_schema("search_images")
    )