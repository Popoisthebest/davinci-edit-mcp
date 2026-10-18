"""Local stdio tools. No HTTP listener, code-execution tool or implicit writes."""

import argparse
import json
from pathlib import Path
from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .transport import Mailbox
from .editing import Editor, approve, load_approval, prepare_media_root

Frame = Annotated[int, Field(strict=True, ge=0, le=2147483647)]
TrackIndex = Annotated[int, Field(strict=True, ge=1, le=16)]
MediaType = Annotated[int, Field(strict=True, ge=1, le=2)]
READ_HINT = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
EDIT_HINT = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False)


def build_server(mailbox: Mailbox) -> FastMCP:
    server = FastMCP("ResolveMCP v0.4 (read-only unless locally approved)")
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
        server.add_tool(make_tool(operation), name=name, description=description, annotations=READ_HINT)
    if isinstance(mailbox, Editor):
        # Enabling tools does not grant permission. Python and Lua recheck the
        # local approval and fresh project ownership on every editing call.
        @server.tool(annotations=EDIT_HINT)
        def resolve_create_test_project() -> dict:
            """Create the locally approved NEW test project; all projects must be closed."""
            return mailbox.call('create_test_project')

        @server.tool(annotations=EDIT_HINT)
        def resolve_create_bin(name: str) -> dict:
            """Create a ResolveMCP_TEST_BIN_<name> bin in the owned test project."""
            return mailbox.call('create_bin',name=name)

        @server.tool(annotations=EDIT_HINT)
        def resolve_import_media(bin_id: str, path: str) -> dict:
            """Import one copied fixture from the locally approved test media folder."""
            return mailbox.call('import_media',bin_id=bin_id,path=path)

        @server.tool(annotations=EDIT_HINT)
        def resolve_create_timeline(name: str) -> dict:
            """Create a new 1080x1920, 30fps timeline at frame zero in the test project."""
            return mailbox.call('create_timeline',name=name)

        @server.tool(annotations=EDIT_HINT)
        def resolve_duplicate_timeline(timeline_id: str, name: str) -> dict:
            """Duplicate only a timeline created by this bridge in the test project."""
            return mailbox.call('duplicate_timeline',timeline_id=timeline_id,name=name)

        @server.tool(annotations=EDIT_HINT)
        def resolve_add_track(timeline_id: str, track_type: Literal['video','audio']) -> dict:
            """Explicitly add a video or stereo audio track to an owned test timeline."""
            return mailbox.call('add_track',timeline_id=timeline_id,track_type=track_type)

        @server.tool(annotations=READ_HINT)
        def resolve_plan_append(timeline_id: str, media_id: str, media_type: MediaType, track_index: TrackIndex,
                                record_frame: Frame, source_in: Frame, source_out: Frame) -> dict:
            """Validate placement without changing Resolve. Source range is [in,out), exact 30fps only."""
            return mailbox.call('plan_append',timeline_id=timeline_id,media_id=media_id,media_type=media_type,
                                track_index=track_index,record_frame=record_frame,source_in=source_in,source_out=source_out)

        @server.tool(annotations=EDIT_HINT)
        def resolve_append_clip(timeline_id: str, media_id: str, media_type: MediaType, track_index: TrackIndex,
                                record_frame: Frame, source_in: Frame, source_out: Frame) -> dict:
            """Append one clip at an exact track/frame in the owned test timeline and verify readback."""
            return mailbox.call('append_clip',timeline_id=timeline_id,media_id=media_id,media_type=media_type,
                                track_index=track_index,record_frame=record_frame,source_in=source_in,source_out=source_out)

        @server.tool(annotations=EDIT_HINT)
        def resolve_save_test_project() -> dict:
            """Explicitly save only the fresh, owned, locally approved test project."""
            return mailbox.call('save_test_project')
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve MCP: read-only by default")
    parser.add_argument("--mailbox", type=Path)
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--enable-writes", action="store_true", help="Expose editing tools; requires an expiring local approval")
    parser.add_argument("--project-name")
    parser.add_argument("--media-root", type=Path)
    parser.add_argument("--confirm-project-name")
    parser.add_argument("--approval-minutes", type=int, default=30)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--stop", action="store_true")
    mode.add_argument("--rotate-session", action="store_true")
    mode.add_argument("--prepare-media-root", type=Path, metavar="NEW_DIRECTORY")
    mode.add_argument("--approve-test-project", action="store_true")
    mode.add_argument("--revoke-approval", action="store_true")
    args = parser.parse_args()
    mailbox = (Editor if args.enable_writes else Mailbox)(args.mailbox, args.timeout)
    if args.prepare_media_root:
        prepare_media_root(mailbox,args.prepare_media_root)
        print('Created a new dedicated test media folder. Copy disposable fixtures into it; no original media is modified.')
    elif args.approve_test_project:
        if not args.project_name or not args.media_root or not args.confirm_project_name:
            parser.error('--project-name, --media-root and --confirm-project-name are required')
        value = approve(mailbox,args.project_name,args.media_root,args.confirm_project_name,args.approval_minutes)
        print(f'Approved NEW test project {value.project_name} until epoch {value.expires}. Existing projects cannot be reused.')
    elif args.revoke_approval:
        with mailbox._locked():
            from .transport import safe_path
            safe_path(mailbox.root/'approval.txt').unlink(missing_ok=True)
        print('Approval revoked. No further edits are allowed; in-flight API calls cannot be cancelled.')
    elif args.rotate_session:
        mailbox.rotate_session()
        print("Session rotated. Restart the Lua bridge and MCP server.")
    elif args.stop:
        print(json.dumps(mailbox.call("stop")))
    elif args.self_test:
        for operation in ("ping", "current_project", "current_timeline", "projects", "timelines", "tracks", "media_pool", "render_settings", "timeline_items"):
            print(operation + ": " + json.dumps(mailbox.call(operation), ensure_ascii=False))
        print("RESOLVE MCP v0.4 READ-ONLY: PASS")
    else:
        if args.enable_writes:
            load_approval(mailbox)
        build_server(mailbox).run(transport="stdio")


if __name__ == "__main__":
    main()
