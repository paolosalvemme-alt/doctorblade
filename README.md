# Doctor Blade Controller V3.0.6

Safety-focused Windows desktop application for controlling a laboratory doctor
blade coater driven by a BIGTREETECH SKR Mini E3 V3 running Marlin firmware.

Version 3.0.6 adds commissioning diagnostics for the two parts that most often
fail on a new build: a live X-min endstop monitor and bed heater checks
(heater power, thermistor plausibility, a heating watch that switches the
heater off if the bed does not warm up, and detection of firmware built without
a bed heater). Wiring for the SKR Mini E3 V3 endstop, silicone pad heater and
thermistor is described in Italian in
[`COLLEGAMENTI_SKR_MINI_E3_V3.md`](COLLEGAMENTI_SKR_MINI_E3_V3.md).

Version 3.0.5 adds optional staged X homing from an operator-entered approximate
distance. It keeps a 40 mm slow zone, enables the mechanical X-min endstop with
`M120` during the guarded fast pre-approach, and then delegates the final
5 mm/s homing to Marlin firmware V1.0.2. Version 3.0.4 validates `M119`
automatically before every X homing command and shows the latched Marlin
`KILLED` state after `M112`, including the required controller reset procedure.
Version 3.0.3 fixed a cross-thread race that could
show a false missing-`x_min` warning even though Marlin had returned the
endstop state. Version 3.0.2 added
the integrated `M119` X-min endstop diagnostic. Version 3.0.1 introduced the
explicit X-axis direction convention and commissioning guidance.
Version 3.0.0 introduced atomic serial operations, cancellation-safe command
sequences, guarded homing state, Marlin restart detection, reliable temperature
polling, guided calibration, GUI safety tests, and fail-safe profile shutdown.

This version focuses on the essential workflow:

- USB serial connection to Marlin
- X-axis homing, jogging, absolute moves, quick stop, emergency stop, and motors off
- Heated bed control through Marlin bed G-code
- Temperature polling and parsing from `M105`
- Simple sequential coating profiles stored as JSON
- Manual/assisted X stroke calibration using an external displacement measurement
- Windows executable generation with PyInstaller

Advanced features such as direct Keyence Ethernet integration, camera integration, database logging, and report generation are intentionally not included yet.

## Hardware Assumptions

- Controller board: BIGTREETECH SKR Mini E3 V3
- Firmware: Marlin
- PC connection: USB serial
- Motion: one X linear stage driven by a NEMA17 stepper through the onboard TMC2209 driver
- Endstop: mechanical X-min limit switch
- Heater: 12 V silicone heated bed controlled through Marlin bed heater output
- Bed thermistor connected to the SKR bed thermistor input
- No Y axis, no Z axis, and no extruder are used by the application logic
- Target OS: Windows 11

## Critical X-Axis Convention

With the home switch installed at the beginning of travel and defined as
`X=0 mm`, the only coherent coordinate convention is:

- `-X` moves physically toward the X-min home switch.
- `+X` moves physically away from home, from `0` toward `200 mm`.
- `G28 X` homes in the negative direction.

If `+X` moves toward the switch, do not change the application range to
`-200...0` and do not swap only the GUI button meanings. Correct Marlin's motor
direction instead. The required firmware relationship is:

```cpp
#define USE_XMIN_PLUG
#define X_HOME_DIR -1
#define X_MIN_POS 0
#define X_MAX_POS 200
```

Set `INVERT_X_DIR` to `true` or `false` according to the motor wiring so that
negative X physically approaches the switch. Its literal value is
hardware-dependent. Keep both X software endstops enabled. See
[`FIRMWARE_X_AXIS.md`](FIRMWARE_X_AXIS.md) for the controlled verification
procedure.

## Install Dependencies

Install Python 3, then from this project folder run:

```bat
python -m pip install -r requirements.txt
```

Dependencies are:

- PySide6 for the GUI
- pyserial for USB serial communication
- pytest for tests
- PyInstaller for building the executable

## Run From Python

```bat
python main.py
```

## Build the Windows Executable

Run:

```bat
build_exe.bat
```

The build script installs dependencies, runs tests, then builds:

```text
dist\DoctorBladeControllerV305.exe
```

The PyInstaller command used by the script is:

```bat
python -m PyInstaller --noconfirm --onefile --windowed --name DoctorBladeControllerV305 main.py
```

## Connect to the SKR Mini E3 V3

1. Connect the SKR Mini E3 V3 to the Windows PC with USB.
2. Power the controller and machine safely.
3. Open the app.
4. Click **Refresh** in the connection panel.
5. Select the detected COM port or type it manually, for example `COM3`.
6. Choose `115200` or `250000` baud to match the Marlin firmware.
7. Click **Connect**.
8. Wait for the status to change from **Initializing** to **Ready**. The app
   waits for board startup and confirms communication with `M115`.

All transmitted G-code is logged with a `>` prefix. All received Marlin lines are shown in the raw serial log.

## Find the COM Port on Windows

Open **Device Manager**, then expand **Ports (COM & LPT)**. The SKR board usually appears as a USB serial device with a COM number such as `COM3`, `COM4`, or similar. Use that COM number in the app.

## Manual Controls

**Quick Stop**, **Emergency Stop** and **Motors Off** are in a bar above the
tabs, so they stay visible whatever tab is open. The tab pages scroll on short
screens (for example 1366x768 laptops) instead of compressing the controls, and
the divider above the serial log can be dragged to resize it.

Use **Home X** before absolute motion. The app blocks absolute moves and profile runs until homing has been done unless **Allow movement before homing** is enabled.

Available controls:

- **Home X** first sends `M119` and proceeds with `G28 X` only if X-min is explicitly `open`
- **Estimated distance to home** optionally enables a confirmed 10 mm/s pre-approach while retaining a 40 mm slow zone
- **Read Position** sends `M114` and parses the X position
- **Check X Endstop (M119)** reads X-min without moving the machine
- **Live endstop monitor** repeats `M119` every 0.5 s while no other machine
  operation is running, shows the X-min state, and counts state changes so the
  switch wiring can be checked by pressing the lever by hand
- **Jog -X (toward home)** performs a relative move toward X-min
- **Jog +X (away from home)** performs a relative move into the usable coating stroke
- **Move to X** performs an absolute X move
- **Speed** is entered in mm/s and converted to Marlin feedrate mm/min
- **Acceleration** sends `M204 T...` for Marlin travel moves without extrusion
- **Software travel limit** prevents absolute moves beyond the configured X range
- **Quick Stop** sends `M410` followed by `G90`
- **Emergency Stop** sends `M112`, marks Marlin as `KILLED`, and requires a board reset or power-cycle
- **Motors Off** sends `M18`

### Test the X-min Endstop Before Homing

1. Connect and wait for **Ready**.
2. Leave the endstop lever released and click **Check X Endstop (M119)**.
   The result must be **OPEN (lever released)**.
3. Hold the lever fully pressed and click the same button again.
   The result must be **TRIGGERED (lever pressed)**.
4. Release the lever and repeat once more; the result must return to **OPEN**.

Pressing the lever by itself does not produce a visible event while the machine
is idle. Marlin reports the state only when `M119` is requested, and normally
uses it to stop motion only during homing. Do not run **Home X** if the status
does not change between `OPEN` and `TRIGGERED`.

Only one normal machine operation can run at a time. This prevents manual moves,
profiles, homing, and calibration commands from interleaving `G90`, `G91`, and
`G1` commands on the serial connection.

### Optional Staged Homing

The distance field is an operator estimate of the carriage's current distance
from X-min. It is deliberately not saved between sessions or attempts.

- `0 mm`, or any estimate up to `40 mm`, uses the standard slow `G28 X`.
- Above `40 mm`, the app proposes a faster pre-approach of `estimate - 40 mm`
  at `10 mm/s`.
- The operator must confirm the calculated pre-approach before movement.
- The app sends `M120` before the relative pre-approach, so X-min remains active
  even before the axis has a valid coordinate.
- After the pre-approach, a second `M119` must still report `open`; otherwise
  `G28 X` is blocked.
- Marlin firmware V1.0.2 completes the reserved slow zone and final switch
  contact at `5 mm/s`, with a second contact at `2.5 mm/s`.

The estimate may be approximate, but it must remain conservative. The 40 mm
zone is a safety margin, not permission to enter an arbitrary value.

After quick stop, profile stop, motors off, serial disconnect, or emergency stop,
the app invalidates its X position and requires homing again. The movement-before-
homing override must be confirmed again in every application session.

If Marlin emits `start` because the controller reset or rebooted, the app cancels
the active operation, invalidates X, repeats the startup handshake, and requires
homing again.

`M112` is intentionally latched by Marlin. After Emergency Stop the controller
does not accept normal commands until the SKR Mini E3 V3 is reset or
power-cycled. The app displays **E-STOP: RESET BOARD** and asks the operator to
confirm that the controller was reset safely before reconnecting. It never
sends `M999` automatically.

## Heated Bed

The heated bed panel can:

- Show the heater power reported by Marlin (`B@`, 0..127, shown as a percentage)
- Flag implausible thermistor readings (below -5 deg C: open thermistor; above
  150 deg C: short circuit or wrong sensor type) and switch the heater off if
  one occurs while heating
- Switch the heater off and explain the likely wiring fault if the bed rises
  less than 2 deg C in 120 s while the target is more than 5 deg C above the
  current temperature (Marlin's own thermal protection remains the primary
  safeguard)
- Detect at connection time whether Marlin reports a bed temperature at all;
  if not, the firmware has no bed configured and bed heating is disabled in the
  app
- Add a wiring hint to Marlin errors such as `MINTEMP`, `MAXTEMP`,
  `Heating failed` and `Thermal Runaway`
- Set bed temperature with `M140 S...`
- Set and wait with `M190 S...`
- Turn the heater off with `M140 S0`
- Poll temperature periodically with `M105`
- Parse responses such as `ok T:20.0 /0.0 B:43.2 /60.0 @:0 B@:127`

The default safety limit is 90 deg C. If a requested setpoint exceeds the configured safety limit, the app warns and requires confirmation.

When the application closes, it sends `M140 S0` if connected.

## Coating Profiles

The coating profile tab stores a sequence of recipe segments. Each segment includes:

- Target X position in mm
- Speed in mm/s
- Acceleration in mm/s^2
- Dwell time in seconds
- Optional bed temperature setpoint
- Wait-for-temperature flag

Before running a profile, the app sends:

```gcode
G21
G90
```

For each segment, it validates travel limits, optionally sets or waits for bed temperature, sets acceleration, moves to the target X position, waits for motion completion with `M400`, then applies dwell with `G4 S...`.

Use **Save JSON** and **Load JSON** to store or reload recipes.

## Keyence-Assisted Stroke Calibration

The calibration tab is manual/assisted. It does not directly integrate with the Keyence IL-S025.

Workflow:

1. Click **Read X Steps/mm from Marlin**. The app sends `M503` and reads the
   reported `M92 X...` value.
2. Home X.
3. Enter a known X travel distance and click **Run +X Calibration Stroke**.
4. Measure the actual travel externally with the Keyence IL-S025 or another displacement sensor.
5. Enter the commanded and measured distances.
6. The app computes:

```text
new_steps = current_steps * commanded_distance / measured_distance
```

Click **Apply X Steps/mm** to send:

```gcode
M92 X<new_steps>
M500
```

After changing steps/mm, the app invalidates the known X position and requires a
new homing cycle.

The app rejects non-finite values such as `NaN` or infinity before generating
G-code or running a loaded profile.

## G-code Reference

| Command | Action | Can block | Safety and usage |
| --- | --- | --- | --- |
| `G21` | Select millimeter units | No | Sent at profile start |
| `G28 X` | Home the X axis toward the configured X endstop | Yes | Sent only after an automatic `M119` confirms X-min is open |
| `G90` | Select absolute positioning | No | Used before absolute and profile moves |
| `G91` | Select relative positioning | No | Used only inside atomic jog or staged-homing sequences |
| `G1 X<mm> F<mm/min>` | Move X at the requested feedrate | Motion continues asynchronously | Targets are checked against the software travel limit |
| `G4 S<seconds>` | Dwell for a profile segment | Yes | Used only for non-negative profile dwell values |
| `M18` | Disable stepper motors | No | Invalidates known X position; re-home afterward |
| `M92 X<steps/mm>` | Set X-axis steps per millimeter | No | Calibration only; followed by `M500` |
| `M105` | Report temperatures | No | Non-blocking periodic polling; also sent once after `M115` at connection to check that the firmware reports a bed (`B:`) |
| `M108` | Break out of a Marlin wait loop | Immediate only with `EMERGENCY_PARSER` | Used before profile cancellation or heater shutdown to interrupt `M190` |
| `M112` | Emergency stop / kill | Immediate with Marlin emergency parser | Latches Marlin KILLED; requires physical reset or power-cycle before reconnecting |
| `M114` | Report current position | No | Used after homing and calibration moves |
| `M115` | Report firmware information | No | Startup handshake before normal controls are enabled |
| `M119` | Report endstop states | No | Manual diagnostic, live endstop monitor (every 0.5 s, skipped while any other operation runs), and automatic pre-homing gate; X-min must be `open` before `G28 X` |
| `M120` | Enable physical endstop checks globally | No | Used before the optional unreferenced fast pre-approach so X-min can still stop negative motion; remains enabled as a conservative limit |
| `M140 S<deg C>` | Set bed target without waiting | No | `S0` turns the heater off |
| `M190 S<deg C>` | Set bed target and wait while heating | Yes | Uses the configured temperature safety confirmation |
| `M204 T<mm/s^2>` | Set travel acceleration | No | Applies to X moves without extrusion |
| `M211` | Report or set software endstops | No | Keep enabled; do not use `S0` for normal operation or direction testing |
| `M400` | Wait for all planned moves to finish | Yes | Used before reporting a move or profile segment complete |
| `M410` | Stop steppers immediately | Immediate with Marlin emergency parser | Position becomes unreliable; Quick Stop follows it with `G90` and requires re-homing |
| `M500` | Save current settings to EEPROM | No | Persists calibrated X steps/mm |
| `M503` | Report active runtime settings | No | Used to read the current `M92 X...` calibration |

## Safety Notes

Use a fuse on the heated bed power line.

For a 12 V 80 W bed:

```text
current = 80 W / 12 V = about 6.7 A
```

A 10 A fuse is appropriate for that 80 W bed when wiring and connectors are properly rated.

For a future 12 V 120 W bed:

```text
current = 120 W / 12 V = 10 A
```

A 15 A fuse may be appropriate only if the wiring, MOSFET, connectors, and power supply are properly rated. An external MOSFET is recommended for higher bed currents.

Always verify Marlin thermal protection, heater wiring, fuse placement, and mechanical endstop behavior before unattended operation.

For responsive `M108`, `M112`, and `M410` handling during blocking commands,
enable Marlin `EMERGENCY_PARSER`. Without it these commands may be delayed behind
the current command queue.
