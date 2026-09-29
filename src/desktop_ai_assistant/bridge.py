import hashlib
import json
from multiprocessing.connection import Listener, Client
import os
import struct
import sys
import threading
import uuid
from .config import data_dir
from .history import encrypt, decrypt


def credentials():
    path = data_dir() / "bridge.key"
    if not path.exists():
        try:
            with path.open("xb") as file:
                file.write(encrypt(os.urandom(32).hex()))
        except FileExistsError:
            pass
    key = bytes.fromhex(decrypt(path.read_bytes()))
    name = hashlib.sha256(str(data_dir()).lower().encode()).hexdigest()[:20]
    return rf"\\.\pipe\DesktopAiAssistant-{name}", key


class BrowserRequestError(RuntimeError):
    code: str

    def __init__(self, message, code):
        super().__init__(message)
        self.code = code


class BrowserBridge:
    listener: object
    clients: dict
    pending: dict
    lock: threading.Lock
    stopped: bool

    def __init__(self):
        address, key = credentials()
        self.listener = Listener(address, family="AF_PIPE", authkey=key)
        self.clients = {}
        self.pending = {}
        self.lock = threading.Lock()
        self.stopped = False
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.stopped:
            try:
                connection = self.listener.accept()
            except (OSError, EOFError):
                break
            client_id = uuid.uuid4().hex
            with self.lock:
                self.clients[client_id] = (connection, threading.Lock())
            threading.Thread(target=self.read, args=(client_id, connection), daemon=True).start()

    def read(self, client_id, connection):
        try:
            while not self.stopped:
                value = json.loads(connection.recv_bytes(1_000_000))
                with self.lock:
                    pending = self.pending.get(value.get("id"))
                    if pending and pending[0] == client_id:
                        pending[2].update(value)
                        pending[1].set()
        except (OSError, EOFError, ValueError):
            pass
        finally:
            with self.lock:
                self.clients.pop(client_id, None)
            connection.close()

    def request(self, client_id, operation, **data):
        request_id = uuid.uuid4().hex
        event, reply = threading.Event(), {}
        with self.lock:
            client = self.clients.get(client_id)
            if not client:
                raise RuntimeError("Browser disconnected")
            self.pending[request_id] = (client_id, event, reply)
        try:
            with client[1]:
                client[0].send_bytes(json.dumps({"id": request_id, "op": operation, **data}).encode())
            if not event.wait(4):
                raise TimeoutError("Browser did not respond")
            if not reply.get("ok"):
                raise BrowserRequestError(reply.get("error", "Unsupported browser field"), reply.get("code", "editor_error"))
            return reply["value"]
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def capture(self, target):
        matches = []
        with self.lock:
            clients = list(self.clients)
        if not clients:
            raise RuntimeError("Browser extension is disconnected. Open its popup and check Desktop connection, then reconnect.")
        errors = []
        for client in clients:
            try:
                snapshot = self.request(client, "capture")
                snapshot.update(kind="browser", client=client, target=target)
                matches.append(snapshot)
            except (RuntimeError, TimeoutError, OSError) as error:
                errors.append(error)
        if len(matches) > 1:
            raise RuntimeError("Several browser windows reported an editor. Focus just the window you want to edit.")
        if not matches:
            relevant = [error for error in errors if getattr(error, "code", "") != "browser_not_focused"]
            raise RuntimeError(str((relevant or errors)[0]))
        return matches[0]

    def apply(self, snapshot, text):
        result = self.request(snapshot["client"], "apply", snapshot=snapshot, text=text)
        result.update(kind="browser", client=snapshot["client"], target=snapshot["target"])
        return result

    def restore(self, snapshot):
        return self.request(snapshot["client"], "restore", snapshot=snapshot)

    def close(self):
        self.stopped = True
        with self.lock:
            for connection, _ in list(self.clients.values()):
                connection.close()
            self.clients.clear()
        self.listener.close()


def native_host():
    import msvcrt
    msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
    msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    from .browser_setup import origin_allowed
    if len(sys.argv) < 3 or not origin_allowed(sys.argv[2]):
        return 2
    address, key = credentials()
    connection = Client(address, family="AF_PIPE", authkey=key)
    from . import __version__
    hello = json.dumps({"op": "hello", "version": __version__}).encode()
    sys.stdout.buffer.write(struct.pack("<I", len(hello)) + hello)
    sys.stdout.buffer.flush()
    def receive():
        try:
            while True:
                payload = connection.recv_bytes(1_000_000)
                sys.stdout.buffer.write(struct.pack("<I", len(payload)) + payload)
                sys.stdout.buffer.flush()
        except (EOFError, OSError):
            os._exit(0)
    threading.Thread(target=receive, daemon=True).start()
    try:
        while True:
            header = sys.stdin.buffer.read(4)
            if not header:
                break
            size = struct.unpack("<I", header)[0]
            if size > 1_000_000:
                return 2
            data = sys.stdin.buffer.read(size)
            if len(data) != size:
                return 2
            connection.send_bytes(data)
    finally:
        connection.close()
    return 0
