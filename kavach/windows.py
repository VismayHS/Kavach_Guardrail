"""Durable undo windows (E6): they close on time, by themselves, and survive a restart.

Before E6, a held payment or a queued email waited until someone called POST /api/settle. The sweeper closes every
window whose time has passed (the payment is booked, the email leaves, each with a `window-closed` receipt) and moves
unanswered approvals up their SLA chain, every `every_s` seconds, with no UI open. With KAVACH_DB_URL set, the holds
themselves are persisted (kavach/store.py): after a restart the sweeper finds them again, and Undo on their receipt
still cancels them while the window is open.

Server: on by default (KAVACH_SWEEP_S=5); KAVACH_SWEEP_S=0 turns it off.
"""
from __future__ import annotations

import threading
import time


class Sweeper:
    def __init__(self, gw, every_s: float = 5.0):
        self.gw, self.every_s = gw, float(every_s)
        self.stop = threading.Event()
        self.ticks, self.settled = 0, 0
        self.started, self.last_tick = time.time(), None      # the heartbeat /metrics reports
        self.thread: threading.Thread | None = None

    def tick(self, now: float | None = None) -> list[str]:
        done = self.gw.settle(now)
        self.gw.hitl.expire(now)
        self.last_tick = time.time()
        self.ticks += 1
        self.settled += len(done)
        return done

    def start(self) -> "Sweeper":
        if self.thread is None and self.every_s > 0:
            self.thread = threading.Thread(target=self._run, daemon=True, name="kavach-windows")
            self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop.wait(self.every_s):
            try:
                self.tick()
            except Exception:          # a bad tick must not stop the windows from closing later
                pass
