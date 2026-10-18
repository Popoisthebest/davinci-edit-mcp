$ErrorActionPreference = 'Stop'
$python = Join-Path $env:LOCALAPPDATA 'ResolveMCP\server\.venv\Scripts\python.exe'
$server = Join-Path $env:LOCALAPPDATA 'ResolveMCP\server\resolve_mcp_server.py'
if (-not (Test-Path -LiteralPath $python)) { throw "Python virtual environment not found: $python" }
if (-not (Test-Path -LiteralPath $server)) { throw "MCP server not found: $server" }
& $python $server --self-test
if ($LASTEXITCODE -ne 0) { throw 'ResolveMCP v0.2 self-test failed' }
