# Native development bootstrap, NOT the complete scientific installer.
# No preinstalled Python/Conda, Bash, WSL, administrator privileges or env updates.
[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'DockingUniversalPreview'),
    [string]$CondaExe = '',
    [string]$ManagerRoot = '',
    [switch]$BootstrapOnly,
    [switch]$PrivateBrowser,
    [switch]$AcceptDevelopmentPreview
)
$ErrorActionPreference = 'Stop'
if (-not $AcceptDevelopmentPreview) {
    throw 'Native Windows is still a development preview. See docs/cross-platform-compatibility.md. Explicitly pass -AcceptDevelopmentPreview to test the bootstrap.'
}
if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw 'This installer must run in native Windows PowerShell, not WSL or Bash.'
}
if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
    throw 'This preview requires native x64 Windows and 64-bit PowerShell.'
}
$Destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $Destination) {
    throw 'The destination already exists. Choose a new folder; existing/partial installations are never overwritten or deleted.'
}
$saved = @{}
foreach ($key in @('PYTHONHOME', 'PYTHONPATH', 'PYTHONUTF8', 'PYTHONIOENCODING', 'CONDA_PKGS_DIRS', 'CONDA_ENVS_PATH', 'CONDARC', 'PATH')) {
    $saved[$key] = [Environment]::GetEnvironmentVariable($key, 'Process')
}
try {
    Remove-Item Env:PYTHONHOME -ErrorAction SilentlyContinue
    Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    # Conda's redirected plan/error output must support non-ASCII destinations
    # even on a Windows console whose legacy code page cannot represent them.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $ownedManager = -not $CondaExe
    if ($ownedManager) {
        # Windows PowerShell/.NET alone starts this path. Do not discover or
        # modify a user's Conda/Python, shell profile, system PATH or registry.
        $asset = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'dependencies/miniforge-windows.json') -Raw | ConvertFrom-Json
        $uri = [Uri]$asset.url
        if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'github.com' -or
            $uri.AbsolutePath -ne "/conda-forge/miniforge/releases/download/$($asset.version)/$($asset.filename)" -or
            $asset.filename -ne [IO.Path]::GetFileName($asset.filename) -or $asset.sha256 -notmatch '^[a-f0-9]{64}$') {
            throw 'The pinned Miniforge download record is invalid; nothing was downloaded.'
        }
        # Do not disable Constructor's space/Unicode path restrictions. The
        # application target may contain either; use a separate, private
        # per-user manager with a fresh installation identity.
        if (-not $ManagerRoot) { $ManagerRoot = Join-Path $env:LOCALAPPDATA 'DockingUniversal/managers' }
        $ManagerRoot = [IO.Path]::GetFullPath($ManagerRoot)
        if ($ManagerRoot -match '[^\x21-\x7E]') {
            throw 'Miniforge requires a space-free ASCII manager folder. Choose a writable -ManagerRoot with that property; the application destination may still contain spaces or Unicode. No existing dependency was changed.'
        }
        $installId = [Guid]::NewGuid().ToString('N')
        $manager = Join-Path $ManagerRoot $installId
        if (Test-Path -LiteralPath $manager) { throw 'The private manager identity already exists; nothing was overwritten.' }
        New-Item -ItemType Directory -Path $Destination -ErrorAction Stop | Out-Null
        $bootstrap = Join-Path $Destination '.bootstrap'
        New-Item -ItemType Directory -Path $bootstrap | Out-Null
        $installer = Join-Path $bootstrap $asset.filename
        $managerStatus = Join-Path $bootstrap 'manager-status.json'
        $record = @{ status = 'downloading'; asset = $asset; private_prefix = $manager; install_id = $installId }
        function Save-ManagerStatus {
            [IO.File]::WriteAllText($managerStatus, ($record | ConvertTo-Json -Depth 8), [Text.UTF8Encoding]::new($false))
        }
        Save-ManagerStatus
        try {
            Write-Host 'Downloading the verified private dependency manager. No preinstalled Python or Conda is needed.'
            $oldProgress = $ProgressPreference
            $oldTls = [Net.ServicePointManager]::SecurityProtocol
            try {
                $ProgressPreference = 'SilentlyContinue'
                [Net.ServicePointManager]::SecurityProtocol = $oldTls -bor [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -UseBasicParsing -Uri $asset.url -OutFile $installer -TimeoutSec 300
            } finally {
                $ProgressPreference = $oldProgress
                [Net.ServicePointManager]::SecurityProtocol = $oldTls
            }
            if ((Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
                throw 'Miniforge checksum mismatch. The downloaded file was NOT executed.'
            }
            $record.status = 'installing'; Save-ManagerStatus
            New-Item -ItemType Directory -Path $ManagerRoot -Force | Out-Null
            Write-Host 'Installing the private dependency manager. This may take a few minutes.'
            # Constructor requires /D last and unquoted, including spaces.
            # NoRegistry/NoShortcuts also prevent unrelated user-level setup.
            $installerArgs = "/InstallationType=JustMe /RegisterPython=0 /AddToPath=0 /NoRegistry=1 /NoShortcuts=1 /S /D=$manager"
            $process = Start-Process -FilePath $installer -ArgumentList $installerArgs -Wait -PassThru -NoNewWindow `
                -RedirectStandardOutput (Join-Path $bootstrap 'manager-install.log') `
                -RedirectStandardError (Join-Path $bootstrap 'manager-install.stderr.log')
            if ($process.ExitCode -ne 0) { throw "Private Miniforge installation failed (exit $($process.ExitCode)). See .bootstrap logs; partial files were retained." }
            $CondaExe = Join-Path $manager 'Scripts/conda.exe'
            if (-not (Test-Path -LiteralPath $CondaExe -PathType Leaf) -or
                -not (Test-Path -LiteralPath (Join-Path $manager 'python.exe') -PathType Leaf)) {
                throw 'The private installer did not produce its required Python/Conda executables.'
            }
            $owner = @{ schema = 'docking-universal-private-manager-v1'; installation = $Destination; install_id = $installId; sha256 = $asset.sha256 }
            $ownerPath = Join-Path $manager 'docking-universal-owner.json'
            if (Test-Path -LiteralPath $ownerPath) { throw 'Refusing to replace a pre-existing private-manager owner record.' }
            [IO.File]::WriteAllText($ownerPath, ($owner | ConvertTo-Json), [Text.UTF8Encoding]::new($false))
            $record.status = 'installed'; Save-ManagerStatus
            # Process-local DLL/tool paths only; restored below. Never write
            # either the user's or the machine's persistent PATH.
            $env:PATH = "$manager;$manager\Scripts;$manager\Library\bin;$($env:PATH)"
            $env:CONDA_PKGS_DIRS = Join-Path $bootstrap 'packages'
            $env:CONDA_ENVS_PATH = Join-Path $Destination 'runtimes'
            $env:CONDARC = Join-Path $bootstrap 'condarc.yml'
            [IO.File]::WriteAllText($env:CONDARC, "channels:`n  - conda-forge`nchannel_priority: strict`n", [Text.UTF8Encoding]::new($false))
        } catch {
            $record.status = 'failed'; $record.error = $_.Exception.Message; Save-ManagerStatus
            throw
        }
    }
    $CondaExe = (Resolve-Path -LiteralPath $CondaExe).Path
    if ([IO.Path]::GetExtension($CondaExe) -ne '.exe') {
        throw 'Pass the native conda.exe, not a .bat or shell function.'
    }
    $base = Split-Path -Parent (Split-Path -Parent $CondaExe)
    $python = Join-Path $base 'python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw 'Native Conda Python was not found.' }
    $installerOptions = @('--destination', $Destination, '--conda', $CondaExe)
    if ($BootstrapOnly) { $installerOptions += '--bootstrap-only' }
    if ($PrivateBrowser) { $installerOptions += '--private-browser' }
    if ($ownedManager) { $installerOptions += @('--owned-manager', '--manager-root', $ManagerRoot) }
    & $python (Join-Path $PSScriptRoot 'tools/install_native_windows.py') @installerOptions
    if ($LASTEXITCODE -ne 0) { throw 'Native bootstrap failed. Inspect bootstrap-status.json in the destination; partial files were retained.' }
} finally {
    foreach ($key in $saved.Keys) {
        [Environment]::SetEnvironmentVariable($key, $saved[$key], 'Process')
    }
}
