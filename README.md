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
