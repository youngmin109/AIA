from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_contributor_docs_exist_and_list_local_validation_commands() -> None:
    contributing = (ROOT / "CONTRIBUTING.md").read_text(encoding="utf-8")
    templates = (
        ROOT / ".github" / "ISSUE_TEMPLATE" / "bug_report.md",
        ROOT / ".github" / "ISSUE_TEMPLATE" / "feature_request.md",
        ROOT / ".github" / "pull_request_template.md",
    )

    assert all(template.is_file() for template in templates)

    blocks = re.findall(r"```powershell\s*\n(.*?)```", contributing, re.DOTALL)
    assert len(blocks) == 1
    commands = {line.strip() for line in blocks[0].splitlines() if line.strip()}
    assert commands == {
        ".venv\\Scripts\\python.exe -m pytest -q",
        "npm --prefix frontend run build",
        "npm --prefix frontend run lint",
    }
