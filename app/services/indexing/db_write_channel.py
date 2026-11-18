"""Dedicated bounded database write channel (actor queue) in front of the relational database.

When multiple git repositories or local paths are synced concurrently, each sync pipeline
produces embedding cache batches and relational AST/route batches. Instead of allowing concurrent
pipeline consumers to contend on SQLite/database locks directly, all write batches are enqueued
into a shared BoundedChannel and executed sequentially by a single dedicated writer thread,
providing natural backpressure to upstream pipeline stages.
"""

import logging
import threading
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable, Optional, TypeVar

from app.services.indexing.channel_pipeline import BoundedChannel

logger = logging.getLogger("contextcortex.indexer.db_write_channel")

R = TypeVar("R")


@dataclass
class DatabaseWriteCommand:
    """Unit of database write work submitted to the DatabaseWriteChannel."""

    action: Callable[[], Any]
    future: Future


class DatabaseWriteChannel:
    """Single-consumer bounded channel that serializes database write transactions
    with backpressure across all concurrent ingestion pipelines."""

    def __init__(self, capacity: int = 32) -> None:
        self.capacity = max(1, int(capacity))
        self._channel: BoundedChannel[DatabaseWriteCommand] = BoundedChannel(capacity=self.capacity)
        self._worker_lock = threading.Lock()
        self._worker_thread: Optional[threading.Thread] = None
        self._stopped = False

    def _ensure_worker_started(self) -> None:
        with self._worker_lock:
            if self._stopped:
                self._channel = BoundedChannel(capacity=self.capacity)
                self._stopped = False
            if self._worker_thread is None or not self._worker_thread.is_alive():
                self._worker_thread = threading.Thread(
                    target=self._consume_loop,
                    name="cc-db-write-channel-worker",
                    daemon=True,
                )
                self._worker_thread.start()

    def _consume_loop(self) -> None:
        for cmd in self._channel.read_all():
            if cmd.future.cancelled():
                continue
            try:
                result = cmd.action()
                cmd.future.set_result(result)
            except BaseException as exc:
                cmd.future.set_exception(exc)

    def submit_async(self, action: Callable[[], R]) -> Future:
        """Enqueues a database write callable, blocking if the bounded channel is full,
        and returns a Future that resolves when the write completes."""
        self._ensure_worker_started()
        fut: Future = Future()
        cmd = DatabaseWriteCommand(action=action, future=fut)
        written = self._channel.write(cmd)
        if not written:
            fut.set_exception(RuntimeError("DatabaseWriteChannel is closed or cancelled."))
        return fut

    def submit(self, action: Callable[[], R]) -> R:
        """Enqueues a database write callable with backpressure and waits for its result."""
        if threading.current_thread() is self._worker_thread:
            # Re-entrant call from within the writer thread itself executes inline
            return action()
        fut = self.submit_async(action)
        return fut.result()

    @property
    def pending_count(self) -> int:
        """Approximate number of queued write commands waiting for the DB writer."""
        return self._channel._queue.qsize()

    def shutdown(self, wait: bool = True) -> None:
        """Completes the channel and optionally waits for pending writes to drain."""
        with self._worker_lock:
            self._stopped = True
            worker = self._worker_thread
            self._channel.complete()
        if wait and worker is not None and worker.is_alive() and threading.current_thread() is not worker:
            worker.join(timeout=10.0)


_global_db_write_channel: Optional[DatabaseWriteChannel] = None
_global_db_write_lock = threading.Lock()


def get_db_write_channel() -> DatabaseWriteChannel:
    """Returns the process-wide DatabaseWriteChannel singleton."""
    global _global_db_write_channel
    with _global_db_write_lock:
        if _global_db_write_channel is None:
            _global_db_write_channel = DatabaseWriteChannel(capacity=32)
        return _global_db_write_channel


def submit_db_write(action: Callable[[], R]) -> R:
    """Submits a database write transaction through the global DatabaseWriteChannel."""
    return get_db_write_channel().submit(action)
