ResolveMCP Server v0.2 — Windows + DaVinci Resolve 21.1.1 Free
===============================================================
용도: 로컬 MCP 서버의 읽기 기능 (ping / 현재 프로젝트 / 현재 타임라인).
기존 프로젝트와 타임라인은 수정하지 않습니다.

사전 조건
- Python 3.12 및 %LOCALAPPDATA%\ResolveMCP\server\.venv
- 가상환경에 mcp 패키지 설치

설치
1. DaVinci Resolve를 완전히 종료합니다.
2. 이 폴더에서 PowerShell 열기:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\01_Install.ps1"
3. DaVinci Resolve 실행 후 테스트 프로젝트 열기
4. 작업 공간 → 스크립트 → Utility → ResolveMCP를 한 번만 실행
5. 같은 PowerShell에서:
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File ".\02_Test.ps1"

예상 결과: RESOLVE MCP BRIDGE: PASS

주의
- 이 코드는 사용자의 PC에서 통신 테스트에 통과했지만, 다른 환경에서의 호환성은 별도 검증이 필요합니다.
- loadfile() 기반 명령 파일은 Lua 코드로 해석되므로 보안상 주의가 필요합니다.
- 공용 네트워크에 노출하지 마세요. v0.1과 v0.2 동시 실행도 피하세요.
- 이 레거시 코드는 직접 편집하지 말고 새 버전에서 개선하세요.
