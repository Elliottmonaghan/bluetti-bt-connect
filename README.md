# bluetti-bt-connect
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Validate with hassfest](https://github.com/Elliottmonaghan/bluetti-bt-connect/actions/workflows/hassfest_validation.yml/badge.svg)](https://github.com/Elliottmonaghan/bluetti-bt-connect/actions/workflows/hassfest_validation.yml)
[![HACS Action](https://github.com/Elliottmonaghan/bluetti-bt-connect/actions/workflows/HACS.yml/badge.svg)](https://github.com/Elliottmonaghan/bluetti-bt-connect/actions/workflows/HACS.yml)

> **This is a fork** of [hassio-bluetti-bt](https://github.com/Patrick762/hassio-bluetti-bt) by [Patrick762](https://github.com/Patrick762), paired with a fork of the underlying [bluetti-bt-lib](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib). All credit for the original integration architecture, protocol reverse-engineering, and core design goes to Patrick762 and the project's other contributors. This fork exists to track device-specific fixes and additions (notably for the Bluetti EP2000) on a faster iteration cycle; where possible, improvements are intended to be contributed back upstream.
>
> Original repository: https://github.com/Patrick762/hassio-bluetti-bt
> Companion library fork: https://github.com/Elliottmonaghan/bluetti-bt-connect-lib

Bluetti Integration for Home Assistant

## Disclaimer
This integration is provided without any warranty or support by Bluetti. I do not take responsibility for any problems it may cause in all cases. Use it at your own risk.

## ✅ EP2000: local control works (v2.0)

Earlier builds warned that grid and working-mode writes on the EP2000 were
accepted without error and then silently reverted. **That is fixed in v2.0.** The
underlying library now sends settings writes to the correct Modbus slave - **slave
0**, the device's settings controller - instead of slave 1 (the inverter, which
echoed writes and then overwrote them from the slave-0 setpoint). Grid
import/export limits, working mode and the switches all **write and persist** over
local Bluetooth now. Full detail is in the
[library's v2.0 release notes](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib/blob/main/RELEASE_NOTES_2.0.0.md).

### EP2000 controls

| Entity | Register | Notes |
|--------|----------|-------|
| AC Output | 2011 | switch |
| Charge From Grid | 2207 | switch |
| Grid Export | 2208 | switch |
| Max Grid Export Power | 2215 | W |
| Max Grid Export Current | 2216 | A |
| Max Grid Import Power | 2213 | W |
| Max Grid Import Current | 2214 | A |
| Working Mode | 2005 | Custom / Self-use / Backup / Time-of-use |
| AI Control Mode | 2241 | switch - **on** = Bluetti's AI/EMS manages the system and overrides manual settings; **off** = manual control |

**Two things to know:**

- After changing a setting, give it a few seconds to settle before trusting the
  value shown - the write goes to the device's settings controller and takes a
  moment to propagate back to the reading.
- If manual settings ever stop sticking, check **AI Control Mode**. If it is on,
  Bluetti's AI is overriding you - turn it off for manual control.

**Grid export and grid-protection settings are regulated for grid-interconnection
safety in many jurisdictions** (anti-islanding, voltage/frequency ride-through).
Know your local rules before changing them.

## Installation
To install this integration, you first need [HACS](https://hacs.xyz/) installed.
After the installation, you can add this repository as a custom repository in HACS, or use this button:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Elliottmonaghan&repository=bluetti-bt-connect&category=integration)

### Supported devices:

See [bluetti-bt-connect-lib](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib?tab=readme-ov-file#supported-powerstations-and-data)

### Available controls:
See [bluetti-bt-connect-lib](https://github.com/Elliottmonaghan/bluetti-bt-connect-lib?tab=readme-ov-file#supported-powerstations-and-data)

### Adding devices or fields

Please open an issue on this repository, or see the upstream issue template at [bluetti-bt-lib](https://github.com/Patrick762/bluetti-bt-lib?tab=readme-ov-file#supported-powerstations-and-data) for the general contribution format.

## Note on domain change

This fork uses the Home Assistant integration domain `bluetti_bt_connect` (rather than `bluetti_bt`) to avoid conflicting with the original integration if both are ever installed side by side. If migrating from the original `hassio-bluetti-bt`, you will need to remove the old integration and re-add this one - existing entities and history will not carry over automatically.
