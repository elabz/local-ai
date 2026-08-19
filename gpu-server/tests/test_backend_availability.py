from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from availability import BackendAvailability


class Clock:
    def __init__(self):
        self.value = 1000.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


def tracker(tmp_path, **kwargs):
    clock = kwargs.pop("clock", Clock())
    state_path = tmp_path / "restart.json"
    return BackendAvailability(
        restart_state_path=str(state_path), clock=clock, wall_clock=clock, **kwargs,
    ), clock


def test_busy_probe_timeout_never_restarts_live_inference(tmp_path):
    availability, clock = tracker(tmp_path, stuck_request_seconds=60)
    availability.probe_succeeded()
    availability.begin_request()
    for _ in range(8):
        decision = availability.probe_failed(child_alive=True)
        assert not decision.restart
        assert decision.reason == "busy_probe_timeout"
        clock.advance(5)
    snapshot = availability.snapshot()
    assert snapshot.state == "busy"
    assert snapshot.in_flight == 1


def test_admission_is_atomically_bounded(tmp_path):
    availability, _ = tracker(tmp_path, max_in_flight=2)
    assert availability.begin_request()
    assert availability.begin_request()
    assert not availability.begin_request()
    snapshot = availability.snapshot()
    assert snapshot.in_flight == 2
    assert snapshot.reason == "capacity_exhausted"


def test_idle_probe_failure_restarts_at_bounded_threshold(tmp_path):
    availability, _ = tracker(tmp_path, idle_failure_limit=3)
    assert not availability.probe_failed().restart
    assert not availability.probe_failed().restart
    decision = availability.probe_failed()
    assert decision.restart
    assert decision.reason == "idle_probe_failure"


def test_child_exit_requests_immediate_bounded_restart(tmp_path):
    availability, _ = tracker(tmp_path)
    decision = availability.child_exited()
    assert decision.restart
    assert decision.reason == "child_exit"
    assert availability.snapshot().state == "unavailable"


def test_stuck_request_restarts_after_age_and_failure_threshold(tmp_path):
    availability, clock = tracker(tmp_path, idle_failure_limit=2, stuck_request_seconds=30)
    availability.begin_request()
    clock.advance(31)
    assert not availability.probe_failed().restart
    decision = availability.probe_failed()
    assert decision.restart
    assert decision.reason == "stuck_request"


def test_old_queue_with_recent_completion_is_progressing_not_stuck(tmp_path):
    availability, clock = tracker(tmp_path, idle_failure_limit=2, stuck_request_seconds=30)
    availability.begin_request()
    clock.advance(20)
    availability.begin_request()
    clock.advance(11)
    availability.end_request()
    assert not availability.probe_failed().restart
    assert availability.snapshot().reason == "busy_probe_timeout"


def test_success_recovers_degraded_backend(tmp_path):
    availability, _ = tracker(tmp_path)
    availability.probe_failed()
    assert availability.snapshot().state == "degraded"
    availability.probe_succeeded()
    assert availability.snapshot().state == "ready"
    assert availability.snapshot().probe_failures == 0


def test_restart_rate_is_persisted_and_suppressed(tmp_path):
    availability, clock = tracker(tmp_path, restart_limit=2, restart_window_seconds=60)
    assert availability.child_exited().restart
    second = BackendAvailability(
        restart_limit=2, restart_window_seconds=60,
        restart_state_path=str(tmp_path / "restart.json"), clock=clock, wall_clock=clock,
    )
    assert second.child_exited().restart
    third = BackendAvailability(
        restart_limit=2, restart_window_seconds=60,
        restart_state_path=str(tmp_path / "restart.json"), clock=clock, wall_clock=clock,
    )
    decision = third.child_exited()
    assert not decision.restart
    assert decision.reason == "restart_suppressed"
    assert third.snapshot().reason == "restart_suppressed"
