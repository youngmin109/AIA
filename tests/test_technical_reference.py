from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCUMENT = ROOT / "docs" / "technical" / "AIA-TECHNICAL-REFERENCE.html"


def test_technical_reference_is_a_local_standalone_document() -> None:
    html = DOCUMENT.read_text(encoding="utf-8")

    assert '<html lang="ko">' in html
    assert "AIA 기술 문서" in html
    assert "Hook Sensor" in html
    assert "File Sensor" in html
    assert "Process Sensor" in html
    assert "Result Bundle" in html
    assert "정량 평가는 무엇을 비교하는가" in html
    assert "현재 구현과 주장 범위" in html
    assert "https://" not in html
    assert "http://" not in html


def test_technical_reference_has_navigation_targets() -> None:
    html = DOCUMENT.read_text(encoding="utf-8")

    for section_id in (
        "start",
        "overview",
        "architecture",
        "run",
        "sensors",
        "policy",
        "evidence",
        "demo",
        "evaluation",
        "limits",
        "runbook",
    ):
        assert f'id="{section_id}"' in html
        assert f'href="#{section_id}"' in html
