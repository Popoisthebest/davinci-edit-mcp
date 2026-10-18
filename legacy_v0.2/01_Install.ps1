$ErrorActionPreference = 'Stop'
$sourceLua = Join-Path $PSScriptRoot 'ResolveMCP.lua'
$sourcePy = Join-Path $PSScriptRoot 'resolve_mcp_server.py'
$utility = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility'
$server = Join-Path $env:LOCALAPPDATA 'ResolveMCP\server'
$venvPy = Join-Path $server '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPy)) { throw 'Python venv missing: follow previous setup to create ResolveMCP\server\.venv' }
& $venvPy -c 'from mcp.server.fastmcp import FastMCP'
if ($LASTEXITCODE -ne 0) { throw 'Python MCP dependency check failed' }
New-Item -ItemType Directory -Force -Path $utility, $server | Out-Null
$destLua = Join-Path $utility 'ResolveMCP.lua'
$destPy = Join-Path $server 'resolve_mcp_server.py'
foreach ($target in @($destLua, $destPy)) {
  if (Test-Path -LiteralPath $target) {
    $back = "$target.bak-$(Get-Date -Format yyyyMMdd-HHmmss)"
    Copy-Item -LiteralPath $target -Destination $back
    Write-Host "BACKUP: $back"
  }
}
Copy-Item -LiteralPath $sourceLua -Destination $destLua -Force
Copy-Item -LiteralPath $sourcePy -Destination $destPy -Force
Write-Host "INSTALLED Lua: $destLua"
Write-Host "INSTALLED MCP: $destPy"
Write-Host 'CLOSE Resolve (stops old v0.1 bridge), reopen it, then run Workspace > Scripts > Utility > ResolveMCP once.'
