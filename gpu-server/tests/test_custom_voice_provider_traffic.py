import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from custom_voice.provider_traffic import SlotRouter


def test_concurrent_request_stays_on_old_slot_while_new_requests_switch(tmp_path: Path) -> None:
    router = SlotRouter(tmp_path / "route.json")
    old_started = threading.Event()
    old_release = threading.Event()
    observed = []

    def old_request() -> None:
        with router.request_slot() as slot:
            observed.append(("old", slot))
            old_started.set()
            old_release.wait(2)

    thread = threading.Thread(target=old_request)
    thread.start()
    assert old_started.wait(1)
    router.switch("green")
    with router.request_slot() as slot:
        observed.append(("new", slot))
    assert router.wait_drained("blue", timeout=0.01) is False
    old_release.set()
    thread.join(1)
    assert router.wait_drained("blue", timeout=0.1) is True
    assert observed == [("old", "blue"), ("new", "green")]


def test_route_state_survives_controller_restart(tmp_path: Path) -> None:
    state = tmp_path / "route.json"
    first = SlotRouter(state)
    first.switch("green")
    assert SlotRouter(state).active_slot() == "green"
