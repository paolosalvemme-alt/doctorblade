"""Thread-safe Marlin serial communication."""

from __future__ import annotations

from contextlib import contextmanager
from queue import Empty, Queue
import threading
import time
from typing import Callable, Iterator

import serial
from serial.tools import list_ports


LineCallback = Callable[[str], None]


class MarlinSerial:
    """Small pyserial wrapper with a background reader and command wait support."""

    def __init__(self) -> None:
        self._serial: serial.Serial | None = None
        self._reader_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._abort_event = threading.Event()
        self._write_lock = threading.Lock()
        self._command_lock = threading.RLock()
        self._session_state = threading.local()
        self._responses: Queue[str] = Queue()
        self.line_callback: LineCallback | None = None
        self.warning_callback: LineCallback | None = None
        self.disconnect_callback: LineCallback | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._serial and self._serial.is_open)

    @staticmethod
    def available_ports() -> list[str]:
        return [port.device for port in list_ports.comports()]

    def connect(self, port: str, baudrate: int) -> None:
        if self.is_connected:
            return
        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0.2,
            write_timeout=2.0,
        )
        self._stop_event.clear()
        self._abort_event.clear()
        self._clear_response_queue()
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name="MarlinSerialReader",
            daemon=True,
        )
        self._reader_thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()
        self.abort_pending()
        serial_port = self._serial
        if serial_port and serial_port.is_open:
            try:
                serial_port.close()
            except serial.SerialException:
                pass
        if (
            self._reader_thread
            and self._reader_thread.is_alive()
            and threading.current_thread() is not self._reader_thread
        ):
            self._reader_thread.join(timeout=1.0)
        self._reader_thread = None
        self._serial = None
        self._clear_response_queue()

    @contextmanager
    def command_session(self, *, block: bool = True) -> Iterator[bool]:
        """Keep a multi-command operation atomic with respect to other operations."""
        acquired = self._command_lock.acquire(blocking=block)
        depth = getattr(self._session_state, "depth", 0)
        try:
            if acquired:
                if depth == 0:
                    self._abort_event.clear()
                self._session_state.depth = depth + 1
            yield acquired
        finally:
            if acquired:
                self._session_state.depth = depth
                self._command_lock.release()

    def abort_pending(self) -> None:
        """Abort any command currently waiting for a Marlin response."""
        self._abort_event.set()

    def send_command(
        self,
        command: str,
        *,
        wait_for_ok: bool = False,
        timeout: float = 10.0,
        block: bool = True,
    ) -> bool:
        """Send a regular command, optionally waiting for Marlin's ok response."""
        acquired, _response_lines = self._execute_command(
            command,
            wait_for_ok=wait_for_ok,
            timeout=timeout,
            block=block,
        )
        return acquired

    def query_command(
        self,
        command: str,
        *,
        timeout: float = 10.0,
        block: bool = True,
    ) -> list[str]:
        """Send a command and return every response line through Marlin's ok."""
        _acquired, response_lines = self._execute_command(
            command,
            wait_for_ok=True,
            timeout=timeout,
            block=block,
        )
        return response_lines

    def _execute_command(
        self,
        command: str,
        *,
        wait_for_ok: bool,
        timeout: float,
        block: bool,
    ) -> tuple[bool, list[str]]:
        if not self.is_connected:
            raise RuntimeError("Serial port is not connected.")

        acquired = self._command_lock.acquire(blocking=block)
        if not acquired:
            return False, []
        response_lines: list[str] = []
        try:
            in_session = getattr(self._session_state, "depth", 0) > 0
            if not in_session:
                self._abort_event.clear()
            if self._abort_event.is_set():
                raise RuntimeError("Command cancelled by a stop or disconnect request.")
            if wait_for_ok:
                self._clear_response_queue()
            if self._abort_event.is_set():
                raise RuntimeError("Command cancelled by a stop or disconnect request.")
            self._write_command(command)
            if wait_for_ok:
                response_lines = self._wait_for_ok(timeout)
        finally:
            self._command_lock.release()
        return True, response_lines

    def send_immediate(self, command: str, *, abort_pending: bool = False) -> None:
        """Send a command without waiting behind the normal command lock."""
        if not self.is_connected:
            raise RuntimeError("Serial port is not connected.")
        if abort_pending:
            self.abort_pending()
        self._write_command(command)

    def _write_command(self, command: str) -> None:
        serial_port = self._serial
        if serial_port is None or not serial_port.is_open:
            raise RuntimeError("Serial port is not connected.")
        clean = command.strip()
        if not clean:
            return
        if "\r" in clean or "\n" in clean:
            raise ValueError("A serial command must contain exactly one G-code line.")
        payload = f"{clean}\n".encode("ascii", errors="replace")
        with self._write_lock:
            serial_port.write(payload)
            serial_port.flush()
        if self.line_callback:
            self.line_callback(f"> {clean}")

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            serial_port = self._serial
            if serial_port is None or not serial_port.is_open:
                break
            try:
                raw = serial_port.readline()
            except (serial.SerialException, OSError) as exc:
                if self._stop_event.is_set():
                    break
                try:
                    serial_port.close()
                except (serial.SerialException, OSError):
                    pass
                self._serial = None
                self.abort_pending()
                self._emit_disconnect(f"Serial connection lost: {exc}")
                break
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            self._responses.put(line)
            self._emit_line(line)
            self._check_warning(line)

    def _wait_for_ok(self, timeout: float) -> list[str]:
        deadline = time.monotonic() + timeout
        response_lines: list[str] = []
        while time.monotonic() < deadline:
            if self._abort_event.is_set():
                raise RuntimeError("Command cancelled by a stop or disconnect request.")
            if not self.is_connected:
                raise ConnectionError("Serial connection was closed while waiting for Marlin.")
            remaining = max(0.05, deadline - time.monotonic())
            try:
                line = self._responses.get(timeout=min(0.25, remaining))
            except Empty:
                continue
            if self._abort_event.is_set():
                raise RuntimeError("Command cancelled by a stop or disconnect request.")
            response_lines.append(line)
            lowered = line.lower()
            if lowered.startswith("ok") or lowered == "ok":
                return response_lines
            if (
                "error" in lowered
                or "kill" in lowered
                or "thermal runaway" in lowered
            ):
                raise RuntimeError(f"Marlin reported: {line}")
        raise TimeoutError(f"Timed out waiting for ok after {timeout:g} seconds.")

    def _clear_response_queue(self) -> None:
        while True:
            try:
                self._responses.get_nowait()
            except Empty:
                return

    def _emit_line(self, line: str) -> None:
        if self.line_callback:
            self.line_callback(line)

    def _emit_disconnect(self, message: str) -> None:
        if self.disconnect_callback:
            self.disconnect_callback(message)

    def _check_warning(self, line: str) -> None:
        lowered = line.lower()
        if "error" in lowered or "kill" in lowered or "thermal runaway" in lowered:
            if self.warning_callback:
                self.warning_callback(line)
