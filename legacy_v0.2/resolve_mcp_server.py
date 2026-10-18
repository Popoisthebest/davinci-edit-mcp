"""Read-only DaVinci Resolve 21.1 Free MCP server for Windows.

Local stdio MCP only; no HTTP listener or arbitrary Lua execution API.
Run with --self-test before registering with an MCP client.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import threading
import time
import uuid

from mcp.server.fastmcp import FastMCP

MAILBOX = Path(os.environ["LOCALAPPDATA"]) / "ResolveMCP"
PREFS = (
    Path(os.environ["APPDATA"])
    / "Blackmagic Design" / "DaVinci Resolve" / "Support"
    / "Fusion" / "Profiles" / "Default" / "Fusion.prefs"
)
COMMAND = MAILBOX / "command_v2.lua"
CALL_LOCK = threading.Lock()
OPS = frozenset({"ping", "current_project", "current_timeline", "stop"})


def _decode_hex(value: str) -> str:
    raw = bytes.fromhex(value)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def call_resolve(op: str, timeout: float = 15.0) -> dict:
    """Exchange one allowlisted command with the Resolve Lua bridge."""
    if op not in OPS:
        raise ValueError("Operation not permitted")
    if not PREFS.is_file():
        raise RuntimeError("Fusion.prefs not found; start DaVinci Resolve first")
    MAILBOX.mkdir(parents=True, exist_ok=True)
    with CALL_LOCK:
        rid = uuid.uuid4().hex
        payload = f'return {{ id = "{rid}", op = "{op}" }}'
        temp = MAILBOX / f"command_v2.{rid}.tmp"
        try:
            temp.write_text(payload, encoding="ascii")
            os.replace(temp, COMMAND)
        finally:
            temp.unlink(missing_ok=True)

        prefix = f"{rid}|"
        until = time.monotonic() + timeout
        while time.monotonic() < until:
            try:
                raw = PREFS.read_bytes().decode("latin-1")
            except (OSError, ValueError):
                time.sleep(0.2)
                continue
            pos = raw.find(prefix)
            if pos >= 0:
                tail = raw[pos:].split('"', 1)[0].split("\\", 1)[0]
                line = tail.split("\n", 1)[0].split("\r", 1)[0]
                fields = line.split("|")
                if len(fields) >= 3 and fields[0] == rid:
                    if fields[1] != "OK":
                        raise RuntimeError(f"Resolve replied: {fields[2]}")
                    return _parse_reply(fields)
            time.sleep(0.2)
        raise TimeoutError(
            "Resolve bridge did not respond in time. Run Workspace > Scripts > "
            "Utility > ResolveMCP once, and check the Lua console."
        )


def _parse_reply(fields: list[str]) -> dict:
    kind = fields[2]
    if kind == "PING" and len(fields) >= 4:
        return {"connected": True, "resolve_version": _decode_hex(fields[3])}
    if kind == "STOPPED":
        return {"stopped": True}
    if kind == "PROJECT" and len(fields) >= 4:
        if fields[3] == "NONE":
            return {"project_open": False}
        if len(fields) >= 5:
            return {"project_open": True, "name": _decode_hex(fields[3]),
                    "timeline_count": int(fields[4])}
    if kind == "TIMELINE" and len(fields) >= 4:
        if fields[3] == "NONE":
            return {"timeline_open": False}
        if len(fields) >= 8:
            return {"timeline_open": True, "name": _decode_hex(fields[3]),
                    "video_tracks": int(fields[4]), "audio_tracks": int(fields[5]),
                    "start_frame": int(fields[6]), "end_frame": int(fields[7])}
    raise RuntimeError(f"Unrecognized bridge response: {kind}")


mcp = FastMCP("ResolveMCP ReadOnly")


@mcp.tool()
def resolve_connection() -> dict:
    """Read DaVinci Resolve version and verify the local bridge connection."""
    return call_resolve("ping")


@mcp.tool()
def resolve_current_project() -> dict:
    """Read the current project's name and number of timelines. No changes."""
    return call_resolve("current_project")


@mcp.tool()
def resolve_current_timeline() -> dict:
    """Read active timeline name, track counts and frame range. No changes."""
    return call_resolve("current_timeline")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        for op in ("ping", "current_project", "current_timeline"):
            try:
                print(f"{op}: {call_resolve(op)}")
            except Exception as error:
                print(f"{op}: FAIL — {error}", file=sys.stderr)
                raise SystemExit(1) from error
        print("RESOLVE MCP BRIDGE: PASS")
    elif args.stop:
        print(call_resolve("stop"))
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
