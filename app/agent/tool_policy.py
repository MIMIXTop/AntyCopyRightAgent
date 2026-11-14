"""Tool access policy for group chats.

Groups are a public space: the agent may talk, answer questions, search the web
and share links, images or voice. Anything that touches a participant's
Classroom, Google Drive, Sheets or Forms data stays in private chats.
"""

GROUP_SAFE_TOOLS = frozenset(
    {
        # Conversation and all public-facing delivery.
        "send_message",
        "ask_choice",
        "speech",
        # Public media: images are fetched from the web, never from user data.
        "search_images",
        "download_image",
        "send_image",
        # Safe lookups.
        "web_search",
        "get_current_time",
        # Loop control.
        "finish",
    }
)
