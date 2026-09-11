# AIA 0.1.14 Release Readiness

0.1.14는 로컬 Security Console의 첫 화면 경험을 보강한 릴리스다. 대시보드에서
사용자는 보호 실행을 시작하기 전에 AIA가 현재 실행 가능한지, Codex Hook Trust가
어떤 상태인지, 어떤 도구 범위를 지원하는지, 최근 실행 결과가 무엇인지 확인할 수
있다.

## 사용 흐름

```powershell
aia demo
aia console --open
```

콘솔에서 `대시보드`를 열면 다음을 확인할 수 있다.

- 실행 준비 상태와 readiness code
- Codex PreToolUse Hook Trust 상태
- Windows 11·Codex CLI·지원되는 PreToolUse 도구라는 보호 범위
- `aia setup` → Codex `/hooks` 검토·신뢰 → `aia hook verify` 순서
- 최근 Protected Run과 Result Bundle 상태

대시보드는 실행을 자동으로 시작하지 않는다. 보호 실행은 기존과 같이 `새 보호
실행` 화면에서 Workspace와 정책을 선택한 뒤 사용자가 명시적으로 시작한다.

## 검증 명령

```powershell
uv sync --locked
uv run pytest -ra
uv run aia --version
uv run aia demo
powershell -ExecutionPolicy Bypass -File .\\scripts\\package-release.ps1 -Force
```

실제 Codex 보호 범위와 제한사항은 [제품 상태](PRODUCT-STATUS.md),
[지원 계약](PRODUCT-SUPPORT.md), [제한사항](LIMITATIONS.md)을 함께 확인한다.
