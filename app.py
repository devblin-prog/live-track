"""
Grand Gaz — Backend F1 Live Timing
Flask + gevent-websocket sur port unique.
- GET /negotiate  → token + cookie AWS
- WS  /ws         → bridge bidirectionnel vers F1
- GET /health     → ok
"""

import os
import requests
from flask import Flask, jsonify, request
from flask_cors import CORS
from geventwebsocket import WebSocketApplication, Resource, WebSocketServer
from geventwebsocket.websocket import WebSocket
import gevent

app = Flask(__name__)

ALLOWED_ORIGINS = [
    "https://grand-gaz.elementfx.com",
    "https://grandgaz.wuaze.com",
    "http://localhost",
    "http://localhost:8000",
]
CORS(app, origins=ALLOWED_ORIGINS)

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
F1_HUB_WS    = "wss://livetiming.formula1.com/signalrcore"

REQ_HEADERS = {
    "User-Agent":      "BestHTTP",
    "Accept-Encoding": "gzip, identity",
    "Connection":      "keep-alive",
}

# ── HTTP routes ───────────────────────────────────────────────────────────────

@app.route("/negotiate")
def negotiate():
    try:
        r = requests.post(F1_NEGOTIATE, headers=REQ_HEADERS, timeout=8)
        aws_cookie = r.cookies.get("AWSALBCORS") or r.cookies.get("AWSALB") or ""
        data = r.json()
        token = data.get("connectionToken") or data.get("connectionId") or ""
        return jsonify({
            "connectionToken": token,
            "connectionId":    data.get("connectionId") or "",
            "awsCookie":       aws_cookie,
            "url":             data.get("url") or F1_HUB_WS,
            "ok":              True
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# ── WebSocket bridge ──────────────────────────────────────────────────────────

class F1BridgeApp(WebSocketApplication):
    def on_open(self):
        ws    = self.ws
        token = request.args.get("id", "")
        cookie= request.args.get("cookie", "")

        origin = request.headers.get("Origin", "")
        if origin and origin not in ALLOWED_ORIGINS:
            ws.close()
            return

        f1_url = F1_HUB_WS + "?id=" + token
        hdrs   = dict(REQ_HEADERS)
        if cookie:
            hdrs["Cookie"] = f"AWSALBCORS={cookie}"

        import websocket as ws_lib   # websocket-client (sync, gevent-friendly)
        self.f1_ws = ws_lib.create_connection(f1_url, header=hdrs)
        f1 = self.f1_ws

        def relay_f1_to_browser():
            try:
                while True:
                    msg = f1.recv()
                    if msg is None:
                        break
                    ws.send(msg)
            except Exception:
                pass
            finally:
                ws.close()

        gevent.spawn(relay_f1_to_browser)

    def on_message(self, msg):
        if msg and hasattr(self, 'f1_ws'):
            try:
                self.f1_ws.send(msg)
            except Exception:
                pass

    def on_close(self, reason):
        if hasattr(self, 'f1_ws'):
            try:
                self.f1_ws.close()
            except Exception:
                pass

# ── Entrypoint ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server = WebSocketServer(
        ("0.0.0.0", port),
        Resource([
            ("^/ws",   F1BridgeApp),
            ("^/.*",   app),
        ])
    )
    print(f"[GrandGaz] Proxy démarré sur port {port}")
    server.serve_forever()
