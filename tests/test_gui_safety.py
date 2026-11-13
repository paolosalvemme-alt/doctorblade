from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import main_blade
from main_blade import MainWindow
from settings_manager import AppSettings


@pytest.fixture(scope="module")
def app() -> QApplication:
    instance = QApplication.instance()
    return instance if instance is not None else QApplication([])


@pytest.fixture
def window(app: QApplication, monkeypatch) -> MainWindow:
    class FakeSettingsManager:
        def load(self) -> AppSettings:
            return AppSettings()

        def save(self, settings: AppSettings) -> None:
            pass

    monkeypatch.setattr(main_blade, "SettingsManager", FakeSettingsManager)
    monkeypatch.setattr(
        main_blade.MarlinSerial,
        "available_ports",
        staticmethod(lambda: []),
    )
    result = MainWindow()
    yield result
    result.serial_link = main_blade.MarlinSerial()
    result.close()
    app.processEvents()


def test_jog_is_blocked_before_homing(window: MainWindow) -> None:
    messages: list[str] = []
    window._show_error = messages.append  # type: ignore[method-assign]
    window.homed = False
    window.allow_unhomed_check.setChecked(False)

    window._jog_x(1.0)

    assert messages == ["Home X first, or enable movement before homing."]
    assert not window.command_jobs


def test_ui_states_the_required_x_axis_convention(window: MainWindow) -> None:
    assert window.jog_minus_button.text() == "Jog -X (toward home)"
    assert window.jog_plus_button.text() == "Jog +X (away from home)"
    assert "-X moves toward the X-min home switch" in window.axis_convention_label.text()
    assert "+X moves away from home" in window.axis_convention_label.text()


def test_negative_coordinates_are_not_used_to_compensate_wrong_motor_direction(
    window: MainWindow,
) -> None:
    messages: list[str] = []
    window._show_error = messages.append  # type: ignore[method-assign]

    assert window._target_in_travel(-1.0) is False
    assert messages == ["Target X must be between 0 and 200 mm."]


def test_endstop_check_sends_m119_without_motion(window: MainWindow) -> None:
    captured_commands: list[str] = []

    class FakeSerial:
        is_connected = True

    def run_sequence(commands, success_message, on_success=None, **kwargs) -> None:
        captured_commands.extend(item.command for item in commands)

    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window._run_command_sequence = run_sequence  # type: ignore[method-assign]

    window._check_x_endstop()

    assert captured_commands == ["M119"]
    assert window.endstop_status_label.text() == "Waiting for M119..."


def test_endstop_check_uses_captured_multiline_response_without_false_warning(
    window: MainWindow,
) -> None:
    messages: list[str] = []

    class FakeSerial:
        is_connected = True

    def run_sequence(commands, success_message, on_success=None, **kwargs) -> None:
        assert commands[0].capture_response is True
        kwargs["on_response"](
            [
                "Reporting endstop status",
                "x_min: TRIGGERED",
                "y_min: TRIGGERED",
                "z_min: TRIGGERED",
                "ok",
            ]
        )

    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window._show_error = messages.append  # type: ignore[method-assign]
    window._run_command_sequence = run_sequence  # type: ignore[method-assign]

    window._check_x_endstop()

    assert window.endstop_status_label.text() == "TRIGGERED (lever pressed)"
    assert messages == []


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("x_min: open", "OPEN (lever released)"),
        ("x_min: TRIGGERED", "TRIGGERED (lever pressed)"),
    ],
)
def test_endstop_status_is_shown_from_m119(
    window: MainWindow,
    line: str,
    expected: str,
) -> None:
    window._handle_serial_line(line)

    assert window.endstop_status_label.text() == expected


def test_home_checks_x_min_before_sending_g28(window: MainWindow) -> None:
    captured = []

    class FakeSerial:
        is_connected = True

    def run_sequence(commands, success_message, on_success=None, **kwargs) -> None:
        captured.extend(commands)

    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window._run_command_sequence = run_sequence  # type: ignore[method-assign]

    window._home_x()

    assert [item.command for item in captured] == ["M119", "G28 X", "G90", "M114"]
    assert captured[0].capture_response is True
    assert captured[0].response_validator is not None


def test_staged_home_uses_guarded_fast_preapproach(
    window: MainWindow,
    monkeypatch,
) -> None:
    captured = []

    class FakeSerial:
        is_connected = True

    def run_sequence(commands, success_message, on_success=None, **kwargs) -> None:
        captured.extend(commands)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )
    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window.home_distance_spin.setValue(120.0)
    window._run_command_sequence = run_sequence  # type: ignore[method-assign]

    window._home_x()

    assert [item.command for item in captured] == [
        "M119",
        "M120",
        "G91",
        "G1 X-80 F600",
        "M400",
        "G90",
        "M119",
        "G28 X",
        "G90",
        "M114",
    ]
    assert captured[0].response_validator is not None
    assert captured[6].response_validator is not None
    assert window.home_distance_spin.value() == 0.0


def test_staged_home_requires_operator_confirmation(
    window: MainWindow,
    monkeypatch,
) -> None:
    captured = []

    class FakeSerial:
        is_connected = True

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.No),
    )
    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window.home_distance_spin.setValue(120.0)
    window._run_command_sequence = (  # type: ignore[method-assign]
        lambda commands, *args, **kwargs: captured.extend(commands)
    )

    window._home_x()

    assert captured == []
    assert window.home_distance_spin.value() == 120.0


def test_quick_stop_restores_absolute_positioning(window: MainWindow) -> None:
    class FakeSerial:
        is_connected = True

        def __init__(self) -> None:
            self.commands: list[tuple[str, bool]] = []

        def send_immediate(
            self,
            command: str,
            *,
            abort_pending: bool = False,
        ) -> None:
            self.commands.append((command, abort_pending))

    fake = FakeSerial()
    window.serial_link = fake  # type: ignore[assignment]

    window._quick_stop()

    assert fake.commands == [("M410", True), ("G90", False)]
    assert window.homed is False
    assert window.current_x_mm is None


def test_controller_restart_invalidates_position(
    window: MainWindow,
    monkeypatch,
) -> None:
    scheduled: list[int] = []
    aborted: list[bool] = []
    monkeypatch.setattr(
        main_blade.QTimer,
        "singleShot",
        staticmethod(lambda delay, callback: scheduled.append(delay)),
    )
    window.serial_link.abort_pending = lambda: aborted.append(True)  # type: ignore[method-assign]
    window.controller_ready = True
    window.homed = True
    window.current_x_mm = 42.0

    window._handle_controller_restart()

    assert window.controller_ready is False
    assert window.homed is False
    assert window.current_x_mm is None
    assert window.status_label.text() == "Restarting"
    assert aborted == [True]
    assert scheduled == [1500]


def test_stop_profile_breaks_wait_stops_motion_and_turns_heater_off(
    window: MainWindow,
) -> None:
    class FakeSerial:
        is_connected = True

        def __init__(self) -> None:
            self.commands: list[tuple[str, bool]] = []

        def send_immediate(
            self,
            command: str,
            *,
            abort_pending: bool = False,
        ) -> None:
            self.commands.append((command, abort_pending))

    fake = FakeSerial()
    window.serial_link = fake  # type: ignore[assignment]
    window.profile_stop_event = threading.Event()
    window.homed = True
    window.current_x_mm = 50.0

    window._stop_profile()

    assert window.profile_stop_event.is_set()
    assert fake.commands == [
        ("M108", True),
        ("M410", True),
        ("M140 S0", True),
    ]
    assert window.homed is False
    assert window.current_x_mm is None


def test_calibration_requires_rehoming_after_apply(
    window: MainWindow,
    monkeypatch,
) -> None:
    captured_commands: list[str] = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )

    def run_sequence(commands, success_message, on_success=None, **kwargs) -> None:
        captured_commands.extend(item.command for item in commands)
        if on_success is not None:
            on_success()

    window._run_command_sequence = run_sequence  # type: ignore[method-assign]
    window.current_steps_spin.setValue(80.0)
    window.commanded_distance_spin.setValue(100.0)
    window.measured_distance_spin.setValue(95.0)
    window.homed = True
    window.current_x_mm = 100.0

    window._apply_calibration()

    assert captured_commands[0].startswith("M92 X84.2105")
    assert captured_commands[1] == "M500"
    assert window.homed is False
    assert window.current_x_mm is None


def test_temperature_poll_waits_for_its_own_ok(window: MainWindow) -> None:
    completed = threading.Event()
    calls: list[tuple[str, bool, float, bool]] = []

    class FakeSerial:
        is_connected = True

        def send_command(
            self,
            command: str,
            *,
            wait_for_ok: bool,
            timeout: float,
            block: bool,
        ) -> bool:
            calls.append((command, wait_for_ok, timeout, block))
            completed.set()
            return True

    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True

    window._poll_temperature()

    assert completed.wait(1.0)
    assert calls == [("M105", True, 3.0, False)]


def test_emergency_stop_latches_killed_state(window: MainWindow, monkeypatch) -> None:
    calls: list[tuple[str, bool]] = []
    critical_messages: list[str] = []

    class FakeSerial:
        is_connected = True

        def send_immediate(self, command: str, *, abort_pending: bool = False) -> None:
            calls.append((command, abort_pending))

        def disconnect(self) -> None:
            self.is_connected = False

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.Yes),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        staticmethod(lambda _parent, _title, message: critical_messages.append(message)),
    )
    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.controller_ready = True
    window.homed = True
    window.current_x_mm = 50.0

    window._emergency_stop()

    assert calls == [("M112", True)]
    assert window.emergency_latched is True
    assert window.controller_ready is False
    assert window.homed is False
    assert window.current_x_mm is None
    assert window.status_label.text() == "E-STOP: RESET BOARD"
    assert "not a software freeze" in critical_messages[0]


def test_reconnect_after_emergency_requires_reset_confirmation(
    window: MainWindow,
    monkeypatch,
) -> None:
    connect_calls: list[tuple[str, int]] = []

    class FakeSerial:
        is_connected = False

        def connect(self, port: str, baudrate: int) -> None:
            connect_calls.append((port, baudrate))

    monkeypatch.setattr(
        QMessageBox,
        "question",
        staticmethod(lambda *args, **kwargs: QMessageBox.No),
    )
    window.serial_link = FakeSerial()  # type: ignore[assignment]
    window.emergency_latched = True
    window.manual_port_edit.setText("COM9")

    window._connect_serial()

    assert connect_calls == []
    assert window.emergency_latched is True
