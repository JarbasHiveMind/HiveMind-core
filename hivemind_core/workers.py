"""Bounded worker pool used to keep slow work off the transport hot path.

Transports call into ``HiveMindListenerProtocol`` from whatever thread owns
their socket — for Tornado that is the single IOLoop thread shared by every
connected client. Work that blocks there (answering a QUERY through the agent
can take up to ``query_timeout`` seconds) stalls every other client on the
process, so it is submitted here instead.

Callables submitted to the pool run on worker threads. Anything they touch
must tolerate that; in particular they may only reach a client through
``HiveMindClientConnection.send_msg``, whose thread-safety contract is
documented on that field.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from typing import Any, Callable, Optional

from ovos_utils.log import LOG


class BoundedWorkerPool:
    """A thread pool that refuses work instead of queueing it without limit.

    ``max_workers`` threads run submitted callables. A further
    ``queue_size`` callables may wait for a free thread; past that
    ``submit`` returns False and the caller decides how to shed the load.
    Backpressure is the point — an unbounded queue turns an overloaded
    listener into one that accepts work it will never get to.
    """

    def __init__(self, max_workers: int, queue_size: int,
                 thread_name_prefix: str = "hivemind-worker"):
        self.max_workers = max_workers
        self.queue_size = queue_size
        self.thread_name_prefix = thread_name_prefix
        self._executor: Optional[ThreadPoolExecutor] = None
        self._slots: Optional[BoundedSemaphore] = None

    @property
    def started(self) -> bool:
        return self._executor is not None

    def start(self) -> None:
        if self.started:
            return
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=self.thread_name_prefix,
        )
        self._slots = BoundedSemaphore(self.max_workers + self.queue_size)

    def submit(self, fn: Callable[..., Any], *args: Any) -> bool:
        """Run ``fn(*args)`` on a worker thread.

        Returns False when the pool is saturated, having run nothing.
        Exceptions raised by ``fn`` are logged, never propagated to the
        worker thread's caller — which has long since moved on.
        """
        if not self.started:
            self.start()

        if not self._slots.acquire(blocking=False):
            return False

        def _run() -> None:
            try:
                fn(*args)
            except Exception:
                LOG.exception(f"Unhandled error in {self.thread_name_prefix}")
            finally:
                self._slots.release()

        try:
            self._executor.submit(_run)
        except Exception:
            self._slots.release()
            raise
        return True

    def shutdown(self, wait: bool = False) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
        self._executor = None
        self._slots = None
