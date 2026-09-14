# 최소 테스트 Fixture

이 디렉터리는 저장소에 포함해도 안전한 작은 Workspace Fixture를 둔다.
실제 사용자 Workspace, `.env` 원문, 실행 중 생성되는 Evidence·JSONL·DB는 포함하지
않는다. 반복 평가용 Fixture는 `scripts/product_evaluation/run_fixture_evaluation.py`가
각 실행마다 임시 Workspace에 결정론적으로 생성한다.
