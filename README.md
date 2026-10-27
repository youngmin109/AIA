# AIA: runtime assurance for AI coding agents

[한국어](README.ko.md) · [Quickstart](docs/QUICKSTART.md) · [Limitations](docs/LIMITATIONS.md) · [Documentation](docs/README.md)

AIA (AI Assurance) is a Windows desktop app that puts a trust layer around the
OpenAI Codex coding agent. Give the agent the permissions it needs to be
useful; AIA watches what it actually does inside your work folder, blocks what
your policy forbids before it runs, records the evidence, and restores the
folder if something goes wrong.

AIA treats the agent as a high-privilege actor to be verified, not trusted
(Zero Trust). Decisions are based on observed behavior, not on the agent's own
account of what it did.

![AIA home screen during a protected run](docs/assets/screenshot-home.jpg)

## How it works

A protected run starts Codex under AIA, saves a baseline of the work folder,
and connects three independent sensors to one policy:

| Layer | What it does |
|---|---|
| **Hook sensor** | Codex asks AIA before it runs a command (`Bash`) or edits files (`apply_patch`). Requests that break the policy are refused before they run. |
| **Process sensor** | AIA launches Codex itself and follows the child and grandchild processes it starts, so actions can be traced back to the agent. |
| **File sensor** | Changes in the work folder are recorded. After the run you can restore the folder to its baseline and check the result with SHA-256 hashes. |
| **Policy** | Four built-in profiles and a custom editor decide which files and commands are allowed, allowed with a record, or forbidden. You can also mark files that must never be touched for a single run. |

Every observation, decision and restore is kept in the result record. When a run
ends, AIA writes a SHA-256 hash list of the record files and recomputes it when
the record is checked later, so changes to a file can be detected.

## Features

- **Protected runs from a desktop app**: pick a folder, a policy and a
  permission level, then talk to Codex in the built-in conversation pane.
- **The same permission levels as the Codex app**: ask for approval, automatic
  review, or full access. AIA checks commands before they run at every level.
- **Approval cards**: when Codex needs network access or a write outside the
  folder, you decide with *Allow once* or *Decline*. Policy denials cannot be
  overridden from the card.
- **Protected files**: name files such as a customer database; deleting,
  moving or overwriting them through a command is refused before it runs.
- **External tools off by default**: MCP servers, plugins and apps that bypass
  the pre-execution check are turned off for protected runs. They stay
  available in the Codex app itself.
- **Several conversations at once**: up to four protected runs in different
  folders. Overlapping folders are refused, because restoring one would undo
  the other.
- **Records and restore**: per-run evidence, process tree, file changes,
  restore points and integrity verification, plus a small desktop companion
  that shows the protection state.

![Policy rules with allow, record and deny colors](docs/assets/screenshot-policy.jpg)

## Requirements

- Windows 11
- [Codex CLI](https://github.com/openai/codex), signed in
- Microsoft Edge WebView2 Runtime (included with Windows 11)

To build from source you also need Python 3.13, [uv](https://docs.astral.sh/uv/)
and Node.js 24.

## Install

**Installer.** Run `AIA-<version>-Setup.exe`. It installs for the current user
under `%LOCALAPPDATA%\Programs\AIA` and does not need administrator rights.
See [INSTALL.md](INSTALL.md).

**From source.**

```powershell
uv sync --group build
.\scripts\build-windows.ps1
```

The script builds the React screens first (`npm ci` and `npm run build` in
`frontend`), then creates `dist\windows\AIA\AIA.exe` and the command-line tool
`dist\windows\aia-cli\aia-cli.exe`. Details are in the
[Windows desktop guide](docs/WINDOWS-DESKTOP.md).

## Quick start

1. Open AIA. The home screen shows whether Codex, the hook and the sensors are
   ready.
2. Connect the hook once from the setup steps in the app: AIA adds its hook to
   Codex, you review and trust it in Codex (`/hooks`), and AIA verifies it with
   a harmless probe. AIA never trusts the hook on your behalf.
3. Press **Start protection**, choose an existing folder, a policy and a
   permission level, and optionally add files that must not be touched.
4. Work with Codex in the conversation pane. The protection panel shows checks,
   blocks, processes and file changes as they happen.
5. Press **End work** to see the result. If needed, restore the folder to its
   baseline and confirm the integrity check.

The full walk-through is in the [user guide](docs/USER-GUIDE.md). Command-line
use (`aia doctor`, `aia hook verify`, `aia protect`, `aia runs`, ...) is
described in the [CLI guide](docs/CLI-GUIDE.md) (Korean).

## What AIA does not do

AIA states its limits instead of claiming full protection. In short:

- Only the chosen work folder is restored. Changes outside it are not undone.
- Commands are judged by their text. A delete hidden inside a script cannot be
  refused in advance; it is recorded and can be restored afterwards.
- External tools you turn on yourself are outside the protection boundary.
- Process evidence narrows down where an action came from; it does not prove
  which process wrote a file.
- The record is tamper-evident, not tamper-proof. It is not signed, so rewriting
  the files together with the hash list goes unnoticed.
- Only Windows 11 and Codex are supported today.

See [LIMITATIONS.md](docs/LIMITATIONS.md) and the
[threat model](docs/THREAT-MODEL.md) for the full list.

## Documentation

- [Documentation index](docs/README.md)
- [System overview](docs/SYSTEM-OVERVIEW.md) and [architecture](ARCHITECTURE.md)
- [Technical paper on the sensors and policy](docs/technical/AIA-RUNTIME-SECURITY-WHITEPAPER.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Changelog](CHANGELOG.md)

## Development

```powershell
uv sync --group dev
npm --prefix frontend ci
.venv\Scripts\python.exe -m pytest -q
uvx ruff@0.15.0 check
npm --prefix frontend test
```

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request,
and report security issues as described in [SECURITY.md](SECURITY.md). Everyone
taking part is expected to follow the [code of conduct](CODE_OF_CONDUCT.md).

## License

AIA is released under the [Apache License 2.0](LICENSE). Bundled third-party
components keep their own licenses; see
[THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md). The AIA name and logo are
not covered by the code license.
