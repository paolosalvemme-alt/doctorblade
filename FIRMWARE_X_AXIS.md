# X-Axis Firmware Convention

This machine uses one X axis, an X-min home switch at the beginning of travel,
and an application range from `0` to the configured positive travel limit.

## Required Coordinate Relationship

- Home switch pressed: nominal position `X=0`.
- Motion toward the home switch: negative X.
- Motion away from home: positive X.
- Usable stroke: `0 <= X <= 200 mm` by default.

Changing the application range to negative coordinates would hide a firmware
direction error and make profiles, calibration, and software endstops
inconsistent.

## Relevant Marlin Configuration

The pertinent `Configuration.h` settings should express this relationship:

```cpp
#define USE_XMIN_PLUG

#define X_HOME_DIR -1

#define X_MIN_POS 0
#define X_MAX_POS 200

#define MIN_SOFTWARE_ENDSTOPS
#define MAX_SOFTWARE_ENDSTOPS
```

The matching Doctor Blade Marlin V1.0.2 also uses:

```cpp
#define HOMING_FEEDRATE_MM_M { (5*60), (20*60), (4*60) }
#define HOMING_BUMP_MM      { 4, 4, 2 }
#define HOMING_BUMP_DIVISOR { 2, 2, 4 }
```

This gives X a 5 mm/s first contact, 4 mm backoff, and 2.5 mm/s second contact.
Controller V3.0.5 may perform a guarded 10 mm/s relative pre-approach, but it
always reserves 40 mm for this Marlin-controlled slow homing sequence.

For Marlin versions with per-axis software-endstop options, keep the X entries
enabled:

```cpp
#define MIN_SOFTWARE_ENDSTOP_X
#define MAX_SOFTWARE_ENDSTOP_X
```

`INVERT_X_DIR` is hardware-dependent:

```cpp
#define INVERT_X_DIR false  // or true
```

Select the value that makes a negative X move approach the X-min switch and a
positive X move leave it. Do not change `X_HOME_DIR` to `1` merely to compensate
for an inverted motor: that would describe an X-max homing arrangement.

The correct `X_MIN_ENDSTOP_HIT_STATE` also depends on switch wiring. Determine
it from `M119`; do not guess it.

## SKR Mini E3 V3 Endstop Hardware

- The X-min switch goes on the 2-pin `X-STOP` connector: `GND` and `PC0`.
- Remove the `X-DIAG` jumper. It connects the TMC2209 DIAG output to the same
  `PC0` line for sensorless homing and corrupts a mechanical switch reading.
- Keep `SENSORLESS_HOMING` disabled and keep `ENDSTOPPULLUPS` (or at least
  `ENDSTOPPULLUP_XMIN`) enabled.
- A normally-closed switch (`COM` to `GND`, `NC` to `PC0`) is preferred: a
  broken wire then reads `TRIGGERED` and the application blocks homing.

Full wiring instructions (Italian) are in
[`COLLEGAMENTI_SKR_MINI_E3_V3.md`](COLLEGAMENTI_SKR_MINI_E3_V3.md).

## Controlled Verification

Perform these checks without the blade, with the heater off, at low speed, and
with the physical power stop immediately accessible.

1. Place the carriage away from both mechanical limits.
2. Send `M119` with the switch released. `x_min` must report `open`.
3. Hold the switch pressed and send `M119` again. `x_min` must report
   `TRIGGERED`.
4. Start `G28 X` while ready to cut power. The first motion must be toward the
   X-min switch.
5. After homing, command a very small positive move at low speed. It must move
   away from the switch.
6. Confirm with `M114` that position increased from zero.
7. Send `M211` and verify software endstops are enabled. Do not use `M211 S0`
   for normal operation or direction testing.

If step 4 is wrong, change `INVERT_X_DIR` and rebuild Marlin. If step 2 or 3 is
wrong, correct the switch connector, wiring, or `X_MIN_ENDSTOP_HIT_STATE`
before any further homing attempt.

## EEPROM After Flashing

Marlin may retain old EEPROM values after a firmware update. Record the active
`M92 X` calibration first. When required by the firmware update procedure,
load the new defaults with `M502`, save them with `M500`, and then restore only
the independently verified X steps/mm value. Re-home before movement.

## Official References

- Marlin configuration:
  https://marlinfw.org/docs/configuration/configuration.html
- Marlin `M119` endstop report:
  https://marlinfw.org/docs/gcode/M119.html
- Marlin `M211` software endstops:
  https://marlinfw.org/docs/gcode/M211.html
