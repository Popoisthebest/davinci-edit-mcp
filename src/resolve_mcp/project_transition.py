"""Authenticate bounded, local project-close observations; never authorize edits."""
import json

from .protocol import BridgeError, unpack
from .transport import read_data


def read_transition(mailbox, approval_id: str) -> dict | None:
    try:
        packet = read_data(mailbox.root / 'project-transition.txt', 262145)
    except FileNotFoundError:
        return None
    _, kind, instance, grant, payload = unpack(mailbox.key, packet, 5)
    if kind != 'PROJECT_TRANSITION' or instance != mailbox.bridge_id or grant != approval_id:
        raise BridgeError('STALE_TRANSITION', 'Transition evidence belongs to another bridge or approval')
    try:
        data = json.loads(bytes.fromhex(payload).decode('utf-8'))
        if (not isinstance(data, dict) or data.get('transition_format') != 1
            or not isinstance(data.get('events'), list) or not 1 <= len(data['events']) <= 128):
            raise ValueError('Invalid transition data')
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BridgeError('INVALID_TRANSITION', 'Invalid transition evidence') from error
    return data
