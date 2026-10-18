# Utility 최소 경로 검사와 Console 대체 연결

후속 사용자 실기기 결과: Console HMAC·authenticated_ping·저장 응답 인증과 최소 Utility 표식이 모두 확인됐습니다. 통신 진단을 마무리하며 아래 과거 절차를 반복하지 않습니다. [현재 증거](verification-status.md)와 [자동 서비스](automatic-service.md)를 기준으로 다음 편집 단계로 진행합니다.

## 현재 판단

Windows 11 / Resolve 21.1.1 Free에서 Console 전체 PASS가 확인됐습니다. 사용자는 Resolve를 완전히 종료·재시작하고 기존 브리지를 실행하지 않은 상태에서도 v3 Utility가 무반응임을 확인했습니다. 같은 v2/v3 검사, 기존 브리지 종료, Resolve 재시작을 다시 요구하지 않습니다. 기존 상주 브리지가 이번 무반응을 설명한다는 가설은 이 증거로 약해졌습니다.

v3는 파일 외 UI 출력을 추가했지만 생성 파일은 약 20KB이며 runtime/codec/native 정의를 포함합니다. 호스트 호출 전 문제와 전체 chunk 파싱·UI/전역 문제를 분리하는 데 충분히 작지 않았습니다. 또한 동일 chunk의 구문 오류는 그 chunk의 pcall로 잡을 수 없습니다. 사용자 PC의 정확한 원인을 아직 특정하지 못했으며 Free 버전 제한이나 FFI 부재를 원인으로 단정하지 않습니다.

이번 최소 Utility 파일은 다음 두 줄뿐입니다. ID는 준비마다 고유합니다.

```lua
if type(print) == "function" then pcall(print,"RMC_UTILITY_ENTER_<ID>") end
error("RMC_UTILITY_ERROR_<ID> (intentional path check)",0)
```

모듈·registry·FFI·bit·UI·io·파일 접근·Resolve API·상주 루프·최상위 return이 없습니다. Lua 5.1/LuaJIT에서 유효하며 두 번째 줄의 오류는 의도된 실행 표식입니다. 이전 전체 진단과 별개의 호스트 호출/오류 출력 검사입니다. 새 파일은 기존 파일을 덮어쓰지 않고 `ResolveMCP_Path_<ID8>.lua`로 설치합니다. 설치 경로·확장자와 실제 파일 해시를 Inspector가 확인합니다.

Console 출력이나 Resolve의 Support/logs에서 고유 표식이 관측되면 해당 실행 경로의 증거가 됩니다. 호스트가 Lua 오류를 항상 Console/디스크 로그로 보내리라는 보장은 없으므로 표식 부재는 미실행의 증명이 아닙니다. Inspector는 최대 32개 로그의 각 1MiB 꼬리에서 토큰만 찾으며 원문을 출력하지 않습니다. 파일을 읽을 수 없거나 로그 폴더가 없으면 이를 구분합니다. micro 파일 자체는 결과 JSON을 쓰지 않습니다. 같은 최소 검사를 반복해 로그를 채우도록 요구하지 않습니다.

## Windows 최소 단계

수정 PR 소스의 저장소 루트에서 PowerShell을 사용합니다. Python 3.12 이외 pip/MCP/Lupa 설치는 필요하지 않습니다.

1. 한 번 준비합니다.

   ```powershell
   $cx = (& py -3.12 .\scripts\ConsoleConnection.py --prepare) | ConvertFrom-Json
   $cx.utility_menu_script
   $cx.console_command
   ```

2. Resolve Lua Console을 열어 둔 상태에서 출력된 새 `ResolveMCP_Path_<ID8>` Utility 항목을 한 번 선택합니다. `RMC_UTILITY_ERROR_...`는 의도된 오류입니다. 새 항목이 안 보이거나 아무 출력이 없어도 재시작/재실행을 반복하지 않고 Console 대체 연결로 진행합니다. micro 파일을 Console에서 실행하지 않습니다. 그렇게 하면 Utility 실행 증거와 섞입니다.

3. 출력된 `$cx.console_command` 한 줄을 Lua Console에 붙여 넣습니다. `manual-read-only`가 출력되고 즉시 제어가 돌아와야 합니다. 이는 별도 Console 서비스 객체를 만들며 자동 polling은 시작하지 않습니다.

4. PowerShell에서 새 요청을 보냅니다.

   ```powershell
   py -3.12 .\scripts\ConsoleConnection.py --ping (Join-Path $cx.root 'connection-info.json')
   ```

   `Request ready`가 표시되면 29초 안에 Lua Console에서 다음 한 줄을 실행합니다.

   ```lua
   print(RMCConsole.step())
   ```

   `true REPLIED`와 PowerShell의 `authenticated_ping: PASS`가 새 연결의 기대 결과입니다. 응답 없이 시간이 지나면 TIMEOUT으로 끝나며 자동 재시도하지 않습니다. 만료/서명을 완화하지 않습니다.

5. 파일 해시·로그 표식·저장된 응답의 인증을 한 번 확인합니다.

   ```powershell
   py -3.12 .\scripts\ConsoleConnection.py --inspect (Join-Path $cx.root 'connection-info.json')
   ```

검증 종료 시 `RMCConsole.close()`로 Console 객체를 닫을 수 있습니다. UI/프로젝트/미디어를 저장하거나 변경하지 않습니다. 모든 Console 조회가 이미 성공했으므로 여기서 전체 조회 검사까지 반복하지 않습니다.

## Console 구조와 보안

새 owner/SYSTEM 전용 `%LOCALAPPDATA%\ResolveMCPConsole_<UUID>\mailbox`를 사용합니다. 기존 운영 mailbox·키·승인 파일·원본 프로젝트·미디어·설치본은 사용하거나 변경하지 않습니다. 입력을 Lua로 실행하지 않고 기존 HMAC-SHA256 데이터 프로토콜로만 해석합니다. 동일 요청 캐시, 만료, 크기/개수 한도, 요청 ID/브리지 인스턴스 검증, 클라이언트 잠금, 경로/reparse 검사와 키 교체 시 중단을 유지합니다. 사용자 실행용 dofile은 준비한 고정 신뢰 소스만 시작하며 내부 모듈에는 동적 파일 로딩이 없습니다.

`step()`은 현재 요청 하나만 처리합니다. 기다리는 루프, bmd.wait, 타이머, fusion:Execute, 셸/외부 실행을 사용하지 않습니다. Windows 뮤텍스는 매 호출 안에서 획득/해제하므로 Console 호출 사이에 같은 OS 스레드를 가정하지 않습니다. 실패 시 자동 재실행하지 않고 응답 저장 실패 뒤에도 같은 요청의 이미 실행한 읽기는 캐시합니다.

조회 핸들러와 수명주기 stop만 구성합니다. v0.4에서도 편집 모듈·dispatcher·로컬 승인 파일을 로드하지 않으며 올바르게 서명된 편집 명령도 OP_NOT_ALLOWED로 거부합니다. 기존 운영 v0.4의 승인/프로젝트/미디어 보호는 바꾸지 않습니다.

이 방식은 수동 요청 처리 대안이며 자동 ChatGPT/MCP 연결 완료를 뜻하지 않습니다. 기존 stdio 서버를 같은 전용 mailbox로 연결하는 것은 프로토콜상 가능하나 각 요청마다 사용자가 step을 호출해야 합니다. 자동화에는 검증된 비차단 호스트 스케줄러가 필요하며 현재 그런 API의 실제 지원을 주장하지 않습니다. Console에서 기존 상주 run()을 직접 실행하는 방식은 UI/Console 점유 가능성 때문에 이번 대안으로 사용하지 않습니다.

## 검증 범위와 복구

자동 검사: 두 줄 파일의 Lua 5.1 오류 경로, 실제 LuaJIT의 수동 요청 처리·HMAC/변조 거부·만료·인스턴스·중복 캐시·쓰기 거부·키 교체·오류 시 뮤텍스 해제, Inspector의 파일/로그/응답 검증을 확인합니다. Windows CI는 실제 FFI/Win32와 Python의 서명 요청을 왕복하며 Resolve 객체는 모의입니다.

사용자 실기기 증거는 기존 Console 전체 PASS와 재시작 후 v3 Utility 무반응입니다. 새 micro 오류의 실제 출력 위치, 새 Console 서비스 객체 유지/step과 실제 연결은 미검증입니다. 실제 편집·설치 업그레이드/롤백 및 PR 병합은 보류합니다.

변경 파일은 console.lua, console_connection.py, bundle.py, ConsoleConnection.py, Console/Windows 회귀 테스트와 관련 문서입니다. 새 Utility 파일과 새 Console 전용 폴더만 수동 정리하면 복구됩니다. v2/v3 증거와 기존 설치본은 보존합니다.
