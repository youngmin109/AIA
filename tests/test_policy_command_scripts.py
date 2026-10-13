"""Commands inside scripts, and commands that name a protected path."""

import pytest

from aia import Operation, PolicyDecision, PolicyProfile, load_policy_document, resolve_profile
from aia.policy import PolicyEngine, command_segments

PROTECTED = PolicyEngine(resolve_profile(PolicyProfile.PROTECTED_DEVELOPMENT).policy)
DB = "\uace0\uac1d\uc815\ubcf4.db"  # a Korean file name, like the demo's customer database

USER_PROTECTED = PolicyEngine(load_policy_document({
    "profile": "CUSTOM",
    "policy_id": "test-user-protected",
    "policy_version": "1.0",
    "schema_version": "1",
    "default_effect": "AUDIT",
    "rules": [{
        "rule_id": "aia-user-protected-path-1",
        "priority": 2001,
        "asset_type": "WORKSPACE",
        "path_patterns": [f"shop/data/{DB}"],
        "operation_effects": {"CREATE": "DENY", "MODIFY": "DENY", "DELETE": "DENY", "MOVE": "DENY", "RENAME": "DENY"},
    }],
}))


def _decision(engine, command):
    result = engine.evaluate_target(operation=Operation.EXECUTE, raw_command=command)
    return result.policy_decision, result.matched_rule_ids


def test_a_script_is_split_into_statements_outside_quotes_and_wrappers_are_opened() -> None:
    script = f"$target = 'C:\\w\\shop\\data\\{DB}'; if (-not (Test-Path $target)) {{ throw 'x; y' }}; Remove-Item -LiteralPath $target -Force"
    segments = command_segments(script)
    assert "remove-item -literalpath $target -force" in segments
    assert "throw 'x; y'" in segments  # the quoted ';' does not split
    wrapped = '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command \'Get-ChildItem; Remove-Item foo.txt\''
    assert "remove-item foo.txt" in command_segments(wrapped)
    assert "rd /s build" in command_segments("cmd.exe /c \"echo hi & rd /s build\"")


@pytest.mark.parametrize("command", [
    f"$target = 'C:\\w\\shop\\data\\{DB}'; Remove-Item -LiteralPath $target -Force",
    "Get-ChildItem; Remove-Item foo.txt",
    "if (Test-Path x) { Remove-Item x }",
    "git status && rm -rf build",
    '"C:\\WINDOWS\\System32\\WindowsPowerShell\\v1.0\\powershell.exe" -Command \'Get-ChildItem; Remove-Item foo.txt\'',
])
def test_a_destructive_command_in_the_middle_of_a_script_is_blocked(command) -> None:
    decision, rules = _decision(PROTECTED, command)
    assert decision is PolicyDecision.VIOLATION and "protected-rm-rf" in rules


@pytest.mark.parametrize("command", [
    "Get-ChildItem -Force | Select-Object Mode, Name",
    "Write-Output 'see docs; Remove-Item is dangerous'",
    "git log --oneline -5",
])
def test_ordinary_commands_and_quoted_text_stay_allowed(command) -> None:
    assert _decision(PROTECTED, command)[0] is PolicyDecision.COMPLIANT


@pytest.mark.parametrize("command", [
    f"$target = 'C:\\workspace\\demo\\shop\\data\\{DB}'; Remove-Item -LiteralPath $target -Force",
    f"Move-Item -LiteralPath 'C:\\workspace\\demo\\shop\\data\\{DB}' -Destination C:\\temp\\x.db",
    f"Rename-Item data\\{DB} old.db",
    f"echo x > shop\\data\\{DB}",
    f"[System.IO.File]::Delete('{DB}')",
])
def test_a_command_that_deletes_moves_renames_or_overwrites_a_protected_file_is_blocked(command) -> None:
    decision, rules = _decision(USER_PROTECTED, command)
    assert decision is PolicyDecision.VIOLATION and rules == ("aia-user-protected-path-1",)


@pytest.mark.parametrize("command", [
    f"Get-Content data\\{DB} -TotalCount 1 > out.txt",  # reads it; the redirect writes elsewhere
    f"Copy-Item data\\{DB} data\\backup\\",  # copying from it is a read
    "Remove-Item data\\orders.db",  # another file
    f"sqlite3 data\\{DB} \"select count(*) from customers\"",
])
def test_reading_copying_or_touching_other_files_is_not_blocked(command) -> None:
    assert _decision(USER_PROTECTED, command)[0] is PolicyDecision.COMPLIANT


def test_derived_denials_never_weaken_an_existing_rule() -> None:
    # The standard profile still denies its destructive commands with the same rule.
    decision, rules = _decision(PROTECTED, "Remove-Item .env")
    assert decision is PolicyDecision.VIOLATION
    assert set(rules) & {"protected-rm-rf", "protected-secret-files"}
