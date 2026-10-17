"""Local proof that the installed Codex Hook was observed in a live run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile
import sys
import tomllib
from typing import Any

from .codex_installation import CodexHookInstaller


_SCHEMA_VERSION = "aia-hook-verification-6"
_RUNTIME_PATH = (Path(__file__).resolve().parent / "codex_hook_runtime.py").resolve()


def _runtime_identity() -> str:
    """Return a stable identity for the Hook runtime in source or frozen mode.

    The desktop and diagnostic PyInstaller executables each unpack the same
    module under a different ``_internal`` directory.  The path is therefore
    useful as a source-mode diagnostic, but cannot identify a frozen runtime.
    The runtime content hash remains the integrity binding in both modes.
    """

    if getattr(sys, "frozen", False):
        return "packaged:aia.codex_hook_runtime"
    return str(_RUNTIME_PATH)


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
    def _codex_config_fingerprint(cls, path: Path) -> str | None:
        """Hash security-relevant Codex configuration, excluding trust bookkeeping.

        Codex records a user's decision to trust a Workspace in ``[projects]``.
        That bookkeeping changes whenever a new project is opened, but it does
        not change the installed AIA Hook or its execution contract. Hashing
        the whole file made a valid Hook proof expire after every new Workspace.
        Keep all other configuration in the fingerprint so changes to execution
        behavior still require a fresh live proof.
        """

        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None

        projects = document.get("projects")
        if isinstance(projects, dict):
            for project_path, settings in list(projects.items()):
                if not isinstance(settings, dict):
                    continue
                settings.pop("trust_level", None)
                if not settings:
                    projects.pop(project_path, None)
            if not projects:
                document.pop("projects", None)

        canonical = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @classmethod
    def _codex_config_hashes_and_table_names(
        cls, path: Path
    ) -> tuple[dict[str, str], list[str]] | None:
        try:
            document = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            return None

        projects = document.get("projects")
        if isinstance(projects, dict):
            for project_path, settings in list(projects.items()):
                if not isinstance(settings, dict):
                    continue
                settings.pop("trust_level", None)
                if not settings:
                    projects.pop(project_path, None)
            if not projects:
                document.pop("projects", None)

        hashes: dict[str, str] = {}
        table_names: list[str] = []
        for name, value in document.items():
            is_table = isinstance(value, (dict, list))
            if is_table:
                table_names.append(name)
            elif not isinstance(value, (str, int, float, bool)):
                continue
            canonical = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            hashes[name] = hashlib.sha256(canonical).hexdigest()
        return hashes, sorted(table_names)

    @classmethod
    def _codex_config_tables_sha256(cls, path: Path) -> dict[str, str] | None:
        """Hash top-level tables and scalar values without retaining their values."""

        metadata = cls._codex_config_hashes_and_table_names(path)
        return metadata[0] if metadata is not None else None

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
        executable_sha256 = cls._sha256(executable_path)
        if executable_sha256 is None:
            return None
        # The program Codex starts for every Hook event.  A standalone
        # forwarder no longer runs codex_hook_runtime.py, so bind its bytes too.
        hook_executable = installer.hook_executable.expanduser().resolve(strict=False)
        return {
            "hook_path": str(hook_path),
            "hook_sha256": hook_sha256,
            "hook_executable": str(hook_executable),
            "hook_executable_sha256": cls._sha256(hook_executable),
            "codex_config": str(config_path),
            "codex_config_sha256": cls._codex_config_fingerprint(config_path),
            "aia_hook_runtime": _runtime_identity(),
            "aia_hook_runtime_sha256": runtime_sha256,
            "codex_executable": str(executable_path),
            # File size and mtime are useful diagnostics but are not a
            # sufficient identity. A same-size replacement can retain a
            # practically indistinguishable timestamp on Windows.
            "codex_executable_sha256": executable_sha256,
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
        if proof.get("aia_hook_runtime") != fingerprint["aia_hook_runtime"]:
            # Proofs written by an earlier packaged build used the physical
            # ``AIA`` or ``aia-cli`` extraction path.  Keep those proofs
            # usable when the runtime bytes are unchanged; the hash, rather
            # than the unpack directory, is the security-relevant binding.
            if not (
                getattr(sys, "frozen", False)
                and proof.get("aia_hook_runtime_sha256")
                == fingerprint["aia_hook_runtime_sha256"]
            ):
                return False
        return all(
            proof.get(key) == value
            for key, value in fingerprint.items()
            if key != "aia_hook_runtime"
        )

    def stale_reasons(
        self,
        installer: CodexHookInstaller,
        executable: str | Path | None,
    ) -> list[str]:
        """Explain stale proof bindings using names only, never their values."""

        proof = self.read()
        if proof is None:
            return ["아직 연결 검증을 한 적이 없어요"]
        if executable is None:
            return ["Codex 실행 파일을 확인할 수 없어요"]

        fingerprint = self._fingerprint(installer, executable)
        if fingerprint is None:
            return ["현재 연결 정보를 확인할 수 없어요"]

        reasons: list[str] = []
        if not installer.is_installed():
            reasons.append("AIA Hook이 설치되어 있지 않아요")

        if any(
            proof.get(key) != fingerprint.get(key)
            for key in ("hook_path", "hook_sha256")
        ):
            reasons.append("Hook 설정 파일(hooks.json)이 바뀌었어요")

        if any(
            proof.get(key) != fingerprint.get(key)
            for key in ("hook_executable", "hook_executable_sha256")
        ):
            reasons.append("AIA Hook 프로그램(aia-hook.exe)이 바뀌었어요")

        codex_executable_changed = any(
            proof.get(key) != fingerprint.get(key)
            for key in (
                "codex_executable",
                "codex_executable_sha256",
                "codex_size",
                "codex_mtime_ns",
            )
        )
        if codex_executable_changed:
            version_suffix = ""
            previous_version = proof.get("codex_version")
            if isinstance(previous_version, str) and re.fullmatch(
                r"\d+\.\d+\.\d+", previous_version
            ):
                try:
                    from .adapters.codex import CodexAdapter

                    current_version = CodexAdapter.executable_version(executable)
                except Exception:
                    current_version = "unknown"
                if isinstance(current_version, str) and re.fullmatch(
                    r"\d+\.\d+\.\d+", current_version
                ):
                    version_suffix = f" ({previous_version} → {current_version})"
            reasons.append(f"Codex 실행 파일이 바뀌었어요{version_suffix}")

        codex_config_changed = any(
            proof.get(key) != fingerprint.get(key)
            for key in ("codex_config", "codex_config_sha256")
        )
        if codex_config_changed:
            stored_hashes = proof.get("codex_config_tables_sha256")
            current_metadata = self._codex_config_hashes_and_table_names(
                self._codex_config_path()
            )
            if not isinstance(stored_hashes, dict) or current_metadata is None:
                reasons.append(
                    "Codex 설정 파일이 바뀌었어요(어느 표인지는 다음 검증부터 보여요)"
                )
            elif not isinstance(proof.get("codex_config_table_names"), list) or not all(
                isinstance(name, str)
                for name in proof["codex_config_table_names"]
            ):
                reasons.append(
                    "Codex 설정 파일이 바뀌었어요(어느 항목인지는 다음 검증부터 보여요)"
                )
            else:
                current_hashes, current_table_names = current_metadata
                stored_table_names = proof["codex_config_table_names"]
                changed_names = sorted(
                    name
                    for name in set(stored_hashes) | set(current_hashes)
                    if stored_hashes.get(name) != current_hashes.get(name)
                    and isinstance(name, str)
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
                )
                if changed_names:
                    table_names = set(stored_table_names) | set(current_table_names)
                    rendered_names = ", ".join(
                        f"[{name}] 표" if name in table_names else f"{name} 항목"
                        for name in changed_names
                    )
                    reasons.append(
                        f"Codex 설정 파일이 바뀌었어요: {rendered_names}"
                    )
                else:
                    reasons.append("Codex 설정 파일이 바뀌었어요")

        runtime_identity_changed = proof.get("aia_hook_runtime") != fingerprint.get(
            "aia_hook_runtime"
        )
        packaged_runtime_matches = bool(
            getattr(sys, "frozen", False)
            and proof.get("aia_hook_runtime_sha256")
            == fingerprint.get("aia_hook_runtime_sha256")
        )
        if (
            runtime_identity_changed
            and not packaged_runtime_matches
        ) or proof.get("aia_hook_runtime_sha256") != fingerprint.get(
            "aia_hook_runtime_sha256"
        ):
            reasons.append("AIA 실행 환경이 달라요")

        if proof.get("schema_version") != _SCHEMA_VERSION or proof.get("verified") is not True:
            if not reasons:
                reasons.append("저장된 연결 검증 증명을 다시 확인해야 해요")
        elif not reasons and not self.is_current(installer, executable):
            reasons.append("저장된 연결 검증 증명을 다시 확인해야 해요")
        return reasons

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
        config_metadata = self._codex_config_hashes_and_table_names(
            self._codex_config_path()
        )
        document: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "verified": True,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "hook_event_count": hook_event_count,
            **fingerprint,
            "codex_version": self._codex_version(executable),
            "codex_config_tables_sha256": (
                config_metadata[0] if config_metadata is not None else None
            ),
            "codex_config_table_names": (
                config_metadata[1] if config_metadata is not None else None
            ),
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

    @staticmethod
    def _codex_version(executable: str | Path) -> str | None:
        try:
            from .adapters.codex import CodexAdapter

            version = CodexAdapter.executable_version(executable)
        except Exception:
            return None
        return version if isinstance(version, str) else None


__all__ = ["HookVerificationStore"]
