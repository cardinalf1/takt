from enum import Enum, auto
import threading
import time
from typing import Callable, List

class AppState(Enum):
    IDLE = auto()
    RECORDING = auto()
    PROCESSING = auto()
    INJECTING = auto()

class StateManager:
    """Thread-safe state manager for the Takt dictation pipeline."""
    def __init__(self):
        self._state = AppState.IDLE
        self._lock = threading.Lock()
        self._listeners: List[Callable[[AppState, AppState], None]] = []
        self._last_active_time = time.time()

    @property
    def current(self) -> AppState:
        with self._lock:
            return self._state

    @property
    def last_active_time(self) -> float:
        with self._lock:
            return self._last_active_time

    @property
    def last_state_change(self) -> float:
        with self._lock:
            return self._last_active_time

    def transition_to(self, new_state: AppState) -> bool:
        """
        Atomically transitions application state.
        Fires registered transition callbacks.
        """
        with self._lock:
            old_state = self._state
            if old_state == new_state:
                return False
            self._state = new_state
            self._last_active_time = time.time()
            listeners = list(self._listeners)

        for listener in listeners:
            try:
                listener(old_state, new_state)
            except Exception as e:
                print(f"[State Warning] Listener error on transition {old_state} -> {new_state}: {e}")

        return True

    def add_listener(self, callback: Callable[[AppState, AppState], None]):
        """Registers a transition listener."""
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)
