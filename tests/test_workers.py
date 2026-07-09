import threading

from hivemind_core.workers import BoundedWorkerPool


def test_submit_runs_callable_on_worker_thread():
    pool = BoundedWorkerPool(max_workers=1, queue_size=1)
    done = threading.Event()
    seen = {}

    def _work(value):
        seen["value"] = value
        seen["thread"] = threading.current_thread().name
        done.set()

    assert pool.submit(_work, 42) is True
    assert done.wait(2)
    assert seen["value"] == 42
    assert seen["thread"] != threading.current_thread().name
    pool.shutdown(wait=True)


def test_submit_refuses_work_when_saturated():
    pool = BoundedWorkerPool(max_workers=1, queue_size=0)
    release = threading.Event()
    started = threading.Event()

    def _block():
        started.set()
        release.wait(2)

    assert pool.submit(_block) is True
    assert started.wait(2)
    # the only slot is taken, so the pool sheds rather than queues
    assert pool.submit(_block) is False

    release.set()
    pool.shutdown(wait=True)


def test_slot_is_released_after_failure():
    pool = BoundedWorkerPool(max_workers=1, queue_size=0)
    failed = threading.Event()

    def _boom():
        failed.set()
        raise RuntimeError("worker blew up")

    assert pool.submit(_boom) is True
    assert failed.wait(2)
    pool.shutdown(wait=True)

    # a worker that raised must not leak its slot
    pool = BoundedWorkerPool(max_workers=1, queue_size=0)
    done = threading.Event()
    assert pool.submit(_boom) is True
    assert failed.wait(2)
    for _ in range(50):
        if pool.submit(done.set):
            break
        threading.Event().wait(0.02)
    assert done.wait(2)
    pool.shutdown(wait=True)


def test_shutdown_allows_restart():
    pool = BoundedWorkerPool(max_workers=1, queue_size=1)
    assert pool.submit(lambda: None) is True
    pool.shutdown(wait=True)
    assert pool.started is False

    done = threading.Event()
    assert pool.submit(done.set) is True
    assert done.wait(2)
    pool.shutdown(wait=True)
