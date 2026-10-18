"""Bounded, authenticated plain-data protocol. Never evaluates Lua or Python."""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
import time

MAX_PACKET = 1024 * 1024
MAX_TTL = 30
IDENTIFIER = re.compile(r"[0-9a-f]{32}\Z")
OPERATION = re.compile(r"[a-z_]{1,40}\Z")


class BridgeError(RuntimeError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(f"{code}: {message}")


def sign(key: bytes, text: str) -> str:
    return hmac.new(key, text.encode("ascii"), hashlib.sha256).hexdigest()


def pack(key: bytes, fields: list[str]) -> bytes:
    body = "\n".join(fields) + "\n"
    packet = (body + sign(key, body) + "\n").encode("ascii")
    if len(packet) > MAX_PACKET:
        raise ValueError("Packet size limit exceeded")
    return packet


def unpack(key: bytes, packet: bytes, count: int) -> list[str]:
    if len(packet) > MAX_PACKET:
        raise BridgeError("INVALID_RESPONSE", "Packet size limit exceeded")
    try:
        text = packet.decode("ascii")
        fields = text.split("\n")
    except UnicodeError as error:
        raise BridgeError("INVALID_RESPONSE", "Non-ASCII envelope") from error
    if len(fields) != count + 2 or fields[-1] != "" or fields[0] != "RMC3":
        raise BridgeError("INVALID_RESPONSE", "Invalid envelope")
    body = "\n".join(fields[:count]) + "\n"
    if not hmac.compare_digest(sign(key, body), fields[-2]):
        raise BridgeError("AUTH_FAILED", "Response authentication failed")
    return fields[:count]


def encode_params(params: dict) -> str:
    records = []
    for key, value in sorted(params.items()):
        if not OPERATION.fullmatch(key):
            raise ValueError("Invalid parameter name")
        if isinstance(value, bool):
            kind, encoded = "b", str(int(value))
        elif isinstance(value, int) and -(2**53) < value < 2**53:
            kind, encoded = "i", str(value)
        elif isinstance(value, str) and len(value.encode("utf-8")) <= 32768 and "\0" not in value:
            kind, encoded = "s", value.encode("utf-8").hex()
        else:
            raise ValueError("Parameters must be bounded strings, integers or booleans")
        records.append(f"{key}:{kind}:{encoded}\n")
    return "".join(records).encode("ascii").hex()


def request(key: bytes, rid: str, bridge: str | None, op: str, params: dict,
            timeout: float, now: float | None = None) -> bytes:
    if not IDENTIFIER.fullmatch(rid) or not OPERATION.fullmatch(op):
        raise ValueError("Invalid request identifier or operation")
    if bridge is not None and not IDENTIFIER.fullmatch(bridge):
        raise ValueError("Invalid bridge identifier")
    if not math.isfinite(timeout) or not 0 < timeout <= MAX_TTL - 1:
        raise ValueError("Timeout must be positive and at most 29 seconds")
    deadline = math.ceil((time.time() if now is None else now) + timeout)
    return pack(key, ["RMC3", rid, str(deadline), bridge or "-", op, encode_params(params)])


def response(key: bytes, packet: bytes, rid: str, bridge: str | None) -> tuple[str, dict]:
    _, actual_id, instance, status, payload = unpack(key, packet, 5)
    if actual_id != rid:
        raise BridgeError("STALE_RESPONSE", "Response belongs to another request")
    if not IDENTIFIER.fullmatch(instance):
        raise BridgeError("INVALID_RESPONSE", "Invalid bridge identifier")
    if bridge is not None and instance != bridge:
        raise BridgeError("BRIDGE_RESTARTED", "Bridge restarted; reconnect before retrying")
    try:
        data = json.loads(bytes.fromhex(payload).decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError) as error:
        raise BridgeError("INVALID_RESPONSE", "Invalid response data") from error
    if not isinstance(data, dict) or status not in {"OK", "ERROR"}:
        raise BridgeError("INVALID_RESPONSE", "Invalid response status or object")
    if status == "ERROR":
        raise BridgeError(str(data.get("code", "API_ERROR")), str(data.get("message", "Bridge error")))
    return instance, data
