"""Local, expiring approval for a newly created disposable test project only."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import time

from .protocol import BridgeError, pack, unpack
from .transport import Mailbox, READ_OPS, atomic_write, safe_path, read_data
from .permissions import protect_directory

WRITE_OPS = frozenset({'create_test_project', 'create_bin', 'import_media', 'create_timeline',
                       'duplicate_timeline', 'add_track', 'plan_append', 'append_clip', 'save_test_project'})
TEST_NAME = re.compile(r'ResolveMCP_TEST_[A-Za-z0-9_-]{1,64}\Z')
MEDIA_NAME = re.compile(r'ResolveMCP_TEST_MEDIA_[A-Za-z0-9_-]{1,64}\Z')


@dataclass(frozen=True)
class Approval:
    identifier: str
    expires: int
    project_name: str
    media_root: Path


def prepare_media_root(mailbox: Mailbox, directory: Path) -> None:
    directory = safe_path(directory)
    if not MEDIA_NAME.fullmatch(directory.name) or directory.exists():
        raise BridgeError('WRITE_DENIED', 'Use a new ResolveMCP_TEST_MEDIA_<name> directory')
    directory.mkdir(mode=0o700)
    protect_directory(directory)
    marker = pack(mailbox.key, ['RMC3', str(directory).encode('utf-8').hex()])
    atomic_write(directory / '.resolve-mcp-test-media', marker)


def verify_media_root(mailbox: Mailbox, directory: Path) -> Path:
    directory = safe_path(directory)
    if not MEDIA_NAME.fullmatch(directory.name) or not directory.is_dir():
        raise BridgeError('WRITE_DENIED', 'A dedicated test media directory is required')
    if os.name != 'nt' and directory.stat().st_mode & 0o077:
        raise BridgeError('WRITE_DENIED', 'Test media directory must have owner-only permissions')
    marker = safe_path(directory / '.resolve-mcp-test-media')
    try:
        fields = unpack(mailbox.key, read_data(marker,8193), 2)
        if bytes.fromhex(fields[1]).decode('utf-8') != str(directory):
            raise ValueError('Different directory')
    except (OSError, ValueError, UnicodeError, BridgeError) as error:
        raise BridgeError('WRITE_DENIED', 'Test media marker does not match this session and directory') from error
    return directory


def approve(mailbox: Mailbox, project_name: str, media_root: Path,
            confirmation: str, minutes: int = 30) -> Approval:
    if confirmation != project_name or not TEST_NAME.fullmatch(project_name):
        raise BridgeError('WRITE_DENIED', 'Confirm the exact new ResolveMCP_TEST_<name> project')
    if type(minutes) is not int or not 1 <= minutes <= 60:
        raise ValueError('Approval lifetime must be 1–60 minutes')
    with mailbox._locked():
        directory = verify_media_root(mailbox, media_root)
        value = Approval(secrets.token_hex(16), int(time.time()) + minutes * 60, project_name, directory)
        atomic_write(mailbox.root / 'approval.txt', pack(mailbox.key,
            ['RMC3', value.identifier, str(value.expires), project_name.encode().hex(), str(directory).encode().hex()]))
        return value


def load_approval(mailbox: Mailbox) -> Approval:
    try:
        path = safe_path(mailbox.root / 'approval.txt')
        _, identifier, expires, name, directory = unpack(mailbox.key, read_data(path,8193), 5)
        value = Approval(identifier, int(expires), bytes.fromhex(name).decode('utf-8'), Path(bytes.fromhex(directory).decode('utf-8')))
        if not re.fullmatch('[0-9a-f]{32}', identifier) or not TEST_NAME.fullmatch(value.project_name):
            raise ValueError('Invalid approval')
        if not time.time() < value.expires <= time.time() + 3600:
            raise ValueError('Expired approval')
        verify_media_root(mailbox, value.media_root)
        return value
    except (OSError, ValueError, UnicodeError, BridgeError) as error:
        raise BridgeError('WRITE_DENIED', 'Missing, revoked, expired or invalid local approval') from error


def approve_bootstrap(mailbox: Mailbox, grant: Approval, expected_name: str, project: dict) -> None:
    """Permit closing only the explicitly confirmed, freshly queried bootstrap.

    Separate from edit approval: bound to its ID, expiry and live bridge instance.
    Resolve independently checks identity and emptiness immediately before close.
    """
    identifier = project.get('project_id')
    if (not re.fullmatch(r'ResolveMCP_BOOT_[0-9a-f]{32}', expected_name)
        or project.get('project_open') is not True or project.get('name') != expected_name
        or not isinstance(identifier, str) or not 0 < len(identifier.encode('utf-8')) <= 256
        or '\0' in identifier or str(project.get('timeline_count')) != '0'
        or mailbox.bridge_id is None):
        raise BridgeError('WRITE_DENIED', 'Open only the exact newly prepared empty bootstrap project')
    with mailbox._locked():
        if load_approval(mailbox) != grant:
            raise BridgeError('WRITE_DENIED', 'Edit approval changed before bootstrap authorization')
        atomic_write(mailbox.root / 'bootstrap-approval.txt', pack(mailbox.key,
            ['RMC3', 'BOOTSTRAP', grant.identifier, str(grant.expires), mailbox.bridge_id,
             expected_name.encode('utf-8').hex(), identifier.encode('utf-8').hex()]))


class Editor(Mailbox):
    def prepare(self, op: str, params: dict) -> dict:
        if op not in WRITE_OPS:
            return super().prepare(op, params)
        approval = load_approval(self)
        if op == 'import_media':
            path = safe_path(Path(params.get('path', '')))
            if not path.is_file() or not path.is_relative_to(approval.media_root) or path.stat().st_nlink != 1:
                raise BridgeError('WRITE_DENIED', 'Import only copied regular files inside the approved test media root')
            if path.suffix.lower() not in {'.mp4','.mov','.mxf','.mkv','.wav','.mp3','.png','.jpg','.jpeg'}:
                raise BridgeError('WRITE_DENIED', 'Unsupported test media file extension')
            params = {**params, 'path': str(path)}
        return params

    def _audit(self, operation: str, event: str, identifier: str) -> None:
        path = safe_path(self.root / 'audit.jsonl')
        if path.exists() and path.stat().st_size > 1024 * 1024:
            raise BridgeError('AUDIT_LIMIT', 'Archive the audit log locally before more edits')
        descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os,'O_NOFOLLOW',0), 0o600)
        with os.fdopen(descriptor, 'ab') as stream:
            stream.write((json.dumps({'time': time.time(), 'event_id': identifier, 'operation': operation, 'event': event}) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())

    def _exchange(self, op: str, params: dict) -> dict:
        if op not in WRITE_OPS:
            return super()._exchange(op, params)
        identifier = secrets.token_hex(16)
        self._audit(op, 'requested', identifier)
        try:
            result = super()._exchange(op, params)
        except BridgeError as error:
            self._audit(op, error.code, identifier)
            raise
        self._audit(op, 'completed', identifier)
        return result
