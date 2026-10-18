# Console·Utility 공통 자동 처리

[통신 실기기 검증](verification-status.md)은 완료했습니다. 이 문서는 새 구조의 동작·한계를 설명하며 같은 통신 검사를 다시 요구하지 않습니다.

기존 `new()`와 `step()`은 그대로 수동 처리합니다. 별도로 `run(seconds, context)`를 호출하면 현재 요청을 순서대로 처리하는 유한 루프를 시작합니다. 기본 180초, 최대 600초이며 stop·키 교체·오류·시간 한도에 도달하면 중단합니다. 시간 한도는 Win32 GetTickCount64 단조 시계로 계산하며 HMAC 요청의 기존 29초 만료는 변경하지 않습니다. 이미 진행 중인 Resolve API 호출을 강제로 취소하는 기능은 없습니다.

`run(180, "Console", 600)` 또는 Utility의 동일 옵션은 요청 처리 전에 최대 600초의 별도 시작 대기를 둡니다. Python `Mailbox.wait_ready(600)`가 새 난수 challenge·만료를 HMAC 서명한 start.txt를 쓰고, 뮤텍스를 소유한 서비스가 서명을 검사해 challenge와 브리지 ID를 서명한 ready.txt로 돌려줍니다. 매 실행 새 challenge를 사용하므로 이전 READY나 unsigned service.json은 준비 완료 증거가 아닙니다. 이 단계는 프로젝트 API·편집 요청·편집 승인 없이 진행하며 종료 시 start.txt를 제거합니다. 준비 후에만 기존 29초 RPC와 별도의 180초 처리 한도가 시작됩니다. 시작 대기 중에는 기존 request.txt도 처리하지 않습니다. 기존 인수 2개의 run과 수동 step은 호환성을 유지합니다.

PR #2의 실제 편집 검증기는 이 대기를 사용합니다. Console 진입에 필요한 새 빈 `ResolveMCP_BOOT_<전체 ID>` 프로젝트를 열어 두고 시작하며, 별도 서명 승인·현재 ID·빈 상태를 검사해 그 프로젝트만 닫고 신규 편집 프로젝트로 전환합니다. 기존 프로젝트를 닫으라는 조건과 Console 진입 조건의 충돌을 제거했습니다. 실제 실행 명령은 [PR #2 검증 절차](https://github.com/Popoisthebest/davinci-edit-mcp/blob/codex/v0.4-test-project-editing/docs/windows-edit-validation.md)에 있습니다. v0.3은 이 공통 대기 기능만 포함하고 편집/프로젝트 닫기를 허용하지 않습니다.

자동 루프 동안에는 전체 mailbox 뮤텍스를 소유해 다른 Utility·Console·운영 브리지와 동시 처리하지 않습니다. 동일한 요청 파일은 다시 처리/저장하지 않습니다. 수동 step의 중복 요청 캐시는 유지하며 저장 실패 후에도 실행된 편집을 다시 실행하지 않습니다. 처리기/I/O 예외는 중단과 FAILED 진단으로 남습니다. API 오류는 서명된 ERROR 응답으로 전달하고 편집 검증기가 다음 작업 중단·승인 폐기를 수행합니다. `service.json`의 context는 진입점 표식이며 인증 증거는 기존 서명된 요청/응답입니다.

Utility에는 고정된 사유 폴더의 payload를 시작하는 10줄 launcher만 설치합니다. 최초 ENTRY 출력 후 명시적인 절대 경로를 loadfile로 컴파일하고, 초기화와 run을 pcall 안에서 호출합니다. 같은 큰 chunk 내부에서 잡을 수 없었던 구문 오류가 이제 PAYLOAD_COMPILE로 구분됩니다. loadfile 부재는 BOOTSTRAP_LOADFILE_UNAVAILABLE입니다. 요청에서 파일명/코드를 받거나 package 경로를 탐색하지 않습니다. Lua 5.1의 getfenv/setfenv가 있으면 launcher의 스크립트 환경을 payload에 전달해 scoped ffi/bit도 보존합니다. 내부 모듈은 계속 고정 factory registry를 사용합니다. 이 신뢰 소스 bootstrap만 파일 로더를 사용하며 v0.2처럼 요청을 Lua 코드로 실행하지 않습니다. payload는 새 owner/SYSTEM 전용 폴더에 보관하며 기존 설치를 덮어쓰지 않습니다.

읽기 전용 자동 서비스가 필요한 경우 `scripts/ConsoleConnection.py --prepare-auto`로 별도 생성할 수 있습니다. 기존 `--prepare` 및 검증된 수동 Console 경로는 유지합니다. 실제 편집 단계에서는 PR #2의 EditValidation.py가 동일한 dispatcher를 사용하고 편집 모듈만 명시적으로 포함합니다. 읽기 전용 번들에는 편집 registry가 없으며 서명된 편집 명령도 거부합니다.

Console 대안은 준비된 신뢰 payload를 한 번 시작하고 짧은 run을 수행합니다. 매 요청마다 step을 입력하지 않습니다. `bmd.wait`를 사용하며 fusion:Execute·타이머·외부 코드 실행을 사용하지 않습니다. API 호출이나 호스트 스케줄링이 UI를 오래 점유할 수 있으므로 이 새 자동 루프의 실제 Console/Utility 반응성은 미검증입니다. 무응답이라고 중복 기동하거나 편집을 재요청하지 않습니다. 하나의 경로만 시작하고 실패 기록을 먼저 확인합니다.

이 구조는 한 번의 로컬 초기화 뒤 기존 stdio MCP 클라이언트가 요청을 보낼 수 있도록 합니다. 최종 ChatGPT 무인 편집의 구성 요소이며 실제 ChatGPT 연결·장시간 안정성·자동 시작·렌더 완료를 뜻하지 않습니다. 전용 승인과 프로젝트 보호를 생략하지 않습니다.

변경 파일: console.lua, native.lua, bundle.py, ConsoleConnection.py, console_connection.py, 자동 서비스/launcher/Windows 회귀 및 증거 문서입니다. 복구는 새 launcher와 전용 폴더만 정리하며 기존 Console·설치본·프로젝트·미디어를 보존합니다.
