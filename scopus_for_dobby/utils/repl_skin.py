"""scopus-for-dobby REPL Skin — Terminal interface for the Scopus CLI.

Based on cli-anything unified REPL skin pattern.
"""

import os
import re
import sys

# ── ANSI color codes ──────────────────────────────────────────────────────────

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_CYAN = "\033[38;5;80m"
_WHITE = "\033[97m"
_GRAY = "\033[38;5;245m"
_DARK_GRAY = "\033[38;5;240m"
_LIGHT_GRAY = "\033[38;5;250m"

_ACCENT = "\033[38;5;172m"   # warm amber for Scopus/Dobby

_GREEN = "\033[38;5;78m"
_YELLOW = "\033[38;5;220m"
_RED = "\033[38;5;196m"
_BLUE = "\033[38;5;75m"

_H_LINE = "\u2500"
_V_LINE = "\u2502"
_TL = "\u256d"
_TR = "\u256e"
_BL = "\u2570"
_BR = "\u256f"


def _strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[^m]*m", "", text)


def _visible_len(text: str) -> int:
    return len(_strip_ansi(text))


class ReplSkin:
    """REPL skin for scopus-for-dobby."""

    def __init__(self, version: str = "1.0.0"):
        self.software = "scopus"
        self.display_name = "Scopus for Dobby"
        self.version = version
        self.accent = _ACCENT

        from pathlib import Path
        hist_dir = Path.home() / ".scopus-for-dobby"
        hist_dir.mkdir(parents=True, exist_ok=True)
        self.history_file = str(hist_dir / "history")

        self._color = self._detect_color_support()

    def _detect_color_support(self) -> bool:
        if os.environ.get("NO_COLOR"):
            return False
        if not hasattr(sys.stdout, "isatty"):
            return False
        return sys.stdout.isatty()

    def _c(self, code: str, text: str) -> str:
        if not self._color:
            return text
        return f"{code}{text}{_RESET}"

    # ── Banner ────────────────────────────────────────────────────────

    def print_banner(self):
        inner = 54

        def _box_line(content: str) -> str:
            pad = inner - _visible_len(content)
            vl = self._c(_DARK_GRAY, _V_LINE)
            return f"{vl}{content}{' ' * max(0, pad)}{vl}"

        top = self._c(_DARK_GRAY, f"{_TL}{_H_LINE * inner}{_TR}")
        bot = self._c(_DARK_GRAY, f"{_BL}{_H_LINE * inner}{_BR}")

        icon = self._c(_ACCENT + _BOLD, "~")
        brand = self._c(_ACCENT + _BOLD, "scopus-for-dobby")
        subtitle = self._c(_GRAY, "Academic paper search & management")
        title = f" {icon}  {brand}"

        ver = f" {self._c(_DARK_GRAY, f'   v{self.version}')}"
        tip = f" {self._c(_DARK_GRAY, '   Type help for commands, quit to exit')}"
        sub = f"    {subtitle}"
        empty = ""

        print(top)
        print(_box_line(title))
        print(_box_line(sub))
        print(_box_line(ver))
        print(_box_line(empty))
        print(_box_line(tip))
        print(bot)
        print()

    # ── Prompt ────────────────────────────────────────────────────────

    def prompt(self, context: str = "") -> str:
        parts = []
        if self._color:
            parts.append(f"{_ACCENT}~{_RESET} ")
        else:
            parts.append("> ")

        parts.append(self._c(self.accent + _BOLD, "dobby"))

        if context:
            parts.append(f" {self._c(_DARK_GRAY, '[')}")
            parts.append(self._c(_LIGHT_GRAY, context))
            parts.append(self._c(_DARK_GRAY, ']'))

        parts.append(self._c(_GRAY, " > "))
        return "".join(parts)

    def prompt_tokens(self, context: str = ""):
        tokens = [
            ("class:icon", "~ "),
            ("class:software", "dobby"),
        ]
        if context:
            tokens.append(("class:bracket", " ["))
            tokens.append(("class:context", context))
            tokens.append(("class:bracket", "]"))
        tokens.append(("class:arrow", " > "))
        return tokens

    def get_prompt_style(self):
        try:
            from prompt_toolkit.styles import Style
        except ImportError:
            return None

        return Style.from_dict({
            "icon": "#d78700 bold",
            "software": "#d78700 bold",
            "bracket": "#585858",
            "context": "#bcbcbc",
            "arrow": "#808080",
            "completion-menu.completion": "bg:#303030 #bcbcbc",
            "completion-menu.completion.current": "bg:#d78700 #000000",
            "auto-suggest": "#585858",
            "bottom-toolbar": "bg:#1c1c1c #808080",
        })

    # ── Messages ──────────────────────────────────────────────────────

    def success(self, message: str):
        icon = self._c(_GREEN + _BOLD, "\u2713")
        print(f"  {icon} {self._c(_GREEN, message)}")

    def error(self, message: str):
        icon = self._c(_RED + _BOLD, "\u2717")
        print(f"  {icon} {self._c(_RED, message)}", file=sys.stderr)

    def warning(self, message: str):
        icon = self._c(_YELLOW + _BOLD, "\u26a0")
        print(f"  {icon} {self._c(_YELLOW, message)}")

    def info(self, message: str):
        icon = self._c(_BLUE, "\u25cf")
        print(f"  {icon} {self._c(_LIGHT_GRAY, message)}")

    def hint(self, message: str):
        print(f"  {self._c(_DARK_GRAY, message)}")

    def section(self, title: str):
        print()
        print(f"  {self._c(self.accent + _BOLD, title)}")
        print(f"  {self._c(_DARK_GRAY, _H_LINE * len(title))}")

    # ── Status display ────────────────────────────────────────────────

    def status(self, label: str, value: str):
        lbl = self._c(_GRAY, f"  {label}:")
        val = self._c(_WHITE, f" {value}")
        print(f"{lbl}{val}")

    def status_block(self, items: dict[str, str], title: str = ""):
        if title:
            self.section(title)
        max_key = max(len(k) for k in items) if items else 0
        for label, value in items.items():
            lbl = self._c(_GRAY, f"  {label:<{max_key}}")
            val = self._c(_WHITE, f"  {value}")
            print(f"{lbl}{val}")

    def progress(self, current: int, total: int, label: str = ""):
        pct = int(current / total * 100) if total > 0 else 0
        bar_width = 20
        filled = int(bar_width * current / total) if total > 0 else 0
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        text = f"  {self._c(_ACCENT, bar)} {self._c(_GRAY, f'{pct:3d}%')}"
        if label:
            text += f" {self._c(_LIGHT_GRAY, label)}"
        print(text)

    # ── Table display ─────────────────────────────────────────────────

    def table(self, headers: list[str], rows: list[list[str]],
              max_col_width: int = 40):
        if not headers:
            return

        col_widths = [min(len(h), max_col_width) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    col_widths[i] = min(
                        max(col_widths[i], len(str(cell))), max_col_width
                    )

        def pad(text: str, width: int) -> str:
            t = str(text)[:width]
            return t + " " * (width - len(t))

        header_cells = [
            self._c(_ACCENT + _BOLD, pad(h, col_widths[i]))
            for i, h in enumerate(headers)
        ]
        sep = self._c(_DARK_GRAY, f" {_V_LINE} ")
        print(f"  {sep.join(header_cells)}")

        sep_line = f"  {'---'.join([_H_LINE * w for w in col_widths])}"
        print(self._c(_DARK_GRAY, sep_line))

        for row in rows:
            cells = []
            for i, cell in enumerate(row):
                if i < len(col_widths):
                    cells.append(self._c(_LIGHT_GRAY, pad(str(cell), col_widths[i])))
            row_sep = self._c(_DARK_GRAY, f" {_V_LINE} ")
            print(f"  {row_sep.join(cells)}")

    # ── Help display ──────────────────────────────────────────────────

    def help(self, commands: dict[str, str]):
        self.section("Commands")
        max_cmd = max(len(c) for c in commands) if commands else 0
        for cmd, desc in commands.items():
            cmd_styled = self._c(self.accent, f"  {cmd:<{max_cmd}}")
            desc_styled = self._c(_GRAY, f"  {desc}")
            print(f"{cmd_styled}{desc_styled}")
        print()

    # ── Paper display ─────────────────────────────────────────────────

    def print_paper(self, index: int, entry: dict):
        """Print a single search result entry."""
        title = entry.get("dc:title", entry.get("title", "N/A"))

        # First author
        creator = entry.get("dc:creator", entry.get("first_author", ""))
        if isinstance(creator, dict):
            authors = creator.get("author", [])
            if authors:
                pn = authors[0].get("preferred-name", {})
                creator = pn.get("ce:indexed-name", "")

        journal = entry.get("prism:publicationName", entry.get("journal", ""))
        year = str(entry.get("prism:coverDate", entry.get("cover_date", "")))[:4]
        volume = entry.get("prism:volume", entry.get("volume", ""))
        doi = entry.get("prism:doi", entry.get("doi", ""))
        eid = entry.get("eid", "")
        cited = entry.get("citedby-count", entry.get("cited_by", "?"))
        oa_raw = entry.get("openaccess", entry.get("open_access", False))
        oa = (str(oa_raw) in ("1", "True", "true"))

        vol_str = f" Vol.{volume}" if volume else ""
        oa_str = f" {self._c(_GREEN, 'OA')}" if oa else ""

        idx = self._c(_ACCENT + _BOLD, f"[{index}]")
        print(f"\n{idx} {self._c(_WHITE, title)}")
        print(f"     {self._c(_LIGHT_GRAY, f'{creator}')} "
              f"{self._c(_DARK_GRAY, '|')} "
              f"{self._c(_GRAY, f'{journal}{vol_str} ({year})')}{oa_str}")
        if doi:
            print(f"     {self._c(_DARK_GRAY, 'DOI:')} {self._c(_GRAY, doi)}  "
                  f"{self._c(_DARK_GRAY, '|')}  "
                  f"{self._c(_BLUE, f'Cited: {cited}')}")
        if eid:
            print(f"     {self._c(_DARK_GRAY, f'EID: {eid}')}")

    # ── Goodbye ───────────────────────────────────────────────────────

    def print_goodbye(self):
        print(f"\n  {self._c(_ACCENT, '~')} {self._c(_GRAY, 'Dobby is free!')}\n")

    # ── Prompt toolkit session ────────────────────────────────────────

    def create_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.history import FileHistory

            style = self.get_prompt_style()
            session = PromptSession(
                history=FileHistory(self.history_file),
                auto_suggest=AutoSuggestFromHistory(),
                style=style,
                enable_history_search=True,
            )
            return session
        except ImportError:
            return None

    def get_input(self, pt_session, context: str = "") -> str:
        if pt_session is not None:
            from prompt_toolkit.formatted_text import FormattedText
            tokens = self.prompt_tokens(context)
            return pt_session.prompt(FormattedText(tokens)).strip()
        else:
            raw_prompt = self.prompt(context)
            return input(raw_prompt).strip()
