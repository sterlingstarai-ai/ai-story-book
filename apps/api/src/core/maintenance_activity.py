"""Wake idle maintenance after request commits; retain no user or request data."""

import asyncio
import time


IDLE_MAINTENANCE_SECONDS = 30 * 60


def seconds_to_tick(interval=IDLE_MAINTENANCE_SECONDS):
    """Align idle DB work with host health checks instead of separate wakeups."""
    return interval - time.time() % interval


class MaintenanceActivity:
    def __init__(self):
        self.version = 0
        self._loop = None
        self._event = None

    def bind(self):
        self._loop = asyncio.get_running_loop()
        self._event = asyncio.Event()

    def unbind(self):
        self._loop = self._event = None

    def notify(self):
        loop = self._loop
        if loop is None or loop.is_closed():
            return

        def wake():
            if self._loop is loop and self._event is not None:
                self.version += 1
                self._event.set()

        try:
            if asyncio.get_running_loop() is loop:
                wake()
                return
        except RuntimeError:
            pass
        try:
            loop.call_soon_threadsafe(wake)
        except RuntimeError:
            pass  # A closing API loop has no remaining maintenance task.

    async def wait(self, observed, timeout):
        event = self._event
        if event is None:
            await asyncio.sleep(timeout)
            return False
        if self.version != observed:
            return True
        event.clear()
        # No await between clearing and checking: same-loop notifications and
        # queued thread callbacks cannot disappear into a lost-wakeup window.
        if self.version != observed:
            return True
        try:
            await asyncio.wait_for(event.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False


maintenance_activity = MaintenanceActivity()
