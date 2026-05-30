from __future__ import annotations
from collections import deque
from typing import Callable


class UndoManager:
    """Simple undo/redo stack based on paired (undo_fn, redo_fn) callables."""

    def __init__(self, max_size: int = 100):
        self._stack: deque = deque(maxlen=max_size)
        self._redo: deque = deque(maxlen=max_size)

    def push(
        self,
        undo_fn: Callable[[], None],
        redo_fn: Callable[[], None],
        description: str = "",
    ):
        self._stack.append((description, undo_fn, redo_fn))
        self._redo.clear()

    def undo(self):
        if self._stack:
            desc, undo_fn, redo_fn = self._stack.pop()
            undo_fn()
            self._redo.append((desc, undo_fn, redo_fn))

    def redo(self):
        if self._redo:
            desc, undo_fn, redo_fn = self._redo.pop()
            redo_fn()
            self._stack.append((desc, undo_fn, redo_fn))

    @property
    def can_undo(self) -> bool:
        return bool(self._stack)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_description(self) -> str:
        return self._stack[-1][0] if self._stack else ""

    @property
    def redo_description(self) -> str:
        return self._redo[-1][0] if self._redo else ""
