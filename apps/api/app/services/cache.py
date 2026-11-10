from __future__ import annotations
from dataclasses import dataclass, field
from time import time
from typing import Any


@dataclass
class CacheEntry:
    bars: dict[int, dict] = field(default_factory=dict)
    loaded: list[tuple[int, int]] = field(default_factory=list)
    updated_at: float = field(default_factory=time)


class SessionBarCache:
    """RAM-only cache partitioned by browser page-load ID, account and symbol.

    Successfully queried windows are remembered even when the provider returns no
    bars. Failed requests are never marked as loaded. A full page reload generates
    a new client_run_id and therefore starts with an empty logical cache.
    """
    def __init__(self, ttl_seconds: int = 3600, max_entries: int = 250):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: dict[str, CacheEntry] = {}

    @staticmethod
    def key(run_id: str, account_id: str, symbol_id: str) -> str:
        return f"{run_id}:{account_id}:{symbol_id}:M1"

    def _cleanup(self):
        now = time()
        expired = [k for k, v in self._entries.items() if now - v.updated_at > self.ttl_seconds]
        for key in expired:
            self._entries.pop(key, None)
        if len(self._entries) > self.max_entries:
            for key, _ in sorted(self._entries.items(), key=lambda kv: kv[1].updated_at)[:len(self._entries)-self.max_entries]:
                self._entries.pop(key, None)

    @staticmethod
    def missing_ranges(loaded: list[tuple[int, int]], start: int, end: int) -> list[tuple[int, int]]:
        if end <= start:
            return []
        merged = []
        for a, b in sorted(loaded):
            if not merged or a > merged[-1][1]:
                merged.append([a, b])
            else:
                merged[-1][1] = max(merged[-1][1], b)
        missing = []
        cursor = start
        for a, b in merged:
            if b <= cursor or a >= end:
                continue
            if a > cursor:
                missing.append((cursor, min(a, end)))
            cursor = max(cursor, b)
            if cursor >= end:
                break
        if cursor < end:
            missing.append((cursor, end))
        return [(a, b) for a, b in missing if b > a]

    def get_missing(self, run_id: str, account_id: str, symbol_id: str, start: int, end: int):
        self._cleanup()
        key = self.key(run_id, account_id, symbol_id)
        entry = self._entries.setdefault(key, CacheEntry())
        entry.updated_at = time()
        return self.missing_ranges(entry.loaded, start, end)

    def put_window(self, run_id: str, account_id: str, symbol_id: str,
                   start: int, end: int, bars: list[dict]):
        self._cleanup()
        key = self.key(run_id, account_id, symbol_id)
        entry = self._entries.setdefault(key, CacheEntry())
        for bar in bars:
            entry.bars[int(bar["time"])] = bar
        entry.loaded.append((int(start), int(end)))
        entry.updated_at = time()

    def upsert_bars(self, run_id: str, account_id: str, symbol_id: str, bars: list[dict]) -> int:
        """Merge fresh bars without claiming an entire historical range was loaded."""
        if not bars:
            return 0
        self._cleanup()
        key = self.key(run_id, account_id, symbol_id)
        entry = self._entries.setdefault(key, CacheEntry())
        added = 0
        for bar in bars:
            ts = int(bar["time"])
            if ts not in entry.bars:
                added += 1
            entry.bars[ts] = bar
        entry.updated_at = time()
        return added

    def get_bars(self, run_id: str, account_id: str, symbol_id: str,
                 start: int | None = None, end: int | None = None) -> list[dict]:
        self._cleanup()
        key = self.key(run_id, account_id, symbol_id)
        entry = self._entries.get(key)
        if not entry:
            return []
        entry.updated_at = time()
        return [v for k, v in sorted(entry.bars.items())
                if (start is None or k >= start) and (end is None or k < end)]

    def status(self, run_id: str, account_id: str, symbol_id: str) -> dict:
        key = self.key(run_id, account_id, symbol_id)
        entry = self._entries.get(key)
        if not entry:
            return {"bars": 0, "loaded_windows": 0, "updated_at": None}
        return {"bars": len(entry.bars), "loaded_windows": len(entry.loaded),
                "updated_at": entry.updated_at}


bar_cache = SessionBarCache()
