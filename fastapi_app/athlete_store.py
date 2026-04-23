"""Athlete persistence — names + colours + per-Set track-id bindings.

The Coach assigns a stable name (e.g. "张三") to a BYTETracker ID
detected in a specific Set. The mapping is per-Set because BYTETracker
state is reset between Sets (see DEVLOG #25), so the same swimmer
gets a fresh ID in every recording. We persist the bindings so the
analysis page can label skeletons with names instead of raw ``#3``.

Schema (``data/athletes.json``)::

    {
      "version": 1,
      "athletes": [
        {
          "id": "ath_xxxxxxxx",                    # stable surrogate key
          "name": "张三",
          "color": "#A855F7",                      # null = use track-id colour
          "bindings": [
            {"set": "set_009_…", "track_id": 3},
            {"set": "set_010_…", "track_id": 5}
          ],
          "created_at": "2026-04-23T12:34:56+00:00"
        }
      ]
    }

Same ``(set, track_id)`` can only belong to ONE athlete — ``bind_track``
removes the binding from any other athlete first. This is what makes
the per-Set lookup table unambiguous when the analysis page asks
"who is #3 in this Set?"
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone

SCHEMA_VERSION = 1


def _empty_data() -> dict:
    return {"version": SCHEMA_VERSION, "athletes": []}


class AthleteStore:
    """Thread-safe JSON-backed store for athlete bindings."""

    def __init__(self, path: str):
        self._path = path
        self._lock = threading.Lock()
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

    # ---- Internals ----------------------------------------------------

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return _empty_data()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return _empty_data()
        if not isinstance(data, dict) or data.get("version") != SCHEMA_VERSION:
            return _empty_data()
        if not isinstance(data.get("athletes"), list):
            data["athletes"] = []
        # Defensive: ensure each athlete has the expected fields.
        for ath in data["athletes"]:
            ath.setdefault("color", None)
            ath.setdefault("bindings", [])
            if not isinstance(ath.get("bindings"), list):
                ath["bindings"] = []
        return data

    def _save(self, data: dict) -> None:
        tmp = self._path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    # ---- Public CRUD --------------------------------------------------

    def list_athletes(self) -> list[dict]:
        with self._lock:
            return list(self._load()["athletes"])

    def get_athlete(self, athlete_id: str) -> dict | None:
        with self._lock:
            for ath in self._load()["athletes"]:
                if ath["id"] == athlete_id:
                    return ath
        return None

    def create_athlete(self, name: str, color: str | None = None) -> dict:
        name = (name or "").strip()
        if not name:
            raise ValueError("name is required")
        with self._lock:
            data = self._load()
            ath = {
                "id": "ath_" + uuid.uuid4().hex[:8],
                "name": name,
                "color": color or None,
                "bindings": [],
                "created_at": datetime.now(timezone.utc)
                .isoformat(timespec="seconds"),
            }
            data["athletes"].append(ath)
            self._save(data)
            return ath

    def update_athlete(
        self,
        athlete_id: str,
        name: str | None = None,
        color: str | None = None,
    ) -> dict | None:
        with self._lock:
            data = self._load()
            for ath in data["athletes"]:
                if ath["id"] != athlete_id:
                    continue
                if name is not None:
                    s = name.strip()
                    if s:
                        ath["name"] = s
                if color is not None:
                    ath["color"] = color or None
                self._save(data)
                return ath
        return None

    def delete_athlete(self, athlete_id: str) -> bool:
        with self._lock:
            data = self._load()
            before = len(data["athletes"])
            data["athletes"] = [
                a for a in data["athletes"] if a["id"] != athlete_id
            ]
            if len(data["athletes"]) == before:
                return False
            self._save(data)
            return True

    # ---- Bindings -----------------------------------------------------

    def bind_track(
        self, athlete_id: str, set_name: str, track_id: int
    ) -> dict | None:
        """Bind ``(set_name, track_id)`` to ``athlete_id``.

        First removes any existing binding for the same ``(set, track_id)``
        from EVERY athlete — a single track in a single Set can only
        belong to one person at a time. Returns the updated athlete
        dict, or None if athlete_id doesn't exist.
        """
        with self._lock:
            data = self._load()
            target: dict | None = None
            for ath in data["athletes"]:
                ath["bindings"] = [
                    b for b in ath.get("bindings", [])
                    if not (
                        b.get("set") == set_name
                        and int(b.get("track_id", -1)) == int(track_id)
                    )
                ]
                if ath["id"] == athlete_id:
                    target = ath
            if target is None:
                return None
            target["bindings"].append({
                "set": set_name,
                "track_id": int(track_id),
            })
            self._save(data)
            return target

    def unbind_track(
        self, athlete_id: str, set_name: str, track_id: int
    ) -> bool:
        with self._lock:
            data = self._load()
            for ath in data["athletes"]:
                if ath["id"] != athlete_id:
                    continue
                before = len(ath.get("bindings", []))
                ath["bindings"] = [
                    b for b in ath.get("bindings", [])
                    if not (
                        b.get("set") == set_name
                        and int(b.get("track_id", -1)) == int(track_id)
                    )
                ]
                if len(ath["bindings"]) == before:
                    return False
                self._save(data)
                return True
        return False

    def lookup_for_set(self, set_name: str) -> dict[int, dict]:
        """Return ``{track_id: {athlete_id, name, color}}`` for one Set.

        Used by the analysis page to render skeleton labels with the
        athlete's name instead of the raw ``#3`` tracker ID.
        """
        out: dict[int, dict] = {}
        with self._lock:
            for ath in self._load()["athletes"]:
                for b in ath.get("bindings", []):
                    if b.get("set") == set_name:
                        try:
                            tid = int(b.get("track_id"))
                        except (TypeError, ValueError):
                            continue
                        out[tid] = {
                            "athlete_id": ath["id"],
                            "name": ath["name"],
                            "color": ath.get("color"),
                        }
        return out
