[CmdletBinding()]
param(
    [string]$Destination = '',
    [string]$Cache = '',
    [switch]$Offline
)
$ErrorActionPreference = 'Stop'
Import-Module -Name (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Utility/Microsoft.PowerShell.Utility.psd1') -Force
Import-Module -Name (Join-Path $PSHOME 'Modules/Microsoft.PowerShell.Archive/Microsoft.PowerShell.Archive.psd1') -Force
function Get-ArchiveSha256([string]$Path) {
    $Stream = [IO.File]::OpenRead($Path)
    $Hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($Hasher.ComputeHash($Stream))).Replace('-', '').ToLowerInvariant() }
    finally { $Hasher.Dispose(); $Stream.Dispose() }
}
if ([string]::IsNullOrWhiteSpace($Destination)) { $Destination = Join-Path $PSScriptRoot 'runtime' }
if ([string]::IsNullOrWhiteSpace($Cache)) { $Cache = Join-Path $PSScriptRoot 'cache' }
if (-not [Environment]::Is64BitOperatingSystem) { throw 'Local analysis requires Windows x64.' }
$Destination = [IO.Path]::GetFullPath($Destination)
$Cache = [IO.Path]::GetFullPath($Cache)
New-Item -ItemType Directory -Force -Path $Destination, $Cache | Out-Null
$Lock = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'windows-lock.json') -Raw | ConvertFrom-Json
$Archive = Join-Path $Cache $Lock.python.filename
if (-not (Test-Path -LiteralPath $Archive -PathType Leaf)) {
    if ($Offline) { throw "Missing offline Python archive: $Archive" }
    $Partial = "$Archive.partial"
    Invoke-WebRequest -Uri $Lock.python.url -OutFile $Partial -UseBasicParsing
    if ((Get-ArchiveSha256 $Partial) -ne $Lock.python.sha256) {
        throw 'Python archive checksum mismatch.'
    }
    Move-Item -LiteralPath $Partial -Destination $Archive
}
if ((Get-ArchiveSha256 $Archive) -ne $Lock.python.sha256) {
    throw 'Python archive checksum mismatch.'
}
$PythonDirectory = Join-Path $Destination 'python'
New-Item -ItemType Directory -Force -Path $PythonDirectory | Out-Null
# Extraction runs under a directory explicitly selected by the caller; no
# pre-existing directories are deleted or moved by this installer.
Expand-Archive -LiteralPath $Archive -DestinationPath $PythonDirectory -Force
$Python = Join-Path $PythonDirectory 'python.exe'
$Arguments = @((Join-Path $PSScriptRoot 'install_runtime.py'), '--destination', $Destination,
    '--cache', $Cache, '--lock', (Join-Path $PSScriptRoot 'windows-lock.json'))
if ($Offline) { $Arguments += '--offline' }
& $Python @Arguments
if ($LASTEXITCODE -ne 0) { throw 'Basic Pitch runtime installation failed.' }
Write-Host "Installed local analysis in $Destination"
