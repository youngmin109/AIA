from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
MARKDOWN_LINK = re.compile(r"!?\[[^\]]*\]\((?:<([^>]+)>|([^\s)]+))")


def test_public_documentation_relative_links_point_to_existing_files() -> None:
    documents = [ROOT / "README.md", ROOT / "README.ko.md"]
    documents.extend(sorted((ROOT / "docs").rglob("*.md")))

    for document in documents:
        document_name = document.relative_to(ROOT).as_posix()
        content = document.read_text(encoding="utf-8")

        for match in MARKDOWN_LINK.finditer(content):
            target = match.group(1) or match.group(2)
            parsed_target = urlsplit(target)
            if parsed_target.scheme or parsed_target.netloc or not parsed_target.path:
                continue

            linked_path = (document.parent / unquote(parsed_target.path)).resolve()
            line_number = content.count("\n", 0, match.start()) + 1
            assert linked_path.exists(), (
                f"{document_name}:{line_number} links to missing file {target!r}"
            )
