from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class WebPreferencesSnapshot:
    allow_lan: bool = False


class WebPreferencesState:
    """Own web access preferences without importing Qt."""

    def __init__(self) -> None:
        self._state = WebPreferencesSnapshot()

    def snapshot(self) -> WebPreferencesSnapshot:
        return replace(self._state)

    def configure(self, *, allow_lan: object) -> WebPreferencesSnapshot:
        if not isinstance(allow_lan, bool):
            raise ValueError("allow_lan must be a boolean")
        self._state = replace(self._state, allow_lan=allow_lan)
        return self.snapshot()

    def load(self, *, web: object) -> WebPreferencesSnapshot:
        values = web if isinstance(web, dict) else {}
        allow_lan = values.get("allow_lan")
        if isinstance(allow_lan, bool):
            self._state = replace(self._state, allow_lan=allow_lan)
        return self.snapshot()

    def reset(self) -> WebPreferencesSnapshot:
        self._state = WebPreferencesSnapshot()
        return self.snapshot()

    def to_desktop_state(self) -> dict[str, bool]:
        return {"web_allow_lan": self._state.allow_lan}

    def to_settings(self) -> dict[str, bool]:
        return {"allow_lan": self._state.allow_lan}
