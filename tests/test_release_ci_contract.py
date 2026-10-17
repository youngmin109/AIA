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


def test_windows_release_builds_signs_and_installs_the_hook_forwarder() -> None:
    # Codex starts aia-hook.exe for every Hook event; it must stay a small build
    # of the stdlib forwarder and land at the fixed path the installer owns.
    build = (ROOT / "scripts" / "build-windows.ps1").read_text(encoding="utf-8")
    hook_build = build[build.index("--name aia-hook"):]
    hook_build = hook_build[: hook_build.index("throw")]
    assert r"src\aia_hook_client\__main__.py" in hook_build
    assert "--collect-all" not in hook_build
    assert "--onedir" in build[build.index("Building the Codex Hook forwarder"):]

    installer = (ROOT / "packaging" / "windows" / "AIA.iss").read_text(encoding="utf-8")
    assert r'Source: "..\..\dist\windows\aia-hook\*"; DestDir: "{app}\aia-hook"' in installer
    assert r"DefaultDirName={localappdata}\Programs\AIA" in installer

    signing = (ROOT / "scripts" / "sign-windows.ps1").read_text(encoding="utf-8")
    assert signing.count(r'"aia-hook\aia-hook.exe"') == 2
    package = (ROOT / "scripts" / "package-windows.ps1").read_text(encoding="utf-8")
    assert r'"dist\windows\aia-hook"' in package


def _installer_section(installer: str, name: str) -> str:
    marker = f"[{name}]\n"
    assert marker in installer
    return installer.split(marker, 1)[1].split("\n[", 1)[0]


def test_installer_clears_both_old_asset_directories_before_files() -> None:
    installer = (ROOT / "packaging" / "windows" / "AIA.iss").read_text(encoding="utf-8")
    delete_section = _installer_section(installer, "InstallDelete")

    assert installer.index("[InstallDelete]") < installer.index("[Files]")
    assert r'Type: filesandordirs; Name: "{app}\_internal\aia_web\static\app\assets"' in delete_section
    assert r'Type: filesandordirs; Name: "{app}\aia-cli\_internal\aia_web\static\app\assets"' in delete_section


def test_installer_delete_targets_are_only_the_two_asset_directories() -> None:
    installer = (ROOT / "packaging" / "windows" / "AIA.iss").read_text(encoding="utf-8")
    delete_section = _installer_section(installer, "InstallDelete")
    delete_commands = [line.strip() for line in delete_section.splitlines() if line.strip()]

    assert delete_commands == [
        r'Type: filesandordirs; Name: "{app}\_internal\aia_web\static\app\assets"',
        r'Type: filesandordirs; Name: "{app}\aia-cli\_internal\aia_web\static\app\assets"',
    ]


def test_installer_delete_keeps_docs_and_hook_install_directories() -> None:
    installer = (ROOT / "packaging" / "windows" / "AIA.iss").read_text(encoding="utf-8")
    delete_section = _installer_section(installer, "InstallDelete")
    delete_targets = [
        line.split('Name: "', 1)[1].split('"', 1)[0]
        for line in delete_section.splitlines()
        if 'Name: "' in line
    ]
    files_section = _installer_section(installer, "Files")

    assert all(r"\docs" not in target and r"\aia-hook" not in target for target in delete_targets)
    assert r'DestDir: "{app}\docs"' in files_section
    assert r'DestDir: "{app}\aia-hook"' in files_section
