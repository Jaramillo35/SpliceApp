"""Step 3: the harness page — metadata, and the way in to every module."""

from __future__ import annotations

from typing import Dict

from defauto import ids
from defauto.backend import Backend
from defauto.navigation import Navigation


class Harness:
    def __init__(self, backend: Backend, navigation: Navigation) -> None:
        self.backend = backend
        self.navigation = navigation

    def open(self) -> str:
        return self.navigation.harness()

    def search(self, needle: str) -> None:
        self.backend.set_text(ids.TEXT_FILTER, needle, ids.UC_HARNESS_EDIT)

    def metadata(self) -> Dict[str, str]:
        """Whatever the header panel is showing, as a plain dictionary.

        Read defensively: the panel is informational, it varies by programme,
        and no workflow should fail because a field an engineer never asked
        for was missing.
        """
        out: Dict[str, str] = {}
        for auto_id in (ids.UC_HARNESS_EDIT, ids.LIST_HARNESS):
            if self.backend.exists(auto_id):
                value = self.backend.selected(auto_id) \
                    if auto_id == ids.LIST_HARNESS else ""
                if value:
                    out["harness"] = value
        return out
