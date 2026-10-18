$ErrorActionPreference = 'Stop'
$python = Join-Path $env:LOCALAPPDATA 'ResolveMCP\server\.venv\Scripts\python.exe'
$server = Join-Path $env:LOCALAPPDATA 'ResolveMCP\server\resolve_mcp_server.py'
& $python $server --stop
if ($LASTEXITCODE -ne 0) { throw 'Stop command failed (you can also close Resolve)' }
