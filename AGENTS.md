# Repository Instructions for Coding Agents

This repository contains a Windows desktop application for controlling a laboratory doctor blade coater through Marlin G-code on a BIGTREETECH SKR Mini E3 V3. Treat the software as laboratory equipment control code, not as a generic GUI app.

## Safety and Scope

- Keep hardware safety checks conservative. Prefer blocking or confirming risky actions over assuming the operator intended them.
- Do not loosen temperature limits, travel-limit checks, homing gates, emergency-stop behavior, or heater shutdown behavior unless explicitly requested.
- Avoid adding advanced features unless the user explicitly asks for them. Examples to avoid by default include direct Keyence Ethernet integration, camera integration, database logging, report generation, unattended automation, and multi-axis machine logic.
- Preserve the first-version machine assumptions unless told otherwise: one X axis, bed heater through Marlin, no Y axis, no Z axis, and no extruder in application logic.

## Architecture

- Keep GUI code separate from serial communication and pure G-code/calculation logic.
- Put PySide6 UI behavior in `main.py` or future UI-focused modules.
- Keep Marlin USB serial behavior in `marlin_serial.py` or similarly named serial modules.
- Keep pure G-code command generation and parsing in `gcode.py`.
- Keep recipe/profile data modeling and JSON behavior in `profile_model.py`.
- Keep calibration math in `calibration.py`.
- Keep settings persistence in `settings_manager.py`.
- Prefer pure functions for command generation, parsing, validation, and calculation so they can be tested without hardware.

## Tests

- Never require real hardware for unit tests.
- Tests must run without an SKR board, USB serial device, heater, thermistor, endstop, motor driver, or Keyence sensor attached.
- Use mocks, fakes, or pure-function tests for serial and G-code behavior.
- Run `pytest` before packaging or changing build artifacts.
- Add or update tests when changing G-code helpers, parsing logic, calibration math, profile serialization, or safety validation.

## Windows Compatibility

- Preserve Windows 11 compatibility.
- Keep COM-port workflows compatible with Windows serial naming such as `COM3`.
- Keep packaging compatible with PyInstaller and `build_exe.bat`.
- Avoid POSIX-only shell commands, paths, or assumptions in project scripts.
- Do not require WSL, Linux tools, or administrator-only setup for normal app use.

## G-code Documentation

- Document every new G-code command used by the application.
- When adding a command, update the README or another clearly named project document with:
  - the command string or pattern;
  - what action it performs;
  - whether it can block;
  - any safety implications;
  - where in the application it is used.
- Prefer adding command-generation helpers in `gcode.py` for new parameterized commands.

## Packaging

- Before packaging, run:

```bat
python -m pytest
```

- Then build with the project script:

```bat
build_exe.bat
```

- The expected executable path is:

```text
dist\DoctorBladeControllerV306.exe
```
