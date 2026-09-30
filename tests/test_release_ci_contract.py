from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def test_release_verifier_and_ci_build_the_spa_before_packaging() -> None:
    verifier = (ROOT / "scripts" / "verify-release.ps1").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert "templates\\new_run.html" not in verifier
    assert "templates\\live_run.html" not in verifier
    assert "static\\app.css" not in verifier
    assert 'app_root = root / "static" / "app"' in verifier
    assert 'required = (app_root / "index.html",)' in verifier
    assert '"assets").glob("*.js")' in verifier

    setup_node = workflow.index("uses: actions/setup-node@v4")
    package_build = workflow.index("run: uv build")
    assert setup_node < package_build
    assert "node-version: 20" in workflow[setup_node:package_build]
    assert "working-directory: frontend" in workflow[setup_node:package_build]
    assert "cache-dependency-path: frontend/package-lock.json" in workflow[setup_node:package_build]
    assert "npm ci" in workflow[setup_node:package_build]
    assert "npm run build" in workflow[setup_node:package_build]
    assert "npm run lint" in workflow[setup_node:package_build]


def test_packages_ship_the_gitignored_react_console() -> None:
    # Hatch drops VCS-ignored files from the sdist and uv builds the wheel from
    # that sdist, so the built console must be declared as a build artifact.
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    artifacts = config["tool"]["hatch"]["build"]["artifacts"]
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "src/aia_web/static/app/" in gitignore
    assert "src/aia_web/static/app/**" in artifacts
