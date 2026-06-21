import threading
import time

from zuse.agentpool import DONE, FAILED, RUNNING, AgentRegistry, AgentRun


def test_agentrun_elapsed_and_fraction():
    run = AgentRun(id="a1", role="r", title="t", max_steps=10)
    assert run.elapsed == 0.0           # not started yet
    assert run.fraction == 0.0

    run.started = time.monotonic() - 0.05
    assert run.elapsed > 0.0

    run.status = RUNNING
    run.step = 5                          # 5/10 by step count
    assert run.fraction == 0.5

    run.todos_total, run.todos_done = 4, 3  # todo plan takes precedence
    assert run.fraction == 0.75
    assert run.percent == 75

    run.status = DONE                     # completed reads full
    assert run.fraction == 1.0
    assert run.percent == 100


def test_failed_agent_reports_how_far_it_got_not_full():
    run = AgentRun(id="a1", role="r", title="t", max_steps=10, step=4, status=FAILED)
    # A failed agent reflects real progress (4/10), not a misleading 100%.
    assert run.fraction == 0.4
    assert run.percent == 40


def test_registry_create_update_snapshot_is_isolated():
    reg = AgentRegistry()
    rid = reg.create("coder", "Implement X", 8)
    reg.start(rid)
    reg.update(rid, step=2, activity="editing")

    snap = reg.snapshot()
    assert len(snap) == 1
    assert snap[0].role == "coder"
    assert snap[0].status == RUNNING
    assert snap[0].step == 2

    # Snapshot hands out copies — mutating one must not affect the registry.
    snap[0].step = 999
    assert reg.snapshot()[0].step == 2

    reg.finish(rid, ok=False, error="boom")
    done = reg.snapshot()[0]
    assert done.status == FAILED
    assert done.error == "boom"
    assert done.ended > 0


def test_registry_preserves_creation_order():
    reg = AgentRegistry()
    ids = [reg.create(f"r{i}", f"t{i}", 5) for i in range(5)]
    assert [r.id for r in reg.snapshot()] == ids


def test_registry_is_thread_safe_under_concurrent_writers():
    reg = AgentRegistry()
    ids = [reg.create(f"r{i}", "t", 10) for i in range(20)]

    def worker(rid: str) -> None:
        reg.start(rid)
        for step in range(1, 11):
            reg.update(rid, step=step, activity=f"step {step}")
        reg.finish(rid, ok=True)

    threads = [threading.Thread(target=worker, args=(rid,)) for rid in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    snap = reg.snapshot()
    assert len(snap) == 20
    assert all(r.status == DONE for r in snap)
    assert all(r.step == 10 for r in snap)
