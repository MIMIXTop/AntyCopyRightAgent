import asyncio
from aiohttp import web
from app.admin.log_stream import log_broadcaster

ADMIN_HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Kira Bot — Live Logs</title>
    <style>
        body {
            background-color: #0d1117;
            color: #c9d1d9;
            font-family: 'JetBrains Mono', 'Courier New', monospace;
            margin: 0;
            padding: 20px;
            display: flex;
            flex-direction: column;
            height: 90vh;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid #30363d;
            padding-bottom: 10px;
            margin-bottom: 10px;
        }
        #status { font-size: 14px; padding: 4px 8px; border-radius: 4px; font-weight: bold; }
        .connected { background: #238636; color: white; }
        .disconnected { background: #da3633; color: white; }
        #terminal {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 15px;
            overflow-y: auto;
            flex-grow: 1;
            white-space: pre-wrap;
            font-size: 13px;
            line-height: 1.5;
        }
        .controls { display: flex; gap: 10px; align-items: center; }
        button {
            background: #21262d; border: 1px solid #30363d; color: #c9d1d9;
            padding: 5px 12px; border-radius: 6px; cursor: pointer;
        }
        button:hover { background: #30363d; }
    </style>
</head>
<body>
    <header>
        <h2>🤖 Kira Agent Dashboard</h2>
        <div class="controls">
            <label><input type="checkbox" id="autoscroll" checked> Автоскролл</label>
            <button onclick="clearLogs()">Очистить экран</button>
            <span id="status" class="disconnected">Подключение...</span>
        </div>
    </header>
    <div id="terminal"></div>

    <script>
        const terminal = document.getElementById("terminal");
        const status = document.getElementById("status");
        const autoscroll = document.getElementById("autoscroll");

        function clearLogs() { terminal.innerHTML = ""; }

        function connect() {
            const evtSource = new EventSource("/admin/logs/stream");

            evtSource.onopen = () => {
                status.textContent = "Live Online";
                status.className = "connected";
            };

            evtSource.onerror = (e) => {
                status.textContent = "Disconnected (Retrying...)";
                status.className = "disconnected";
            };

            evtSource.onmessage = (event) => {
                const line = document.createElement("div");
                line.textContent = event.data;
                terminal.appendChild(line);

                if (autoscroll.checked) {
                    terminal.scrollTop = terminal.scrollHeight;
                }
            };
        }

        connect();
    </script>
</body>
</html>
"""

def format_sse(text: str) -> bytes:
    """Безопасно форматирует даже многострочный текст (трейсбеки) в SSE."""
    clean_text = str(text).replace("\r", "")
    lines = clean_text.split("\n")
    # Каждая строчка обязана начинаться с data:
    payload = "".join(f"data: {line}\n" for line in lines)
    return f"{payload}\n".encode("utf-8")

async def admin_page(request: web.Request) -> web.Response:
    return web.Response(text=ADMIN_HTML, content_type="text/html")

async def sse_log_stream(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream; charset=utf-8",
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Access-Control-Allow-Origin": "*",
        },
    )
    await response.prepare(request)

    # 1. Сразу отправляем приветственное сообщение, чтобы плашка стала зеленой
    await response.write(format_sse("⚡ [SYSTEM] Соединение установлено. Ожидание логов..."))

    # 2. Выгружаем накопленную историю
    for old_log in list(log_broadcaster.history):
        await response.write(format_sse(old_log))

    # 3. Подписываемся на живые логи
    queue = log_broadcaster.subscribe()
    try:
        while True:
            log_line = await queue.get()
            await response.write(format_sse(log_line))
    except (asyncio.CancelledError, ConnectionResetError):
        pass
    finally:
        log_broadcaster.unsubscribe(queue)

    return response

def create_admin_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/admin", admin_page)
    app.router.add_get("/admin/logs/stream", sse_log_stream)
    return app