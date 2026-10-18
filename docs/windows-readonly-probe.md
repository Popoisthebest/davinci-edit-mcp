# Windows 실기기 조회 전용 진단

먼저 이 진단만 실행합니다. 클립 편집·프로젝트 생성/전환/저장·미디어 import·승인 생성·Fusion prefs 변경·상주 브리지 시작을 하지 않습니다. 실제 편집 검증은 Console과 Utility 결과를 확인한 뒤 사용자의 후속 승인에 따릅니다. v0.4 코드의 존재나 CI 통과는 이 순서를 생략하는 근거가 아닙니다.

Resolve에 대해서는 읽기 전용입니다. Win32 파일 읽기/쓰기 검사는 새 `%LOCALAPPDATA%\ResolveMCPProbe_<UUID>` 아래에만 진단 파일을 만듭니다. 기존 프로젝트·미디어·v0.2/현재 브리지·mailbox·세션 키·승인 파일은 읽거나 변경하지 않습니다. 기존 설치를 업그레이드하는 `Install.ps1`은 이 단계에 필요하지 않습니다.

## 실행

수정된 PR #1 또는 #2의 소스를 Windows에 준비하고 저장소 루트에서 PowerShell을 실행합니다. Python 3.12만 필요하며 pip/MCP/Lupa 설치는 필요하지 않습니다.

```powershell
$info = (& py -3.12 .\scripts\PrepareProbe.py --install-utility) | ConvertFrom-Json
$info
```

전용 새 폴더에 Console/Utility용 자체 완결 Lua 파일과 `probe-info.json`을 생성합니다. 현재 사용자/SYSTEM 전용 ACL을 새 폴더에 적용하며, `--install-utility`는 고유한 `ResolveMCP_ReadOnlyProbe_<ID>.lua` 메뉴 항목만 추가합니다. 기존 항목을 덮어쓰지 않습니다. 같은 명령을 다시 실행하면 새로운 진단 폴더/항목을 만듭니다.

1. Console: 아래 PowerShell 명령으로 출력된 한 줄을 Resolve Lua 콘솔에서 실행합니다.

   ```powershell
   'dofile([[' + $info.console_script + ']])'
   ```

   이 `dofile`은 사용자가 지정한 신뢰하는 진단 파일을 한 번 시작하는 명령입니다. 내부 모듈은 파일을 찾아 실행하지 않습니다. 한글 사용자 경로에서 Console의 `dofile` 자체가 실패하면 다음으로 파일 내용을 복사하고 Lua 콘솔에 붙여넣어 실행할 수 있습니다. Console의 붙여넣기/실행 UI 동작 자체도 아직 실기기 미검증입니다.

   ```powershell
   Get-Content -Raw -Encoding UTF8 -LiteralPath $info.console_script | Set-Clipboard
   ```

2. Utility: Workspace → Scripts → Utility에서 `$info.utility_menu_script`에 표시된 파일명과 일치하는 `ResolveMCP_ReadOnlyProbe_<ID>`를 한 번 실행합니다. 메뉴가 새 파일을 아직 표시하지 않으면 작업을 수동으로 보존하고 Resolve를 다시 연 뒤 확인합니다. 진단 준비 도구가 Resolve를 종료하거나 프로젝트를 저장하지는 않습니다.

각 실행은 즉시 종료되며 `Console-<UUID>` / `Utility-<UUID>` 별도 하위 폴더와 `result.json`을 남깁니다. 같은 Resolve 프로세스에서 반복 실행해도 독립된 새 폴더를 사용합니다.

```powershell
Get-ChildItem -LiteralPath $info.probe_root -Filter result.json -Recurse |
    ForEach-Object { Get-Content -Raw -Encoding UTF8 -LiteralPath $_.FullName }
```

## 결과 해석

- `GLOBALS`: 전역 ffi/bit의 실제 사용 함수 전체를 점검합니다. require/package는 필요하지 않습니다.
- `MODULE_GRAPH`: 고정 내부 registry로 모든 모듈의 정의를 로드합니다. v0.4에서도 편집 dispatcher는 구성하지 않습니다.
- `BRIDGE_HOST_FUNCTIONS`: 실제 상주 브리지에 필요한 bmd.wait/os.time 제공 여부를 확인하되 상주 루프는 실행하지 않습니다.
- `FFI_WIN32_CALL`: ffi.typeof/new 및 kernel32 GetCurrentProcessId의 실제 호출입니다.
- `WIN32_FILE_IO`: 별도 새 폴더의 한글 파일을 실제 Win32 API로 생성·읽기·교체·재읽기합니다.
- `HMAC_VECTOR`, `AUTHENTICATED_CHANNEL`: 기존 HMAC 벡터, 변조 거부, 중복 응답, 서명된 데이터 파일 왕복을 확인합니다. 실제 mailbox의 키를 사용하지 않습니다.
- `QUERY_*`: 버전·현재 프로젝트/타임라인·프로젝트/타임라인/트랙/미디어 풀·렌더 설정·클립 배치를 조회합니다. 이름이나 미디어 경로 전체를 진단 JSON에 저장하지 않습니다.
- `RESULT=PASS`: 해당 실행 환경의 검사 통과입니다. 실제 편집은 `NOT_RUN`이며 편집 성공을 뜻하지 않습니다.
- `PARTIAL`/`SKIP`: 프로젝트/타임라인이 열려 있지 않아 해당 조회가 수행되지 않았습니다. PASS로 계산하지 않습니다.
- `FAIL`: 실패한 단계와 상세를 확인합니다. 공유키나 승인 권한을 낮추거나 임의 코드 실행 경로로 우회하지 않습니다.

`context`는 준비한 파일의 진입점 표식이며 Resolve UI를 자동 감지한 결과가 아닙니다. 해당 파일을 안내된 Console/Utility에서 실행했는지 사용자가 확인해야 합니다. Console 결과와 Utility 결과는 서로 대체할 수 없습니다. 두 `result.json`의 context, resolve_version, result, checks와 오류가 발생했다면 콘솔 출력을 전달해 주세요. 그 결과를 검토하기 전에는 실기기 편집 검사나 `--enable-writes`를 실행하지 않습니다.

## 호환성·구조 기록

사용자 제공 증거: Resolve 21.1.1.10 Free의 Console에서 require/package는 nil이고 전역 ffi/bit가 존재하며 ffi.typeof('int')가 성공했습니다. 이는 Win32 DLL 함수와 파일 I/O 성공, 모든 bit 함수의 존재, Utility 환경을 입증하지 않습니다. 이 문서의 진단 실행 결과는 아직 사용자 실기기 미검증입니다.

기존 PR #1의 require 호출은 native.lua의 ffi 1곳·경로 검사 bit 1곳, crypto.lua의 bit 1곳으로 총 3곳입니다. PR #2에는 native.lua의 canonical 경로 검사 bit 1곳이 더 있어 총 4곳입니다. 다른 require 호출은 없었습니다. 종전 시작 코드의 debug.getinfo, 파일별 dofile과 설치 launcher의 dofile 의존성도 함께 제거했습니다.

`runtime.lua`는 전역 라이브러리의 실제 사용 메서드를 검사하고 실패 시 중단합니다. `bundle.py`는 신뢰하는 고정 파일 목록을 Lua factory로 묶습니다. `loader.lua`는 이 registry만 허용하고 캐시·순환 의존성·반환 타입을 검사합니다. package.path, package.preload, debug, loadfile, dofile, loadstring을 통한 내부 탐색/실행은 없습니다. 요청 데이터는 계속 인증된 데이터로만 해석됩니다. HMAC·RPC allowlist·경로/권한 검사·프로젝트 보호·로컬 승인 조건은 유지합니다.

자동 검사: 실제 LuaJIT에 ffi/bit 전역을 주입한 뒤 require/package/io/debug/파일 로더를 제거해 회귀 검사합니다. Windows CI는 실제 FFI/Win32를 호출하지만 Resolve 객체는 모의입니다. 사용자 PC의 Console/Utility 결과를 대신하지 않습니다.

변경 파일: bundle.py, runtime.lua, loader.lua, probe.lua, native.lua, crypto.lua, ResolveMCP3.lua, Install.ps1, PrepareProbe.py, 로더/Win32/기존 통신 회귀 테스트 및 문서입니다. 복구 시 새 `utility_menu_script` 항목만 수동 제거하고 진단 폴더를 보관 또는 정리하면 됩니다. 현재 브리지 활성 manifest와 원본 프로젝트는 복구 대상이 아닙니다.
