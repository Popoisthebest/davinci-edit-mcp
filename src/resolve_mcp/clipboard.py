"""Copy a Lua command as clipboard data after the PowerShell run has started."""
import os
import subprocess


def copy_lua_command(command: str) -> None:
    if os.name != 'nt':
        raise RuntimeError('Console clipboard launch requires Windows')
    # The fixed program reads stdin as data. Never interpolate/evaluate the Lua
    # command as PowerShell, and never expose this helper as an MCP operation.
    subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-STA', '-Command',
                    'Set-Clipboard -Value ([Console]::In.ReadToEnd())'],
                   input=command, text=True, encoding='ascii', check=True, timeout=10,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
