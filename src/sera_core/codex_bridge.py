"""Minimal stdio JSON-RPC client for the official Codex App Server
(``codex app-server --listen stdio://``)."""
from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterable


def find_codex() -> str | None:
    """Locate a ``codex`` binary: ``$CODEX_BINARY``, ``PATH`` or common install paths."""
    candidates = [
        os.environ.get("CODEX_BINARY"),
        shutil.which("codex"),
        "/Applications/Codex.app/Contents/Resources/codex",
        str(Path.home() / ".local/bin/codex"),
    ]
    return next((c for c in candidates if c and Path(c).is_file()), None)


class BridgeError(RuntimeError):
    pass


class CodexBridge:
    """Spawns the Codex App Server and multiplexes requests and events.

    * ``call()`` sends a request and waits for its response.
    * ``respond()`` answers a *server request* (such as an approval).
    * every notification or server request goes to ``on_event``.

    Config overrides passed in ``config`` apply only to this child process;
    the user's own Codex configuration is never edited.
    """

    def __init__(self, on_event: Callable[[dict], None], log_dir: str | os.PathLike,
                 binary: str | None = None, config: Iterable[str] = (),
                 client_name: str = "sera_core", client_version: str = "0.1.0",
                 command: list[str] | None = None):
        self.on_event = on_event
        self.log_dir = Path(log_dir)
        self.binary = binary
        self.config = list(config)
        self.client = {"name": client_name, "title": client_name, "version": client_version}
        self.command = command
        self.pending: dict[int, queue.Queue] = {}
        self.lock = threading.RLock()
        self.write_lock = threading.Lock()
        self.counter = 0
        self.proc: subprocess.Popen | None = None
        self.closed = False

    def _command(self) -> list[str]:
        if self.command:
            return list(self.command)
        binary = self.binary or find_codex()
        if not binary:
            raise BridgeError("Codex was not found. Install the Codex CLI or set CODEX_BINARY.")
        cmd = [binary, "app-server", "--listen", "stdio://", "-c", "analytics.enabled=false"]
        for override in self.config:
            cmd += ["-c", override]
        return cmd

    def start(self) -> dict:
        self.log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._stderr = (self.log_dir / "engine.log").open("ab")
        self.proc = subprocess.Popen(self._command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=self._stderr, text=True, bufsize=1, start_new_session=True)
        threading.Thread(target=self._read, daemon=True).start()
        result = self.call("initialize", {"clientInfo": self.client,
                                          "capabilities": {"experimentalApi": True}}, timeout=40)
        self.send({"method": "initialized", "params": {}})
        return result

    def send(self, message: dict) -> None:
        with self.write_lock:
            if not self.proc or self.proc.poll() is not None:
                raise BridgeError("The Codex engine is not running.")
            self.proc.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def call(self, method: str, params: dict | None = None, timeout: float = 60) -> dict:
        with self.lock:
            self.counter += 1
            identifier = self.counter
            reply: queue.Queue = queue.Queue(maxsize=1)
            self.pending[identifier] = reply
        try:
            self.send({"id": identifier, "method": method, "params": params or {}})
            response = reply.get(timeout=timeout)
            if response.get("error"):
                raise BridgeError(response["error"].get("message", "Request failed."))
            return response.get("result", {})
        except queue.Empty:
            raise BridgeError(f"No response to {method} within {timeout}s.") from None
        finally:
            with self.lock:
                self.pending.pop(identifier, None)

    def respond(self, identifier, result: dict | None = None, error: dict | None = None) -> None:
        body: dict = {"id": identifier}
        if error:
            body["error"] = error
        else:
            body["result"] = result
        self.send(body)

    def _read(self) -> None:
        try:
            for line in self.proc.stdout:
                try:
                    body = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if "method" not in body and "id" in body:
                    with self.lock:
                        reply = self.pending.get(body["id"])
                    if reply:
                        reply.put(body)
                    continue
                try:
                    self.on_event(body)
                except Exception:  # a bad handler must not kill the protocol reader
                    pass
        finally:
            with self.lock:
                for reply in self.pending.values():
                    try:
                        reply.put_nowait({"error": {"message": "The Codex engine stopped. See engine.log."}})
                    except queue.Full:
                        pass
            if not self.closed:
                try:
                    self.on_event({"method": "bridge/disconnected", "params": {}})
                except Exception:
                    pass

    def close(self) -> None:
        self.closed = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=3)
        if hasattr(self, "_stderr"):
            self._stderr.close()
