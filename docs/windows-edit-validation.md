# v0.4 신규 세션에서 프로젝트 종료 확인과 편집 검증

Console HMAC·응답 인증·최소 Utility 진입 및 `__flags` 빈 상태 검사는 사용자 실기기에서 확인됐습니다. 후속 편집은 CloseProject=true 직후 현재 프로젝트가 남아 생성 전에 거부됐으며 service_stop은 PASS입니다. 이번에는 별도 진단을 반복하지 않고 같은 편집 시퀀스에 안전한 종료 관측을 포함합니다. 수정 후 실제 종료·클립 편집은 아직 미검증입니다.

## Windows 최소 실행

PR #2의 최신 소스 루트 PowerShell에서 준비합니다. Python 3.12와 기본 Windows PowerShell을 사용합니다. 새 manifest 형식은 3입니다. 기존 실패 세션의 edit-info.json·Lua 서비스·Console 명령·Utility 항목은 재사용하지 않습니다. 이전 결과와 테스트 프로젝트는 보존합니다.

```powershell
$ev = (& py -3.12 .\scripts\EditValidation.py --prepare) | ConvertFrom-Json
$ev.bootstrap_project_name
$ev.bootstrap_project_name | Set-Clipboard
```

현재 클립보드는 프로젝트 이름용입니다. Resolve 프로젝트 관리자에서 그 이름으로 새 빈 프로젝트를 만들고 열어 둡니다. 기존 프로젝트를 복제/rename하지 않고 미디어·타임라인·bin·렌더 작업을 추가하지 않습니다. 기존 작업은 사용자가 보존하고 UI에서 나옵니다. 그 새 프로젝트에서 Lua Console을 엽니다.

다음 블록은 PowerShell에서만 실행합니다. 두 정확한 이름을 인수로 전달하는 동작이 빈 임시 프로젝트를 닫고 별도의 신규 편집 프로젝트를 만들겠다는 로컬 승인입니다.

```powershell
py -3.12 .\scripts\EditValidation.py --run (Join-Path $ev.root 'edit-info.json') --confirm-project-name $ev.project_name --confirm-bootstrap-project-name $ev.bootstrap_project_name
```

Python이 실행된 뒤 Lua 명령만 클립보드에 복사합니다. `Clipboard now contains LUA CONSOLE ONLY`가 나오면 Resolve Lua Console에서 Ctrl+V → Enter를 한 번 누릅니다. 이후 PowerShell 명령을 추가로 복사할 필요가 없습니다. PowerShell 창에 Lua를 붙이지 않습니다. 이전의 `$ev.console_command | Set-Clipboard` 수동 단계는 제거했습니다.

클립보드를 사용할 수 없으면 출력된 새 `LuaConsoleCommand.txt` 파일의 한 줄만 Lua Console에 복사합니다. 이 파일은 고정된 새 payload를 시작하는 Lua 명령만 포함하고 준비 manifest에서 무결성을 검사합니다. PowerShell 코드가 들어 있지 않습니다. 명령을 클립보드로 전달하는 고정 프로그램은 stdin을 데이터로 읽으며 Lua를 PowerShell로 평가하지 않습니다.

시작 대기는 최대 10분입니다. 새 HMAC challenge/READY 확인 후에만 15분 편집 승인을 생성하고 개별 요청의 기존 29초 제한을 시작합니다. 이후 사람의 Console 조작 없이 전체 시퀀스를 처리합니다. Console과 Utility를 동시에 시작하지 않습니다. Utility를 선택한다면 위 실행 명령에 `--host Utility`를 붙이고 새 `$ev.utility_menu_script` 항목을 한 번 실행합니다. 이 경로는 클립보드를 바꾸지 않습니다.

결과는 PowerShell과 `$ev.result_file`에 나옵니다. 성공 기대값은 `result: PASS`, `editing_test: PASS`입니다. 실패 시에도 종료 관측을 자동으로 수집하므로 별도 Console 진단 명령은 필요하지 않습니다.

## 종료 완료 확인과 관측의 의미

정확한 임시 프로젝트 이름·고유 ID·빈 상태와 기존 편집 승인/별도 전환 승인을 검사합니다. GetClipList·GetSubFolderList·GetRenderJobList는 `_flags`/`__flags` 유한 숫자형 메타데이터만 제외합니다. 실제 항목·다른 키·메타테이블·잘못된 반환형은 계속 거부합니다. 대상 이름 충돌 검사와 전환 직전 재검사도 유지합니다.

CloseProject는 승인된 빈 임시 프로젝트 객체에 정확히 한 번만 호출합니다. true 반환 뒤에도 종료를 추정하지 않습니다. 50ms 간격의 조회로 최대 5초 동안 관측하며 두 차례 연속 GetCurrentProject=nil을 요구합니다. 생성 직전에 승인·세션·현재 상태를 다시 검사합니다. 이미 진행 중인 Resolve API 호출은 강제 취소할 수 없습니다. 새 프로젝트를 만들거나 close를 다시 실행해 종료를 탐색하지 않습니다.

| 관측 | 처리 |
| --- | --- |
| 같은 임시 이름/ID와 같은 객체 참조 | 종료 지연 또는 기존 참조 잔존으로 관측; 조회만 대기 |
| 같은 임시 이름/ID와 다른 wrapper | 같은 ID의 별도 객체로 관측; 채택/편집 없이 조회만 대기 |
| 이전과 같은 참조지만 getter를 읽을 수 없음 | STALE_REFERENCE_CANDIDATE; nil의 증거로 사용하지 않음 |
| 두 차례 연속 nil, 생성 직전에도 nil | CLOSE_CONFIRMED → READY_TO_CREATE; 이때만 새 프로젝트 생성 |
| 다른 이름/ID의 프로젝트 | DIFFERENT_PROJECT_ACTIVE; 추가 닫기/저장/생성 없이 중단 |
| 다른 객체의 신원 불명·API 오류·잘못된 타입 | 안전하게 중단하고 기록 |
| 같은 객체/ID가 한도까지 잔존 | CLOSE_PENDING_TIMEOUT 또는 STALE_REFERENCE_UNRESOLVED; 재시도하지 않음 |
| 확인 뒤 생성 직전 다른 프로젝트 활성화 | PROJECT_ACTIVATED_BEFORE_CREATE; 생성 중단 |

같은 객체가 몇 차례 관측된 뒤 nil이 되었다는 사실만으로 Resolve 내부의 비동기 종료와 오래된 wrapper 잔존 중 하나를 확정할 수는 없습니다. 보고서는 실제 관측과 완료 조건을 구분합니다. 자동 활성화된 다른 프로젝트는 읽기만 하며 닫거나 저장·이름 변경·LoadProject하지 않습니다.

## 안전한 기록과 편집 범위

새 전용 ACL 폴더의 mailbox/project-transition.txt에 현재 이름·고유 ID의 반환 타입/값, GetCurrentProject의 타입, CloseProject의 반환값/타입, 객체 참조 일치 여부, 경과 시간과 최종 분류를 기록합니다. 문자열은 256바이트, 관측은 제한된 횟수로 묶습니다. 원시 API 예외문·객체 주소·세션 키·원본 미디어 경로는 기록하지 않습니다. 프로젝트 이름/ID는 로컬 결과에 포함되며 외부로 자동 전송하지 않습니다.

관측 파일은 기존 세션 키의 HMAC으로 서명하고 브리지 ID와 편집 승인 ID에 묶습니다. Python은 서명을 검증한 기록만 결과의 `project_transition`에 포함하고 `project_transition_authentication: PASS`를 표시합니다. 위조/다른 세션 기록은 UNCONFIRMED로 구분합니다. 서명된 기록은 과거 관측이며 현재 상태나 새 편집 승인을 대신하지 않습니다. CloseProject 전 기록 쓰기가 실패하면 프로젝트를 닫지 않습니다.

`CALLING_CLOSE`는 호출 의도를 기록한 상태이며 API 반환이나 종료 성공의 증거가 아닙니다. 호출 후 파일 쓰기가 실패하면 이 상태를 남기고 생성 없이 중단합니다. `close_project` 반환 관측과 연속 nil이 있어야 종료 완료를 인정합니다.

종료가 확인되면 별도의 새 `ResolveMCP_TEST_probe_<ID>` 프로젝트·bin에 자체 합성 H.264 파일을 가져옵니다. 1080×1920/30fps/시작 프레임 0 타임라인에 소스 [3,63)의 60프레임을 V1 0–60에 배치하고 프로젝트/타임라인/미디어 ID·좌우 여유 3/27을 재조회한 뒤 이 새 프로젝트만 저장합니다. API 조회와 실제 픽셀/재생 확인은 구분합니다. 렌더·오디오·자막·삭제는 이번 범위 밖입니다.

HMAC·allowlist·요청 만료/중복·뮤텍스·양쪽 승인·신규 프로젝트/타임라인/미디어 소유권·경로/ACL/reparse/hardlink 보호와 감사 로그를 유지합니다. 실패 시 두 승인부터 폐기하고 다음 편집/저장을 중단합니다. 진행 여부가 불확실한 편집은 자동 재전송·undo·삭제하지 않으며 부분 새 프로젝트와 이전 실패 결과를 보존합니다. 같은 edit-info 재실행은 거부합니다.

## 자동 검증·복구

회귀 검사는 즉시/지연 종료, 같은 ID의 다른 wrapper, 읽을 수 없는 참조, 잔존 시간 초과, 다른 프로젝트 자동 활성화, nil 이후 재활성화, 승인 폐기/키 교체, 위조/오래된 관측, 진단 쓰기 실패 시 무변경과 클립보드 데이터 전달/파일 대안을 확인합니다. Windows CI는 실제 FFI/Win32/HMAC 파일 교환과 클립보드를 검사하지만 Resolve API는 모의입니다. 실제 사용자 PC 결과와 구분합니다.

변경 파일은 edits.lua, Console/Utility adapter, project_transition.py, edit_validation.py, clipboard.py, EditValidation.py 및 회귀/실기기 문서입니다. 복구는 새 launcher·전용 폴더와 생성된 테스트 프로젝트를 사용자가 UI에서 보존/정리하는 범위입니다. 기존 설치/사용자 프로젝트/원본을 수정하지 않습니다. PR #2는 초안으로 유지하며 병합하지 않습니다.
