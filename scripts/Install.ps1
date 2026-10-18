param([string]$Python = 'py')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (Get-Process -Name Resolve -ErrorAction SilentlyContinue) { throw 'Close Resolve before installation or upgrade.' }
$repo = Split-Path -Parent $PSScriptRoot
$pythonArgs = @()
if ([IO.Path]::GetFileNameWithoutExtension($Python) -eq 'py') { $pythonArgs = @('-3.12') }
& $Python @pythonArgs -c 'import sys; assert sys.version_info[:2] == (3,12), "Python 3.12 is required"'
if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 check failed' }
$version = (& $Python @pythonArgs -c 'import pathlib,tomllib,sys; print(tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))["project"]["version"])' (Join-Path $repo 'pyproject.toml')).Trim()
if ($LASTEXITCODE -ne 0 -or $version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid package version' }
$root = Join-Path $env:LOCALAPPDATA 'ResolveMCPNext'
$utility = Join-Path $env:APPDATA 'Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\ResolveMCPNext.lua'

function Assert-NoReparse([string]$Path) {
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            if ((Get-Item -Force -LiteralPath $current).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Reparse path forbidden: $current" }
        }
        $parent = [IO.Path]::GetDirectoryName($current)
        if ($parent -eq $current) { break }
        $current = $parent
    }
}
Assert-NoReparse $root
Assert-NoReparse $utility
New-Item -ItemType Directory -Force -Path $root | Out-Null
# Dedicated application root only; never change ACLs on existing Resolve folders.
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetOwner($sid)
$acl.SetAccessRuleProtection($true, $false)
foreach ($identity in @($sid.Value, 'S-1-5-18')) {
    $rule = New-Object Security.AccessControl.FileSystemAccessRule(
        (New-Object Security.Principal.SecurityIdentifier($identity)), 'FullControl',
        'ContainerInherit,ObjectInherit', 'None', 'Allow')
    $acl.AddAccessRule($rule)
}
Set-Acl -LiteralPath $root -AclObject $acl
$stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0,8)
$backup = Join-Path $root "backups\$stamp"
New-Item -ItemType Directory -Force -Path $backup | Out-Null
$active = Join-Path $root 'active.json'
$state = @{ ActiveExisted = (Test-Path -LiteralPath $active); UtilityExisted = (Test-Path -LiteralPath $utility) }
if ($state.ActiveExisted) { Copy-Item -LiteralPath $active -Destination (Join-Path $backup 'active.json') }
if ($state.UtilityExisted) { Copy-Item -LiteralPath $utility -Destination (Join-Path $backup 'utility.lua') }
$state | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $backup 'state.json') -Encoding UTF8
$release = Join-Path $root "releases\$version-$stamp"
New-Item -ItemType Directory -Force -Path $release | Out-Null
& $Python @pythonArgs -m venv (Join-Path $release '.venv')
if ($LASTEXITCODE -ne 0) { throw "venv failed; previous installation unchanged. Backup: $stamp" }
$venvPython = Join-Path $release '.venv\Scripts\python.exe'
& $venvPython -m pip install $repo
if ($LASTEXITCODE -ne 0) { throw "Installation failed; previous installation unchanged. Backup: $stamp" }
& $venvPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Dependency compatibility check failed' }
# Initialize only the new mailbox. No Fusion.prefs or v0.2 files are touched.
& $venvPython -c 'from resolve_mcp.transport import Mailbox; Mailbox()'
if ($LASTEXITCODE -ne 0) { throw 'Mailbox initialization failed' }
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $utility) | Out-Null
$newUtility = "$utility.$stamp.tmp"
# Self-contained trusted factories: no package system/debug/path bootstrap needed.
& $venvPython -m resolve_mcp.bundle --output $newUtility
if ($LASTEXITCODE -ne 0) { throw 'Lua bundle generation failed; active installation unchanged' }
$manifest = @{ version = $version; python = $venvPython; utility = $utility; backup = $stamp }
$newActive = "$active.$stamp.tmp"
[IO.File]::WriteAllText($newActive, ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding($false)))
try {
    Move-Item -LiteralPath $newUtility -Destination $utility -Force
    Move-Item -LiteralPath $newActive -Destination $active -Force
} catch {
    # Restore the previous launcher/manifest after a partial activation.
    if ($state.UtilityExisted) { Copy-Item -LiteralPath (Join-Path $backup 'utility.lua') -Destination $utility -Force }
    else { Remove-Item -LiteralPath $utility -Force -ErrorAction SilentlyContinue }
    if ($state.ActiveExisted) { Copy-Item -LiteralPath (Join-Path $backup 'active.json') -Destination $active -Force }
    else { Remove-Item -LiteralPath $active -Force -ErrorAction SilentlyContinue }
    throw
}
Write-Host "Installed v$version; rollback backup: $stamp"
Write-Host 'Start Resolve, then Workspace > Scripts > Utility > ResolveMCPNext once.'
Write-Host 'Windows/Resolve compatibility remains unverified until the read-only self-test passes.'
