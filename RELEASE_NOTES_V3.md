# Doctor Blade Controller V3.0.6

Release date: 2026-11-13

## Commissioning Diagnostics

- Added a live X-min endstop monitor that repeats `M119` every 0.5 s without
  motion, never interleaves with other operations, and counts lever
  transitions.
- The bed tab shows Marlin heater power (`B@`) and a thermistor/heater status.
- Implausible thermistor readings are flagged; the heater is switched off if
  one occurs while a target is set.
- An application heating watch switches the heater off if the bed rises less
  than 2 deg C in 120 s while far below target.
- The startup handshake now also sends `M105` and disables bed commands if the
  firmware reports no bed temperature (`TEMP_SENSOR_BED 0`). Profiles that set
  bed temperatures are blocked in that case.
- Marlin errors such as `MINTEMP`, `MAXTEMP`, `Heating failed`,
  `Thermal Runaway` and `Homing Failed` are shown with a wiring hint.
- Added `COLLEGAMENTI_SKR_MINI_E3_V3.md` (Italian) with SKR Mini E3 V3 wiring
  for the X-min endstop, the silicone pad heater, and the bed thermistor.
- The executable name is unchanged (`DoctorBladeControllerV305.exe`) so the
  existing build script and settings location keep working.

# Doctor Blade Controller V3.0.5

Release date: 2026-06-09

## Staged Homing

- Added an operator-entered approximate distance to X-min.
- Estimates up to 40 mm retain the standard slow Marlin homing sequence.
- Longer estimates use a confirmed `estimate - 40 mm` relative pre-approach at
  10 mm/s before `G28 X`.
- `M120` enables the mechanical X-min limit during the unreferenced
  pre-approach.
- `M119` is validated before and after the fast stage.
- The estimate is cleared after starting and is never persisted.
- Marlin V1.0.2 is required for the intended 5 mm/s final homing zone.
- Quick Stop now sends `G90` after `M410` so an interrupted relative
  pre-approach cannot leave Marlin in relative-positioning mode.

## Homing Safety Gate

- `Home X` now captures an `M119` response before sending `G28 X`.
- Homing is blocked if X-min is already `TRIGGERED` or absent from the response.
- Tests verify the exact `M119`, `G28 X`, `G90`, `M114` command order.

## Emergency Stop State

- `M112` is now presented explicitly as a latched Marlin `KILLED` state, not
  as an application freeze.
- The status panel displays **E-STOP: RESET BOARD** after the command.
- Reconnection requires operator confirmation that the controller was reset or
  power-cycled and the hazard was cleared.
- The application does not send `M999` automatically.

## M119 Response Fix

- Fixed a cross-thread race that could report a missing `x_min` line even when
  the Marlin raw log contained `x_min: open` or `x_min: TRIGGERED`.
- The diagnostic now validates the response lines captured atomically from the
  `M119` command.
- Added serial and GUI regression tests for multiline `M119` responses.

## Endstop Diagnostic

- Added **Check X Endstop (M119)** to the manual-motion panel.
- The UI parses and displays `x_min: open` and `x_min: TRIGGERED`.
- The diagnostic sends no movement or heater command.
- Tests verify the parser, displayed states, and that the button sends only
  `M119`.

## X-Axis Direction Clarification

- The interface now states the required physical convention: `-X` moves toward
  the X-min home switch and `+X` moves away from home.
- Jog buttons include the expected physical direction in their labels.
- The application deliberately continues to reject negative coordinates after
  homing; a reversed motor must be corrected with Marlin `INVERT_X_DIR`.
- `FIRMWARE_X_AXIS.md` documents `X_HOME_DIR`, X bounds, `M119`, software
  endstops, and a controlled commissioning procedure.

## V3.0.0 Reliability Changes

- Serial command sequences are atomic, preventing interleaved `G90`, `G91`,
  and movement commands.
- Stop requests remain active until the current sequence exits.
- Temperature polling waits for its own Marlin `ok`, preventing stale replies
  from acknowledging unrelated commands.
- Marlin `start` messages invalidate the X position and trigger a new startup
  handshake.
- Profile cancellation sends `M108`, `M410`, and `M140 S0` to break temperature
  waits, stop motion, and turn off the bed heater.
- Quick stop, emergency stop, disconnect, motors off, calibration changes, and
  command failures invalidate the known X position.

## Calibration Changes

- Current X steps/mm can be read from the `M92 X...` line reported by `M503`.
- A guarded positive-X calibration stroke is available after homing.
- Applying `M92` and `M500` requires a new homing cycle.

## Validation and Tests

- Non-finite numeric values are rejected before G-code generation.
- Hand-edited profile booleans are parsed explicitly.
- Unit, serial race, model, entry point, and headless GUI safety tests are
  included and require no connected hardware.
