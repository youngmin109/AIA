# AIA 문서 길잡이

AIA 문서는 대부분 한국어로 쓰여 있습니다. Most documents are in Korean; start
with the [English README](../README.md) for an overview.

## 처음 쓰는 사람

| 문서 | 내용 |
|---|---|
| [빠른 시작](QUICKSTART.md) | 설치 후 첫 보호 실행까지 |
| [사용자 가이드](USER-GUIDE.md) | 화면별 사용법과 상태 읽는 법 |
| [개인 보호 안내](PERSONAL-PROTECTION.md) | 정책, 꼭 지킬 파일, 복구 지점 |
| [Windows 데스크톱](WINDOWS-DESKTOP.md) | 데스크톱 앱 실행과 빌드 |
| [문제 해결](TROUBLESHOOTING.md) | 자주 생기는 문제와 해결 방법 |
| [명령줄 안내](CLI-GUIDE.md) | `aia` 명령으로 보호 실행·점검·증명하기 |
| [사용자 가이드(위키판)](wikidocs/AIA-사용자-가이드.md) | 처음 쓰는 절차를 길게 풀어 쓴 판 |

## 무엇을 지키고 무엇을 못 지키는지

| 문서 | 내용 |
|---|---|
| [한계](LIMITATIONS.md) | 지원 범위와 하지 않는 일 |
| [제품 지원 범위](PRODUCT-SUPPORT.md) | 지원하는 환경과 상태 해석 |
| [제품 상태](PRODUCT-STATUS.md) | 지금 동작하는 기능과 검증 상태 |
| [위협 모델](THREAT-MODEL.md) | 어떤 위협을 다루고 어떤 위협은 범위 밖인지 |
| [실제 Codex 차단 증명](ACTUAL-CODEX-PROOF.md) | 실제 Codex로 확인한 사전 차단 |
| [주장 범위표](validation/CLAIM-MATRIX.md) | 제품이 주장할 수 있는 것과 근거 |

## 구조와 기술

| 문서 | 내용 |
|---|---|
| [시스템 구성](SYSTEM-OVERVIEW.md) | 전체 구성도 |
| [보호 실행 흐름](AIA-PROTECTED-RUN-FLOW.md) | 보호 실행이 시작부터 결과까지 거치는 단계 |
| [아키텍처](../ARCHITECTURE.md), [제품 정의](../PROJECT.md) | 상위 흐름과 보안 불변식 |
| [코어 구조](core/CORE-ARCHITECTURE.md), [코어 목록](core/CORE-INVENTORY.md) | 모듈 구성 |
| [센서·정책 기술 문서](technical/AIA-RUNTIME-SECURITY-WHITEPAPER.md) | 훅·파일·프로세스 센서와 정책의 원리 |
| [정책 설정 구조](technical/POLICY-SETTINGS-STRUCTURE.md) | 정책 파일 형식 |
| [기술 참고서(HTML)](technical/AIA-TECHNICAL-REFERENCE.html) | 발표·코드 리뷰용 순서대로 보는 기술 문서 |

## 배포

| 문서 | 내용 |
|---|---|
| [배포](DISTRIBUTION.md) | 배포 묶음 구성 |
| [Windows 코드 서명](WINDOWS-SIGNING.md) | 서명 인증서와 릴리스 패키징 |
| [릴리스 기록](releases/) | 버전별 릴리스 문서 |

## 개발 기록

제품을 만들면서 남긴 기록입니다. 지금 동작과 다를 수 있으니, 현재 동작은 위의
문서를 기준으로 봐 주세요.

| 폴더·문서 | 내용 |
|---|---|
| [epics/](epics/) | 작업 묶음(EPIC)별 계약과 결정 |
| [codex-parity/](codex-parity/) | Codex 작업 경험 맞추기(EPIC-022) 진행 기록 |
| [ui-redesign/](ui-redesign/) | 화면 개편(리퀴드 글래스) 기록 |
| [validation/](validation/) | 평가 기준, 평가 결과, 검증 증거 |
| [history/](history/) | 개발 중 인수인계 문서 |
| [P0 참고](REFERENCE-P0.md), [제품 업데이트 10/2](PRODUCT-UPDATE-2026-10-02.md) | 초기 검증과 중간 업데이트 |
| [assets/](assets/), [generated/](generated/) | 그림과 생성한 문서(docx) |
