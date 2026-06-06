"""Session state management — tracks current search results, context, and history.

Persists last search/abstract results to disk so that subcommand mode
(separate CLI invocations) can reference previous results.

Storage: ~/.scopus-for-dobby/session/
"""

import json

from scopus_for_dobby.utils.api_client import CONFIG_DIR

SESSION_DIR = CONFIG_DIR / "session"


def _ensure_session_dir():
    SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _save_json(name: str, data: dict):
    """Save session data to a JSON file."""
    _ensure_session_dir()
    path = SESSION_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def _load_json(name: str) -> dict | None:
    """Load session data from a JSON file."""
    path = SESSION_DIR / f"{name}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


class Session:
    """Stateful session for the Scopus CLI.

    Persists last_search and last_abstract to disk so they survive
    across separate CLI invocations.
    """

    def __init__(self):
        self._last_search: dict | None = None
        self._last_abstract: dict | None = None
        self._working_collection: str | None = None
        self._working_collection_loaded: bool = False
        self._search_history: list[str] = []

    @property
    def last_search(self) -> dict | None:
        if self._last_search is None:
            self._last_search = _load_json("last_search")
        return self._last_search

    @last_search.setter
    def last_search(self, value: dict):
        self._last_search = value
        # Strip non-serializable internal keys before persisting
        to_save = {k: v for k, v in value.items() if k != "_rate_limit"}
        _save_json("last_search", to_save)

    @property
    def last_abstract(self) -> dict | None:
        if self._last_abstract is None:
            self._last_abstract = _load_json("last_abstract")
        return self._last_abstract

    @last_abstract.setter
    def last_abstract(self, value: dict):
        self._last_abstract = value
        # Strip _raw (large) and _rate_limit before persisting
        to_save = {k: v for k, v in value.items() if k not in ("_raw", "_rate_limit")}
        _save_json("last_abstract", to_save)

    @property
    def working_collection(self) -> str | None:
        if not self._working_collection_loaded:
            data = _load_json("working_collection")
            self._working_collection = data.get("name") if data else None
            self._working_collection_loaded = True
        return self._working_collection

    @working_collection.setter
    def working_collection(self, name: str | None):
        self._working_collection = name
        self._working_collection_loaded = True
        _save_json("working_collection", {"name": name})

    def add_to_history(self, query: str):
        """Record a search query."""
        self._search_history.append(query)

    @property
    def search_history(self) -> list[str]:
        return list(self._search_history)

    def get_entry_by_index(self, index: int) -> dict | None:
        """Get an entry from the last search results by 1-based index.

        Args:
            index: 1-based index from the displayed results.

        Returns:
            The entry dict, or None if out of range.
        """
        search = self.last_search
        if not search:
            return None
        entries = search.get("entries", [])
        if 1 <= index <= len(entries):
            return entries[index - 1]
        return None

    def get_entries_by_indices(self, indices: list[int]) -> list[dict]:
        """Get multiple entries by 1-based indices.

        Args:
            indices: List of 1-based indices.

        Returns:
            List of entry dicts (skips invalid indices).
        """
        search = self.last_search
        if not search:
            return []
        entries = search.get("entries", [])
        result = []
        for i in indices:
            if 1 <= i <= len(entries):
                result.append(entries[i - 1])
        return result

    def get_all_last_entries(self) -> list[dict]:
        """Get all entries from the last search."""
        search = self.last_search
        if not search:
            return []
        return search.get("entries", [])


# Global session instance
_session: Session | None = None


def get_session() -> Session:
    """Get or create the global session."""
    global _session
    if _session is None:
        _session = Session()
    return _session
