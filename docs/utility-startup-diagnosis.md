# Utility 진입 진단 v3

후속 실기기 결과로 최소 Utility 실행 표식과 Console HMAC 왕복·응답 인증이 확인됐습니다. 이 과거 진단을 반복하지 않습니다. [현재 증거와 다음 단계](verification-status.md)를 따릅니다.

최신 사용자 결과: Resolve 완전 종료·재시작 후 기존 브리지를 실행하지 않아도 v3 Utility는 무반응이었습니다. 같은 v3 검사나 재시작을 반복하지 않습니다. 이 문서는 이전 분석 기록이며 현재의 최소 Utility 파일과 Console 대안은 [Console 대체 연결](console-fallback.md)에 있습니다.

## 현재 증거와 분석

사용자는 Windows 11 / Resolve 21.1.1 Free에서 v2 Console 전체 PASS를 확인했습니다. 실제 Utility 메뉴의 `ResolveMCP_ReadOnlyProbe_v2_d9114720`을 반복 실행해도 파일 기록은 PREPARED / NOT_ENTERED였습니다. 이 결과를 보존하며 같은 v2 검사나 Console 전체 검사를 다시 요구하지 않습니다. 실제 편집과 PR 병합은 보류합니다.

Console PASS로 혼합형 프로젝트 목록 수정과 Console의 FFI/Win32/HMAC/조회는 확인됐습니다. Utility의 Lua 환경, 실행 스케줄러, 전역 라이브러리와 파일 접근 권한까지 입증되지는 않습니다. v2의 NOT_ENTERED는 Python이 준비한 값이며, Resolve가 스크립트를 호출하지 않았다는 증거가 아닙니다.

소스에서 확인한 문제와 아직 확인하지 못한 원인을 구분합니다.

| 원인 후보 | 확인된 사실 및 이번 수정 |
| --- | --- |
| 스크립트 환경과 `_G` 차이 | 기존 runtime은 `rawget(_G,'ffi')`를 사용했습니다. Lua의 별도 스크립트 환경이나 `__index`를 통해 ffi가 제공되면 일반 전역 조회는 성공해도 rawget은 nil이 됩니다. 이 실패를 LuaJIT에서 재현했고 ffi/bit/resolve/bmd를 스크립트 환경에서 정상 조회하도록 수정했습니다. 실제 Utility가 이 방식인지는 미검증입니다. |
| 초기 파일 기록의 FFI 의존성 | v2는 runtime.ffi 검사, native의 cdef/DLL 초기화, codec 로딩과 파일 쓰기를 통과해야 첫 기록을 남깁니다. 그 전에 실패하면 Console 출력 외 증거가 없습니다. 별도 v3 진입 진단은 파일과 독립적인 UI 및 호스트 오류 경로를 추가했습니다. |
| Console과 다른 Lua/라이브러리 | Utility가 LuaJIT인지, ffi가 없거나 일부 메서드만 있는지는 아직 알 수 없습니다. v3는 Lua 버전, jit.version 및 전역의 resolved/raw _G 유형을 기록합니다. FFI를 설치하거나 require로 가져오는 우회는 하지 않습니다. |
| 초기 선언·DLL·호출·저장 실패 | v3는 FFI_GLOBALS, FFI_TYPEOF_NEW, FFI_CDEF, FFI_KERNEL32_LOAD, FFI_CALL, FFI_ADVAPI32_LOAD, CODEC_MODULE, NATIVE_MODULE, RECEIPT_WRITE 단계를 분리합니다. native 저장 오류에는 WriteFile/Flush/Replace/Move의 Win32 코드도 보존합니다. |
| 스크립트가 호출되기 전 문제 | 동일 Lua chunk의 구문 오류는 그 chunk의 pcall로 잡을 수 없습니다. v3는 큰 조회/편집 레지스트리에서 분리한 ASCII 전용 파일이며 Lua 5.1/LuaJIT 컴파일을 검사합니다. 설치 파일 해시도 확인합니다. 호스트가 파일 자체를 거부하거나 실행을 대기시키는 경우에는 Lua 코드만으로 이를 관측할 수 없습니다. |
| 기존 Utility 작업의 실행 대기 | legacy와 운영 브리지는 `while`/`bmd.wait` 상주 루프를 갖습니다. Resolve가 Utility 실행을 직렬화한다면 다른 실행이 대기할 가능성이 있습니다. 현재 호스트의 스케줄링 방식은 확인되지 않았으므로 원인으로 단정하거나 기존 브리지를 자동 종료하지 않습니다. |

프로젝트 목록 조회는 첫 기록보다 뒤에 있으므로 현재 NOT_ENTERED의 직접 원인이 아닙니다. v2의 초기 파일 어댑터는 bit에 의존하지 않으므로 bit 부재 하나만으로는 기록 전체 부재를 설명하지 못합니다. HMAC 또는 프로젝트 보호 조건을 낮추어도 이 문제를 해결하지 못합니다.

## 수정본이 제공하는 별도 진단

이것은 v2 전체 검사의 반복이 아닌 Utility 진입 전용 진단입니다. Console 파일을 생성하거나 프로젝트 getter, HMAC 검사, 승인 파일, mailbox, 편집 dispatcher를 실행하지 않습니다. 독립된 고정 runtime/codec/native 레지스트리만 포함하며 require/package/debug/io/loadfile/dofile/loadstring이 필요하지 않습니다. 새 native 구현도 기존 경로/reparse 검사와 원자적 교체를 사용합니다. 기존 설치와 v2 결과를 덮어쓰지 않습니다.

수정 소스의 Windows 저장소 루트에서 준비할 수 있습니다.

```powershell
$entry = (& py -3.12 .\scripts\PrepareProbe.py --utility-entry --install-utility) | ConvertFrom-Json
$entry.utility_menu_script
```

새 항목의 이름은 `ResolveMCP_UtilityEntry_v3_<ID>`입니다. 실제 Utility에서 이 새 항목이 호출되면 먼저 `ENTRY reached` 대화상자, 이후 최종 단계/오류 대화상자를 표시하려고 시도합니다. Fusion/fu/Resolve의 Fusion 객체에 AskUser가 있으면 이를 사용하며, 그렇지 않으면 사용 가능한 Windows FFI의 MessageBoxW를 시도합니다. UI 호출에는 프로젝트 변경이나 prefs 저장이 없습니다. 호스트 UI와 FFI가 모두 없으면 단계와 원인을 포함한 Lua 오류를 발생시킵니다. UI와 파일 출력이 모두 불가능한 상태를 성공으로 반환하지 않습니다.

파일 기록이 가능하면 전용 새 폴더의 `Utility-launch.json`에 환경 및 최종 결과를 남깁니다. 확인 명령은 파일과 해시만 읽습니다.

```powershell
py -3.12 .\scripts\InspectProbe.py --info (Join-Path $entry.probe_root 'probe-info.json')
```

| 새 증거 | 해석 |
| --- | --- |
| `ffi resolved/raw _G = table/nil` | 기존 rawget 경로가 라이브러리를 놓치는 환경임을 확인할 수 있습니다. |
| `FFI_GLOBALS` 실패 | Utility 환경에서 FFI가 없거나 필요한 함수/Windows 런타임 조건을 충족하지 않습니다. 대화상자에 정확한 검증 오류를 표시합니다. |
| 선언·DLL·함수 호출 단계 실패 | 해당 단계의 FFI 오류를 확인합니다. Console 결과로 대체하지 않습니다. |
| `RECEIPT_WRITE` 실패 | 진입과 FFI 호출은 진행됐지만 파일 기록이 실패했습니다. 대화상자의 Win32 코드를 확인합니다. 준비 상태가 그대로 남을 수 있습니다. |
| `FINISHED / PASS` | 소형 진입 진단과 보호된 파일 쓰기까지 확인됐습니다. 전체 Utility 조회와 편집은 실행하지 않았습니다. |
| 대화상자도 파일도 없음 | 메뉴 실행 전의 호스트 문제 또는 모든 출력 경로의 부재를 구분할 수 없습니다. 메뉴 실행 대기·호스트 출력/구문 오류 등은 여전히 후보입니다. NOT_ENTERED만으로 미실행을 확정하거나 같은 검사를 반복하도록 안내하지 않습니다. |

대화상자는 호스트 API의 가용성에 달려 있습니다. 자동 테스트에서는 모의 AskUser와 실제 Win32 FFI/파일 I/O를 사용하며 Resolve UI 자체의 표시를 입증하지 않습니다. 코드가 한 번도 실행되지 않은 경우 그 코드가 기록을 남기게 만들 수는 없습니다.

## 검증·보호·복구

회귀 검사는 환경 상속, FFI 없는 Lua 5.1, UI 불가 시 호스트 오류, 선언/DLL/호출별 실패, ASCII 컴파일, Windows의 실제 Unicode 파일 저장 및 공유 잠금 실패를 확인합니다. Windows의 파일 실패는 실제 독점 핸들을 열어 재현하며 준비 기록을 변경하지 못해도 UI 오류가 보이는지 검사합니다. 기존 HMAC·allowlist·프로젝트 보호·경로/ACL 및 편집 승인 회귀를 함께 실행합니다.

실기기 확인 범위는 사용자가 보고한 v2 Console 전체 PASS까지입니다. 이 수정본의 실제 Utility UI/환경과 운영 브리지 시작, 설치/업그레이드/롤백 및 실제 편집은 미검증입니다. 이번 변경으로 쓰기 승인이나 지원 API 범위를 늘리지 않습니다.

변경 파일: runtime.lua, probe.lua, native.lua, utility_entry.lua, bundle.py, inspection.py, PrepareProbe.py, Utility 진입/Windows/Inspector 회귀 검사와 문서입니다. 복구는 새 v3 Utility 항목과 새 전용 진단 폴더만 수동 정리하면 됩니다. 기존 v2 결과·브리지·프로젝트·미디어는 보존합니다.
