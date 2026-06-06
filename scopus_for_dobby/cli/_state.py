"""Shared mutable state for CLI subcommands."""


class _State:
    json_output: bool = False
    repl_mode: bool = False


state = _State()
