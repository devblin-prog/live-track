"""
Grand Gaz — Backend F1 Live Timing
Rôle : negotiate SignalR F1 + bridge WebSocket complet (cookie AWSALBCORS transparent).
Deploy sur Render (free tier).
"""

import asyncio
import threading
import requests
import websockets
from flask import Flask, jsonify, request
from flask_cors import CORS
from websockets.sync.client import connect as ws_connect

app = Flask(__name__)

ALLOWED_ORIGINS = [
    "https://grand-gaz.elementfx.com",
    "https://grandgaz.wuaze.com",
    "http://localhost",
    "http://localhost:8000",
]
CORS(app, origins=ALLOWED_ORIGINS)

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
F1_HUB       = "wss://livetiming.formula1.com/signalrcore"

HEADERS = {
    "User-Agent":      "BestHTTP",
    "Accept-Encoding": "gzip, identity",
    "Connection":      "keep-alive",
}

# ── Negotiate ────────────────────────────────────────────────────────────────

@app.route("/negotiate")
def negotiate():
    try:
        r = requests.post(F1_NEGOTIATE, headers=HEADERS, timeout=8)
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

# ── WebSocket bridge ──────────────────────────────────────────────────────────
# Le navigateur se connecte en WS à /ws?id=TOKEN
# Le proxy ouvre un WS vers F1 avec le cookie AWS et relaie tout.

async def bridge(ws_browser, token: str, aws_cookie: str):
    """Relaie bidirectionnellement entre le navigateur et F1."""
    f1_url = F1_HUB + "?id=" + token
    f1_headers = dict(HEADERS)
    if aws_cookie:
        f1_headers["Cookie"] = f"AWSALBCORS={aws_cookie}"

    try:
        async with websockets.connect(f1_url, additional_headers=f1_headers) as ws_f1:
            async def browser_to_f1():
                async for msg in ws_browser:
                    await ws_f1.send(msg)

            async def f1_to_browser():
                async for msg in ws_f1:
                    await ws_browser.send(msg)

            await asyncio.gather(browser_to_f1(), f1_to_browser())
    except Exception as e:
        print(f"[bridge] Erreur: {e}")

async def ws_handler(websocket):
    path = websocket.request.path          # ex: /ws?id=TOKEN
    params = {}
    if "?" in path:
        for kv in path.split("?", 1)[1].split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v

    token      = params.get("id", "")
    aws_cookie = params.get("cookie", "")

    # Vérifier l'origine
    origin = websocket.request.headers.get("Origin", "")
    if origin and origin not in ALLOWED_ORIGINS:
        await websocket.close(1008, "Origin not allowed")
        return

    await bridge(websocket, token, aws_cookie)

def run_ws_server():
    """Lance le serveur WS dans son propre thread/event loop."""
    async def _serve():
        async with websockets.serve(ws_handler, "0.0.0.0", 10001):
            await asyncio.Future()   # tourne indéfiniment
    asyncio.run(_serve())

# Démarrer le bridge WS en thread daemon au lancement Flask
_ws_thread = threading.Thread(target=run_ws_server, daemon=True)
_ws_thread.start()

# ── Health ────────────────────────────────────────────────────────────────────

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
