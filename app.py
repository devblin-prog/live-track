"""
Grand Gaz — Backend F1 Live Timing
Flask simple — negotiate uniquement.
Compatible Python 3.14+, zéro dépendance C.
"""

import os
import requests
from flask import Flask, jsonify
from flask_cors import CORS

app = Flask(__name__)

CORS(app, origins=[
    "https://grand-gaz.elementfx.com",
    "https://grandgaz.wuaze.com",
    "http://localhost",
    "http://localhost:8000",
])

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
F1_HUB_WS    = "wss://livetiming.formula1.com/signalrcore"

REQ_HEADERS = {
    "User-Agent":      "BestHTTP",
    "Accept-Encoding": "gzip, identity",
}

@app.route("/negotiate")
def negotiate():
    try:
        r = requests.post(F1_NEGOTIATE, headers=REQ_HEADERS, timeout=8)
        aws = r.cookies.get("AWSALBCORS") or r.cookies.get("AWSALB") or ""
        data = r.json()
        token = data.get("connectionToken") or data.get("connectionId") or ""
        return jsonify({
            "connectionToken": token,
            "connectionId":    data.get("connectionId") or "",
            "awsCookie":       aws,
            "url":             data.get("url") or F1_HUB_WS,
            "ok":              True
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
