#!/bin/bash
# Pinned author release asset 478866068. No Homebrew or system installation.
# stdout is the verified executable path; diagnostics go to stderr.
set -euo pipefail

[[ $# -eq 0 ]] || { echo 'XcodeGen installer accepts no arguments.' >&2; exit 1; }
[[ $(uname -s) == Darwin ]] || { echo 'XcodeGen installation requires macOS.' >&2; exit 1; }
architecture=$(uname -m)
[[ $architecture == arm64 || $architecture == x86_64 ]] || { echo 'Unsupported macOS architecture.' >&2; exit 1; }
[[ -n ${RUNNER_TEMP:-} && -d $RUNNER_TEMP && ! -L $RUNNER_TEMP ]] || { echo 'A private ordinary RUNNER_TEMP directory is required.' >&2; exit 1; }
[[ $RUNNER_TEMP != *$'\n'* && $RUNNER_TEMP != *$'\r'* ]] || { echo 'Invalid temporary directory.' >&2; exit 1; }
for tool in curl python3 lipo; do
  command -v "$tool" >/dev/null || { echo "Required tool is unavailable: $tool" >&2; exit 1; }
done

# A fresh private directory prevents stale or unrelated tools from being reused.
installation=$(mktemp -d "$RUNNER_TEMP/notelite-xcodegen-2.46.0.XXXXXXXX")
archive="$installation/xcodegen.artifactbundle.zip"
echo 'Downloading the pinned official XcodeGen 2.46.0 artifact.' >&2
curl --fail --location --proto '=https' --proto-redir '=https' --tlsv1.2 \
  --connect-timeout 10 --max-time 90 --retry 2 --retry-all-errors \
  --retry-delay 2 --retry-max-time 180 \
  --output "$archive" \
  'https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.artifactbundle.zip' >&2

python3 - "$archive" "$installation/products" "$architecture" <<'PY_XCODEGEN_VALIDATOR'
import hashlib,json,os,stat,struct,sys,zipfile
from pathlib import Path,PurePosixPath

VERSION='2.46.0'
ARCHIVE_SHA256='ef6d0a23bfb7393387f98e321ffd78a487231172e2e78c48d3c26275c263fd0c'
ARCHIVE_BYTES=4286070
BINARY_SHA256='8774da746668bc18fe74e54cbaf10f2631a1fb05947cd374179aa912f14f99db'
PREFIX='xcodegen.artifactbundle/'
BIN=PREFIX+'xcodegen-2.46.0-macosx/bin/'
REQUIRED={PREFIX+'info.json',BIN+'xcodegen',BIN+'LICENSE',
          BIN+'XcodeGen_XcodeGenKit.bundle/Contents/Info.plist',
          BIN+'XcodeGen_XcodeGenKit.bundle/Contents/Resources/SettingPresets/base.yml'}

def require(condition,message):
    if not condition:raise ValueError(message)

def validate_macho(data,architecture):
    require(architecture in ('arm64','x86_64'),'Unsupported architecture')
    require(len(data)>=48 and data[:4]==b'\xca\xfe\xba\xbe','Expected official universal Mach-O')
    count=struct.unpack_from('>I',data,4)[0]
    require(count==2,'Expected both original macOS architectures')
    found=set();regions=[]
    for i in range(count):
        cpu,subtype,offset,size,alignment=struct.unpack_from('>5I',data,8+20*i)
        name={0x1000007:'x86_64',0x100000c:'arm64'}.get(cpu)
        require(name and name not in found and 48<=offset and size>=56 and offset+size<=len(data),'Invalid Mach-O architecture bounds')
        found.add(name);regions.append((offset,offset+size));segment=data[offset:offset+size]
        require(segment[:4]==b'\xcf\xfa\xed\xfe','Expected 64-bit macOS executable')
        _,thin_cpu,_,kind,commands,command_bytes,_,_=struct.unpack_from('<8I',segment)
        require(thin_cpu==cpu and kind==2 and 0<commands<=4096 and 32+command_bytes<=len(segment),'Invalid Mach-O executable header')
        cursor=32;macos=False
        for _ in range(commands):
            require(cursor+8<=32+command_bytes,'Truncated Mach-O command')
            command,length=struct.unpack_from('<2I',segment,cursor)
            require(length>=8 and cursor+length<=32+command_bytes,'Invalid Mach-O command bounds')
            if command==0x32:
                require(length>=24,'Truncated build-version command')
                macos=struct.unpack_from('<I',segment,cursor+8)[0]==1
            cursor+=length
        require(cursor==32+command_bytes and macos,'Expected actual macOS deployment metadata')
    require(found=={'arm64','x86_64'} and architecture in found,'Missing current macOS architecture')
    regions.sort();require(regions[0][1]<=regions[1][0],'Overlapping Mach-O slices')

def inspect_archive(archive,architecture):
    require(stat.S_ISREG(archive.lstat().st_mode),'Archive must be an ordinary file')
    require(archive.stat().st_size==ARCHIVE_BYTES,'Official artifact size differs')
    require(hashlib.sha256(archive.read_bytes()).hexdigest()==ARCHIVE_SHA256,'Official artifact SHA256 differs')
    with zipfile.ZipFile(archive) as source:
        entries=source.infolist();require(0<len(entries)<=512,'Invalid artifact member count')
        names=set();members={};folded=set();total=0
        for entry in entries:
            raw=entry.orig_filename.rstrip('/');path=PurePosixPath(raw)
            require(raw and (raw.startswith(PREFIX.rstrip('/')+'/') or raw==PREFIX.rstrip('/')),'Unexpected artifact root')
            require(entry.filename==entry.orig_filename and not path.is_absolute() and '\\' not in raw and ':' not in raw and
                    all(p not in ('','.','..') for p in raw.split('/')) and not any(ord(c)<32 for c in raw),'Unsafe artifact path')
            require(raw not in names and raw.casefold() not in folded,'Duplicate artifact path')
            names.add(raw);members[raw]=entry;folded.add(raw.casefold())
            mode=(entry.external_attr>>16)&0xffff
            require(stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR) and not mode&0o7000,'Linked, special or privileged artifact member')
            require(stat.S_IFMT(mode)!=stat.S_IFDIR or entry.is_dir(),'Contradictory directory member')
            total+=entry.file_size;require(0<=entry.file_size<=20*1024**2 and total<=32*1024**2,'Artifact contents are too large')
        require(REQUIRED<=names,'Official executable, license or adjacent resources are missing')
        info=json.loads(source.read(PREFIX+'info.json'))
        value=info.get('artifacts',{}).get('xcodegen',{})
        require(info.get('schemaVersion')=='1.0' and set(info.get('artifacts',{}))=={'xcodegen'} and value.get('version')==VERSION and value.get('type')=='executable','Wrong official artifact version or type')
        require(value.get('variants')==[{'supportedTriples':['x86_64-apple-macosx','arm64-apple-macosx'],'path':'xcodegen-2.46.0-macosx/bin/xcodegen'}],'Unexpected official artifact architectures or path')
        binary=source.read(BIN+'xcodegen')
        require(hashlib.sha256(binary).hexdigest()==BINARY_SHA256,'Official executable SHA256 differs')
        validate_macho(binary,architecture)
        license_data=source.read(BIN+'LICENSE')
        require(license_data.startswith(b'MIT License') and b'Copyright (c) 2018 Yonas Kolb' in license_data,'Missing original MIT license')
        for raw in names:
            for parent in PurePosixPath(raw).parents:
                if str(parent)=='.':break
                if str(parent) in members:require(members[str(parent)].is_dir(),'A member has a file ancestor')
        return entries

def extract_verified(archive,destination,architecture):
    entries=inspect_archive(archive,architecture)
    require(not destination.exists() and not destination.is_symlink(),'Refusing to replace tools or follow an extraction link')
    require(destination.parent.is_dir() and not destination.parent.is_symlink(),'Extraction parent must be ordinary')
    destination.mkdir(mode=0o700)
    root=destination.resolve(strict=True)
    with zipfile.ZipFile(archive) as source:
        for entry in sorted(entries,key=lambda e:(len(PurePosixPath(e.filename).parts),e.filename)):
            output=root.joinpath(*PurePosixPath(entry.filename).parts)
            require(output.is_relative_to(root),'Artifact escaped private installation')
            if entry.is_dir():output.mkdir(parents=True,exist_ok=True)
            else:
                output.parent.mkdir(parents=True,exist_ok=True)
                with source.open(entry) as input_stream,output.open('xb') as output_stream:
                    import shutil
                    shutil.copyfileobj(input_stream,output_stream,1024*1024)
                output.chmod((entry.external_attr>>16)&0o777)
    require((root/(BIN+'xcodegen')).is_file() and os.access(root/(BIN+'xcodegen'),os.X_OK),'Executable permissions were not preserved')

if __name__=='__main__':
    extract_verified(Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3])
PY_XCODEGEN_VALIDATOR

binary="$installation/products/xcodegen.artifactbundle/xcodegen-2.46.0-macosx/bin/xcodegen"
lipo -verify_arch "$architecture" "$binary" >&2
actual_version=$("$binary" --version)
case ${actual_version//$'\r'/} in
  '2.46.0'|'Version: 2.46.0'|'xcodegen, version 2.46.0'|'xcodegen 2.46.0'|'XcodeGen 2.46.0') ;;
  *) echo 'The official executable did not report exact XcodeGen 2.46.0.' >&2; exit 1 ;;
esac
if [[ -n ${GITHUB_PATH:-} ]]; then
  printf '%s\n' "${binary%/*}" >> "$GITHUB_PATH"
fi
echo 'Verified official XcodeGen 2.46.0, current Mach-O architecture, MIT license and adjacent resources.' >&2
printf '%s\n' "$binary"
