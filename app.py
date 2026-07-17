"""
Grand Gaz — Backend F1 Live Timing
Rôle : faire le negotiate SignalR F1 (nécessite un cookie AWS AWSALBCORS)
       et le renvoyer au navigateur via CORS.
Deploy sur Render (free tier).
"""

from flask import Flask, jsonify
from flask_cors import CORS
import requests

app = Flask(__name__)

ALLOWED_ORIGINS = [
    "https://grand-gaz.elementfx.com",   # domaine actuel
    "https://grandgaz.wuaze.com",         # ancien domaine (garde pour sécurité)
    "http://localhost",
    "http://localhost:8000",
]

CORS(app, origins=ALLOWED_ORIGINS)

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"

HEADERS = {
    "User-Agent": "BestHTTP",
    "Accept-Encoding": "gzip, identity",
    "Connection": "keep-alive",
}

@app.route("/negotiate")
def negotiate():
    try:
        r = requests.post(F1_NEGOTIATE, headers=HEADERS, timeout=8)

        # Récupérer le cookie AWSALBCORS si présent
        aws_cookie = r.cookies.get("AWSALBCORS") or r.cookies.get("AWSALB") or ""

        data = r.json()

        return jsonify({
            "connectionToken": data.get("connectionToken") or data.get("connectionId") or "",
            "connectionId":    data.get("connectionId") or "",
            "awsCookie":       aws_cookie,
            "url":             data.get("url") or "wss://livetiming.formula1.com/signalrcore",
            "ok":              True
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
