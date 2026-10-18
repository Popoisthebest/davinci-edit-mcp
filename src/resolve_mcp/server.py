"""Local stdio tools. No HTTP listener, code-execution tool or implicit writes."""

import argparse
import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .transport import Mailbox


def build_server(mailbox: Mailbox) -> FastMCP:
    server = FastMCP("ResolveMCP ReadOnly v0.3")
    tools = {
        "resolve_connection": ("ping", "Read bridge version, session and capabilities."),
        "resolve_current_project": ("current_project", "Read current project without switching projects."),
        "resolve_current_timeline": ("current_timeline", "Read active timeline and frame range."),
        "resolve_projects": ("projects", "List projects in the current database folder; never open them."),
        "resolve_timelines": ("timelines", "List current project timelines without activating them."),
        "resolve_tracks": ("tracks", "Read current timeline track names and clip counts."),
        "resolve_media_pool": ("media_pool", "Read bins and media metadata without importing files."),
        "resolve_render_settings": ("render_settings", "Read render format and timeline output settings."),
        "resolve_timeline_items": ("timeline_items", "Read clip placement in the current timeline."),
    }
    for name, (operation, description) in tools.items():
        def make_tool(op):
            def tool() -> dict:
                return mailbox.call(op)
            return tool
        server.add_tool(make_tool(operation), name=name, description=description)
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve MCP: read-only by default")
    parser.add_argument("--mailbox", type=Path)
    parser.add_argument("--timeout", type=float, default=10)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--stop", action="store_true")
    mode.add_argument("--rotate-session", action="store_true")
    args = parser.parse_args()
    mailbox = Mailbox(args.mailbox, args.timeout)
    if args.rotate_session:
        mailbox.rotate_session()
        print("Session rotated. Restart the Lua bridge and MCP server.")
    elif args.stop:
        print(json.dumps(mailbox.call("stop")))
    elif args.self_test:
        for operation in ("ping", "current_project", "current_timeline", "projects", "timelines", "tracks", "media_pool", "render_settings", "timeline_items"):
            print(operation + ": " + json.dumps(mailbox.call(operation), ensure_ascii=False))
        print("RESOLVE MCP v0.3 READ-ONLY: PASS")
    else:
        build_server(mailbox).run(transport="stdio")


if __name__ == "__main__":
    main()
