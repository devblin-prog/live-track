"""
Grand Gaz — F1 Live Timing Proxy
asyncio pur, zéro dépendance C — compatible Python 3.14
- GET /negotiate  → token + cookie AWS
- GET /ws         → upgrade WebSocket, bridge bidirectionnel vers F1
- GET /health     → ok
"""

import os, json, time, sys
import urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie

F1_NEGOTIATE = "https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1"
F1_HUB_WS    = "wss://livetiming.formula1.com/signalrcore"
F1_HUB_WSS   = "livetiming.formula1.com"

ALLOWED_ORIGINS = {
    "https://grand-gaz.elementfx.com",
    "https://grandgaz.wuaze.com",
    "http://localhost",
    "http://localhost:8000",
}

REQ_HEADERS = {
    "User-Agent":      "BestHTTP",
    "Accept-Encoding": "identity",
    "Connection":      "keep-alive",
}

def do_negotiate(max_attempts=3):
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            req = urllib.request.Request(F1_NEGOTIATE, method="POST", headers=REQ_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                body    = resp.read()
                data    = json.loads(body)
                token   = data.get("connectionToken") or data.get("connectionId") or ""
                # Récupérer TOUS les Set-Cookie (AWSALB et AWSALBCORS) et les renvoyer
                # tels quels sous forme "NOM=valeur; NOM2=valeur2" pour le Cookie du handshake WS.
                # (l'ancienne version prenait la valeur d'AWSALB et l'envoyait sous le nom AWSALBCORS)
                pairs = []
                for sc in resp.headers.get_all("Set-Cookie") or []:
                    first = sc.split(";", 1)[0].strip()
                    if first.startswith("AWSALB"):
                        pairs.append(first)
                aws = "; ".join(pairs)
                return token, aws, data
        except Exception as e:
            last_err = e
            print(f"[negotiate] tentative {attempt}/{max_attempts} échouée: {e}", file=sys.stderr)
            if attempt < max_attempts:
                time.sleep(0.8 * attempt)
    raise last_err

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"  # requis : un upgrade WebSocket (101) doit être répondu en HTTP/1.1

    def log_message(self, fmt, *args):
        pass  # silencieux

    def cors_headers(self):
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        else:
            self.send_header("Access-Control-Allow-Origin", "https://grand-gaz.elementfx.com")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Vary", "Origin")

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/negotiate":
            try:
                token, aws, data = do_negotiate()
                body = json.dumps({
                    "connectionToken": token,
                    "connectionId":    data.get("connectionId") or "",
                    "awsCookie":       aws,
                    "url":             data.get("url") or F1_HUB_WS,
                    "ok":              True
                }).encode()
            except Exception as e:
                body = json.dumps({"ok": False, "error": str(e)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.cors_headers()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif path == "/ws":
            # WebSocket upgrade + bridge
            self._ws_bridge()

        else:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def _ws_bridge(self):
        try:
            self._ws_bridge_inner()
        except Exception as e:
            print(f"[ws_bridge] erreur: {e}", file=sys.stderr)
            try:
                self.connection.close()
            except Exception:
                pass

    def _ws_bridge_inner(self):
        import base64, hashlib, ssl, socket as sock_mod, threading

        # Lire les query params
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = {}
        for kv in qs.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                from urllib.parse import unquote_plus
                params[k] = unquote_plus(v)

        token  = params.get("id", "")
        cookie = params.get("cookie", "")

        # Vérif upgrade
        if self.headers.get("Upgrade", "").lower() != "websocket":
            self.send_response(400)
            self.end_headers()
            return

        # Handshake WS côté navigateur
        ws_key = self.headers.get("Sec-WebSocket-Key", "")
        accept = base64.b64encode(
            hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        ).decode()

        self.send_response(101, "Switching Protocols")
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", accept)
        origin = self.headers.get("Origin", "")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
        self.end_headers()
        self.wfile.flush()

        browser_sock = self.connection

        # Connexion WS vers F1
        f1_path = "/signalrcore?id=" + token
        ssl_ctx = ssl.create_default_context()
        f1_sock = ssl_ctx.wrap_socket(
            sock_mod.create_connection((F1_HUB_WSS, 443), timeout=10),
            server_hostname=F1_HUB_WSS
        )
        # Handshake WS vers F1
        f1_key = base64.b64encode(os.urandom(16)).decode()
        hs = (
            f"GET {f1_path} HTTP/1.1\r\n"
            f"Host: {F1_HUB_WSS}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {f1_key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"User-Agent: BestHTTP\r\n"
        )
        if cookie:
            # cookie = "AWSALB=...; AWSALBCORS=..." (nouveau format) ou simple valeur (ancien format)
            hs += f"Cookie: {cookie if '=' in cookie else 'AWSALBCORS=' + cookie}\r\n"
        hs += "\r\n"
        f1_sock.sendall(hs.encode())

        # Lire réponse HTTP de F1
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += f1_sock.recv(1)
        if b"101" not in buf:
            print(f"[ws_bridge] F1 a refusé le handshake: {buf[:200]!r}", file=sys.stderr)
            browser_sock.close()
            f1_sock.close()
            return

        print("[ws_bridge] handshake F1 OK, pont ouvert", file=sys.stderr)

        # Le navigateur envoie souvent sa 1ère frame WS juste après la requête d'upgrade,
        # dans le même paquet TCP. self.rfile (bufferisé) a pu déjà l'aspirer dans son
        # tampon interne pendant la lecture des headers HTTP : il faut la récupérer avant
        # de basculer sur le socket brut, sinon elle est perdue et F1 attend indéfiniment.
        try:
            leftover = self.rfile.peek(65536) if hasattr(self.rfile, "peek") else b""
        except Exception:
            leftover = b""
        if leftover:
            leftover = self.rfile.read(len(leftover))
            if leftover:
                f1_sock.sendall(leftover)

        # Bridge raw TCP bidirectionnel
        def relay(src, dst):
            try:
                while True:
                    data = src.recv(4096)
                    if not data:
                        break
                    dst.sendall(data)
            except Exception:
                pass
            finally:
                try: src.close()
                except: pass
                try: dst.close()
                except: pass

        t1 = threading.Thread(target=relay, args=(browser_sock, f1_sock), daemon=True)
        t2 = threading.Thread(target=relay, args=(f1_sock, browser_sock), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()

class Server(ThreadingHTTPServer):
    daemon_threads = True

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    server = Server(("0.0.0.0", port), Handler)
    print(f"[GrandGaz] Proxy démarré sur port {port} (threaded)")
    server.serve_forever()
