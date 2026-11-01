# Haltech CAN V2 on LIVI with TJD CarPiHAT

This guide covers the read-only RPM and wheel-speed path from a Haltech Elite
2500 / WB2 CAN network to LIVI running on a Raspberry Pi 4 with a TJD CarPiHAT.
It does not configure the ECU, make LIVI an ECU tuning tool, or add CAN
transmission.

## What is supported

With the integration enabled:

- The Pi 4 OS configures the CarPiHAT MCP2515 as `can0` at **1 Mbit/s**, in
  controller **listen-only** mode.
- LIVI reads standard Haltech CAN V2 broadcast frames for engine RPM (`0x360`)
  and wheel speed (`0x370`) and feeds the existing `rpm` and `speedKph`
  telemetry fields.
- The app toggle starts or stops the reader. It does not change the CAN
  controller mode or configure the ECU.
- Unsupported frames are ignored. WB2 wideband values, gear, temperatures and
  other CAN signals are **not currently decoded or displayed by this adapter**.
- The ECU must already be configured in Haltech ESP to broadcast the supported
  frames. A speed signal is only available if the ECU has a valid/configured
  wheel-speed source.

The frame IDs and basic field scaling are also listed in the
[Haltech CANBus V2 reference](https://ftyracing.com/tech/haltech-canbus-v2-protocol-info/).
Use the current Haltech protocol document and your ECU's ESP configuration as
the authority for the specific ECU firmware and broadcast profile.

## Hardware and wiring

### Identify the HAT and bus first

The TJD CarPiHAT quick-start guide describes an SPI MCP2515 CAN controller with
an 8 MHz crystal, an interrupt on BCM GPIO 23, and a 120 ohm resistor across
CAN-H/CAN-L. It also notes that the resistor is present on the board. The Pi 4
image configuration in this repository assumes those details.

The user-provided “batch ID 01/26” does not identify the PCB revision or prove
that its CAN circuit, clock, interrupt, and termination match that guide. Before
connecting it, check the HAT silkscreen and board against the
[TJD CarPiHAT documentation](https://github.com/SamT-J/CarPiHat). If those
hardware details differ, stop: do not use this image configuration until the
overlay and termination are confirmed for that exact board.

### Topology

Connect LIVI as a parallel node on the **Haltech CAN network** shared by the
Elite ECU and WB2. Use the Haltech CAN hub or an approved CAN splice and keep
the CAN pair short and twisted. Do not connect LIVI to the Mercedes factory
vehicle CAN as a substitute for the Haltech ECU bus.

```text
Elite 2500 ─┐
            ├── Haltech CAN hub / correctly terminated bus
WB2 ────────┤
            └── CarPiHAT CAN-H and CAN-L
```

For the Haltech DTM-4 CAN connector, Haltech's
[auxiliary CAN port reference](https://support.haltech.com/portal/en/kb/articles/auxiliary-can-bus-port-7-4-2020)
lists:

| DTM-4 pin | Haltech wire colour | Signal |
|---|---|---|
| 1 | Red | +12 V supply |
| 2 | Black | Signal ground |
| 3 | White | CAN-H |
| 4 | Blue | CAN-L |

Pin numbers are molded into the connector. Check the connector's own numbering;
do not identify pins only by viewing angle or wire colour. This is the DTM-4
CAN connector pinout, **not** the Elite 2500 26-pin ECU connector pinout. On
that ECU connector, Haltech identifies B23 as CAN-H and B24 as CAN-L in its
[Elite 2500 connector reference](https://support.haltech.com/portal/en/kb/articles/main-connector-26-pin-elite2500).

Connect only CAN-H to CAN-H and CAN-L to CAN-L at the CarPiHAT CAN port. **Do
not connect the DTM-4 +12 V pin to the HAT CAN port or Raspberry Pi GPIO/power
pins.** Power the Pi/HAT through the normal CarPiHAT power input. Check whether
the exact HAT CAN interface is isolated and how it references ground; follow
the HAT and Haltech wiring diagrams for DTM-4 pin 2 (signal ground). Do not
omit a required CAN signal reference or add a ground path contrary to those
diagrams.

With all bus equipment powered off, confirm that exactly the two physical ends
of the bus are terminated. The CarPiHAT guide says its board has a 120 ohm
termination resistor; an extra enabled termination in the middle of an already
terminated network can cause faults. If qualified to do so, a resistance
measurement across CAN-H/CAN-L on an unpowered, settled, fully connected bus
will typically be about 60 ohms for two 120 ohm end terminators in parallel.
Do not add a terminator based only on that rule of thumb; follow the ECU, hub,
and HAT documentation for the actual topology.

Do not hot-plug or probe exposed CAN/power conductors with the vehicle running.
Use a fused automotive supply and an automotive-qualified installer if you are
unsure about the harness or termination.

## Configure the Haltech ECU and WB2

LIVI cannot change these settings. In Haltech ESP, with the correct Elite 2500
map connected:

1. Confirm the ECU, WB2 and Haltech CAN hub are online and communicating.
2. Enable the Haltech CAN V2 / ECU broadcast output profile for the bus, at the
   matching **1 Mbit/s** bitrate. Do not change a shared bus to another bitrate
   just to make LIVI connect.
3. Enable the required broadcast channels. For the current LIVI adapter this
   means RPM and wheel speed. Verify the selected wheel-speed source is
   configured and produces a credible value in ESP/data logging.
4. Configure/enable the WB2 device and verify both wideband channels in ESP
   according to the current WB2 manual. This confirms ECU-to-WB2 operation;
   it does **not** make those WB2 readings appear in LIVI yet.
5. Save the ECU map and verify its broadcast settings using Haltech's
   documentation for the installed ECU firmware. Do not infer a working
   broadcast just from the ECU and WB2 sharing a hub.

The precise ESP menu names depend on software/firmware version. Consult
[Haltech CAN protocol information](https://support.haltech.com/portal/en/kb/haltech/technical-library/haltech-can-protocol-information)
and the [WB1/WB2 CAN wideband guide](https://support.haltech.com/portal/en/kb/articles/can-wideband-controller-wb1-and-wb2-bosch-lsu-4-9-lambda-sensors).

## Build and install the Pi 4 OS

The CAN device-tree and service changes are for the **Pi 4** image. They are
not enabled in the Pi 5 configuration.

On the documented x86-64 Linux build host, after supplying a compatible LIVI
ARM64 AppImage and its checksum:

```sh
make check
make pi4
```

On macOS Apple Silicon, use the repository's documented Docker build workflow
in [README.md](../README.md). Do not overwrite
the source image when testing: write the newly built
`output/pi4/images/livi-os-rpi4.img` to a spare SD card, verify its checksum,
and retain the existing recovery/rollback precautions.

**AppImage compatibility gate:** the Buildroot package checks that the AppImage
contains the immutable helper resources and the `resources/livi-os-helper-api`
version `1` marker. It intentionally stops if those resources are absent or
incompatible. The inspected LIVI source checkout did not contain that marker
in its app packaging, so a fresh AppImage from that checkout must not be
assumed compatible. Reconcile and verify the AppImage packaging/API marker
before using it with `make pi4`; do not bypass the package validation.

At first boot, the OS applies the CarPiHAT SPI device-tree overlay and starts
`livi-can.service`. The service configures `can0` at 1 Mbit/s and sets
listen-only mode before bringing the interface up. If the `can0` interface is
not created, LIVI cannot receive CAN data; do not weaken listen-only mode as a
workaround.

## Enable and verify LIVI

1. Boot the updated Pi 4 image with the correctly wired CarPiHAT.
2. Check the OS setup:

   ```sh
   systemctl status livi-can.service
   ip -details link show can0
   ```

   Confirm the interface is up, reports 1 Mbit/s and has CAN listen-only mode
   enabled. If the service failed or the interface is absent, stop and resolve
   the board revision, SPI overlay, kernel module, or wiring issue before
   enabling the app setting.

3. For a receive-only frame check, run the restricted capture helper and stop
   it with Ctrl-C:

   ```sh
   sudo -n /usr/libexec/livi-can-capture
   ```

   With broadcasts active, look for standard frames such as `can0 360#...` and
   `can0 370#...`. No output can mean no ECU broadcast, wrong bitrate, wiring
   or termination trouble, or an unsupported configuration. Do not test by
   transmitting frames.

4. In LIVI, open **Settings → General → Vehicle Telemetry** and enable
   **Receive Haltech CAN V2 telemetry (can0, 1 Mbit/s, listen-only)**. The
   setting is saved and takes effect without restarting LIVI.
5. Open the existing telemetry dashboard and show its RPM and speed widgets
   using the dashboard settings if needed. Confirm the displayed RPM and speed
   agree with ESP/data logging under a safe stationary/bench test where
   possible. Wheel speed requires the vehicle/sensor conditions that produce
   that signal.
6. If frames stop arriving for about 1.5 seconds, LIVI clears the affected
   reading to zero. Turn the setting off to stop the app reader; the OS CAN
   interface remains in listen-only mode.

QEMU can validate the Pi OS storage/boot path but does not emulate the
CarPiHAT's MCP2515 electronics, CAN wiring, Haltech ECU, or WB2. Physical
hardware verification is required.

## References

- [TJD CarPiHAT quick-start guide](https://github.com/SamT-J/CarPiHat/wiki/Quick-Start-Guide)
- [Haltech auxiliary CAN bus port / DTM-4](https://support.haltech.com/portal/en/kb/articles/auxiliary-can-bus-port-7-4-2020)
- [Elite 2500 26-pin connector](https://support.haltech.com/portal/en/kb/articles/main-connector-26-pin-elite2500)
- [Haltech CAN protocol information](https://support.haltech.com/portal/en/kb/haltech/technical-library/haltech-can-protocol-information)
- [WB1/WB2 CAN wideband guide](https://support.haltech.com/portal/en/kb/articles/can-wideband-controller-wb1-and-wb2-bosch-lsu-4-9-lambda-sensors)
- [CAN V2 message summary](https://ftyracing.com/tech/haltech-canbus-v2-protocol-info/)
