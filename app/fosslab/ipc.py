"""Tiny local messaging so xschem/KLayout menus can talk to a running manager.

The manager listens on /tmp/fosslab-<uid>-<mode>.sock; ``fosslab reveal``
sends {"cmd": "reveal", "lib": ..., "cell": ...}. If nobody listens the
caller starts a new manager instead.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from pathlib import Path
from typing import Callable


def sock_path(mode: str = "main") -> Path:
    return Path(f"/tmp/fosslab-{os.getuid()}-{mode}.sock")


def send(msg: dict, modes: tuple[str, ...] = ("main", "supervisor")) -> bool:
    data = (json.dumps(msg) + "\n").encode()
    for mode in modes:
        p = sock_path(mode)
        if not p.exists():
            continue
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect(str(p))
                s.sendall(data)
            return True
        except OSError:
            continue
    return False


class Server:
    def __init__(self, handler: Callable[[dict], None], mode: str = "main"):
        self.handler = handler
        self.mode = mode
        self.path = sock_path(mode)
        self.sock: socket.socket | None = None

    def start(self) -> bool:
        if self.path.exists():
            if send({"cmd": "ping"}, modes=(self.mode,)):
                return False            # another manager already listens
            self.path.unlink(missing_ok=True)
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(str(self.path))
        os.chmod(self.path, 0o600)
        self.sock.listen(8)
        threading.Thread(target=self._loop, daemon=True).start()
        return True

    def _loop(self) -> None:
        assert self.sock is not None
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                try:
                    while chunk := conn.recv(65536):
                        buf += chunk
                except OSError:
                    continue
            for line in buf.decode(errors="replace").splitlines():
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("cmd") != "ping":
                    self.handler(msg)

    def stop(self) -> None:
        if self.sock:
            self.sock.close()
        self.path.unlink(missing_ok=True)
