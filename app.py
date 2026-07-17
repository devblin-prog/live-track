"""
Grand Gaz — Backend F1 Live Timing
HTTP + WebSocket bridge sur le même port (Render free = 1 seul port).
- GET  /negotiate  → token + cookie AWS
- WS   /ws?id=TOKEN&cookie=AWS  → bridge bidirectionnel vers F1
"""

import asyncio
import os
import requests
import websockets
from hypercorn.asyncio import serve
from hypercorn.config import Config
from quart import Quart, jsonify, websocket
from quart_cors import cors

app = Quart(__name__)
app = cors(app, allow_origin=[
    "https://grand-gaz.elementfx.com",
    "https://grandgaz.wuaze.com",
    "http://localhost",
    "http://localhost:8000",
])

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
F1_HUB       = "wss://livetiming.formula1.com/signalrcore"

REQ_HEADERS = {
    "User-Agent":      "BestHTTP",
    "Accept-Encoding": "gzip, identity",
    "Connection":      "keep-alive",
}

# ── Negotiate ────────────────────────────────────────────────────────────────

@app.route("/negotiate")
async def negotiate():
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(
            None,
            lambda: requests.post(F1_NEGOTIATE, headers=REQ_HEADERS, timeout=8)
        )
        aws_cookie = r.cookies.get("AWSALBCORS") or r.cookies.get("AWSALB") or ""
        data = r.json()
        token = data.get("connectionToken") or data.get("connectionId") or ""
        return jsonify({
            "connectionToken": token,
            "connectionId":    data.get("connectionId") or "",
            "awsCookie":       aws_cookie,
            "url":             data.get("url") or F1_HUB,
            "ok":              True
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ── WebSocket bridge (/ws) ────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_bridge():
    token      = websocket.args.get("id", "")
    aws_cookie = websocket.args.get("cookie", "")

    f1_url = F1_HUB + "?id=" + token
    ws_headers = dict(REQ_HEADERS)
    if aws_cookie:
        ws_headers["Cookie"] = f"AWSALBCORS={aws_cookie}"

    try:
        async with websockets.connect(f1_url, additional_headers=ws_headers) as f1_ws:

            async def browser_to_f1():
                while True:
                    data = await websocket.receive()
                    await f1_ws.send(data)

            async def f1_to_browser():
                async for msg in f1_ws:
                    await websocket.send(msg)

            await asyncio.gather(browser_to_f1(), f1_to_browser())

    except Exception as e:
        print(f"[bridge] Erreur WS: {e}")

# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/health")
async def health():
    return jsonify({"status": "ok"})

# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]
    asyncio.run(serve(app, config))
