# v0.4 신규 프로젝트 실제 편집 검증

Console HMAC·응답 인증과 최소 Utility 진입은 사용자 Windows 실기기에서 PASS입니다. 통신 진단을 반복하지 않고 다음 한 번의 편집 시퀀스로 진행합니다. 여기서 구현한 새 자동 서비스와 편집 기능의 실제 Free 21.1.1 호환성은 실행 결과가 나오기 전까지 미검증입니다.

## 최소 실행

PR #2의 최신 소스를 사용합니다. Resolve에서 기존 작업은 사용자가 먼저 보존하고 프로젝트를 닫아 프로젝트 관리자 화면으로 이동합니다. 도구는 기존 프로젝트를 저장·닫기·전환하지 않으며 열려 있으면 편집 전에 거부합니다.

저장소 루트의 PowerShell에서 준비합니다. Python 3.12만 필요합니다.

```powershell
$ev = (& py -3.12 .\scripts\EditValidation.py --prepare) | ConvertFrom-Json
$ev.project_name
$ev.utility_menu_script
$ev.console_command | Set-Clipboard
```

원본 대신 전용 폴더에 3초/90프레임, 1080×1920, 정확히 30fps, 영상 전용 H.264 테스트 파일을 생성합니다. Windows에서 FFmpeg 설치·다운로드는 필요하지 않습니다. 준비 시에는 로컬 편집 승인이나 Resolve API 호출을 하지 않습니다.

아래 명령이 정확한 신규 테스트 프로젝트의 15분 로컬 승인을 생성하고 편집 시퀀스를 시작합니다.

```powershell
py -3.12 .\scripts\EditValidation.py --run (Join-Path $ev.root 'edit-info.json') --confirm-project-name $ev.project_name
```

`Edit requests ready`가 표시되면 29초 안에 한 경로만 시작합니다.

- 검증된 Console을 우선 사용하려면 Lua Console에 클립보드의 한 줄을 붙여 넣어 실행합니다. 한 번만 시작하면 모든 편집 요청이 자동 처리됩니다.
- Utility 자동 처리를 함께 확인하려면 출력된 새 `ResolveMCP_Edit_<ID>` 항목을 한 번 실행합니다. Console 경로와 동시에 시작하지 않습니다.

두 경로가 같은 HMAC dispatcher·승인·프로젝트 보호를 사용합니다. Utility가 실패하거나 아무 반응이 없으면 같은 실행에서 Console을 뒤늦게 중복 기동하거나 재요청하지 않습니다. 타임아웃 결과와 service.json을 확인하고 코드를 수정한 뒤 새 준비로 진행합니다. 준비를 반복하는 것만으로 Resolve의 부분 프로젝트를 삭제하거나 재사용하지 않습니다.

기대 결과는 PowerShell의 `result: PASS`, `editing_test: PASS`와 `$ev.result_file`의 결과 파일입니다. 테스트 프로젝트에는 파란 배경/노란 도형의 짧은 클립이 영상 트랙 1의 0–60 프레임에 놓입니다. 실제 재생/디코딩 화면은 사용자가 한 번 확인할 수 있으며 API 조회 성공이 픽셀/오디오 검증을 대신하지 않습니다.

## 자동 시퀀스와 보호

서명된 요청으로 다음 순서를 한 번만 실행합니다.

1. 열려 있는 프로젝트가 없는지 조회합니다. 기존 프로젝트가 열려 있으면 무변경 종료합니다.
2. `ResolveMCP_TEST_probe_<UUID>` 신규 프로젝트와 전용 bin을 만듭니다.
3. 세션 HMAC marker가 있는 전용 미디어 폴더의 생성 파일만 가져옵니다.
4. 1080×1920, 30fps, 시작 프레임 0의 신규 타임라인을 만들고 실제 설정을 재검사합니다.
5. 소스 [3,63), 60프레임을 V1의 0프레임에 배치합니다. 배치 전 계획 검사와 배치 후 getter 검사를 수행합니다.
6. timeline_items와 프로젝트를 다시 조회해 미디어 ID·프로젝트/타임라인 ID·트랙·0–60 프레임·좌우 여유 3/27프레임을 검증합니다.
7. 이 신규 프로젝트만 저장하고 승인 폐기·서비스 stop을 요청합니다.

기존 HMAC, 요청 만료/중복, 양쪽 로컬 승인, 신규 프로젝트 ID, 타임라인/미디어 세션 소유권, 경로/ACL/reparse/hardlink, 감사 로그를 유지합니다. 편집 생성 검사도 혼합 문자열/숫자 프로젝트 목록을 안전하게 확인하며 기존 문자열 이름 충돌은 계속 거부합니다. 승인되지 않은 기존 프로젝트를 닫거나 이름을 바꾸지 않습니다.

실패/시간 초과에서는 다음 편집과 자동 저장을 중단하고 승인부터 폐기합니다. `failed_stage`, `error_code`, `may_have_changes`와 감사 로그를 남깁니다. 실행 여부가 불확실한 편집은 재시도·삭제·undo하지 않습니다. 같은 edit-info의 재실행은 started.json으로 거부합니다. 이미 진행 중인 API를 취소할 수 없으므로 새 부분 프로젝트를 보존해 확인합니다.

## 검증·지원 상태와 복구

자동 검사는 모의 Resolve에서 전체 시퀀스, 원본 열림 거부, 이름 충돌·혼합형 목록, 배치 실패 후 중단/무재시도/무저장, 승인 폐기와 한 번만 실행을 확인합니다. Windows CI는 실제 FFI/Win32/ACL/canonical 경로와 Python↔Lua HMAC 요청으로 같은 시퀀스를 수행하지만 Resolve API는 모의입니다. 사용자 PC의 실제 편집 성공은 아직 NOT_RUN입니다.

생성 소재는 이 저장소에서 FFmpeg의 color/drawbox로 만든 자체 합성 영상입니다. 원본 경로나 외부 저작물은 포함하지 않습니다. base64 리소스의 SHA256을 고정해 새 전용 폴더에만 복원합니다. 내보내기·렌더·오디오·자막·컷/삭제는 이번 검증에 포함하지 않습니다.

변경 파일: edit_validation.py, EditValidation.py, fixtures/portrait30.mp4.b64, pyproject.toml, edits.lua 및 회귀 테스트입니다. 공통 서비스 변경은 automatic-service.md에 있습니다. 복구 시 생성된 신규 테스트 프로젝트는 사용자 UI에서 보존/정리하고 새 launcher·전용 폴더만 정리합니다. 원본 프로젝트/미디어와 이전 통신 검증 결과는 그대로 둡니다. PR #1/#2는 병합하지 않습니다.
