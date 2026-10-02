from collections.abc import Callable
from typing import Protocol


class UpdateHost(Protocol):
    """The app's event loop: every manager state change runs on the thread that owns it."""

    def call_later(self, seconds: float, callback: Callable[[], None]) -> Callable[[], None]:
        """Runs callback once after seconds; the returned function cancels it."""
        ...

    def run_in_background[T](self, work: Callable[[], T], on_done: Callable[[T], None],
                             on_error: Callable[[Exception], None]) -> None:
        """Runs work on a worker thread; on_done or on_error run on the host thread."""
        ...

    def post(self, callback: Callable[[], None]) -> None:
        """Runs callback on the host thread; callable from any thread."""
        ...
