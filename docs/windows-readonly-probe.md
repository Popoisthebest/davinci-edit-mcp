# Windows 실기기 조회 전용 진단

먼저 이 진단만 실행합니다. 클립 편집·프로젝트 생성/전환/저장·미디어 import·승인 생성·Fusion prefs 변경·상주 브리지 시작을 하지 않습니다. 실제 편집 검증은 Console과 Utility 결과를 확인한 뒤 사용자의 후속 승인에 따릅니다. v0.4 코드의 존재나 CI 통과는 이 순서를 생략하는 근거가 아닙니다.

Resolve에 대해서는 읽기 전용입니다. Win32 파일 읽기/쓰기 검사는 새 `%LOCALAPPDATA%\ResolveMCPProbe_<UUID>` 아래에만 진단 파일을 만듭니다. 기존 프로젝트·미디어·v0.2/현재 브리지·mailbox·세션 키·승인 파일은 읽거나 변경하지 않습니다. 기존 설치를 업그레이드하는 `Install.ps1`은 이 단계에 필요하지 않습니다.

## 실행

수정된 PR #1 또는 #2의 소스를 Windows에 준비하고 저장소 루트에서 PowerShell을 실행합니다. Python 3.12만 필요하며 pip/MCP/Lupa 설치는 필요하지 않습니다.

```powershell
$info = (& py -3.12 .\scripts\PrepareProbe.py --install-utility) | ConvertFrom-Json
$info
```

전용 새 폴더에 Console/Utility용 자체 완결 Lua 파일과 `probe-info.json`을 생성합니다. 현재 사용자/SYSTEM 전용 ACL을 새 폴더에 적용하며, `--install-utility`는 고유한 `ResolveMCP_ReadOnlyProbe_v2_<ID>.lua` 메뉴 항목만 추가합니다. 기존 항목을 덮어쓰지 않습니다. 같은 명령을 다시 실행하면 새로운 진단 폴더/항목을 만듭니다.

1. Console: 아래 PowerShell 명령으로 출력된 한 줄을 Resolve Lua 콘솔에서 실행합니다.

   ```powershell
   'dofile([[' + $info.console_script + ']])'
   ```

   이 `dofile`은 사용자가 지정한 신뢰하는 진단 파일을 한 번 시작하는 명령입니다. 내부 모듈은 파일을 찾아 실행하지 않습니다. 한글 사용자 경로에서 Console의 `dofile` 자체가 실패하면 다음으로 파일 내용을 복사하고 Lua 콘솔에 붙여넣어 실행할 수 있습니다. Console의 붙여넣기/실행 UI 동작 자체도 아직 실기기 미검증입니다.

   ```powershell
   Get-Content -Raw -Encoding UTF8 -LiteralPath $info.console_script | Set-Clipboard
   ```

2. Utility: Workspace → Scripts → Utility에서 `$info.utility_menu_script`에 표시된 파일명과 일치하는 `ResolveMCP_ReadOnlyProbe_v2_<ID>`를 한 번 실행합니다. 메뉴가 새 파일을 아직 표시하지 않으면 작업을 수동으로 보존하고 Resolve를 다시 연 뒤 확인합니다. 진단 준비 도구가 Resolve를 종료하거나 프로젝트를 저장하지는 않습니다.

이전 준비 파일은 수정 내용을 자동으로 반영하지 않습니다. 이번 버전은 `probe_format=2`이며 위 준비 명령을 다시 실행해 새 UUID의 소스를 만드세요. 과거 메뉴 항목은 그대로 보존합니다. 새로 출력된 v2 이름을 정확히 선택해야 합니다.

각 실행은 즉시 종료되며 `Console-<UUID>` / `Utility-<UUID>` 별도 하위 폴더와 `result.json`을 남깁니다. 같은 Resolve 프로세스에서 반복 실행해도 독립된 새 폴더를 사용합니다.

```powershell
py -3.12 .\scripts\InspectProbe.py --info (Join-Path $info.probe_root 'probe-info.json')
```

이 명령은 Lua나 Resolve를 실행하지 않고 파일과 해시만 읽습니다. Console/Utility 소스 및 설치된 메뉴 파일의 해시, 실행 기록, 마지막 단계와 결과 파일 경로를 보여 줍니다. `context`는 준비된 파일의 표식입니다. Utility 페이로드를 Console에서 직접 실행한 성공을 Utility 메뉴 성공으로 기록하지 않습니다.

결과 파일이 없을 때는 다음을 구분합니다.

| 검사 결과 | 해석과 확인 사항 |
| --- | --- |
| `menu_script_integrity=MISMATCH/MISSING` | 준비한 새 파일과 설치 파일이 다르거나 없어졌습니다. v2 준비를 다시 하고 새 UUID의 메뉴 항목을 선택합니다. 기존 항목은 덮어쓰지 않습니다. |
| `status=PREPARED`, `last_stage=NOT_ENTERED` | 초기 Lua 기록이 없습니다. 잘못된/오래된 메뉴, 구문·실행 시작 오류, Utility 전역 FFI 부재, 파일 쓰기 차단을 구분해야 합니다. 메뉴가 실행되지 않았다고 확정할 수 없습니다. Resolve의 스크립트 출력/오류에서 `ENTRY`, `NO_FILE_WRITER`와 오류를 확인합니다. |
| `status=RUNNING` | 초기 실행은 기록됐습니다. `last_stage`가 중단/지연된 단계이며 Resolve 종료나 API 지연도 함께 확인합니다. |
| `status=FINISHED`, `result=FAIL` | `checks`, `entry_error`, `result_write_error`를 확인합니다. FFI가 있으면 bit 부재도 실패 보고서로 남깁니다. |
| `result_file_written=false` | 실행 기록에 있는 디렉터리/오류를 확인합니다. 결과 파일 쓰기 실패는 별도 기록합니다. |
| `status=FINISHED`, `report_result=PASS` | 그 파일이 안내된 실제 UI에서 실행됐는지 확인합니다. 편집 성공은 아닙니다. |

준비 시 `<context>-launch.json`을 PREPARED로 만듭니다. Lua는 가능한 한 일찍 이를 갱신하고 각 단계의 진행 결과를 새 진단 폴더의 `result.json`에 저장합니다. native 파일 어댑터의 reparse/directory 플래그 검사는 기존과 같은 비트 마스크 의미를 산술로 검사하므로 전역 bit 없이도 초기 기록이 가능합니다. HMAC/운영 브리지는 여전히 필수 bit 함수 전체가 있어야 동작합니다.

FFI 자체가 없거나 Win32 DLL/파일 접근이 차단되면 결과 파일 기록을 보장할 수 없습니다. 이 경우 출력의 `ENTRY` 및 `NO_FILE_WRITER`를 수집합니다. io/셸 실행/Fusion prefs로 우회하지 않습니다. 파일 전체가 구문 분석에 실패한 경우에도 초기 Lua 기록이 남지 않을 수 있으며 CI의 번들 검사와 설치 파일 해시로 구분합니다.

## 결과 해석

- `GLOBALS`: 전역 ffi/bit의 실제 사용 함수 전체를 점검합니다. require/package는 필요하지 않습니다.
- `MODULE_GRAPH`: 고정 내부 registry로 모든 모듈의 정의를 로드합니다. v0.4에서도 편집 dispatcher는 구성하지 않습니다.
- `BRIDGE_HOST_FUNCTIONS`: 실제 상주 브리지에 필요한 bmd.wait/os.time 제공 여부를 확인하되 상주 루프는 실행하지 않습니다.
- `FFI_WIN32_CALL`: ffi.typeof/new 및 kernel32 GetCurrentProcessId의 실제 호출입니다.
- `WIN32_FILE_IO`: 별도 새 폴더의 한글 파일을 실제 Win32 API로 생성·읽기·교체·재읽기합니다.
- `HMAC_VECTOR`, `AUTHENTICATED_CHANNEL`: 기존 HMAC 벡터, 변조 거부, 중복 응답, 서명된 데이터 파일 왕복을 확인합니다. 실제 mailbox의 키를 사용하지 않습니다.
- `QUERY_*`: 버전·현재 프로젝트/타임라인·프로젝트/타임라인/트랙/미디어 풀·렌더 설정·클립 배치를 조회합니다. 이름이나 미디어 경로 전체를 진단 JSON에 저장하지 않습니다. `QUERY_projects.normalization`에는 문자열로 수락한 개수와 제외한 값의 유형·개수만 기록합니다. 숫자/count/ID/객체를 프로젝트명으로 변환하지 않습니다. `may_be_incomplete=true`는 비문자열을 제외했으므로 목록 완전성을 보장하지 않는다는 뜻입니다. 정렬 PASS와 목록 완전성은 다릅니다.
- `RESULT=PASS`: 해당 실행 환경의 검사 통과입니다. 실제 편집은 `NOT_RUN`이며 편집 성공을 뜻하지 않습니다.
- `PARTIAL`/`SKIP`: 프로젝트/타임라인이 열려 있지 않아 해당 조회가 수행되지 않았습니다. PASS로 계산하지 않습니다.
- `FAIL`: 실패한 단계와 상세를 확인합니다. 공유키나 승인 권한을 낮추거나 임의 코드 실행 경로로 우회하지 않습니다.

`context`는 준비한 파일의 진입점 표식이며 Resolve UI를 자동 감지한 결과가 아닙니다. 해당 파일을 안내된 Console/Utility에서 실행했는지 사용자가 확인해야 합니다. Console 결과와 Utility 결과는 서로 대체할 수 없습니다. 두 `result.json`의 context, resolve_version, result, checks와 오류가 발생했다면 콘솔 출력을 전달해 주세요. 그 결과를 검토하기 전에는 실기기 편집 검사나 `--enable-writes`를 실행하지 않습니다.

## 호환성·구조 기록

사용자 제공 증거: Resolve 21.1.1.10 Free의 Console에서 require/package는 nil이고 전역 ffi/bit가 존재하며 ffi.typeof('int')가 성공했습니다. 이는 Win32 DLL 함수와 파일 I/O 성공, 모든 bit 함수의 존재, Utility 환경을 입증하지 않습니다. 후속 사용자 검사에서는 Console용과 Utility용 페이로드를 모두 Console에서 직접 실행했을 때 QUERY_projects 외 모든 검사가 PASS였으며, 문자열/숫자 혼합 정렬 오류가 보고됐습니다. 실제 Utility 메뉴 실행은 결과 파일이 없어 검증되지 않았습니다. 이번 v2 수정본의 사용자 PC 실행은 재검증이 필요합니다.

기존 PR #1의 require 호출은 native.lua의 ffi 1곳·경로 검사 bit 1곳, crypto.lua의 bit 1곳으로 총 3곳입니다. PR #2에는 native.lua의 canonical 경로 검사 bit 1곳이 더 있어 총 4곳입니다. 다른 require 호출은 없었습니다. 종전 시작 코드의 debug.getinfo, 파일별 dofile과 설치 launcher의 dofile 의존성도 함께 제거했습니다.

`runtime.lua`는 전역 라이브러리의 실제 사용 메서드를 검사하고 실패 시 중단합니다. `bundle.py`는 신뢰하는 고정 파일 목록을 Lua factory로 묶습니다. `loader.lua`는 이 registry만 허용하고 캐시·순환 의존성·반환 타입을 검사합니다. package.path, package.preload, debug, loadfile, dofile, loadstring을 통한 내부 탐색/실행은 없습니다. 요청 데이터는 계속 인증된 데이터로만 해석됩니다. HMAC·RPC allowlist·경로/권한 검사·프로젝트 보호·로컬 승인 조건은 유지합니다.

자동 검사: 실제 LuaJIT에 ffi/bit 전역을 주입한 뒤 require/package/io/debug/파일 로더를 제거해 회귀 검사합니다. Windows CI는 실제 FFI/Win32를 호출하지만 Resolve 객체는 모의입니다. 사용자 PC의 Console/Utility 결과를 대신하지 않습니다.

변경 파일: reads.lua, inspection.py, InspectProbe.py, 프로젝트 목록/실행 기록 회귀 테스트, bundle.py, runtime.lua, loader.lua, probe.lua, native.lua, crypto.lua, ResolveMCP3.lua, Install.ps1, PrepareProbe.py, 로더/Win32/기존 통신 회귀 테스트 및 문서입니다. 복구 시 새 `utility_menu_script` 항목만 수동 제거하고 진단 폴더를 보관 또는 정리하면 됩니다. 현재 브리지 활성 manifest와 원본 프로젝트는 복구 대상이 아닙니다.
