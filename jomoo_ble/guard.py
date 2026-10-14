"""Shower guard: suspend automatic lid opening, then restore exactly what was there.

Pure Python so it can be tested without Home Assistant. The state survives restarts
through an injected store. Rules:

* suspend: remember the current automatic-lid-opening value, then turn it off only if
  it was on. A failed suspend keeps the remembered value (``pending``) so a retry never
  mistakes "already turned off by us" for "was off before".
* resume: turn it back on only if it was on before; never write "off". A failed resume
  keeps the guard active so it can be retried.
* cancel: the user changed the setting by hand while the guard was active; forget the
  remembered value so the manual choice is not overwritten later.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Optional, Protocol

from .client import SessionManager, SetSettings, Snapshot


class GuardStore(Protocol):
    async def load(self) -> Optional[dict]: ...
    async def save(self, data: dict) -> None: ...


@dataclass(frozen=True)
class GuardState:
    active: bool = False
    pending: bool = False
    previous: Optional[bool] = None


class ShowerGuard:
    def __init__(
        self,
        session: SessionManager,
        store: GuardStore,
        on_change: Optional[Callable[[GuardState], None]] = None,
    ) -> None:
        self._session = session
        self._store = store
        self._on_change = on_change
        self.state = GuardState()

    async def load(self) -> None:
        data = await self._store.load() or {}
        previous = data.get("previous")
        self.state = GuardState(
            active=bool(data.get("active")),
            pending=bool(data.get("pending")),
            previous=previous if isinstance(previous, bool) else None,
        )

    async def _set(self, state: GuardState) -> None:
        self.state = state
        await self._store.save(asdict(state))
        if self._on_change is not None:
            self._on_change(state)

    async def suspend(self) -> Optional[Snapshot]:
        if self.state.active:
            return None  # already suspended; no connection, no beep

        async def remember(snapshot: Snapshot) -> bool:
            if not self.state.pending or self.state.previous is None:
                settings = snapshot.settings
                if settings is None:
                    return False
                await self._set(GuardState(pending=True, previous=settings.auto_cover))
            return True

        snapshot = await self._session.command(SetSettings({"auto_cover": False}), remember)
        await self._set(GuardState(active=True, previous=self.state.previous))
        return snapshot

    async def resume(self) -> Optional[Snapshot]:
        if not (self.state.active or self.state.pending):
            return None
        snapshot = None
        if self.state.previous:
            snapshot = await self._session.command(SetSettings({"auto_cover": True}))
        await self._set(GuardState())
        return snapshot

    async def cancel(self) -> None:
        if self.state != GuardState():
            await self._set(GuardState())
