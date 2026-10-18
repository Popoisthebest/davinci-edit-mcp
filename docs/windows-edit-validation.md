# v0.4 임시 프로젝트에서 시작하는 실제 편집 검증

Console을 열기 위해 편집 화면이 필요하므로 시작용 빈 프로젝트와 실제 편집 프로젝트를 분리합니다. 준비 때마다 다른 정확한 이름을 생성합니다. 기존 사용자 프로젝트는 사용자가 먼저 보존하고 UI에서 나옵니다. 도구가 사용자 프로젝트를 저장·닫기·이름 변경·열기·편집하지 않습니다. 기존 통신·최소 Utility 검사는 반복하지 않습니다.

## Windows 최소 실행

PR #2의 최신 소스를 내려받아 저장소 루트의 PowerShell에서 실행합니다. Python 3.12만 필요합니다. 이번 `__flags` 수정은 준비 시 생성하는 Lua payload에 포함되므로 기존 실패 세션의 edit-info.json/서비스/Console 명령/Utility 항목을 재사용하지 않습니다. 이전 실패 보고서·테스트 프로젝트는 보존하고 아래 `--prepare`로 새 폴더·세션 키·두 프로젝트 이름·launcher를 생성합니다. 통신이나 메타데이터 진단은 반복하지 않고 바로 편집 시퀀스를 실행합니다.

```powershell
$ev = (& py -3.12 .\scripts\EditValidation.py --prepare) | ConvertFrom-Json
$ev.bootstrap_project_name
$ev.bootstrap_project_name | Set-Clipboard
```

Resolve 프로젝트 관리자에서 클립보드의 정확한 이름으로 새 빈 프로젝트를 만들고 열어 둡니다. 기존 프로젝트를 복제하거나 이름을 바꾸지 않습니다. 미디어·타임라인·bin·렌더 작업을 추가하지 않습니다. 이 프로젝트의 편집 화면에서 Lua Console을 열 수 있습니다.

PowerShell에서 다음을 실행합니다. 두 이름 확인은 이 빈 프로젝트를 닫고, 표시된 별도의 신규 편집 프로젝트를 만들겠다는 로컬 승인입니다.

```powershell
$ev.console_command | Set-Clipboard
py -3.12 .\scripts\EditValidation.py --run (Join-Path $ev.root 'edit-info.json') --confirm-project-name $ev.project_name --confirm-bootstrap-project-name $ev.bootstrap_project_name
```

`Waiting up to 10 minutes`가 표시되면 열린 임시 프로젝트의 Lua Console에 클립보드의 한 줄을 붙여 넣어 한 번 실행합니다. 29초 안에 실행할 필요가 없습니다. 시작 대기는 최대 10분이며 편집 승인은 아직 생성되지 않습니다. 브리지가 새 HMAC challenge에 READY로 응답한 후에만 15분 편집 승인을 생성하고, 개별 요청의 기존 29초 제한을 시작합니다. 이후 사람이 Console에서 명령을 입력할 필요 없이 전체 시퀀스를 처리합니다.

Utility 자동 실행을 선택한다면 같은 임시 프로젝트가 열린 상태에서 `$ev.utility_menu_script`의 새 `ResolveMCP_Edit_<ID>` 항목을 한 번 실행합니다. Console과 동시에 실행하지 않습니다. Utility 전체 실행 및 프로젝트 전환 후 Console 지속 동작은 실기기 미검증입니다. Console 통신 자체는 기존 사용자 검증 PASS이며 새 경로 결과와 구분합니다.

## 결과와 보호

기대 결과는 PowerShell의 `result: PASS`, `editing_test: PASS` 및 `$ev.result_file`의 보고서입니다. 자동 시퀀스는 다음과 같습니다.

1. 인증된 현재 프로젝트 조회에서 생성된 임시 이름·고유 ID·타임라인 0개를 확인합니다.
2. 임시 프로젝트 전환 승인을 별도로 서명합니다. 승인 ID·만료·현재 브리지 ID·프로젝트 이름·고유 ID에 묶습니다. 접두사만으로 기존 프로젝트를 채택하지 않습니다.
3. Lua가 다시 현재 이름·ID와 빈 상태(타임라인·미디어·하위 bin·렌더 작업 없음)를 확인합니다. GetClipList·GetSubFolderList·GetRenderJobList는 빈 일반 테이블 또는 `_flags`/`__flags`의 유한 숫자형 메타데이터만 있는 일반 테이블을 허용합니다. 두 키가 함께 있으면 각각 유한한 숫자여야 합니다. 실제 항목이 하나라도 있거나 다른 키·문자열/boolean/table형 메타데이터·NaN/무한대·nil/non-table·메타테이블이 있으면 거부합니다. 숫자 인덱스의 희소 항목과 이름으로 된 항목도 검사하며 단순 `#list`/`ipairs`로 빈 상태를 판정하지 않습니다. 대상 이름 충돌 검사 뒤 전환 직전 재검사합니다. 누락된 API·다른 프로젝트·승인 변경은 닫기 전에 거부합니다.
4. 승인된 빈 임시 프로젝트만 `CloseProject`로 닫습니다. `SaveProject`, 삭제, rename, `LoadProject`는 수행하지 않습니다. 닫기 실패나 예상치 못한 현재 프로젝트는 생성 전에 중단하며 전환을 재시도하지 않습니다.
5. 별도 `ResolveMCP_TEST_probe_<ID>` 신규 프로젝트·bin을 만들고 전용 테스트 파일을 가져옵니다. 이 브리지가 방금 만든 ID만 이후 편집 대상으로 허용합니다.
6. 1080×1920 / 30fps / 시작 프레임 0 타임라인을 만들고, 소스 [3,63)의 60프레임을 V1의 0프레임에 배치합니다. 설정·미디어/타임라인/프로젝트 ID·0–60 프레임·좌우 여유 3/27프레임을 API로 재조회합니다.
7. 새 편집 프로젝트만 저장하고, 두 승인부터 폐기한 뒤 서비스 stop을 요청합니다. 임시 프로젝트와 새 편집 프로젝트는 삭제하지 않습니다.

합성 영상은 자체 생성한 3초/90프레임, 1080×1920, 정확히 30fps의 영상 전용 H.264 파일입니다. 원본이나 다운로드·FFmpeg 설치 없이 고정 SHA256 리소스를 새 전용 미디어 폴더에만 복원합니다. 사용자가 새 프로젝트에서 파란 배경·노란 도형의 클립 재생을 확인할 수 있습니다. API 조회 성공과 실제 픽셀/디코딩 검증은 별개입니다.

HMAC, 허용 명령, 요청 만료·중복·브리지 ID, 양쪽 로컬 승인, 세션 소유권, 경로/ACL/reparse/hardlink 보호와 감사 로그를 유지합니다. 새 일반 프로젝트 열기·닫기 MCP 도구는 추가하지 않습니다. 기존 무프로젝트 상태의 저수준 신규 생성 경로도 유지하지만 이 검증기는 정확한 임시 프로젝트를 요구합니다.

준비 대기 만료는 `STARTUP_TIMEOUT` / `editing_test: NOT_RUN`이며 편집 요청을 발행하지 않습니다. 편집 시작 후 실패/시간 초과에서는 다음 편집·저장을 중단하고 `failed_stage`, `error_code`, `may_have_changes`를 기록합니다. 같은 edit-info의 재실행은 거부합니다. 실행 여부가 불확실한 요청을 재전송하거나 자동 undo·삭제·원본 복원을 하지 않습니다. 새 부분 프로젝트를 보존해 확인합니다. 이미 진행 중인 Resolve API 호출은 강제 취소할 수 없습니다.

## 검증 상태와 복구

사용자 Windows에서 타임라인 0개·현재 타임라인 nil·메타테이블 nil·세 목록의 숫자형 `__flags`(밑줄 2개)만 존재함을 확정했습니다. `_flags`와는 다른 문자열 키이며, 이전 검증기는 `__flags`를 허용하지 않아 닫기/편집 전에 거부했습니다. 이 수정 후 실제 Windows Resolve의 전환·클립 편집은 아직 미검증입니다.

자동 검사는 세 목록 모두에서 메타데이터만 있는 빈 상태의 전환 허용, 실제/희소/이름 항목·잘못된 메타데이터·알 수 없는 구조의 무변경 거부와 기존 전체 편집·프로젝트/HMAC 보호를 검사합니다. Windows CI는 실제 Win32/FFI/ACL/canonical 경로와 Python↔Lua HMAC 교환으로 같은 메타데이터 모양의 전체 시퀀스를 검사하지만 Resolve API는 모의입니다. 렌더·오디오·자막·삭제는 이번 범위 밖입니다.

이번 수정 파일: edits.lua, edit_support.py, test_editing.py, test_edit_validation_windows.py, AGENTS.md 및 실기기 문서입니다. 기존 설치본은 덮어쓰지 않습니다. 복구는 새 launcher와 전용 폴더만 정리하고, 생성된 두 테스트 프로젝트는 사용자가 UI에서 보존/정리합니다. 기존 프로젝트와 원본에는 접근하지 않습니다. PR #1/#2는 병합하지 않습니다.
