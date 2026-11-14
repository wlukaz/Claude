"""Minimal Home Assistant client using only the Python standard library.

Speaks the Home Assistant WebSocket API (ws:// or wss://) so nothing has to be
installed with pip. Used by ha_dashboard.py.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import ssl
import struct
from urllib.parse import urlparse


class HAError(Exception):
    pass


class _WebSocket:
    """Just enough of RFC 6455 for a JSON request/response client."""

    def __init__(self, url: str, timeout: float = 60):
        u = urlparse(url)
        secure = u.scheme in ("wss", "https")
        host = u.hostname
        port = u.port or (443 if secure else 80)
        path = u.path or "/"
        raw = socket.create_connection((host, port), timeout=8)
        raw.settimeout(timeout)
        if secure:
            ctx = ssl.create_default_context()
            if os.environ.get("HA_INSECURE_TLS") == "1":
                # For self-signed certificates on a local network only.
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            raw = ctx.wrap_socket(raw, server_hostname=host)
        self.sock = raw
        self._buf = b""
        key = base64.b64encode(os.urandom(16)).decode()
        host_header = host if u.port is None else f"{host}:{u.port}"
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        while b"\r\n\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise HAError("Connection closed during WebSocket handshake")
            self._buf += chunk
        head, self._buf = self._buf.split(b"\r\n\r\n", 1)
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise HAError(f"WebSocket handshake failed: {status.decode(errors='replace')}")

    def _read(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self.sock.recv(max(65536, n - len(self._buf)))
            if not chunk:
                raise HAError("Connection closed by Home Assistant")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack("!H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack("!Q", n)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(header + mask + masked)

    def send(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def recv(self) -> str:
        message = b""
        while True:
            b1, b2 = self._read(2)
            fin, opcode = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b2 & 0x80 else None
            payload = self._read(n)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == 0x9:  # ping
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode == 0x8:
                raise HAError("Home Assistant closed the connection")
            message += payload
            if fin:
                return message.decode()

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        self.sock.close()


class HomeAssistant:
    def __init__(self, url: str, token: str):
        url = url.rstrip("/")
        if "://" not in url:
            url = "http://" + url
        u = urlparse(url)
        ws_scheme = "wss" if u.scheme == "https" else "ws"
        self.ws = _WebSocket(f"{ws_scheme}://{u.netloc}/api/websocket")
        self._id = 0
        first = json.loads(self.ws.recv())
        if first.get("type") != "auth_required":
            raise HAError(f"Unexpected greeting: {first}")
        self.version = first.get("ha_version", "?")
        self.ws.send(json.dumps({"type": "auth", "access_token": token}))
        res = json.loads(self.ws.recv())
        if res.get("type") != "auth_ok":
            raise HAError("Login failed - check your long-lived access token")

    def call(self, msg_type: str, **kwargs):
        self._id += 1
        msg = {"id": self._id, "type": msg_type, **kwargs}
        self.ws.send(json.dumps(msg))
        while True:
            res = json.loads(self.ws.recv())
            if res.get("id") != self._id or res.get("type") != "result":
                continue  # ignore stray events
            if not res.get("success"):
                err = res.get("error", {})
                raise HAError(f"{err.get('code', 'error')}: {err.get('message', '')}")
            return res.get("result")

    def try_call(self, msg_type: str, **kwargs):
        try:
            return self.call(msg_type, **kwargs)
        except HAError:
            return None

    def close(self) -> None:
        self.ws.close()
