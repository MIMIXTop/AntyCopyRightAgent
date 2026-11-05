import asyncio
from types import SimpleNamespace

import pytest

from app.api.telegram.media_groups import MediaGroupBuffer


def make_part(chat_id: int, group_id: str, index: int):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id),
        media_group_id=group_id,
        index=index,
    )


@pytest.mark.asyncio
async def test_media_group_buffer_processes_album_once_with_all_parts():
    batches = []

    async def process(parts):
        batches.append(parts)

    buffer = MediaGroupBuffer(process, delay=0.05)

    parts = [make_part(1, "album-1", i) for i in range(4)]
    await asyncio.gather(*(buffer.add(part) for part in parts))

    assert len(batches) == 1
    assert batches[0] == parts


@pytest.mark.asyncio
async def test_media_group_buffer_keeps_groups_separate():
    batches = []

    async def process(parts):
        batches.append(parts)

    buffer = MediaGroupBuffer(process, delay=0.05)

    album_a = [make_part(1, "album-a", i) for i in range(2)]
    album_b = [make_part(1, "album-b", i) for i in range(3)]
    await asyncio.gather(*(buffer.add(part) for part in album_a + album_b))

    assert len(batches) == 2
    by_group = {batches[0][0].media_group_id: batches[0], batches[1][0].media_group_id: batches[1]}
    assert by_group["album-a"] == album_a
    assert by_group["album-b"] == album_b


@pytest.mark.asyncio
async def test_media_group_buffer_swallows_processing_errors():
    calls = []

    async def process(parts):
        calls.append(parts)
        raise RuntimeError("boom")

    buffer = MediaGroupBuffer(process, delay=0.05)

    # Must not raise: one album should not produce four duplicated failures.
    await asyncio.gather(
        *(buffer.add(make_part(1, "album-1", i)) for i in range(4))
    )

    assert len(calls) == 1
    # Buffer is reusable for the next album.
    assert not buffer._tasks
    assert not buffer._buffers


@pytest.mark.asyncio
async def test_media_group_buffer_arrivals_within_delay_are_batched():
    batches = []

    async def process(parts):
        batches.append(parts)

    buffer = MediaGroupBuffer(process, delay=0.1)

    # Parts arrive as separate concurrent updates with a small stagger, like
    # real album delivery (each aiogram update runs in its own task).
    async def stream():
        tasks = []
        for i in range(4):
            tasks.append(asyncio.create_task(buffer.add(make_part(1, "album-1", i))))
            await asyncio.sleep(0.01)
        await asyncio.gather(*tasks)

    await asyncio.wait_for(stream(), timeout=2)

    assert len(batches) == 1
    assert [part.index for part in batches[0]] == [0, 1, 2, 3]


@pytest.mark.asyncio
async def test_standalone_attachments_arriving_together_are_batched():
    batches = []

    async def process(parts):
        batches.append(parts)

    buffer = MediaGroupBuffer(process, delay=0.1)

    async def stream():
        tasks = []
        for i in range(3):
            tasks.append(asyncio.create_task(buffer.add(make_part(1, None, i))))
            await asyncio.sleep(0.01)
        await asyncio.gather(*tasks)

    await asyncio.wait_for(stream(), timeout=2)

    assert len(batches) == 1
    assert [part.index for part in batches[0]] == [0, 1, 2]
