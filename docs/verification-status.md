# 실기기 증거와 현재 단계

사용자 제공 Windows 11 / DaVinci Resolve 21.1.1 Free 결과를 기준으로 합니다.

| 범위 | 상태 | 근거/한계 |
| --- | --- | --- |
| Console 전역·FFI·Win32·조회 진단 | PASS | 사용자 전체 Console 검사 결과 |
| Console HMAC 요청·authenticated_ping·저장 응답 인증 | PASS | 사용자가 실제 왕복 및 인증 성공 확인 |
| 최소 Utility 스크립트 실행 | PASS | 사용자가 고유 실행 표식 확인 |
| 빈 SDK 목록의 `__flags` 숫자 메타데이터 | 확인 | 실제 키는 문자열 `__flags`(밑줄 2개), 값은 number, 메타테이블 nil; GetClipList·GetSubFolderList·GetRenderJobList 모두 동일; 타임라인 0개·현재 타임라인 nil |
| 신규 세션의 `current_project`·`__flags` 검사·서비스 stop | PASS | 사용자 편집 시도에서 확인; CloseProject=true 뒤 현재 프로젝트가 남아 생성 전에 거부됨 |
| CloseProject 이후 종료 완료 확인·클립보드 자동 복사 | 미검증 | 새 제한 관측/서명 기록·실행 시 Lua 복사 구조; 실제 종료가 지연되는 원인은 아직 확정되지 않음 |
| Utility 전체 payload·자동 처리·UI 반응성 | 미검증 | 최소 스크립트 성공만으로 전체 서비스 성공을 뜻하지 않음 |
| HMAC 시작 대기·빈 임시 프로젝트에서 안전 전환 | 미검증 | 자동 회귀/Windows CI의 Resolve 객체는 모의; 사용자 PC 전환 결과 필요 |
| 신규 테스트 프로젝트 실제 가져오기·타임라인·클립 배치·조회 | NOT_RUN | PR #2의 편집 검증기로 다음 단계 진행 |
| 실제 렌더·오디오·완성 영상 | NOT_RUN | 이번 범위에 없음 |

통신 진단은 완료했습니다. v2/v3·최소 표식·Console HMAC 검사를 다시 요구하지 않습니다. 기존 프로젝트와 원본은 보존하며 PR #1과 #2는 병합하지 않습니다. 편집 자동 검사는 모의 Resolve이며 실제 API 결과와 구분합니다.

실기기에서 확정한 키는 `__flags`입니다. `_flags`만 허용하던 검증기가 빈 임시 프로젝트를 거부한 원인을 수정했습니다. PR #2는 빈 일반 테이블 또는 `_flags`/`__flags`의 유한 숫자형 메타데이터만 있는 일반 테이블을 허용합니다. 두 키가 함께 있으면 각각 같은 검사를 적용합니다. 미디어·폴더·렌더 작업 모두 실제 항목·다른 키·잘못된 값·메타테이블·잘못된 반환형은 계속 거부합니다. 기본 모의 SDK와 Windows Win32/HMAC 전체 편집 검사에 실제 `__flags` 구조를 반영했습니다. 추가 사용자 진단 없이 수정했으며, 수정 후 실제 프로젝트 전환·클립 편집은 아직 미검증입니다.

후속 실기기에서는 빈 상태 검사를 통과했으나 CloseProject=true 직후 GetCurrentProject가 객체를 반환했습니다. 반환값만으로 종료를 인정하지 않고, 최대 5초의 조회·두 차례 연속 nil·생성 직전 재검사를 추가했습니다. 같은 승인 ID의 객체 잔존·같은 ID의 다른 wrapper·읽을 수 없는 이전 참조·다른 프로젝트·API 오류를 기록하며, 비동기 종료와 오래된 객체가 같은 관측을 만들면 내부 원인을 단정하지 않습니다. close는 한 번만 시도하고 다른 프로젝트는 저장/닫기/열기하지 않습니다. 서명된 로컬 관측은 편집 승인으로 사용하지 않습니다.

[자동 서비스 구조](automatic-service.md)는 기존 수동 Console step을 보존하고, 별도 명시적 실행 시에만 유한한 처리 루프를 시작합니다. 실제 편집 준비 및 명령은 [PR #2](https://github.com/Popoisthebest/davinci-edit-mcp/pull/2)의 docs/windows-edit-validation.md에 있습니다.
