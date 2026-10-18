param([Parameter(Mandatory=$true)][string]$BackupId)
$ErrorActionPreference = 'Stop'
if (Get-Process -Name Resolve -ErrorAction SilentlyContinue) { throw 'Close Resolve before rollback.' }
if ($BackupId -notmatch '^\d{8}-\d{6}-[0-9a-f]{8}$') { throw 'Invalid backup identifier' }
$root = Join-Path $env:LOCALAPPDATA 'ResolveMCPNext'
$backup = Join-Path $root "backups\$BackupId"
$state = Get-Content -Raw -LiteralPath (Join-Path $backup 'state.json') | ConvertFrom-Json
$utility = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\ResolveMCPNext.lua'
$active = Join-Path $root 'active.json'
foreach ($path in @($root,$backup,$utility,$active)) {
    $current = [IO.Path]::GetFullPath($path)
    while ($current) {
        if ((Test-Path -LiteralPath $current) -and ((Get-Item -Force -LiteralPath $current).Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Reparse paths are forbidden' }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}
if ($state.ActiveExisted -and -not (Test-Path -LiteralPath (Join-Path $backup 'active.json'))) { throw 'Backup manifest missing' }
if ($state.UtilityExisted -and -not (Test-Path -LiteralPath (Join-Path $backup 'utility.lua'))) { throw 'Backup launcher missing' }
$preserve = Join-Path $root ('backups\before-rollback-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $preserve | Out-Null
if (Test-Path -LiteralPath $utility) { Copy-Item -LiteralPath $utility -Destination (Join-Path $preserve 'utility.lua') }
if (Test-Path -LiteralPath $active) { Copy-Item -LiteralPath $active -Destination (Join-Path $preserve 'active.json') }
if ($state.UtilityExisted) { Copy-Item -LiteralPath (Join-Path $backup 'utility.lua') -Destination $utility -Force }
else { Remove-Item -LiteralPath $utility -Force -ErrorAction SilentlyContinue }
if ($state.ActiveExisted) { Copy-Item -LiteralPath (Join-Path $backup 'active.json') -Destination $active -Force }
else { Remove-Item -LiteralPath $active -Force -ErrorAction SilentlyContinue }
Write-Host "Rolled back launcher and manifest. Release files and mailbox retained. Previous state: $preserve"
Write-Host 'The legacy v0.2 installation, projects, media, preferences and cache were not modified.'
