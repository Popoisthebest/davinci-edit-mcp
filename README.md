# davinci-edit-mcp

DaVinci Resolve Free Edition을 위한 AI 영상 편집 MCP 개발 프로젝트입니다.

Windows 11 + DaVinci Resolve 21.1.1 Free 실기기에서 Console HMAC 통신·응답 인증과 최소 Utility 실행 표식이 확인됐습니다. 통신 진단은 완료했으며 [현재 검증 상태](docs/verification-status.md)에 증거와 한계를 기록했습니다. v0.4 신규 테스트 프로젝트 편집의 구현·검증 준비는 [PR #2](https://github.com/Popoisthebest/davinci-edit-mcp/pull/2)에 있으며 실제 편집은 아직 NOT_RUN입니다. 렌더링 자동화는 미구현입니다.

## 검증된 기능 (v0.2)

- `ping`: 버전 정보 및 브리지 연결
- `current_project`: 현재 프로젝트명 및 타임라인 개수
- `current_timeline`: 타임라인명, 비디오/오디오 트랙 수, 프레임 범위
- Lua `loadfile` 입력 + Fusion prefs 응답의 로컬 왕복 통신

기존 테스트 출력: `RESOLVE MCP BRIDGE: PASS` (사용자 Windows PC에서 수동 확인).

## 개발 시작

Codex에 레포지토리를 연결하고 `CODEX_START.md`를 첫 지시로 제공하세요. `AGENTS.md`와 `SPEC.md`의 보안/원본 보존 조건을 우선 적용합니다.

기존 v0.2 소스는 `legacy_v0.2/`에 보관했습니다. 작동 중인 설치본을 바로 덮어쓰지 말고, 새 모듈을 별도 경로에서 구현하고 테스트하세요.

## 새 개발 버전 v0.3

`src/resolve_mcp/`에 인증된 데이터 전용 통신, 읽기 전용 MCP 도구 9개와 Windows 설치/복구 스크립트를 추가했습니다. `legacy_v0.2/`는 변경하지 않았습니다. 자동 테스트는 실제 LuaJIT와 모의 Resolve 객체를 사용하며, Windows/Resolve Free 실기기 호환성은 미검증입니다.

설치·자동 검사·제한 사항은 [v0.3 기록](docs/v0.3.md)을 확인하세요.

## 목표

1. v0.3: 안정성, 조회 기능, 보안 강화
2. v0.4: 테스트 프로젝트에서 미디어 가져오기 및 프레임 기반 클립 배치
3. v0.5: 자막, 근거 자료, 기본 애니메이션, 오디오 편집
4. v0.6+: 검증 가능한 쇼츠 조립 계획, H.264 출력 및 품질 검사
5. v1.0: ChatGPT Desktop Work 플러그인 연결 및 E2E 실기기 검증

## 안전·라이선스

이 브리지는 연구용 코드이며 보안 심사를 마친 제품이 아닙니다. 특히 `loadfile`은 내용이 Lua 코드인 로컬 파일을 실행합니다. 브리지를 공용 네트워크에 노출하지 말고, 쓰기 기능 추가 전 요청 무결성·접근권한·상태 변경 승인·원본 보존 정책을 먼저 구현해야 합니다.

외부 오픈소스 코드를 도입할 경우 라이선스를 검토해야 합니다. 프로젝트 전체 라이선스는 아직 결정되지 않았습니다. 공개 저장소에 올렸다고 임의의 재사용 권한이 부여되지는 않습니다.
