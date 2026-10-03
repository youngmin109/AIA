# 콘솔 스타일 구조

`src/index.css`가 아래 순서로 불러온다. 순서가 곧 우선순위이므로 바꾸지 않는다.

| 파일 | 역할 |
| --- | --- |
| `theme.css` | 색·글꼴·간격·그림자 토큰(다크 기본 + `[data-theme='light']`)과 기본 요소 스타일. **색 값은 이 파일에만 둔다.** |
| `shell.css` | 앱 골격(사이드바·상단바·대화·결과·대화상자 등) |
| `redesign.css` | 제품 화면(대시보드·정책·설정 카드) |
| `product-update.css` | 세션 목록·가디언 도움말·복구 흐름·모션 |
| `components.css` | 예전 인라인 `style={{}}`를 옮긴 컴포넌트 클래스. 마지막에 불러와 같은 우선순위의 공용 규칙보다 앞선다. |

## 규칙

- 새 색이 필요하면 `theme.css`에 역할 이름의 토큰을 만들고 `var(--토큰)`으로 쓴다. 두 테마에서 값이 다르면 light 블록에서 다시 정의한다.
- 컴포넌트에 `style={{...}}`를 쓰지 않는다. 동적인 값은 클래스 조합이나 CSS 변수로 넘긴다.
- 버튼은 `components/common/Button`(variant: cta·primary·secondary·outline·text·icon·iconText), 상태 표시는 `Badge`(ok·warn·bad·neutral·accent)와 `StatusPill`(good·ok·neutral·warning·warn·bad), 빈 화면은 `EmptyState`를 쓴다.
- 위 규칙은 `frontend/tests/design-tokens.test.mjs`가 검사한다(`npm test`).

## 알려진 정리 대상

- 같은 선택자가 두 번 이상 정의된 곳이 120개 남아 있다. 사이에 같은 우선순위(specificity)의 규칙이 있어, 합치면 적용 순서가 바뀔 수 있는 경우만 남겼다.
- `status-pill`에 `warn` 톤을 주는 곳이 있지만 `.status-pill.warn` 규칙은 없다(기본 모양으로 보인다).
