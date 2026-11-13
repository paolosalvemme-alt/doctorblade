from __future__ import annotations

import threading
import time
from typing import Callable

import pytest

from marlin_serial import MarlinSerial


class FakeSerial:
    def __init__(self, on_write: Callable[[bytes], None] | None = None) -> None:
        self.is_open = True
        self.writes: list[bytes] = []
        self.on_write = on_write

    def write(self, payload: bytes) -> int:
        self.writes.append(payload)
        if self.on_write is not None:
            self.on_write(payload)
        return len(payload)

    def flush(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False


def connected_link(on_write: Callable[[bytes], None] | None = None) -> MarlinSerial:
    link = MarlinSerial()
    link._serial = FakeSerial(on_write)  # type: ignore[assignment]
    return link


def test_send_command_waits_for_ok() -> None:
    link = connected_link()
    fake = link._serial
    assert isinstance(fake, FakeSerial)

    def answer(_payload: bytes) -> None:
        link._responses.put("echo: processing")
        link._responses.put("ok")

    fake.on_write = answer
    assert link.send_command("M114", wait_for_ok=True, timeout=0.5)
    assert fake.writes == [b"M114\n"]


def test_query_command_returns_multiline_response_through_ok() -> None:
    link = connected_link()
    fake = link._serial
    assert isinstance(fake, FakeSerial)

    def answer(_payload: bytes) -> None:
        link._responses.put("Reporting endstop status")
        link._responses.put("x_min: TRIGGERED")
        link._responses.put("y_min: open")
        link._responses.put("ok")

    fake.on_write = answer

    assert link.query_command("M119", timeout=0.5) == [
        "Reporting endstop status",
        "x_min: TRIGGERED",
        "y_min: open",
        "ok",
    ]
    assert fake.writes == [b"M119\n"]


def test_marlin_error_is_raised() -> None:
    link = connected_link(lambda _payload: link._responses.put("Error: bad command"))
    with pytest.raises(RuntimeError, match="Marlin reported"):
        link.send_command("M999", wait_for_ok=True, timeout=0.5)


def test_command_session_blocks_other_regular_commands() -> None:
    link = connected_link()
    session_started = threading.Event()
    release_session = threading.Event()

    def hold_session() -> None:
        with link.command_session() as acquired:
            assert acquired
            session_started.set()
            release_session.wait(1.0)

    thread = threading.Thread(target=hold_session)
    thread.start()
    assert session_started.wait(0.5)
    try:
        assert link.send_command("M105", block=False) is False
    finally:
        release_session.set()
        thread.join(1.0)


def test_immediate_stop_aborts_pending_wait() -> None:
    link = connected_link()
    errors: list[Exception] = []

    def wait_for_response() -> None:
        try:
            link.send_command("M400", wait_for_ok=True, timeout=2.0)
        except Exception as exc:  # noqa: BLE001 - captured for assertion.
            errors.append(exc)

    thread = threading.Thread(target=wait_for_response)
    thread.start()
    time.sleep(0.05)
    link.send_immediate("M410", abort_pending=True)
    thread.join(1.0)

    assert not thread.is_alive()
    assert errors
    assert "cancelled" in str(errors[0]).lower()


def test_stop_cancels_remaining_commands_in_atomic_session() -> None:
    first_command_written = threading.Event()
    release_first_response = threading.Event()
    link = connected_link()
    fake = link._serial
    assert isinstance(fake, FakeSerial)

    def answer(payload: bytes) -> None:
        if payload == b"G91\n":
            first_command_written.set()
            release_first_response.wait(1.0)
            link._responses.put("ok")

    fake.on_write = answer
    errors: list[Exception] = []

    def run_sequence() -> None:
        try:
            with link.command_session() as acquired:
                assert acquired
                link.send_command("G91", wait_for_ok=True, timeout=1.0)
                link.send_command("G1 X10", wait_for_ok=False)
        except Exception as exc:  # noqa: BLE001 - captured for assertion.
            errors.append(exc)

    thread = threading.Thread(target=run_sequence)
    thread.start()
    assert first_command_written.wait(0.5)
    link.send_immediate("M410", abort_pending=True)
    release_first_response.set()
    thread.join(1.0)

    assert not thread.is_alive()
    assert b"G1 X10\n" not in fake.writes
    assert errors
    assert "cancelled" in str(errors[0]).lower()


def test_new_atomic_session_clears_previous_abort() -> None:
    link = connected_link(lambda _payload: link._responses.put("ok"))
    link.abort_pending()
    with link.command_session() as acquired:
        assert acquired
        assert link.send_command("M115", wait_for_ok=True, timeout=0.5)


def test_multiline_command_is_rejected() -> None:
    link = connected_link()
    with pytest.raises(ValueError, match="exactly one"):
        link.send_immediate("G90\nG1 X100")
