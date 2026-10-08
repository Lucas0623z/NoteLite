param(
    [string]$Compiler,
    [string]$OutputDirectory
)
$ErrorActionPreference = 'Stop'
$repository = Split-Path -Parent $PSScriptRoot
$sourceDirectory = Join-Path $repository 'native\audio'
if (-not $OutputDirectory) { $OutputDirectory = Join-Path $sourceDirectory 'build' }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
if (-not $Compiler) {
    # Standard Windows/CI shells do not put cl.exe on PATH. Import the installed
    # developer environment without requiring a special launching shell.
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    if (Test-Path -LiteralPath $vswhere) {
        $installation = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
        if ($installation) {
            $environmentScript = Join-Path $installation 'Common7\Tools\VsDevCmd.bat'
            if (Test-Path -LiteralPath $environmentScript) {
                $environmentLines = & cmd.exe /d /s /c "`"$environmentScript`" -no_logo -arch=x64 >nul && set"
                if ($LASTEXITCODE -ne 0) { throw 'Could not initialize the installed Visual Studio C compiler.' }
                foreach ($line in $environmentLines) {
                    $separator = $line.IndexOf('=')
                    if ($separator -gt 0) {
                        [Environment]::SetEnvironmentVariable($line.Substring(0, $separator), $line.Substring($separator + 1), 'Process')
                    }
                }
                $candidate = Get-Command cl -ErrorAction SilentlyContinue
                if ($candidate) { $Compiler = $candidate.Source }
            }
        }
    }
}
if (-not $Compiler) {
    foreach ($name in @('gcc', 'clang', 'cl')) {
        $candidate = Get-Command $name -ErrorAction SilentlyContinue
        if ($candidate) { $Compiler = $candidate.Source; break }
    }
}
if (-not $Compiler) {
    # CLion's Windows distribution includes an offline MinGW compiler.
    foreach ($root in @('C:\Program Files\JetBrains', 'C:\', 'D:\')) {
        $installs = Get-ChildItem -LiteralPath $root -Directory -Filter 'CLion*' -ErrorAction SilentlyContinue
        foreach ($install in $installs) {
            $candidate = Join-Path $install.FullName 'bin\mingw\bin\gcc.exe'
            if (Test-Path -LiteralPath $candidate) { $Compiler = $candidate; break }
        }
        if ($Compiler) { break }
    }
}
if (-not $Compiler) { throw 'A Windows C compiler is required. Run from a Visual Studio developer shell or pass -Compiler C:\path\to\gcc.exe. The vendored audio source needs no network access.' }
$executable = Join-Path $OutputDirectory 'NoteLiteAudio.exe'
$main = Join-Path $sourceDirectory 'main.c'
$pitch = Join-Path $sourceDirectory 'pitch.c'
$compilerName = [IO.Path]::GetFileNameWithoutExtension($Compiler)
Push-Location $OutputDirectory
try {
    if ($compilerName -eq 'cl' -or $compilerName -eq 'clang-cl') {
        & $Compiler /nologo /O2 /W4 /std:c11 $main $pitch "/Fe:$executable" /link /SUBSYSTEM:CONSOLE
    } else {
        & $Compiler -std=c11 -O2 -Wall -Wextra -municode -static-libgcc $main $pitch -o $executable -lm
    }
    if ($LASTEXITCODE -ne 0) { throw "Native audio compilation failed with exit code $LASTEXITCODE" }
    & $executable --version
    if ($LASTEXITCODE -ne 0) { throw 'Native audio executable did not start.' }
    Write-Output "Built $executable"
} finally { Pop-Location }
