param([switch]$SelfTest, [switch]$StopBridge, [switch]$RotateSession)
$ErrorActionPreference = 'Stop'
$root = Join-Path $env:LOCALAPPDATA 'ResolveMCPNext'
$active = Get-Content -Raw -LiteralPath (Join-Path $root 'active.json') | ConvertFrom-Json
$arguments = @('-m', 'resolve_mcp.server')
if (([int]$SelfTest.IsPresent + [int]$StopBridge.IsPresent + [int]$RotateSession.IsPresent) -gt 1) { throw 'Choose one operation.' }
if ($SelfTest) { $arguments += '--self-test' }
if ($StopBridge) { $arguments += '--stop' }
if ($RotateSession) { $arguments += '--rotate-session' }
& $active.python @arguments
if ($LASTEXITCODE -ne 0) { throw "ResolveMCP exited with status $LASTEXITCODE" }
