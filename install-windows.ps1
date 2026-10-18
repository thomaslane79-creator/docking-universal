# Native development bootstrap, NOT the complete scientific installer.
# No Bash, WSL, Git Bash, administrator privileges, or existing-env updates.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$CondaExe = $env:CONDA_EXE,
    [switch]$AcceptDevelopmentPreview
)
$ErrorActionPreference = 'Stop'
if (-not $AcceptDevelopmentPreview) {
    throw 'Native Windows is still a development preview. See docs/cross-platform-compatibility.md. Explicitly pass -AcceptDevelopmentPreview to test the bootstrap.'
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This installer must run in native Windows PowerShell, not WSL or Bash.'
}
if (-not $CondaExe) {
    $CondaExe = (Get-Command conda.exe -ErrorAction Stop).Source
}
$CondaExe = (Resolve-Path -LiteralPath $CondaExe).Path
if ([IO.Path]::GetExtension($CondaExe) -ne '.exe') {
    throw 'Pass the native conda.exe, not a .bat or shell function.'
}
$base = (& $CondaExe info --base | Out-String).Trim()
if ($LASTEXITCODE -ne 0) { throw 'Conda could not report its native base directory.' }
$python = Join-Path $base 'python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Native Conda Python was not found.' }
& $python (Join-Path $PSScriptRoot 'tools/install_native_windows.py') --destination $Destination --conda $CondaExe
if ($LASTEXITCODE -ne 0) { throw 'Native bootstrap failed. Inspect bootstrap-status.json in the destination; partial files were retained.' }
