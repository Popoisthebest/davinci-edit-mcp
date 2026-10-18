"""One authenticated mailbox, serialized across threads and server processes."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import secrets
import stat
import threading
import time

from .protocol import BridgeError, IDENTIFIER, MAX_PACKET, pack, unpack, request, response
from .permissions import protect_directory

READ_OPS = frozenset({"ping", "current_project", "current_timeline", "projects",
                      "timelines", "tracks", "media_pool", "render_settings", "timeline_items"})


def default_root() -> Path:
    if not os.environ.get("LOCALAPPDATA"):
        raise BridgeError("CONFIGURATION", "LOCALAPPDATA is missing; use --mailbox for offline tests")
    return Path(os.environ["LOCALAPPDATA"]) / "ResolveMCPNext" / "mailbox"


def safe_path(path: Path) -> Path:
    """Reject links and Windows junctions, including parent directory links."""
    path = path.absolute()
    if '..' in path.parts:
        raise BridgeError("UNSAFE_PATH", "Parent traversal is not allowed")
    for component in [path, *path.parents]:
        try:
            info = component.lstat()
        except FileNotFoundError:
            # An atomic replacement can temporarily remove a mailbox filename.
            # lstat also detects dangling symlinks, without an exists/stat race.
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BridgeError("UNSAFE_PATH", "Symlinks and reparse points are not allowed")
    return path


def atomic_write(path: Path, data: bytes) -> None:
    safe_path(path)
    temporary = path.with_name(path.name + "." + secrets.token_hex(16) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        safe_path(path)
        if os.name == 'nt':
            # MoveFileEx (used by os.replace) can reject replacement of an open
            # destination even when the reader shares DELETE. ReplaceFile is
            # designed for replacing an existing file and preserves its ACL.
            import ctypes
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.ReplaceFileW.argtypes = [w.LPCWSTR,w.LPCWSTR,w.LPCWSTR,w.DWORD,w.LPVOID,w.LPVOID]
            kernel.ReplaceFileW.restype = w.BOOL
            if not kernel.ReplaceFileW(str(path),str(temporary),None,0,None,None):
                code = ctypes.get_last_error()
                if code not in (2,3):raise ctypes.WinError(code)
                # There is no existing file on the first publication.
                os.replace(temporary,path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def read_data(path: Path, limit: int = MAX_PACKET + 1) -> bytes:
    """Read with FILE_SHARE_DELETE so Windows writers can replace a packet.

    A reader keeps its old complete file; the next poll sees the new file.
    No command or Resolve API is retried.
    """
    safe_path(path)
    if os.name != 'nt':
        with path.open('rb') as stream:
            return stream.read(limit)
    import ctypes
    from ctypes import wintypes as w
    import msvcrt
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR,w.DWORD,w.DWORD,w.LPVOID,w.DWORD,w.DWORD,w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    until = time.monotonic() + 0.25
    while True:
        handle = kernel.CreateFileW(str(path),0x80000000,7,None,3,0x200000,None)
        if handle != ctypes.c_void_p(-1).value:
            break
        code = ctypes.get_last_error()
        # ReplaceFile briefly holds its replacement handle without sharing.
        # Retry only the read, never a published command or a Resolve API call.
        if code not in (32,33) or time.monotonic() >= until:
            raise ctypes.WinError(code)
        time.sleep(0.002)
    try:
        descriptor = msvcrt.open_osfhandle(handle,os.O_RDONLY | os.O_BINARY)
    except BaseException:
        kernel.CloseHandle(handle)
        raise
    with os.fdopen(descriptor,'rb') as stream:
        return stream.read(limit)


class Mailbox:
    def __init__(self, root: Path | None = None, timeout: float = 10.0):
        if not 0 < timeout <= 29:
            raise ValueError("Timeout must be between 0 and 29 seconds")
        self.root = safe_path(root if root is not None else default_root())
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        protect_directory(self.root)
        if os.name != "nt" and self.root.stat().st_mode & 0o077:
            raise BridgeError("UNSAFE_PERMISSIONS", "Mailbox must have owner-only permissions")
        self.timeout = timeout
        self._thread_lock = threading.Lock()
        self.bridge_id: str | None = None
        with self._locked():
            key_file = safe_path(self.root / "session.key")
            if not key_file.exists():
                atomic_write(key_file, secrets.token_hex(32).encode("ascii"))
            self.key = self._read_key()

    def _read_key(self) -> bytes:
        path = safe_path(self.root / "session.key")
        if os.name != "nt" and path.stat().st_mode & 0o077:
            raise BridgeError("UNSAFE_PERMISSIONS", "Session key must be owner-only")
        try:
            raw = read_data(path,65).decode('ascii')
            if len(raw) != 64 or any(c not in "0123456789abcdef" for c in raw):
                raise ValueError("Invalid session key")
            return bytes.fromhex(raw)
        except (ValueError, UnicodeError) as error:
            raise BridgeError("CONFIGURATION", "Invalid session key; restore or rotate locally") from error

    @contextmanager
    def _locked(self):
        until = time.monotonic() + self.timeout
        if not self._thread_lock.acquire(timeout=self.timeout):
            raise BridgeError("BUSY", "Another request is in progress")
        stream = None
        acquired = False
        try:
            path = safe_path(self.root / "client.lock")
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            stream = os.fdopen(descriptor, "r+b", buffering=0)
            if path.stat().st_size == 0:
                stream.write(b"\0")
            while not acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= until:
                        raise BridgeError("BUSY", "Another server owns the mailbox")
                    time.sleep(0.01)
            yield
        finally:
            if stream is not None:
                if acquired:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()
            self._thread_lock.release()

    def _exchange(self, op: str, params: dict) -> dict:
        if self._read_key() != self.key:
            self.bridge_id = None
            raise BridgeError("SESSION_CHANGED", "Session rotated; restart this server")
        rid = secrets.token_hex(16)
        packet = request(self.key, rid, self.bridge_id, op, params, self.timeout)
        atomic_write(self.root / "request.txt", packet)
        until = time.monotonic() + self.timeout
        while time.monotonic() < until:
            path = safe_path(self.root / "response.txt")
            try:
                encoded = read_data(path)
            except FileNotFoundError:
                time.sleep(0.01)
                continue
            try:
                instance, data = response(self.key, encoded, rid, self.bridge_id)
            except BridgeError as error:
                if error.code == "STALE_RESPONSE":
                    time.sleep(0.01)
                    continue
                if error.code == "BRIDGE_RESTARTED":
                    self.bridge_id = None
                raise
            self.bridge_id = instance
            return data
        raise BridgeError("TIMEOUT", "No matching bridge response; outcome is unknown, do not auto-retry writes")

    def call(self, op: str, **params) -> dict:
        if op not in READ_OPS and op != "stop":
            raise BridgeError("OP_NOT_ALLOWED", "Operation is not enabled")
        with self._locked():
            if self.bridge_id is None and op != "ping":
                self._exchange("ping", {})
            return self._exchange(op, params)

    def wait_ready(self, timeout: float = 600) -> None:
        """Authenticate a fresh service before starting any RPC deadline.

        This startup gate has no Resolve operation or editing authorization.
        An old READY, diagnostic service.json, or unsigned file cannot open it.
        """
        if not 0 < timeout <= 600:
            raise ValueError('Startup wait must be between 0 and 600 seconds')
        with self._locked():
            if self._read_key() != self.key:
                raise BridgeError('SESSION_CHANGED', 'Session rotated before startup')
            challenge = secrets.token_hex(16)
            start = safe_path(self.root / 'start.txt')
            atomic_write(start, pack(self.key, ['RMC3', 'START', challenge, str(int(time.time()) + 600)]))
            until = time.monotonic() + timeout
            try:
                while time.monotonic() < until:
                    if self._read_key() != self.key:
                        raise BridgeError('SESSION_CHANGED', 'Session rotated during startup')
                    try:
                        _, kind, nonce, instance = unpack(self.key, read_data(self.root / 'ready.txt', 1025), 4)
                    except FileNotFoundError:
                        time.sleep(0.02)
                        continue
                    if kind == 'READY' and nonce == challenge:
                        if not IDENTIFIER.fullmatch(instance):
                            raise BridgeError('INVALID_RESPONSE', 'Invalid ready bridge identifier')
                        self.bridge_id = instance
                        return
                    time.sleep(0.02)
                raise BridgeError('STARTUP_TIMEOUT', 'No authenticated service ready; no edit request was published')
            finally:
                start.unlink(missing_ok=True)

    def rotate_session(self) -> None:
        with self._locked():
            self.key = secrets.token_bytes(32)
            atomic_write(self.root / "session.key", self.key.hex().encode("ascii"))
            for name in ("request.txt", "response.txt", "start.txt", "ready.txt"):
                safe_path(self.root / name).unlink(missing_ok=True)
            self.bridge_id = None
