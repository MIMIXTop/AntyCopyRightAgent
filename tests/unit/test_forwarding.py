from aiogram.types import (
    Chat,
    Document,
    Message,
    MessageOriginChannel,
    MessageOriginChat,
    MessageOriginHiddenUser,
    MessageOriginUser,
    PhotoSize,
    User,
)

from app.api.telegram.forwarding import describe_forward, describe_reply_context

DATE = 1_700_000_000


def make_message(
    text: str | None = None,
    *,
    caption: str | None = None,
    forward_origin=None,
    reply_to: Message | None = None,
    document: Document | None = None,
    photo: list[PhotoSize] | None = None,
    from_user: User | None = None,
) -> Message:
    return Message(
        message_id=1,
        date=DATE,
        chat=Chat(id=1, type="private"),
        from_user=from_user
        or User(id=1, is_bot=False, first_name="Teacher"),
        text=text,
        caption=caption,
        forward_origin=forward_origin,
        reply_to_message=reply_to,
        document=document,
        photo=photo,
    )


def user_origin(first_name: str = "Иван", username: str | None = "ivan") -> MessageOriginUser:
    return MessageOriginUser(
        date=DATE,
        sender_user=User(
            id=42,
            is_bot=False,
            first_name=first_name,
            username=username,
        ),
    )


def test_regular_message_has_no_forward_source():
    assert describe_forward(make_message("привет")) is None


def test_forward_from_user_with_username():
    message = make_message(forward_origin=user_origin())
    assert describe_forward(message) == "от пользователя Иван (@ivan)"


def test_forward_from_user_without_username():
    message = make_message(forward_origin=user_origin(username=None))
    assert describe_forward(message) == "от пользователя Иван"


def test_forward_from_hidden_user():
    message = make_message(
        forward_origin=MessageOriginHiddenUser(
            date=DATE,
            sender_user_name="Иван",
        )
    )
    assert describe_forward(message) == "от пользователя со скрытым профилем «Иван»"


def test_forward_from_chat():
    message = make_message(
        forward_origin=MessageOriginChat(
            date=DATE,
            sender_chat=Chat(
                id=-100,
                type="supergroup",
                title="Группа",
                username="group",
            ),
        )
    )
    assert describe_forward(message) == "из чата «Группа» (@group)"


def test_forward_from_channel_with_signature():
    message = make_message(
        forward_origin=MessageOriginChannel(
            date=DATE,
            chat=Chat(
                id=-100,
                type="channel",
                title="Базы данных",
                username="db_channel",
            ),
            message_id=7,
            author_signature="Редактор",
        )
    )
    assert (
        describe_forward(message)
        == "из канала «Базы данных» (@db_channel), подпись автора: Редактор"
    )


def test_automatic_forward_is_marked():
    message = make_message(
        forward_origin=MessageOriginChannel(
            date=DATE,
            chat=Chat(id=-100, type="channel", title="Новости"),
            message_id=7,
        )
    ).model_copy(update={"is_automatic_forward": True})

    assert describe_forward(message) == "из канала «Новости» (автоматическая пересылка)"


def test_legacy_forward_fields_still_work():
    from_user = make_message().model_copy(
        update={"forward_from": User(id=42, is_bot=False, first_name="Иван")}
    )
    assert describe_forward(from_user) == "от пользователя Иван"

    from_chat = make_message().model_copy(
        update={
            "forward_from_chat": Chat(
                id=-100,
                type="channel",
                title="Канал",
                username="chan",
            )
        }
    )
    assert describe_forward(from_chat) == "из канала «Канал» (@chan)"

    hidden = make_message().model_copy(update={"forward_sender_name": "Иван"})
    assert describe_forward(hidden) == "от пользователя со скрытым профилем «Иван»"


def test_reply_to_forward_includes_source_and_quote():
    replied = make_message(
        "старый пост",
        forward_origin=MessageOriginChannel(
            date=DATE,
            chat=Chat(id=-100, type="channel", title="Канал", username="chan"),
            message_id=7,
        ),
    )
    message = make_message("что это?", reply_to=replied)

    context = describe_reply_context(message)

    assert context is not None
    assert "из канала «Канал» (@chan)" in context
    assert "Цитата:\nстарый пост\nКонец цитаты." in context


def test_reply_to_forward_uses_caption_and_media():
    replied = make_message(
        caption="подпись к фото",
        forward_origin=user_origin(),
        photo=[
            PhotoSize(
                file_id="f",
                file_unique_id="u",
                width=10,
                height=10,
            )
        ],
    )
    context = describe_reply_context(make_message("что тут?", reply_to=replied))

    assert context is not None
    assert "подпись к фото" in context


def test_reply_to_forward_without_text_mentions_the_file():
    replied = make_message(
        forward_origin=user_origin(),
        document=Document(
            file_id="f",
            file_unique_id="u",
            file_name="notes.pdf",
        ),
    )
    context = describe_reply_context(make_message("что это?", reply_to=replied))

    assert context is not None
    assert "файл notes.pdf" in context


def test_reply_to_forward_truncates_long_quotes():
    replied = make_message(
        "x" * 2500,
        forward_origin=user_origin(),
    )
    context = describe_reply_context(make_message("что это?", reply_to=replied))

    assert context is not None
    assert "…" in context
    assert "x" * 2001 not in context


def test_reply_to_a_regular_message_is_not_quoted():
    replied = make_message("обычное сообщение")
    assert describe_reply_context(make_message("ответ", reply_to=replied)) is None


def test_reply_to_automatic_channel_forward_is_quoted():
    replied = make_message(
        "пост канала",
        forward_origin=MessageOriginChannel(
            date=DATE,
            chat=Chat(id=-100, type="channel", title="Канал", username="chan"),
            message_id=7,
        ),
        from_user=User(
            id=136817688,
            is_bot=True,
            first_name="Channel",
        ),
    ).model_copy(update={"is_automatic_forward": True})
    context = describe_reply_context(make_message("вопрос", reply_to=replied))

    assert context is not None
    assert "автоматическая пересылка" in context
    assert "пост канала" in context
