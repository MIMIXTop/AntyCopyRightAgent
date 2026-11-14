import json

from app.agent.image_store import ImageStore
from app.agent.models import ToolContext, ToolResult
from app.agent.tools import ToolRegistry
from app.api.telegram.service import TelegramService
from app.core.errors import ToolArgumentsError
from app.core.logging import logger
from app.tools.loader import load_schema

MAX_CAPTION_CHARS = 1024


def register_image_tools(
    registry: ToolRegistry,
    telegram: TelegramService,
    image_store: ImageStore,
):
    logger.info("Registering image tools")

    async def download_image(context: ToolContext, args: dict) -> ToolResult:
        logger.info(
            "download_image tool called: chat_id=%s arguments=%s",
            context.chat_id,
            args,
        )
        image_url = args.get("image_url")
        if not isinstance(image_url, str) or not image_url.strip():
            raise ToolArgumentsError("download_image", "image_url is required")

        image = await image_store.download(image_url, context.chat_id)
        return ToolResult(
            context.call_id,
            json.dumps(image, ensure_ascii=False),
        )

    async def send_image(context: ToolContext, args: dict) -> ToolResult:
        logger.info(
            "send_image tool called: chat_id=%s arguments=%s",
            context.chat_id,
            args,
        )
        image_id = args.get("image_id")
        if not isinstance(image_id, str) or not image_id.strip():
            raise ToolArgumentsError("send_image", "image_id is required")
        caption = args.get("caption")
        if caption is not None:
            if not isinstance(caption, str):
                raise ToolArgumentsError("send_image", "caption must be a string")
            caption = caption.strip() or None
            if caption and len(caption) > MAX_CAPTION_CHARS:
                raise ToolArgumentsError(
                    "send_image",
                    f"caption must be {MAX_CAPTION_CHARS} characters or fewer",
                )

        image = image_store.get(image_id, context.chat_id)
        await telegram.send_photo(
            chat_id=context.chat_id,
            photo=image.data,
            caption=caption,
            filename=image.filename,
            delivery=context.delivery,
        )
        return ToolResult(context.call_id, '{"status":"delivered"}')

    registry.register("download_image", download_image, load_schema("download_image"))
    registry.register("send_image", send_image, load_schema("send_image"))
