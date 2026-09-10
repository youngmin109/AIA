"""Local proof that the installed Codex Hook was observed in a live run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .codex_installation import CodexHookInstaller


_SCHEMA_VERSION = "aia-hook-verification-3"
_RUNTIME_PATH = (Path(__file__).resolve().parent / "codex_hook_runtime.py").resolve()


class HookVerificationStore:
    """Persist and validate one local, installation-bound Hook proof."""

    def __init__(self, control_root: str | Path) -> None:
        self.control_root = Path(control_root).expanduser().resolve(strict=False)
        self.path = self.control_root / "hook-verification.json"

    @staticmethod
    def _sha256(path: Path) -> str | None:
        try:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    @classmethod
    def _codex_config_path(cls) -> Path:
        configured = os.environ.get("CODEX_HOME")
        root = (
            Path(configured).expanduser().resolve(strict=False)
            if configured
            else (Path.home() / ".codex").resolve(strict=False)
        )
        return root / "config.toml"

    @classmethod
    def _fingerprint(
        cls,
        installer: CodexHookInstaller,
        executable: str | Path,
    ) -> dict[str, object] | None:
        hook_path = installer.path.resolve(strict=False)
        executable_path = Path(executable).expanduser().resolve(strict=False)
        hook_sha256 = cls._sha256(hook_path)
        runtime_sha256 = cls._sha256(_RUNTIME_PATH)
        if hook_sha256 is None or runtime_sha256 is None:
            return None
        config_path = cls._codex_config_path()
        try:
            stat = executable_path.stat()
        except OSError:
            return None
        return {
            "hook_path": str(hook_path),
            "hook_sha256": hook_sha256,
            "codex_config": str(config_path),
            "codex_config_sha256": cls._sha256(config_path),
            "aia_hook_runtime": str(_RUNTIME_PATH),
            "aia_hook_runtime_sha256": runtime_sha256,
            "codex_executable": str(executable_path),
            "codex_size": stat.st_size,
            "codex_mtime_ns": stat.st_mtime_ns,
        }

    def read(self) -> dict[str, Any] | None:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def is_current(
        self,
        installer: CodexHookInstaller,
        executable: str | Path,
    ) -> bool:
        proof = self.read()
        fingerprint = self._fingerprint(installer, executable)
        if proof is None or fingerprint is None:
            return False
        if proof.get("schema_version") != _SCHEMA_VERSION:
            return False
        if proof.get("verified") is not True:
            return False
        return all(proof.get(key) == value for key, value in fingerprint.items())

    def write_verified(
        self,
        *,
        installer: CodexHookInstaller,
        executable: str | Path,
        session_id: str,
        hook_event_count: int,
    ) -> Path:
        fingerprint = self._fingerprint(installer, executable)
        if fingerprint is None:
            raise OSError("cannot fingerprint the installed Hook and Codex executable")
        document: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "verified": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "hook_event_count": hook_event_count,
            **fingerprint,
        }
        self.control_root.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.control_root,
                prefix=".hook-verification.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
                temporary_path = Path(stream.name)
            os.replace(temporary_path, self.path)
        except OSError:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        return self.path


__all__ = ["HookVerificationStore"]
