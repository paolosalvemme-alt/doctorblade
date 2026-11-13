from __future__ import annotations

from dataclasses import dataclass
import sys
import threading
import time
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from calibration import calculate_new_steps
from gcode import (
    cmd_accel,
    cmd_bed_set,
    cmd_bed_wait,
    cmd_dwell,
    cmd_move_x,
    cmd_move_x_relative,
    cmd_steps_x,
    feedrate_mm_min,
    format_gcode_number,
    parse_bed_power,
    parse_bed_temp,
    parse_x_min_endstop,
    parse_x_min_endstop_response,
    parse_x_position,
    parse_x_steps,
    response_reports_bed,
    staged_home_pretravel,
    validate_x_min_open_response,
)
from diagnostics import (
    BedHeatingWatch,
    bed_power_percent,
    classify_bed_reading,
    explain_marlin_message,
)
from marlin_serial import MarlinSerial
from profile_model import CoatingProfile, CoatingSegment
from settings_manager import AppSettings, SettingsManager


APP_DISPLAY_NAME = "Doctor Blade Controller V3.0.6"
APP_VERSION = "3.0.6"
STAGED_HOME_MARGIN_MM = 40.0
STAGED_HOME_FAST_SPEED_MM_S = 10.0
ENDSTOP_MONITOR_INTERVAL_MS = 500


@dataclass(frozen=True)
class CommandSpec:
    command: str
    wait_for_ok: bool = False
    timeout: float = 10.0
    immediate: bool = False
    capture_response: bool = False
    response_validator: Callable[[list[str]], None] | None = None


class SerialSignalBridge(QObject):
    line_received = Signal(str)
    warning_received = Signal(str)
    disconnected = Signal(str)
    temperature_poll_failed = Signal(str)
    endstop_poll_failed = Signal(str)


class SerialCommandWorker(QObject):
    finished = Signal(bool, str, object)

    def __init__(
        self,
        serial_link: MarlinSerial,
        commands: list[CommandSpec],
        success_message: str,
    ) -> None:
        super().__init__()
        self.serial_link = serial_link
        self.commands = commands
        self.success_message = success_message

    @Slot()
    def run(self) -> None:
        response_lines: list[str] = []
        try:
            with self.serial_link.command_session() as acquired:
                if not acquired:
                    raise RuntimeError("Another serial operation is already running.")
                for command in self.commands:
                    if command.immediate:
                        self.serial_link.send_immediate(command.command)
                    elif command.capture_response:
                        command_response = self.serial_link.query_command(
                            command.command,
                            timeout=command.timeout,
                        )
                        response_lines.extend(command_response)
                        if command.response_validator is not None:
                            command.response_validator(command_response)
                    else:
                        self.serial_link.send_command(
                            command.command,
                            wait_for_ok=command.wait_for_ok,
                            timeout=command.timeout,
                        )
            self.finished.emit(True, self.success_message, response_lines)
        except Exception as exc:  # noqa: BLE001 - GUI should show all serial failures.
            self.finished.emit(False, str(exc), response_lines)


class ProfileWorker(QObject):
    finished = Signal(bool, str)
    progress = Signal(int, str)
    position_changed = Signal(float)

    def __init__(
        self,
        serial_link: MarlinSerial,
        profile: CoatingProfile,
        travel_limit_mm: float,
        stop_event: threading.Event,
    ) -> None:
        super().__init__()
        self.serial_link = serial_link
        self.profile = profile
        self.travel_limit_mm = travel_limit_mm
        self.stop_event = stop_event

    @Slot()
    def run(self) -> None:
        try:
            with self.serial_link.command_session() as acquired:
                if not acquired:
                    raise RuntimeError("Another serial operation is already running.")
                self.profile.validate(self.travel_limit_mm)
                self.serial_link.send_command("G21", wait_for_ok=True, timeout=10.0)
                self.serial_link.send_command("G90", wait_for_ok=True, timeout=10.0)

                for index, segment in enumerate(self.profile.segments):
                    if self.stop_event.is_set():
                        self.finished.emit(False, "Profile stopped before the next segment.")
                        return

                    self.progress.emit(index, f"Running segment {index + 1}")

                    if segment.bed_temp_c is not None:
                        temp_command = (
                            cmd_bed_wait(segment.bed_temp_c)
                            if segment.wait_for_temperature
                            else cmd_bed_set(segment.bed_temp_c)
                        )
                        self.serial_link.send_command(
                            temp_command,
                            wait_for_ok=True,
                            timeout=1800.0 if segment.wait_for_temperature else 10.0,
                        )

                    if self.stop_event.is_set():
                        self.finished.emit(False, "Profile stopped before motion.")
                        return

                    self.serial_link.send_command(
                        cmd_accel(segment.acceleration_mm_s2),
                        wait_for_ok=True,
                        timeout=10.0,
                    )
                    self.serial_link.send_command(
                        cmd_move_x(segment.target_x_mm, segment.speed_mm_s),
                        wait_for_ok=True,
                        timeout=10.0,
                    )
                    self.serial_link.send_command(
                        "M400",
                        wait_for_ok=True,
                        timeout=3600.0,
                    )
                    self.position_changed.emit(segment.target_x_mm)

                    if self.stop_event.is_set():
                        self.finished.emit(False, "Profile stopped after motion.")
                        return

                    if segment.dwell_s > 0:
                        self.serial_link.send_command(
                            cmd_dwell(segment.dwell_s),
                            wait_for_ok=True,
                            timeout=max(30.0, segment.dwell_s + 30.0),
                        )

            self.finished.emit(True, "Profile complete.")
        except Exception as exc:  # noqa: BLE001 - GUI should show all profile failures.
            self.finished.emit(False, str(exc))


class SegmentDialog(QDialog):
    def __init__(
        self,
        parent: QWidget,
        segment: CoatingSegment | None,
        defaults: AppSettings,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coating Segment")

        self.target_x_spin = self._spin(0.0, 100000.0, 3)
        self.speed_spin = self._spin(0.001, 1000.0, 3)
        self.accel_spin = self._spin(0.001, 100000.0, 3)
        self.dwell_spin = self._spin(0.0, 36000.0, 3)
        self.use_bed_check = QCheckBox("Use bed temperature")
        self.bed_temp_spin = self._spin(0.0, 300.0, 1)
        self.wait_temp_check = QCheckBox("Wait for temperature")

        if segment is None:
            self.speed_spin.setValue(defaults.default_speed_mm_s)
            self.accel_spin.setValue(defaults.default_acceleration_mm_s2)
            self.bed_temp_spin.setValue(defaults.default_bed_temperature_c)
        else:
            self.target_x_spin.setValue(segment.target_x_mm)
            self.speed_spin.setValue(segment.speed_mm_s)
            self.accel_spin.setValue(segment.acceleration_mm_s2)
            self.dwell_spin.setValue(segment.dwell_s)
            self.use_bed_check.setChecked(segment.bed_temp_c is not None)
            if segment.bed_temp_c is not None:
                self.bed_temp_spin.setValue(segment.bed_temp_c)
            else:
                self.bed_temp_spin.setValue(defaults.default_bed_temperature_c)
            self.wait_temp_check.setChecked(segment.wait_for_temperature)

        self.use_bed_check.toggled.connect(self._set_bed_enabled)
        self._set_bed_enabled(self.use_bed_check.isChecked())

        form = QFormLayout()
        form.addRow("Target X (mm)", self.target_x_spin)
        form.addRow("Speed (mm/s)", self.speed_spin)
        form.addRow("Acceleration (mm/s^2)", self.accel_spin)
        form.addRow("Dwell (s)", self.dwell_spin)
        form.addRow("", self.use_bed_check)
        form.addRow("Bed temperature (deg C)", self.bed_temp_spin)
        form.addRow("", self.wait_temp_check)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    @staticmethod
    def _spin(minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setSingleStep(1.0)
        return spin

    def _set_bed_enabled(self, enabled: bool) -> None:
        self.bed_temp_spin.setEnabled(enabled)
        self.wait_temp_check.setEnabled(enabled)

    def segment(self) -> CoatingSegment:
        return CoatingSegment(
            target_x_mm=self.target_x_spin.value(),
            speed_mm_s=self.speed_spin.value(),
            acceleration_mm_s2=self.accel_spin.value(),
            dwell_s=self.dwell_spin.value(),
            bed_temp_c=self.bed_temp_spin.value() if self.use_bed_check.isChecked() else None,
            wait_for_temperature=self.wait_temp_check.isChecked()
            if self.use_bed_check.isChecked()
            else False,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1100, 760)
        self._apply_theme()

        self.settings_manager = SettingsManager()
        self.settings = self.settings_manager.load()
        self.serial_link = MarlinSerial()
        self.bridge = SerialSignalBridge()
        self.serial_link.line_callback = self.bridge.line_received.emit
        self.serial_link.warning_callback = self.bridge.warning_received.emit
        self.serial_link.disconnect_callback = self.bridge.disconnected.emit

        self.bridge.line_received.connect(self._handle_serial_line)
        self.bridge.warning_received.connect(self._handle_marlin_warning)
        self.bridge.disconnected.connect(self._handle_serial_disconnect)
        self.bridge.temperature_poll_failed.connect(self._temperature_poll_failed)
        self.bridge.endstop_poll_failed.connect(self._endstop_poll_failed)

        self.command_jobs: list[tuple[QThread, SerialCommandWorker]] = []
        self.profile_thread: QThread | None = None
        self.profile_worker: ProfileWorker | None = None
        self.profile_stop_event: threading.Event | None = None
        self.profile_segments: list[CoatingSegment] = []
        self.current_x_mm: float | None = None
        self.homed = False
        self.controller_ready = False
        self.emergency_latched = False
        self.connection_generation = 0
        self.temperature_poll_active = False
        self.endstop_poll_active = False
        self.last_x_endstop_state: bool | None = None
        self.endstop_transitions = 0
        self.bed_available: bool | None = None
        self.bed_heating_watch = BedHeatingWatch()
        self.thermistor_fault: str | None = None

        self.temp_timer = QTimer(self)
        self.temp_timer.setInterval(2000)
        self.temp_timer.timeout.connect(self._poll_temperature)

        self.endstop_timer = QTimer(self)
        self.endstop_timer.setInterval(ENDSTOP_MONITOR_INTERVAL_MS)
        self.endstop_timer.timeout.connect(self._poll_endstop)

        self._build_ui()
        self._apply_settings_to_ui()
        self._refresh_ports()
        self._update_connection_ui(False)
        self._update_calibration()

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("mainSurface")
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 14, 14, 14)
        main_layout.setSpacing(12)

        main_layout.addWidget(self._connection_group())

        tabs = QTabWidget()
        tabs.setObjectName("mainTabs")
        tabs.addTab(self._manual_motion_tab(), "Manual Motion")
        tabs.addTab(self._heated_bed_tab(), "Heated Bed")
        tabs.addTab(self._profile_tab(), "Coating Profile")
        tabs.addTab(self._calibration_tab(), "Calibration")
        main_layout.addWidget(tabs, stretch=1)

        log_group = QGroupBox("Raw Serial Log")
        log_group.setObjectName("logGroup")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setObjectName("serialLog")
        self.log_edit.setReadOnly(True)
        self.log_edit.document().setMaximumBlockCount(3000)
        log_layout.addWidget(self.log_edit)
        main_layout.addWidget(log_group, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Disconnected.")

    def _apply_theme(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #edf1f5;
            }
            #mainSurface {
                background: #edf1f5;
            }
            QGroupBox {
                background: #fbfdff;
                border: 1px solid #d5dee9;
                border-radius: 8px;
                color: #233142;
                font-weight: 600;
                margin-top: 18px;
                padding: 14px 12px 12px 12px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 7px;
            }
            #connectionGroup {
                background: #edfaff;
                border-color: #87cfe4;
            }
            #logGroup {
                background: #f6f8fb;
                border-color: #b8c4d2;
            }
            QTabWidget::pane {
                border: 1px solid #cfd9e5;
                border-radius: 8px;
                background: #ffffff;
                top: -1px;
            }
            QTabBar::tab {
                background: #dfe7f0;
                color: #25364a;
                padding: 8px 16px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                margin-right: 3px;
            }
            QTabBar::tab:selected {
                background: #ffffff;
                color: #122033;
                border: 1px solid #cfd9e5;
                border-bottom: 1px solid #ffffff;
            }
            #motionPage {
                background: #eef6ff;
            }
            #bedPage {
                background: #fff4e8;
            }
            #profilePage {
                background: #eefaf3;
            }
            #calibrationPage {
                background: #f5f0ff;
            }
            QLabel {
                color: #27384c;
            }
            QLineEdit, QComboBox, QDoubleSpinBox, QTextEdit, QTableWidget {
                background: #ffffff;
                border: 1px solid #b9c5d3;
                border-radius: 5px;
                color: #172435;
                padding: 4px 6px;
                selection-background-color: #2f80ed;
            }
            QDoubleSpinBox {
                min-height: 24px;
            }
            QPushButton {
                background: #ffffff;
                border: 1px solid #9cadbf;
                border-radius: 6px;
                color: #162333;
                padding: 7px 12px;
                font-weight: 600;
            }
            QPushButton:hover {
                background: #f1f6fb;
                border-color: #7392b7;
            }
            QPushButton:pressed {
                background: #dfeaf5;
            }
            QPushButton:disabled {
                background: #e7ebf0;
                color: #7b8794;
                border-color: #c7d0da;
            }
            QPushButton#connectButton, QPushButton#primaryAction {
                background: #1f7a53;
                border-color: #16623f;
                color: white;
            }
            QPushButton#connectButton:hover, QPushButton#primaryAction:hover {
                background: #269362;
            }
            QPushButton#warningButton {
                background: #f2a541;
                border-color: #c97e19;
                color: #271806;
            }
            QPushButton#warningButton:hover {
                background: #f5b45f;
            }
            QPushButton#dangerButton {
                background: #b83232;
                border-color: #8e2525;
                color: white;
            }
            QPushButton#dangerButton:hover {
                background: #cf3f3f;
            }
            QLabel#positionReadout {
                background: #dceeff;
                border: 1px solid #8fbfe8;
                border-radius: 6px;
                color: #12395f;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#temperatureReadout {
                background: #ffe3c5;
                border: 1px solid #e3a35f;
                border-radius: 6px;
                color: #633509;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#safetyNote {
                background: #fff4ce;
                border: 1px solid #c99a24;
                border-radius: 6px;
                color: #5e4300;
                font-weight: 600;
                padding: 7px 9px;
            }
            QLabel#endstopOpen {
                background: #dceeff;
                border: 1px solid #75aadb;
                border-radius: 6px;
                color: #12395f;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#endstopTriggered {
                background: #dff3e5;
                border: 1px solid #63a977;
                border-radius: 6px;
                color: #18562b;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#endstopUnknown {
                background: #f2f4f7;
                border: 1px solid #aeb8c4;
                border-radius: 6px;
                color: #536171;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#faultReadout {
                background: #ffe0e0;
                border: 1px solid #c94b4b;
                border-radius: 6px;
                color: #7a1414;
                font-weight: 700;
                padding: 6px 8px;
            }
            QLabel#calibrationReadout {
                background: #eadfff;
                border: 1px solid #b59bea;
                border-radius: 6px;
                color: #38205f;
                font-weight: 700;
                padding: 6px 8px;
            }
            QTextEdit#serialLog {
                background: #101822;
                color: #d8f2e6;
                border-color: #2a3746;
                font-family: Consolas, "Courier New", monospace;
            }
            QHeaderView::section {
                background: #dcebdc;
                border: 1px solid #b9cbb9;
                color: #1d3927;
                padding: 5px;
                font-weight: 600;
            }
            QTableWidget {
                gridline-color: #c9d7c9;
                alternate-background-color: #f7fbf7;
            }
            QStatusBar {
                background: #dde5ee;
                color: #26374a;
            }
            """
        )

    def _connection_group(self) -> QGroupBox:
        group = QGroupBox("Connection")
        group.setObjectName("connectionGroup")
        layout = QGridLayout(group)

        self.port_combo = QComboBox()
        self.refresh_ports_button = QPushButton("Refresh")
        self.manual_port_edit = QLineEdit()
        self.manual_port_edit.setPlaceholderText("Manual port, e.g. COM3")
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200", "250000"])
        self.connect_button = QPushButton("Connect")
        self.connect_button.setObjectName("connectButton")
        self.disconnect_button = QPushButton("Disconnect")
        self.status_label = QLabel("Disconnected")
        self.status_label.setAlignment(Qt.AlignCenter)

        layout.addWidget(QLabel("COM selector"), 0, 0)
        layout.addWidget(self.port_combo, 0, 1)
        layout.addWidget(self.refresh_ports_button, 0, 2)
        layout.addWidget(QLabel("Manual COM"), 1, 0)
        layout.addWidget(self.manual_port_edit, 1, 1, 1, 2)
        layout.addWidget(QLabel("Baud rate"), 0, 3)
        layout.addWidget(self.baud_combo, 0, 4)
        layout.addWidget(self.connect_button, 0, 5)
        layout.addWidget(self.disconnect_button, 1, 5)
        layout.addWidget(QLabel("Status"), 1, 3)
        layout.addWidget(self.status_label, 1, 4)

        self.refresh_ports_button.clicked.connect(self._refresh_ports)
        self.connect_button.clicked.connect(self._connect_serial)
        self.disconnect_button.clicked.connect(self._disconnect_serial)

        return group

    def _manual_motion_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("motionPage")
        layout = QGridLayout(widget)

        self.current_x_label = QLabel("Unknown")
        self.current_x_label.setObjectName("positionReadout")
        self.home_button = QPushButton("Home X")
        self.read_position_button = QPushButton("Read Position")
        self.endstop_status_label = QLabel("Unknown")
        self.endstop_status_label.setObjectName("endstopUnknown")
        self.check_endstop_button = QPushButton("Check X Endstop (M119)")
        self.endstop_monitor_check = QCheckBox(
            "Live endstop monitor (M119 every 0.5 s, no motion)"
        )
        self.endstop_changes_label = QLabel("State changes seen: 0")
        self.endstop_wiring_label = QLabel(
            "Endstop wiring: switch signal on X-STOP pin PC0, ground on X-STOP GND. "
            "Remove the X-DIAG jumper when a mechanical switch is used. Press and "
            "release the lever with the monitor on: the state must follow the lever."
        )
        self.endstop_wiring_label.setWordWrap(True)
        self.endstop_wiring_label.setObjectName("safetyNote")
        self.home_distance_spin = self._make_spin(0.0, 100000.0, 1, 0.0)
        self.home_distance_spin.setSpecialValueText("0 (standard slow homing)")
        self.jog_distance_spin = self._make_spin(0.001, 1000.0, 3, 1.0)
        self.jog_minus_button = QPushButton("Jog -X (toward home)")
        self.jog_plus_button = QPushButton("Jog +X (away from home)")
        self.absolute_x_spin = self._make_spin(0.0, 100000.0, 3, 0.0)
        self.move_absolute_button = QPushButton("Move to X")
        self.speed_spin = self._make_spin(0.001, 1000.0, 3, 5.0)
        self.accel_spin = self._make_spin(0.001, 100000.0, 3, 300.0)
        self.travel_limit_spin = self._make_spin(0.001, 100000.0, 3, 200.0)
        self.allow_unhomed_check = QCheckBox("Allow movement before homing")
        self.axis_convention_label = QLabel(
            "Required axis convention: -X moves toward the X-min home switch; "
            "+X moves away from home across the 0...travel-limit range."
        )
        self.axis_convention_label.setWordWrap(True)
        self.axis_convention_label.setObjectName("safetyNote")
        self.staged_home_label = QLabel(
            "Optional staged homing: enter the approximate current distance to X-min. "
            "The app approaches at 10 mm/s only to the start of a 40 mm slow zone, "
            "then Marlin V1.0.2 completes G28 X at 5 mm/s."
        )
        self.staged_home_label.setWordWrap(True)
        self.staged_home_label.setObjectName("safetyNote")
        self.quick_stop_button = QPushButton("Quick Stop")
        self.quick_stop_button.setObjectName("warningButton")
        self.emergency_stop_button = QPushButton("Emergency Stop")
        self.emergency_stop_button.setObjectName("dangerButton")
        self.motors_off_button = QPushButton("Motors Off")

        layout.addWidget(QLabel("Current X"), 0, 0)
        layout.addWidget(self.current_x_label, 0, 1)
        layout.addWidget(self.home_button, 0, 2)
        layout.addWidget(self.read_position_button, 0, 3)
        layout.addWidget(QLabel("X-min endstop"), 1, 0)
        layout.addWidget(self.endstop_status_label, 1, 1)
        layout.addWidget(self.check_endstop_button, 1, 2, 1, 2)
        layout.addWidget(self.endstop_monitor_check, 2, 0, 1, 2)
        layout.addWidget(self.endstop_changes_label, 2, 2, 1, 2)
        layout.addWidget(self.endstop_wiring_label, 3, 0, 1, 4)
        layout.addWidget(QLabel("Estimated distance to home (mm)"), 4, 0)
        layout.addWidget(self.home_distance_spin, 4, 1)
        layout.addWidget(self.staged_home_label, 4, 2, 1, 2)
        layout.addWidget(QLabel("Jog distance (mm)"), 5, 0)
        layout.addWidget(self.jog_distance_spin, 5, 1)
        layout.addWidget(self.jog_minus_button, 5, 2)
        layout.addWidget(self.jog_plus_button, 5, 3)
        layout.addWidget(QLabel("Absolute X (mm)"), 6, 0)
        layout.addWidget(self.absolute_x_spin, 6, 1)
        layout.addWidget(self.move_absolute_button, 6, 2, 1, 2)
        layout.addWidget(QLabel("Speed (mm/s)"), 7, 0)
        layout.addWidget(self.speed_spin, 7, 1)
        layout.addWidget(QLabel("Acceleration (mm/s^2)"), 7, 2)
        layout.addWidget(self.accel_spin, 7, 3)
        layout.addWidget(QLabel("Software travel limit (mm)"), 8, 0)
        layout.addWidget(self.travel_limit_spin, 8, 1)
        layout.addWidget(self.allow_unhomed_check, 8, 2, 1, 2)
        layout.addWidget(self.axis_convention_label, 9, 0, 1, 4)
        layout.addWidget(self.quick_stop_button, 10, 0)
        layout.addWidget(self.emergency_stop_button, 10, 1)
        layout.addWidget(self.motors_off_button, 10, 2)
        layout.setColumnStretch(4, 1)
        layout.setRowStretch(11, 1)

        self.home_button.clicked.connect(self._home_x)
        self.read_position_button.clicked.connect(self._read_position)
        self.check_endstop_button.clicked.connect(self._check_x_endstop)
        self.endstop_monitor_check.toggled.connect(self._toggle_endstop_monitor)
        self.jog_minus_button.clicked.connect(lambda: self._jog_x(-1.0))
        self.jog_plus_button.clicked.connect(lambda: self._jog_x(1.0))
        self.move_absolute_button.clicked.connect(self._move_absolute_x)
        self.allow_unhomed_check.toggled.connect(self._confirm_unhomed_movement)
        self.quick_stop_button.clicked.connect(self._quick_stop)
        self.emergency_stop_button.clicked.connect(self._emergency_stop)
        self.motors_off_button.clicked.connect(self._motors_off)
        self.travel_limit_spin.valueChanged.connect(self._update_absolute_limit)

        return widget

    def _heated_bed_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("bedPage")
        layout = QGridLayout(widget)

        self.current_bed_label = QLabel("Unknown")
        self.current_bed_label.setObjectName("temperatureReadout")
        self.target_bed_label = QLabel("Unknown")
        self.target_bed_label.setObjectName("temperatureReadout")
        self.bed_setpoint_spin = self._make_spin(0.0, 300.0, 1, 60.0)
        self.bed_safety_spin = self._make_spin(0.0, 300.0, 1, 90.0)
        self.set_bed_button = QPushButton("Set Bed Temperature")
        self.wait_bed_button = QPushButton("Set and Wait")
        self.heater_off_button = QPushButton("Heater Off")
        self.heater_off_button.setObjectName("warningButton")
        self.bed_power_label = QLabel("Unknown")
        self.bed_power_label.setObjectName("temperatureReadout")
        self.thermistor_status_label = QLabel("Unknown")
        self.thermistor_status_label.setObjectName("endstopUnknown")
        self.thermistor_status_label.setWordWrap(True)
        self.bed_wiring_label = QLabel(
            "Heater wiring: the silicone pad's two heater wires go to the HB screw "
            "terminal (switched by PC9) and the two thin thermistor wires go to the "
            "THB connector (GND + PC4). The pad voltage must equal the power supply "
            "voltage. A mains-voltage (230 V) pad must never be connected to HB: it "
            "needs a solid-state relay driven by HB. See COLLEGAMENTI_SKR_MINI_E3_V3.md."
        )
        self.bed_wiring_label.setWordWrap(True)
        self.bed_wiring_label.setObjectName("safetyNote")

        layout.addWidget(QLabel("Current bed temperature (deg C)"), 0, 0)
        layout.addWidget(self.current_bed_label, 0, 1)
        layout.addWidget(QLabel("Target bed temperature (deg C)"), 1, 0)
        layout.addWidget(self.target_bed_label, 1, 1)
        layout.addWidget(QLabel("Heater power (Marlin B@)"), 2, 0)
        layout.addWidget(self.bed_power_label, 2, 1)
        layout.addWidget(QLabel("Thermistor / heater check"), 3, 0)
        layout.addWidget(self.thermistor_status_label, 3, 1, 1, 2)
        layout.addWidget(QLabel("Setpoint (deg C)"), 4, 0)
        layout.addWidget(self.bed_setpoint_spin, 4, 1)
        layout.addWidget(QLabel("Safety limit (deg C)"), 5, 0)
        layout.addWidget(self.bed_safety_spin, 5, 1)
        layout.addWidget(self.set_bed_button, 6, 0)
        layout.addWidget(self.wait_bed_button, 6, 1)
        layout.addWidget(self.heater_off_button, 6, 2)
        layout.addWidget(self.bed_wiring_label, 7, 0, 1, 3)
        layout.setColumnStretch(3, 1)
        layout.setRowStretch(8, 1)

        self.set_bed_button.clicked.connect(lambda: self._set_bed_temperature(wait=False))
        self.wait_bed_button.clicked.connect(lambda: self._set_bed_temperature(wait=True))
        self.heater_off_button.clicked.connect(self._heater_off)

        return widget

    def _profile_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("profilePage")
        layout = QVBoxLayout(widget)

        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Profile name"))
        self.profile_name_edit = QLineEdit("Untitled profile")
        name_layout.addWidget(self.profile_name_edit)
        layout.addLayout(name_layout)

        self.profile_table = QTableWidget(0, 6)
        self.profile_table.setHorizontalHeaderLabels(
            [
                "Target X (mm)",
                "Speed (mm/s)",
                "Accel (mm/s^2)",
                "Dwell (s)",
                "Bed temp",
                "Wait temp",
            ]
        )
        self.profile_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.profile_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.profile_table.setSelectionMode(QTableWidget.SingleSelection)
        self.profile_table.setAlternatingRowColors(True)
        layout.addWidget(self.profile_table, stretch=1)

        button_layout = QHBoxLayout()
        self.add_segment_button = QPushButton("Add Segment")
        self.edit_segment_button = QPushButton("Edit Segment")
        self.delete_segment_button = QPushButton("Delete Segment")
        self.run_profile_button = QPushButton("Run Profile")
        self.run_profile_button.setObjectName("primaryAction")
        self.stop_profile_button = QPushButton("Stop Profile")
        self.stop_profile_button.setObjectName("warningButton")
        self.save_profile_button = QPushButton("Save JSON")
        self.load_profile_button = QPushButton("Load JSON")
        self.stop_profile_button.setEnabled(False)

        for button in (
            self.add_segment_button,
            self.edit_segment_button,
            self.delete_segment_button,
            self.run_profile_button,
            self.stop_profile_button,
            self.save_profile_button,
            self.load_profile_button,
        ):
            button_layout.addWidget(button)
        layout.addLayout(button_layout)

        self.add_segment_button.clicked.connect(self._add_segment)
        self.edit_segment_button.clicked.connect(self._edit_segment)
        self.delete_segment_button.clicked.connect(self._delete_segment)
        self.run_profile_button.clicked.connect(self._run_profile)
        self.stop_profile_button.clicked.connect(self._stop_profile)
        self.save_profile_button.clicked.connect(self._save_profile)
        self.load_profile_button.clicked.connect(self._load_profile)

        return widget

    def _calibration_tab(self) -> QWidget:
        widget = QWidget()
        widget.setObjectName("calibrationPage")
        layout = QGridLayout(widget)

        explanation = QLabel(
            "Measure the actual X stroke externally with the Keyence IL-S025 or another "
            "displacement sensor, then enter the measured travel here. The V3 app "
            "does not talk directly to the Keyence sensor."
        )
        explanation.setWordWrap(True)

        self.current_steps_spin = self._make_spin(0.001, 100000.0, 4, 80.0)
        self.commanded_distance_spin = self._make_spin(0.001, 100000.0, 4, 100.0)
        self.measured_distance_spin = self._make_spin(0.001, 100000.0, 4, 100.0)
        self.computed_steps_label = QLabel("80")
        self.computed_steps_label.setObjectName("calibrationReadout")
        self.read_steps_button = QPushButton("Read X Steps/mm from Marlin")
        self.run_calibration_move_button = QPushButton("Run +X Calibration Stroke")
        self.apply_calibration_button = QPushButton("Apply X Steps/mm")
        self.apply_calibration_button.setObjectName("primaryAction")

        layout.addWidget(explanation, 0, 0, 1, 3)
        layout.addWidget(QLabel("Current X steps/mm"), 1, 0)
        layout.addWidget(self.current_steps_spin, 1, 1)
        layout.addWidget(QLabel("Commanded travel distance (mm)"), 2, 0)
        layout.addWidget(self.commanded_distance_spin, 2, 1)
        layout.addWidget(QLabel("Measured travel distance (mm)"), 3, 0)
        layout.addWidget(self.measured_distance_spin, 3, 1)
        layout.addWidget(QLabel("Computed X steps/mm"), 4, 0)
        layout.addWidget(self.computed_steps_label, 4, 1)
        layout.addWidget(self.read_steps_button, 5, 0, 1, 2)
        layout.addWidget(self.run_calibration_move_button, 6, 0, 1, 2)
        layout.addWidget(self.apply_calibration_button, 7, 0, 1, 2)
        layout.setColumnStretch(2, 1)
        layout.setRowStretch(8, 1)

        self.current_steps_spin.valueChanged.connect(self._update_calibration)
        self.commanded_distance_spin.valueChanged.connect(self._update_calibration)
        self.measured_distance_spin.valueChanged.connect(self._update_calibration)
        self.read_steps_button.clicked.connect(self._read_x_steps)
        self.run_calibration_move_button.clicked.connect(self._run_calibration_move)
        self.apply_calibration_button.clicked.connect(self._apply_calibration)

        return widget

    @staticmethod
    def _make_spin(
        minimum: float,
        maximum: float,
        decimals: int,
        value: float,
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        spin.setValue(value)
        spin.setSingleStep(1.0)
        return spin

    def _apply_settings_to_ui(self) -> None:
        self.manual_port_edit.setText(self.settings.last_com_port)
        self.baud_combo.setCurrentText(str(self.settings.baud_rate))
        self.speed_spin.setValue(self.settings.default_speed_mm_s)
        self.accel_spin.setValue(self.settings.default_acceleration_mm_s2)
        self.travel_limit_spin.setValue(self.settings.travel_limit_mm)
        self.bed_safety_spin.setValue(self.settings.bed_safety_limit_c)
        # This hazardous override must be re-enabled explicitly for every session.
        self.allow_unhomed_check.setChecked(False)
        self.bed_setpoint_spin.setValue(self.settings.default_bed_temperature_c)
        self._update_absolute_limit()

    def _settings_from_ui(self) -> AppSettings:
        return AppSettings(
            last_com_port=self._selected_port(),
            baud_rate=int(self.baud_combo.currentText()),
            default_speed_mm_s=self.speed_spin.value(),
            default_acceleration_mm_s2=self.accel_spin.value(),
            travel_limit_mm=self.travel_limit_spin.value(),
            bed_safety_limit_c=self.bed_safety_spin.value(),
            allow_movement_before_homing=False,
            default_bed_temperature_c=self.bed_setpoint_spin.value(),
        )

    def _refresh_ports(self) -> None:
        selected = self.port_combo.currentText() or self.settings.last_com_port
        self.port_combo.clear()
        try:
            ports = MarlinSerial.available_ports()
        except Exception as exc:  # noqa: BLE001 - surface pyserial/listing issues.
            self._show_error(f"Could not list serial ports: {exc}")
            ports = []
        self.port_combo.addItems(ports)
        if selected in ports:
            self.port_combo.setCurrentText(selected)

    def _selected_port(self) -> str:
        manual = self.manual_port_edit.text().strip()
        return manual or self.port_combo.currentText().strip()

    def _connect_serial(self) -> None:
        if self.emergency_latched:
            reset_confirmed = QMessageBox.question(
                self,
                "Reset Required After Emergency Stop",
                "M112 leaves Marlin in the KILLED state. Power-cycle the controller "
                "or press its RESET button, inspect the machine, and clear the hazard "
                "before reconnecting.\n\nHas the controller been reset safely?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reset_confirmed != QMessageBox.Yes:
                return
        port = self._selected_port()
        if not port:
            self._show_error("Choose or enter a COM port first.")
            return
        try:
            self.serial_link.connect(port, int(self.baud_combo.currentText()))
        except Exception as exc:  # noqa: BLE001 - GUI should show connection failures.
            self._show_error(f"Could not connect to {port}: {exc}")
            return
        self.connection_generation += 1
        generation = self.connection_generation
        self.controller_ready = False
        self._invalidate_position("Controller connected; X must be homed.")
        self._append_log(f"Connected to {port} at {self.baud_combo.currentText()} baud.")
        self._update_connection_ui(True)
        self.status_label.setText("Initializing")
        self.statusBar().showMessage(f"Connected to {port}; waiting for Marlin startup.")
        QTimer.singleShot(2000, lambda: self._initialize_controller(generation))

    def _initialize_controller(self, generation: int) -> None:
        if generation != self.connection_generation:
            return
        if not self.serial_link.is_connected or self.controller_ready:
            return
        if self._operation_active():
            QTimer.singleShot(250, lambda: self._initialize_controller(generation))
            return
        self._run_command_sequence(
            [
                CommandSpec("M115", wait_for_ok=True, timeout=15.0),
                CommandSpec(
                    "M105",
                    wait_for_ok=True,
                    timeout=10.0,
                    capture_response=True,
                ),
            ],
            "Marlin controller ready.",
            self._controller_initialized,
            on_response=self._check_bed_reported,
            require_ready=False,
        )

    def _check_bed_reported(self, response_lines: list[str]) -> None:
        """Warn when the flashed Marlin build has no bed heater configured."""
        self.bed_available = response_reports_bed(response_lines)
        self._update_bed_controls()
        if not self.bed_available:
            self._set_thermistor_status(
                "Marlin reports no bed temperature (no B: in M105).", fault=True
            )
            self._show_error(
                "Marlin does not report a bed temperature, so this firmware has no "
                "bed heater configured (TEMP_SENSOR_BED is 0). Bed heating is "
                "disabled in the app. Rebuild Marlin with TEMP_SENSOR_BED set to the "
                "pad thermistor type (usually 1 for a 100k NTC); the SKR Mini E3 V3 "
                "pins are HEATER_BED_PIN PC9 and TEMP_BED_PIN PC4."
            )

    def _update_bed_controls(self) -> None:
        enabled = self.bed_available is not False
        self.set_bed_button.setEnabled(enabled)
        self.wait_bed_button.setEnabled(enabled)

    def _controller_initialized(self) -> None:
        self.emergency_latched = False
        self.controller_ready = True
        self.status_label.setText("Ready")
        self.temp_timer.start()
        self.statusBar().showMessage("Marlin controller ready; home X before movement.")

    def _disconnect_serial(self) -> None:
        self.temp_timer.stop()
        if self.profile_stop_event is not None:
            self.profile_stop_event.set()
        if self.serial_link.is_connected:
            try:
                if self._operation_active():
                    self.serial_link.send_immediate("M108", abort_pending=True)
                    self.serial_link.send_immediate("M410", abort_pending=True)
                self.serial_link.send_immediate(cmd_bed_set(0.0), abort_pending=True)
            except Exception as exc:  # noqa: BLE001
                self._append_log(f"Shutdown command warning: {exc}")
        self.serial_link.disconnect()
        self.connection_generation += 1
        self.controller_ready = False
        self._invalidate_position("Disconnected; X position is unknown.")
        self._update_connection_ui(False)
        self.statusBar().showMessage("Disconnected.")

    def _update_connection_ui(self, connected: bool) -> None:
        if not connected:
            self._stop_endstop_monitor()
            self.bed_available = None
            self.bed_heating_watch.reset()
            self._update_bed_controls()
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.status_label.setText("Connected" if connected else "Disconnected")
        color = "#1f7a3a" if connected else "#8a1f1f"
        self.status_label.setStyleSheet(
            f"QLabel {{ color: white; background: {color}; padding: 4px; border-radius: 3px; }}"
        )

    def _handle_serial_line(self, line: str) -> None:
        self._append_log(line)
        if line.strip().lower() == "start":
            self._handle_controller_restart()
            return
        bed = parse_bed_temp(line)
        if bed is not None:
            current, target = bed
            self.current_bed_label.setText(f"{current:.1f}")
            self.target_bed_label.setText("Unknown" if target is None else f"{target:.1f}")
            self._check_bed_health(current, target)

        bed_power = parse_bed_power(line)
        if bed_power is not None:
            self.bed_power_label.setText(
                f"{bed_power_percent(bed_power):.0f} % (B@:{bed_power})"
            )

        x_position = parse_x_position(line)
        if x_position is not None:
            self.current_x_mm = x_position
            self.current_x_label.setText(f"{x_position:.3f} mm")

        x_steps = parse_x_steps(line)
        if x_steps is not None and x_steps > 0:
            self.current_steps_spin.setValue(x_steps)

        x_min_triggered = parse_x_min_endstop(line)
        if x_min_triggered is not None:
            self._set_x_endstop_status(x_min_triggered)

    def _check_bed_health(self, current: float, target: float | None) -> None:
        fault = classify_bed_reading(current)
        if fault is not None:
            first_report = fault != self.thermistor_fault
            self.thermistor_fault = fault
            self._set_thermistor_status(fault, fault=True)
            self.bed_heating_watch.reset()
            if first_report:
                if target is not None and target > 0:
                    self._heater_off()
                self._show_error(fault)
            return
        if self.thermistor_fault is not None:
            self.thermistor_fault = None
        warning = self.bed_heating_watch.update(self._clock(), current, target)
        if warning is not None:
            self._set_thermistor_status("Bed is not heating - heater switched off.", fault=True)
            self._heater_off()
            self._show_error(warning)
            return
        if target is not None and target > 0:
            self._set_thermistor_status(
                f"Thermistor plausible; heating toward {target:g} deg C.", fault=False
            )
        else:
            self._set_thermistor_status("Thermistor plausible; heater off.", fault=False)

    def _set_thermistor_status(self, text: str, *, fault: bool) -> None:
        self.thermistor_status_label.setText(text)
        self.thermistor_status_label.setObjectName(
            "faultReadout" if fault else "endstopTriggered"
        )
        self.thermistor_status_label.style().unpolish(self.thermistor_status_label)
        self.thermistor_status_label.style().polish(self.thermistor_status_label)

    @staticmethod
    def _clock() -> float:
        return time.monotonic()

    def _set_x_endstop_status(self, triggered: bool) -> None:
        if (
            self.last_x_endstop_state is not None
            and triggered != self.last_x_endstop_state
        ):
            self.endstop_transitions += 1
            self.endstop_changes_label.setText(
                f"State changes seen: {self.endstop_transitions}"
            )
        self.last_x_endstop_state = triggered
        self.endstop_status_label.setText(
            "TRIGGERED (lever pressed)" if triggered else "OPEN (lever released)"
        )
        self.endstop_status_label.setObjectName(
            "endstopTriggered" if triggered else "endstopOpen"
        )
        self.endstop_status_label.style().unpolish(self.endstop_status_label)
        self.endstop_status_label.style().polish(self.endstop_status_label)

    def _handle_controller_restart(self) -> None:
        self.controller_ready = False
        self.temp_timer.stop()
        self.serial_link.abort_pending()
        if self.profile_stop_event is not None:
            self.profile_stop_event.set()
        self._invalidate_position("Marlin restarted; waiting for controller initialization.")
        self.status_label.setText("Restarting")
        generation = self.connection_generation
        QTimer.singleShot(1500, lambda: self._initialize_controller(generation))

    def _handle_marlin_warning(self, line: str) -> None:
        lowered = line.lower()
        if self.emergency_latched and ("kill" in lowered or "halted" in lowered):
            self.statusBar().showMessage("Marlin is KILLED; reset or power-cycle required.")
            return
        self.statusBar().showMessage(f"Marlin warning: {line}")
        hint = explain_marlin_message(line)
        message = line if hint is None else f"{line}\n\n{hint}"
        QMessageBox.warning(self, "Marlin Warning", message)

    def _handle_serial_disconnect(self, message: str) -> None:
        self._append_log(message)
        self.temp_timer.stop()
        self.connection_generation += 1
        self.controller_ready = False
        self._invalidate_position("Serial connection lost; X position is unknown.")
        self._update_connection_ui(False)
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, "Serial Connection", message)

    def _append_log(self, line: str) -> None:
        self.log_edit.append(line)

    def _show_error(self, message: str) -> None:
        self.statusBar().showMessage(message)
        QMessageBox.warning(self, APP_DISPLAY_NAME, message)

    def _ensure_connected(self, *, require_ready: bool = True) -> bool:
        if not self.serial_link.is_connected:
            self._show_error("Connect to the SKR Mini E3 V3 first.")
            return False
        if require_ready and not self.controller_ready:
            self._show_error("Wait for Marlin initialization to complete.")
            return False
        return True

    def _operation_active(self) -> bool:
        return bool(self.command_jobs or self.profile_thread is not None)

    def _invalidate_position(self, status_message: str | None = None) -> None:
        self.homed = False
        self.current_x_mm = None
        if hasattr(self, "current_x_label"):
            self.current_x_label.setText("Unknown - home X")
        if status_message:
            self.statusBar().showMessage(status_message)

    def _run_command_sequence(
        self,
        commands: list[CommandSpec],
        success_message: str,
        on_success: Callable[[], None] | None = None,
        *,
        on_response: Callable[[list[str]], None] | None = None,
        require_ready: bool = True,
        invalidate_position_on_failure: bool = False,
    ) -> None:
        if not self._ensure_connected(require_ready=require_ready):
            return
        if self._operation_active():
            self._show_error("Another machine operation is already running.")
            return

        thread = QThread(self)
        worker = SerialCommandWorker(self.serial_link, commands, success_message)
        worker.moveToThread(thread)
        self.command_jobs.append((thread, worker))

        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda ok, message, response_lines, callback=on_success, response_callback=on_response, invalidate=invalidate_position_on_failure: self._command_finished(
                ok,
                message,
                response_lines,
                callback,
                response_callback,
                invalidate,
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda t=thread, w=worker: self._remove_command_job(t, w))
        thread.start()

    def _remove_command_job(self, thread: QThread, worker: SerialCommandWorker) -> None:
        try:
            self.command_jobs.remove((thread, worker))
        except ValueError:
            pass

    def _command_finished(
        self,
        ok: bool,
        message: str,
        response_lines: list[str],
        on_success: Callable[[], None] | None,
        on_response: Callable[[list[str]], None] | None,
        invalidate_position_on_failure: bool,
    ) -> None:
        if ok:
            self.statusBar().showMessage(message)
            if callable(on_response):
                on_response(response_lines)
            if callable(on_success):
                on_success()
        else:
            if invalidate_position_on_failure:
                self._invalidate_position(
                    "Operation failed; re-home X before further movement."
                )
            self._show_error(message)

    def _home_x(self) -> None:
        if not self._ensure_connected():
            return
        if self._operation_active():
            self._show_error("Another machine operation is already running.")
            return

        estimated_distance = self.home_distance_spin.value()
        try:
            fast_distance = staged_home_pretravel(
                estimated_distance,
                STAGED_HOME_MARGIN_MM,
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return
        if estimated_distance > self.travel_limit_spin.value():
            self._show_error(
                "Estimated home distance cannot exceed the software travel limit."
            )
            return

        if fast_distance > 0:
            result = QMessageBox.question(
                self,
                "Confirm Staged Homing",
                f"Estimated distance to X-min: {estimated_distance:g} mm.\n"
                f"Fast pre-approach: {fast_distance:g} mm toward home at "
                f"{STAGED_HOME_FAST_SPEED_MM_S:g} mm/s.\n"
                f"Reserved slow zone: {STAGED_HOME_MARGIN_MM:g} mm.\n\n"
                "M120 will keep the X-min endstop active during the pre-approach. "
                "Confirm that the estimate is conservative and the physical power "
                "cutoff is accessible.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if result != QMessageBox.Yes:
                return

        # Do not retain a position estimate that may be stale on the next attempt.
        self.home_distance_spin.setValue(0.0)
        self._invalidate_position("Homing X.")

        def mark_homed() -> None:
            self.homed = True
            if self.current_x_mm is None:
                self.current_x_mm = 0.0
                self.current_x_label.setText("0.000 mm")

        commands = [
            CommandSpec(
                "M119",
                wait_for_ok=True,
                timeout=10.0,
                capture_response=True,
                response_validator=validate_x_min_open_response,
            )
        ]
        if fast_distance > 0:
            commands.extend(
                [
                    CommandSpec("M120", wait_for_ok=True, timeout=10.0),
                    CommandSpec("G91", wait_for_ok=True, timeout=10.0),
                    CommandSpec(
                        cmd_move_x_relative(
                            -fast_distance,
                            STAGED_HOME_FAST_SPEED_MM_S,
                        ),
                        wait_for_ok=True,
                        timeout=10.0,
                    ),
                    CommandSpec("M400", wait_for_ok=True, timeout=180.0),
                    CommandSpec("G90", wait_for_ok=True, timeout=10.0),
                    CommandSpec(
                        "M119",
                        wait_for_ok=True,
                        timeout=10.0,
                        capture_response=True,
                        response_validator=validate_x_min_open_response,
                    ),
                ]
            )
        commands.extend(
            [
                CommandSpec("G28 X", wait_for_ok=True, timeout=180.0),
                CommandSpec("G90", wait_for_ok=True, timeout=10.0),
                CommandSpec("M114", wait_for_ok=True, timeout=10.0),
            ]
        )

        self._run_command_sequence(
            commands,
            "X homing complete. +X must move away from the X-min switch.",
            mark_homed,
            invalidate_position_on_failure=True,
        )

    def _read_position(self) -> None:
        self._run_command_sequence(
            [CommandSpec("M114", wait_for_ok=True, timeout=10.0)],
            "Position read.",
        )

    def _check_x_endstop(self) -> None:
        if not self._ensure_connected():
            return
        if self._operation_active():
            self._show_error("Another machine operation is already running.")
            return
        self.endstop_status_label.setText("Waiting for M119...")
        self.endstop_status_label.setObjectName("endstopUnknown")
        self.endstop_status_label.style().unpolish(self.endstop_status_label)
        self.endstop_status_label.style().polish(self.endstop_status_label)

        def verify_response(response_lines: list[str]) -> None:
            state = parse_x_min_endstop_response(response_lines)
            if state is not None:
                self._set_x_endstop_status(state)
                return
            self.endstop_status_label.setText("No X-min status in M119 response")
            self._show_error(
                "Marlin replied to M119 but did not report x_min. "
                "Check USE_XMIN_PLUG and the firmware endstop configuration."
            )

        self._run_command_sequence(
            [
                CommandSpec(
                    "M119",
                    wait_for_ok=True,
                    timeout=10.0,
                    capture_response=True,
                )
            ],
            "X-min endstop state read.",
            on_response=verify_response,
        )

    def _toggle_endstop_monitor(self, enabled: bool) -> None:
        if not enabled:
            self.endstop_timer.stop()
            return
        if not self.serial_link.is_connected or not self.controller_ready:
            self._stop_endstop_monitor()
            self._show_error("Connect and wait for Ready before starting the monitor.")
            return
        self.endstop_transitions = 0
        self.last_x_endstop_state = None
        self.endstop_changes_label.setText("State changes seen: 0")
        self.endstop_timer.start()
        self.statusBar().showMessage(
            "Live endstop monitor running: press and release the X-min lever."
        )

    def _stop_endstop_monitor(self) -> None:
        self.endstop_timer.stop()
        if hasattr(self, "endstop_monitor_check"):
            self.endstop_monitor_check.blockSignals(True)
            self.endstop_monitor_check.setChecked(False)
            self.endstop_monitor_check.blockSignals(False)

    def _poll_endstop(self) -> None:
        if not self.serial_link.is_connected or not self.controller_ready:
            return
        # Never interleave with homing, motion, or profile command sequences.
        if self._operation_active() or self.endstop_poll_active:
            return
        self.endstop_poll_active = True
        threading.Thread(
            target=self._endstop_poll_worker,
            name="MarlinEndstopPoll",
            daemon=True,
        ).start()

    def _endstop_poll_worker(self) -> None:
        try:
            # The reply is parsed by _handle_serial_line, which updates the label.
            self.serial_link.send_command(
                "M119",
                wait_for_ok=True,
                timeout=3.0,
                block=False,
            )
        except Exception as exc:  # noqa: BLE001
            if self.serial_link.is_connected:
                self.bridge.endstop_poll_failed.emit(str(exc))
        finally:
            self.endstop_poll_active = False

    def _endstop_poll_failed(self, message: str) -> None:
        self._stop_endstop_monitor()
        self._show_error(f"Endstop monitor stopped: {message}")

    def _jog_x(self, direction: float) -> None:
        if not self._absolute_motion_allowed():
            return
        distance = self.jog_distance_spin.value() * direction
        if self.homed and self.current_x_mm is None:
            self._show_error("Read or home X before jogging so travel limits can be checked.")
            return
        if self.current_x_mm is not None and self.homed:
            target = self.current_x_mm + distance
            if not self._target_in_travel(target):
                return

        feed = format_gcode_number(feedrate_mm_min(self.speed_spin.value()))
        delta = format_gcode_number(distance)
        commands = [
            CommandSpec(cmd_accel(self.accel_spin.value()), wait_for_ok=True),
            CommandSpec("G91", wait_for_ok=True),
            CommandSpec(f"G1 X{delta} F{feed}", wait_for_ok=True),
            CommandSpec("M400", wait_for_ok=True, timeout=3600.0),
            CommandSpec("G90", wait_for_ok=True),
        ]

        def update_position() -> None:
            if self.current_x_mm is not None:
                self.current_x_mm += distance
                self.current_x_label.setText(f"{self.current_x_mm:.3f} mm")

        self._run_command_sequence(
            commands,
            "Jog complete.",
            update_position,
            invalidate_position_on_failure=True,
        )

    def _move_absolute_x(self) -> None:
        if not self._absolute_motion_allowed():
            return
        target = self.absolute_x_spin.value()
        if not self._target_in_travel(target):
            return
        commands = [
            CommandSpec("G90", wait_for_ok=True),
            CommandSpec(cmd_accel(self.accel_spin.value()), wait_for_ok=True),
            CommandSpec(cmd_move_x(target, self.speed_spin.value()), wait_for_ok=True),
            CommandSpec("M400", wait_for_ok=True, timeout=3600.0),
        ]

        def update_position() -> None:
            self.current_x_mm = target
            self.current_x_label.setText(f"{target:.3f} mm")

        self._run_command_sequence(
            commands,
            "Move complete.",
            update_position,
            invalidate_position_on_failure=True,
        )

    def _absolute_motion_allowed(self) -> bool:
        if self.homed or self.allow_unhomed_check.isChecked():
            return True
        self._show_error("Home X first, or enable movement before homing.")
        return False

    def _confirm_unhomed_movement(self, enabled: bool) -> None:
        if not enabled:
            return
        result = QMessageBox.warning(
            self,
            "Movement Without Homing",
            "Without homing, the software cannot guarantee the X travel limits. "
            "Enable this override for the current session?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            self.allow_unhomed_check.blockSignals(True)
            self.allow_unhomed_check.setChecked(False)
            self.allow_unhomed_check.blockSignals(False)

    def _target_in_travel(self, target: float) -> bool:
        limit = self.travel_limit_spin.value()
        if 0 <= target <= limit:
            return True
        self._show_error(f"Target X must be between 0 and {limit:g} mm.")
        return False

    def _update_absolute_limit(self) -> None:
        self.absolute_x_spin.setMaximum(self.travel_limit_spin.value())
        self.home_distance_spin.setMaximum(self.travel_limit_spin.value())

    def _quick_stop(self) -> None:
        if not self._ensure_connected(require_ready=False):
            return
        if self.profile_stop_event is not None:
            self.profile_stop_event.set()
        try:
            self.serial_link.send_immediate("M410", abort_pending=True)
            self.serial_link.send_immediate("G90")
            self._invalidate_position("Quick stop sent; re-home X before further movement.")
            self.statusBar().showMessage("Quick stop sent.")
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def _emergency_stop(self) -> None:
        if not self._ensure_connected(require_ready=False):
            return
        result = QMessageBox.question(
            self,
            "Emergency Stop",
            "Send M112 emergency stop to Marlin?\n\n"
            "This puts the controller in the KILLED state. Motion and heaters stop, "
            "but the controller must then be reset or power-cycled before it can be "
            "used again.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return
        try:
            self.emergency_latched = True
            self.serial_link.send_immediate("M112", abort_pending=True)
            self.temp_timer.stop()
            self.serial_link.disconnect()
            self.connection_generation += 1
            self.controller_ready = False
            self._invalidate_position(
                "Emergency stop sent; reset or power-cycle the controller."
            )
            self._update_connection_ui(False)
            self.status_label.setText("E-STOP: RESET BOARD")
            self.status_label.setStyleSheet(
                "QLabel { color: white; background: #8a1f1f; "
                "padding: 4px; border-radius: 3px; }"
            )
            self.statusBar().showMessage(
                "Marlin KILLED by M112; reset or power-cycle required."
            )
            QMessageBox.critical(
                self,
                "Emergency Stop Active",
                "Marlin is now in the KILLED state. This is not a software freeze.\n\n"
                "Remove power if danger remains. Before reconnecting, inspect the "
                "machine and reset or power-cycle the SKR Mini E3 V3.",
            )
        except Exception as exc:  # noqa: BLE001
            self.emergency_latched = False
            self._show_error(str(exc))

    def _motors_off(self) -> None:
        self._run_command_sequence(
            [CommandSpec("M18", wait_for_ok=True)],
            "Motors off; re-home X before movement.",
            lambda: self._invalidate_position("Motors off; X position is unknown."),
        )

    def _confirm_temperature(self, temp_c: float) -> bool:
        limit = self.bed_safety_spin.value()
        if temp_c <= limit:
            return True
        result = QMessageBox.warning(
            self,
            "Bed Temperature Safety Limit",
            f"{temp_c:g} deg C is above the configured safety limit of {limit:g} deg C. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return result == QMessageBox.Yes

    def _set_bed_temperature(self, wait: bool) -> None:
        temp = self.bed_setpoint_spin.value()
        if not self._confirm_temperature(temp):
            return
        command = cmd_bed_wait(temp) if wait else cmd_bed_set(temp)
        self._run_command_sequence(
            [
                CommandSpec(
                    command,
                    wait_for_ok=True,
                    timeout=1800.0 if wait else 10.0,
                )
            ],
            "Bed temperature command complete." if wait else "Bed temperature set.",
        )

    def _heater_off(self) -> None:
        if not self._ensure_connected(require_ready=False):
            return
        if self.profile_stop_event is not None:
            self.profile_stop_event.set()
        try:
            if self._operation_active():
                self.serial_link.send_immediate("M108", abort_pending=True)
                self.serial_link.send_immediate("M410", abort_pending=True)
                self._invalidate_position(
                    "Active operation stopped; re-home X before movement."
                )
            self.serial_link.send_immediate(cmd_bed_set(0.0), abort_pending=True)
            self.statusBar().showMessage("Heater off command sent.")
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def _poll_temperature(self) -> None:
        if not self.serial_link.is_connected or not self.controller_ready:
            return
        if self.temperature_poll_active:
            return
        self.temperature_poll_active = True
        threading.Thread(
            target=self._temperature_poll_worker,
            name="MarlinTemperaturePoll",
            daemon=True,
        ).start()

    def _temperature_poll_worker(self) -> None:
        try:
            self.serial_link.send_command(
                "M105",
                wait_for_ok=True,
                timeout=3.0,
                block=False,
            )
        except Exception as exc:  # noqa: BLE001
            if self.serial_link.is_connected:
                self.bridge.temperature_poll_failed.emit(str(exc))
        finally:
            self.temperature_poll_active = False

    def _temperature_poll_failed(self, message: str) -> None:
        self.temp_timer.stop()
        self._show_error(f"Temperature polling stopped: {message}")

    def _add_segment(self) -> None:
        dialog = SegmentDialog(self, None, self._settings_from_ui())
        if dialog.exec() == QDialog.Accepted:
            self.profile_segments.append(dialog.segment())
            self._update_profile_table()

    def _edit_segment(self) -> None:
        row = self._selected_profile_row()
        if row is None:
            self._show_error("Select a segment to edit.")
            return
        dialog = SegmentDialog(self, self.profile_segments[row], self._settings_from_ui())
        if dialog.exec() == QDialog.Accepted:
            self.profile_segments[row] = dialog.segment()
            self._update_profile_table()
            self.profile_table.selectRow(row)

    def _delete_segment(self) -> None:
        row = self._selected_profile_row()
        if row is None:
            self._show_error("Select a segment to delete.")
            return
        del self.profile_segments[row]
        self._update_profile_table()

    def _selected_profile_row(self) -> int | None:
        rows = self.profile_table.selectionModel().selectedRows()
        if not rows:
            return None
        return rows[0].row()

    def _update_profile_table(self) -> None:
        self.profile_table.setRowCount(len(self.profile_segments))
        for row, segment in enumerate(self.profile_segments):
            values = [
                f"{segment.target_x_mm:g}",
                f"{segment.speed_mm_s:g}",
                f"{segment.acceleration_mm_s2:g}",
                f"{segment.dwell_s:g}",
                "-" if segment.bed_temp_c is None else f"{segment.bed_temp_c:g}",
                "Yes" if segment.wait_for_temperature else "No",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.profile_table.setItem(row, column, item)

    def _profile_from_ui(self) -> CoatingProfile:
        return CoatingProfile(
            name=self.profile_name_edit.text().strip() or "Untitled profile",
            segments=list(self.profile_segments),
        )

    def _save_profile(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Profile",
            "coating_profile.json",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            self._profile_from_ui().save(path)
            self.statusBar().showMessage(f"Profile saved to {path}.")
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"Could not save profile: {exc}")

    def _load_profile(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Load Profile",
            "",
            "JSON files (*.json)",
        )
        if not path:
            return
        try:
            profile = CoatingProfile.load(path)
            self.profile_name_edit.setText(profile.name)
            self.profile_segments = profile.segments
            self._update_profile_table()
            self.statusBar().showMessage(f"Profile loaded from {path}.")
        except Exception as exc:  # noqa: BLE001
            self._show_error(f"Could not load profile: {exc}")

    def _run_profile(self) -> None:
        if not self._ensure_connected():
            return
        if self._operation_active():
            self._show_error("Another machine operation is already running.")
            return
        if not self._absolute_motion_allowed():
            return

        profile = self._profile_from_ui()
        try:
            profile.validate(self.travel_limit_spin.value())
        except ValueError as exc:
            self._show_error(str(exc))
            return

        if self.bed_available is False and any(
            segment.bed_temp_c is not None for segment in profile.segments
        ):
            self._show_error(
                "This profile sets bed temperatures, but the connected Marlin build "
                "has no bed heater configured."
            )
            return

        hot_segments = [
            segment.bed_temp_c
            for segment in profile.segments
            if segment.bed_temp_c is not None
            and segment.bed_temp_c > self.bed_safety_spin.value()
        ]
        if hot_segments and not self._confirm_temperature(max(hot_segments)):
            return

        self.profile_stop_event = threading.Event()
        self.profile_thread = QThread(self)
        self.profile_worker = ProfileWorker(
            self.serial_link,
            profile,
            self.travel_limit_spin.value(),
            self.profile_stop_event,
        )
        self.profile_worker.moveToThread(self.profile_thread)
        self.profile_thread.started.connect(self.profile_worker.run)
        self.profile_worker.progress.connect(self._profile_progress)
        self.profile_worker.position_changed.connect(self._profile_position_changed)
        self.profile_worker.finished.connect(self._profile_finished)
        self.profile_worker.finished.connect(self.profile_thread.quit)
        self.profile_worker.finished.connect(self.profile_worker.deleteLater)
        self.profile_thread.finished.connect(self._profile_thread_finished)
        self.profile_thread.finished.connect(self.profile_thread.deleteLater)
        self.profile_thread.start()

        self.run_profile_button.setEnabled(False)
        self.stop_profile_button.setEnabled(True)
        self.statusBar().showMessage("Profile running.")

    def _stop_profile(self) -> None:
        if self.profile_stop_event is not None:
            self.profile_stop_event.set()
        if self.serial_link.is_connected:
            try:
                self.serial_link.send_immediate("M108", abort_pending=True)
                self.serial_link.send_immediate("M410", abort_pending=True)
                self.serial_link.send_immediate(cmd_bed_set(0.0), abort_pending=True)
                self._invalidate_position(
                    "Profile stopped; re-home X before further movement."
                )
            except Exception as exc:  # noqa: BLE001
                self._show_error(str(exc))
                return
        self.statusBar().showMessage("Stop requested.")

    def _profile_progress(self, index: int, message: str) -> None:
        if 0 <= index < self.profile_table.rowCount():
            self.profile_table.selectRow(index)
        self.statusBar().showMessage(message)

    def _profile_position_changed(self, x_mm: float) -> None:
        self.current_x_mm = x_mm
        self.current_x_label.setText(f"{x_mm:.3f} mm")

    def _profile_finished(self, ok: bool, message: str) -> None:
        self.stop_profile_button.setEnabled(False)
        if ok:
            self.statusBar().showMessage(message)
        elif self.profile_stop_event is not None and self.profile_stop_event.is_set():
            self.statusBar().showMessage(message)
        else:
            self._invalidate_position(
                "Profile failed; re-home X before further movement."
            )
            self._show_error(message)

    def _profile_thread_finished(self) -> None:
        self.run_profile_button.setEnabled(True)
        self.profile_worker = None
        self.profile_thread = None
        self.profile_stop_event = None

    def _update_calibration(self) -> None:
        try:
            value = calculate_new_steps(
                self.current_steps_spin.value(),
                self.commanded_distance_spin.value(),
                self.measured_distance_spin.value(),
            )
        except ValueError:
            self.computed_steps_label.setText("Invalid")
            return
        self.computed_steps_label.setText(f"{value:.4f}")

    def _read_x_steps(self) -> None:
        self._run_command_sequence(
            [CommandSpec("M503", wait_for_ok=True, timeout=15.0)],
            "Marlin settings read.",
        )

    def _run_calibration_move(self) -> None:
        if not self.homed:
            self._show_error("Home X before running a calibration stroke.")
            return
        if self.current_x_mm is None:
            self._show_error("Read the current X position before calibration.")
            return
        distance = self.commanded_distance_spin.value()
        target = self.current_x_mm + distance
        if not self._target_in_travel(target):
            return

        def update_position() -> None:
            self.current_x_mm = target
            self.current_x_label.setText(f"{target:.3f} mm")

        self._run_command_sequence(
            [
                CommandSpec("G90", wait_for_ok=True),
                CommandSpec(cmd_accel(self.accel_spin.value()), wait_for_ok=True),
                CommandSpec(
                    cmd_move_x(target, self.speed_spin.value()),
                    wait_for_ok=True,
                ),
                CommandSpec("M400", wait_for_ok=True, timeout=3600.0),
                CommandSpec("M114", wait_for_ok=True),
            ],
            f"Calibration stroke complete: commanded +{distance:g} mm.",
            update_position,
            invalidate_position_on_failure=True,
        )

    def _apply_calibration(self) -> None:
        try:
            value = calculate_new_steps(
                self.current_steps_spin.value(),
                self.commanded_distance_spin.value(),
                self.measured_distance_spin.value(),
            )
        except ValueError as exc:
            self._show_error(str(exc))
            return
        result = QMessageBox.question(
            self,
            "Apply X Calibration",
            f"Change X steps/mm from {self.current_steps_spin.value():.4f} "
            f"to {value:.4f} and save it to Marlin EEPROM?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if result != QMessageBox.Yes:
            return

        def calibration_applied() -> None:
            self.current_steps_spin.setValue(value)
            self._invalidate_position(
                "Calibration saved; home X again before further movement."
            )

        self._run_command_sequence(
            [
                CommandSpec(cmd_steps_x(value), wait_for_ok=True),
                CommandSpec("M500", wait_for_ok=True),
            ],
            "Calibration saved to Marlin EEPROM.",
            calibration_applied,
        )

    def closeEvent(self, event) -> None:  # type: ignore[override]
        if self.profile_thread is not None:
            result = QMessageBox.question(
                self,
                "Profile Running",
                "A profile is still running. Stop it and close the app?",
            )
            if result != QMessageBox.Yes:
                event.ignore()
                return
            self._stop_profile()

        self.temp_timer.stop()
        self.endstop_timer.stop()
        if self.serial_link.is_connected:
            try:
                if self._operation_active():
                    self.serial_link.send_immediate("M108", abort_pending=True)
                    self.serial_link.send_immediate("M410", abort_pending=True)
                self.serial_link.send_immediate(cmd_bed_set(0.0), abort_pending=True)
            except Exception:
                pass
            self.serial_link.disconnect()

        active_threads = [thread for thread, _worker in self.command_jobs]
        if self.profile_thread is not None:
            active_threads.append(self.profile_thread)
        for thread in active_threads:
            if thread.isRunning():
                thread.quit()
                thread.wait(1500)

        try:
            self.settings_manager.save(self._settings_from_ui())
        except Exception:
            pass

        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
