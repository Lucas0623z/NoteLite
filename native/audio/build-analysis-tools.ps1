param([Parameter(Mandatory=$true)][string]$Compiler,
      [Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$repository=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$aubio=Join-Path $repository 'local-analysis\vendor\aubio\src'
$nakamura=Join-Path $repository 'local-analysis\vendor\nakamura\Code'
if (-not (Test-Path -LiteralPath (Join-Path $aubio 'aubio.h'))) { throw 'Pinned aubio source is missing.' }
if (-not (Test-Path -LiteralPath $nakamura)) { throw 'Pinned Nakamura source is missing.' }
$destination=Join-Path $OutputDirectory 'analysis-tools'
$configuration=Join-Path $destination 'config'
New-Item -ItemType Directory -Path $configuration -Force | Out-Null
$header=@'
#define HAVE_STDLIB_H 1
#define HAVE_STDIO_H 1
#define HAVE_MATH_H 1
#define HAVE_STRING_H 1
#define HAVE_ERRNO_H 1
#define HAVE_LIMITS_H 1
#define HAVE_STDARG_H 1
#define HAVE_C99_VARARGS_MACROS 1
#define HAVE_WIN_HACKS 1
'@
[IO.File]::WriteAllText((Join-Path $configuration 'config.h'),$header,[Text.UTF8Encoding]::new($false))
$sources=@(Get-ChildItem -LiteralPath $aubio -Recurse -File -Filter '*.c' | ForEach-Object FullName)
$adapter=Join-Path $PSScriptRoot 'aubio_mono.c'
$exe=Join-Path $destination 'AubioMono.exe'
$compilerName=[IO.Path]::GetFileNameWithoutExtension($Compiler)
$msvc=$compilerName -eq 'cl' -or $compilerName -eq 'clang-cl'
$response=Join-Path $configuration 'aubio.rsp'
$argsList=if($msvc){ @('/nologo','/O2','/std:c11','/DHAVE_CONFIG_H',"/I`"$configuration`"","/I`"$aubio`"",('"'+$adapter+'"'),"/Fe:`"$exe`"") } else { @('-std=c11','-O2','-DHAVE_CONFIG_H','-municode','-static-libgcc',('-I"'+$configuration.Replace('\','/')+'"'),('-I"'+$aubio.Replace('\','/')+'"'),('"'+$adapter.Replace('\','/')+'"'),'-o',('"'+$exe.Replace('\','/')+'"')) }
$argsList+=@($sources|ForEach-Object {if($msvc){'"'+$_+'"'}else{'"'+$_.Replace('\','/')+'"'}})
if($msvc){$argsList+=@('/link','/SUBSYSTEM:CONSOLE')}else{$argsList+='-lm'}
[IO.File]::WriteAllLines($response,$argsList,[Text.UTF8Encoding]::new($false))
Push-Location $configuration
try {
    & $Compiler "@$response"
    if($LASTEXITCODE -ne 0){throw "Actual aubio compilation failed: $LASTEXITCODE"}
    & $exe --version
    if($LASTEXITCODE -ne 0){throw 'AubioMono did not start.'}
} finally {Pop-Location}
$cppCompiler=if($msvc){$Compiler}else{Join-Path (Split-Path -Parent $Compiler) 'g++.exe'}
if(-not(Test-Path -LiteralPath $cppCompiler)){throw 'Nakamura requires the corresponding C++ compiler.'}
$programs=Join-Path $destination 'nakamura'
New-Item -ItemType Directory -Path $programs -Force|Out-Null
if(-not $msvc){
    # Keep the compiler's default C runtime ABI. Forcing the CLion static
    # winpthreads archive through UCRT makes fstream crash on actual input.
    # Ship its matching small pthread DLL alongside the binaries instead.
    $pthread=Join-Path (Split-Path -Parent $cppCompiler) 'libwinpthread-1.dll'
    if(Test-Path -LiteralPath $pthread){Copy-Item -LiteralPath $pthread -Destination (Join-Path $programs 'libwinpthread-1.dll') -Force}
}
$tools=[ordered]@{ErrorDetection='ErrorDetection_v190702.cpp';RealignmentMOHMM='RealignmentMOHMM_v170427.cpp';ScorePerfmMatcher='ScorePerfmMatcher_v170101_2.cpp';midi2pianoroll='midi2pianoroll_v170504.cpp';MusicXMLToFmt3x='MusicXMLToFmt3x_v170104.cpp';MusicXMLToHMM='MusicXMLToHMM_v170104.cpp';SprToFmt3x='SprToFmt3x_v170225.cpp';Fmt3xToHmm='Fmt3xToHmm_v170225.cpp';MatchToCorresp='MatchToCorresp_v170918.cpp'}
Push-Location $configuration
try {
    foreach($name in $tools.Keys){
        $source=Join-Path $nakamura $tools[$name]
        $binary=Join-Path $programs "$name.exe"
        if($msvc){ & $cppCompiler /nologo /O2 /EHsc /std:c++14 '/DM_PI=3.14159265358979323846' $source "/Fe:$binary" /link /SUBSYSTEM:CONSOLE }
        else{ & $cppCompiler -std=c++14 -O2 '-DM_PI=3.14159265358979323846' -static-libgcc -static-libstdc++ $source -o $binary }
        if($LASTEXITCODE -ne 0){throw "Nakamura $name compilation failed: $LASTEXITCODE"}
    }
}finally{Pop-Location}
$smoke=Join-Path $configuration 'nakamura-smoke'
New-Item -ItemType Directory -Path $smoke -Force|Out-Null
$spr=Join-Path $smoke 'score_spr.txt'
$fmt=Join-Path $smoke 'score_fmt3x.txt'
$hmm=Join-Path $smoke 'score_hmm.txt'
$pre=Join-Path $smoke 'pre_match.txt'
$error=Join-Path $smoke 'error_match.txt'
$aligned=Join-Path $smoke 'aligned_match.txt'
$corresp=Join-Path $smoke 'corresp.txt'
$inputSpr="0`t0`t0.5`tC4`t80`t64`t0`n1`t0.5`t1`tD4`t80`t64`t0`n2`t1`t1.5`tE4`t80`t64`t0`n"
[IO.File]::WriteAllText($spr,$inputSpr,[Text.UTF8Encoding]::new($false))
foreach($output in @($fmt,$hmm,$pre,$error,$aligned,$corresp)){if(Test-Path -LiteralPath $output){Remove-Item -LiteralPath $output -Force}}
$commands=@(@('SprToFmt3x',$spr,$fmt),@('Fmt3xToHmm',$fmt,$hmm),@('ScorePerfmMatcher',$hmm,$spr,$pre,'0.001'),@('ErrorDetection',$fmt,$hmm,$pre,$error,'0'),@('RealignmentMOHMM',$fmt,$hmm,$error,$aligned,'0.3'),@('MatchToCorresp',$aligned,$spr,$corresp))
foreach($command in $commands){
    $binary=Join-Path $programs ($command[0]+'.exe')
    $arguments=$command[1..($command.Length-1)]
    & $binary @arguments
    if($LASTEXITCODE -ne 0){throw "Actual Nakamura I/O smoke failed in $($command[0]): $LASTEXITCODE"}
}
if(-not(Test-Path -LiteralPath $corresp) -or (Get-Item -LiteralPath $corresp).Length -eq 0){throw 'Nakamura did not produce correspondence output.'}
$pairs=@(Get-Content -LiteralPath $corresp | Where-Object {$_ -and -not $_.StartsWith('//')})
if($pairs.Count -ne 3){throw 'Nakamura smoke did not align all three notes.'}
for($index=0;$index -lt 3;$index++){
    $fields=$pairs[$index] -split '\s+'
    $expected=60+2*$index
    if($fields.Length -lt 10 -or [int]$fields[3] -ne $expected -or [int]$fields[8] -ne $expected){throw 'Nakamura smoke returned incorrect note correspondence.'}
}
Write-Output "Built actual aubio and nine Nakamura tools in $destination"
