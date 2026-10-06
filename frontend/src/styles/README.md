# 콘솔 스타일 구조 (리퀴드 글래스, EPIC-020)

`src/index.css`가 아래 순서로 불러온다. 화면별 파일은 서로 다른 클래스 이름을 써서 순서에 기대지 않는다.

| 파일 | 역할 |
| --- | --- |
| `theme.css` | 다크 글래스 토큰(배경·유리·상태 색·그림자)과 기본 요소. 색상 테마는 `html[data-tint="violet\|indigo\|teal"]`, 유리 효과 끄기는 `html[data-glass="off"]`. **색 값은 이 파일에만 둔다.** |
| `glass.css` | 앱 셸·레일·유리 카드·버튼·배지·차트·폼·대화상자·가디언 아바타·모션 등 공통 부품 |
| `home.css` | ① 홈, ② 실행 중 |
| `sheet.css` | ④ 새 보호 실행 시트, Hook 연결 3단계 |
| `work.css` | ⑤ 작업창(대화·보호 패널), ⑥ 승인·종료 대화상자 |
| `result.css` | ③ 결과, ⑦ 복구 |
| `manage.css` | ⑧ 정책, ⑨ 기록, ⑩ 설정 |

## 규칙

- 새 색이 필요하면 `theme.css`에 역할 이름의 토큰을 만들고 `var(--토큰)`으로 쓴다. 투명도만 다른 흰색은 `--fill-*`, `--line-*`를 쓴다.
- 컴포넌트에 `style={{...}}`를 쓰지 않는다. 값에 따라 길이가 바뀌는 그래프는 SVG 속성(`width`, `stroke-dasharray`)으로 그린다(`components/common/Charts.tsx`).
- 버튼은 `components/common/Button`(cta·primary·secondary·outline·text·icon·iconText, 위험 동작은 `className="is-danger"`), 화면의 주 동작 하나는 `RoundAction`, 상태 표시는 `Badge`·`StatusPill`·`StatusDot`, 숫자는 `StatTile`, 아이콘 타일은 `GlossyIcon`·`TileCorner`를 쓴다.
- 움직임은 `html[data-motion]`과 `prefers-reduced-motion`을 따른다(`glass.css` 끝의 규칙).
- 위 규칙은 `frontend/tests/design-tokens.test.mjs`가 검사한다(`npm test`).
