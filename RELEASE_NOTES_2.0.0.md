# bluetti-bt-connect 2.0.0

**Local control of the Bluetti EP2000 works.** Grid import/export limits, working
mode and the switches now write and persist over local Bluetooth. The
long-standing "accepted but silently reverts" behaviour is fixed.

## What changed

- **Requires `bluetti-bt-connect-lib==2.0.0`**, which contains the real fix:
  settings writes now go to **Modbus slave 0** (the device's settings controller)
  instead of slave 1 (the inverter, which echoed writes and then overwrote them).
  See the [library 2.0.0 notes](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib/blob/main/RELEASE_NOTES_2.0.0.md)
  for the full investigation.
- **New "AI Control Mode" switch** (register 2241). When on, Bluetti's AI/EMS
  manages the system and overrides your manual settings; off = manual control.
  If settings ever stop sticking, this is the first thing to check.
- **Max Grid Import Power / Current entities now appear** - their read bounds were
  too low and had been discarding the device's real values (8600 W / 45 A).
- **Removed the "Bluetooth settings password" option** added in 1.8.0. It was
  based on a misread (register 7 sets the BT password; it is not a login) and did
  nothing useful.

## EP2000 controls

AC Output, Charge From Grid, Grid Export (switches); Max Grid Export Power/Current
and Max Grid Import Power/Current (numbers); Working Mode (select); AI Control Mode
(switch). All write and persist over local BLE.

## Upgrading

1. In HACS, update **Bluetti BT Connect** to **2.0.0**.
2. Restart Home Assistant (Home Assistant reinstalls the pinned library on
   restart, so this is required to pull lib 2.0.0).
3. Set a grid limit or working mode and confirm it holds after a poll cycle.

Notes:
- After a write, allow a few seconds for the value to settle before trusting the
  read-back - it propagates from the settings controller back to the reading.
- Keep **AI Control Mode** off for manual control.
- **Grid export and grid-protection settings are regulated for grid-interconnection
  safety in many jurisdictions.** Know your local rules before changing them.

## Credits

Fork of [hassio-bluetti-bt](https://github.com/Patrick762/hassio-bluetti-bt) by
[Patrick762](https://github.com/Patrick762), paired with the
[bluetti-bt-connect-lib](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib)
fork. All credit for the original integration and protocol work to Patrick762 and
the upstream contributors.
