from pathlib import Path
import struct
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
    # Native TypeScript stripping in the dependency-free frontend tests needs
    # Node 24. Keep the package/build contract and require those tests in CI.
    assert "node-version: 24" in workflow[setup_node:package_build]
    assert "working-directory: frontend" in workflow[setup_node:package_build]
    assert "cache-dependency-path: frontend/package-lock.json" in workflow[setup_node:package_build]
    assert "npm ci" in workflow[setup_node:package_build]
    assert "npm run build" in workflow[setup_node:package_build]
    assert "npm run lint" in workflow[setup_node:package_build]
    assert "npm test" in workflow[setup_node:package_build]


def test_packages_ship_the_gitignored_react_console() -> None:
    # Hatch drops VCS-ignored files from the sdist and uv builds the wheel from
    # that sdist, so the built console must be declared as a build artifact.
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    artifacts = config["tool"]["hatch"]["build"]["artifacts"]
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "src/aia_web/static/app/" in gitignore
    assert "src/aia_web/static/app/**" in artifacts


def test_desktop_build_bundles_a_multi_size_icon_for_the_title_bar() -> None:
    # The title bar draws a 16px frame. The desktop window loads it from the
    # .ico bundled beside aia_desktop/launcher.py instead of shrinking the exe icon.
    build = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    assert '--add-data "${iconPath};aia_desktop"' in build
    ico = (ROOT / "packaging" / "windows" / "aia.ico").read_bytes()
    reserved, kind, count = struct.unpack_from("<HHH", ico)
    sizes = {ico[6 + 16 * index] or 256 for index in range(count)}
    assert (reserved, kind) == (0, 1)
    assert {16, 24, 32, 48, 256} <= sizes
