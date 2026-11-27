"""Platform-independent input events and resume detection."""
from __future__ import annotations

import sys
from dataclasses import dataclass


@dataclass
class KeySnapshot:
    """Ordered state recovery, rather than a synthetic press or release."""

    held: list[int] | None
    sec: int
    usec: int


class ResumeWatch:
    def __init__(self):
        self.offset = suspend_offset()

    def resumed(self):
        offset = suspend_offset()
        resumed = offset - self.offset > 0.1
        self.offset = offset
        return resumed


def suspend_offset():
    if sys.platform == "darwin":
        from .macos import suspend_offset as offset
    else:
        from .keyboards import suspend_offset as offset
    return offset()
