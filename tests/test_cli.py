from __future__ import annotations

from aia.cli import _parser


def test_protect_without_task_selects_interactive_mode() -> None:
    args = _parser().parse_args(["protect", "C:/workspace/my-project"])

    assert args.task is None


def test_protect_with_task_keeps_one_shot_mode() -> None:
    args = _parser().parse_args(
        ["protect", "C:/workspace/my-project", "--task", "inspect"]
    )

    assert args.task == "inspect"
