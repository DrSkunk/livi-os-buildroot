# Haltech CAN telemetry with CarPiHAT and LIVI

Research checked: 2026-11-02. This is a configuration and commissioning guide,
not a claim that the current LIVI OS image implements CAN bring-up.

LIVI currently consumes **engine RPM and vehicle speed only**. There are two
possible connections:

| Route | ECU output | Pi CAN hardware | Status |
| --- | --- | --- | --- |
| A: standard Haltech broadcast | Haltech CAN V2, 1 Mbit/s | An interface supporting 1 Mbit/s and listen-only mode | Matches LIVI's current OS contract; recommended for Elite |
| B: custom Nexus broadcast | Two GCAN transmit frames, 500 kbit/s on a separate bus | Stock 8 MHz MCP2515 CarPiHAT | Conditional on ECU capabilities and additional OS integration |

**Correction to earlier advice:** installing NSP or Elite firmware 3.00 does
not add Generic CAN (GCAN) to an Elite ECU. Haltech explicitly excludes every
Elite model and Nexus Rebel from full GCAN. Do not buy hardware or change an
ECU configuration based on that earlier assumption.

## 1. Record the hardware before changing anything

Record:

- Exact ECU model, current firmware, and programming software/version.
- Available independent CAN buses, their assigned functions and bitrates.
  Two connectors do not necessarily mean two independent buses.
- Connected Haltech peripherals, OEM CAN connections, and existing terminators.
- CarPiHAT revision and actual oscillator marking.
- Installed LIVI AppImage version and the OS image revision.

Back up the ECU map before changing settings or updating firmware. Use the
pinout and installation manual for the exact ECU; there is no universal
Haltech connector pin assignment. Have an installer/tuner review changes to
an existing vehicle network.

The [CarPiHAT quick-start guide][carpihat] documents an MCP2515 with an **8 MHz**
crystal, SPI0 CS0 on BCM8 and interrupt on BCM23. With the Linux MCP251x
driver's timing limits, this clock cannot produce 1 Mbit/s. Changing the
overlay to claim a 16 MHz oscillator does not change the physical clock.
An actual hardware modification requires separate electrical validation.

## 2. Exact data LIVI requires

These settings are verified against Haltech's broadcast protocol document
version 2.0 and LIVI's [receiver implementation][receiver].

| Setting | Engine speed | Vehicle speed |
| --- | --- | --- |
| CAN identifier, hexadecimal | `0x360` | `0x370` |
| CAN identifier, decimal | `864` | `880` |
| Frame format | Classic CAN, standard 11-bit data frame | Classic CAN, standard 11-bit data frame |
| Bytes, zero-based | 0 and 1 | 0 and 1 |
| Signal length/type | 16-bit unsigned | 16-bit unsigned |
| Byte order | Big-endian: byte 0 is most significant | Big-endian: byte 0 is most significant |
| Decoding | `rpm = raw` | `speedKph = raw / 10` |
| Encoding | `raw = rpm` | `raw = speedKph * 10` |
| Offset | 0 | 0 |
| Standard broadcast rate | 50 Hz / every 20 ms | 20 Hz / every 50 ms |

LIVI ignores bytes 2-7. Standard Haltech frames also carry other channels in
those bytes; do not overwrite them on a shared Haltech network.

For route B, use DLC 8 with unused bytes zero on a dedicated LIVI bus. This is
a **LIVI-compatible subset**, not a complete replacement for the Haltech V2
protocol. Other receivers could interpret those zeros as real readings.
LIVI itself accepts payload lengths from 2 through 8 bytes.

Do not use extended 29-bit IDs, CAN FD, remote/request frames, multiplexing, a
different byte offset, or OBD-II polling. LIVI is a passive broadcast receiver.

### Scaling and byte checks

Configure the physical-unit relationship, not just an unexplained multiplier:

- If the editor defines `physical = raw * factor + offset`, use factor `1`
  for RPM and `0.1` for speed in km/h.
- If it defines a transmit conversion `raw = source * multiplier + offset`,
  use multiplier `1` for RPM and `10` for speed in km/h.
- Confirm source units. A speed channel displayed in mph must not be encoded
  directly as if it were km/h.
- Byte numbering and Motorola start-bit conventions vary between tools.
  Select bytes 0-1, most-significant byte first; do not assume a numeric
  start-bit value means the same thing in every editor.

Expected first two bytes:

| Physical value | Raw unsigned value | Bytes 0-1 |
| --- | --- | --- |
| 0 RPM | 0 | `00 00` |
| 1,000 RPM | 1000 | `03 E8` |
| 3,000 RPM | 3000 | `0B B8` |
| 0 km/h | 0 | `00 00` |
| 50.0 km/h | 500 | `01 F4` |
| 100.0 km/h | 1000 | `03 E8` |
| 123.4 km/h | 1234 | `04 D2` |

The speed signal must come from a valid, calibrated ECU vehicle-speed channel.
If the ECU shows zero or an incorrect value, changing CAN scaling will not
repair the source. Verify the configured sensor/CAN source, tyre circumference,
and pulse calibration as applicable to the installation.

## 3. Route A: keep the normal 1 Mbit/s Haltech network

This avoids custom messages and is the practical route for an Elite ECU.

1. In the ECU's programming software, inspect the CAN configuration and select
   the physical bus assigned to Haltech devices/broadcast. Keep it at
   **1 Mbit/s**. Do not change a bus used by existing Haltech peripherals to
   500 kbit/s.
2. Verify that the normal Haltech ECU broadcast is present on that bus.
   The broadcast protocol applies to Elite and Nexus ECUs, but exact menu
   names and any enable/port-selection settings depend on model and firmware.
   Use that model's help/manual rather than assuming an NSP checkbox exists.
   GCAN is not needed to receive the standard broadcast.
3. Check live engine RPM and vehicle speed in the ECU software first.
4. Connect an appropriate CAN adapter as described below, then check for
   `0x360` and `0x370` and their byte values.

Use an adapter whose actual firmware/driver supports both **1 Mbit/s and
listen-only mode**. A SocketCAN USB adapter such as a suitable `gs_usb` device
can leave the CarPiHAT available for power/ignition. Check listen-only support
for the exact adapter firmware; a product family name is not sufficient.
Keep the CarPiHAT CAN overlay disabled if its CAN controller is unused, and
verify that the selected adapter is consistently named `can0`.

Changing the CarPiHAT crystal to 16 MHz is a hardware-rework alternative, not a
software setting or a necessary ECU modification.

## 4. Route B: eligible Nexus GCAN at 500 kbit/s

### Eligibility and limits

Haltech's [official GCAN announcement][gcan] lists:

- Nexus T1/T2, S2/S3, R3/R5 and the Nexus Plug-in range.
- iC-7 and uC-10 displays also support GCAN, but their inclusion does not
  establish that a particular display can bridge two buses in your installation.
- **Not supported:** all Elite models and Nexus Rebel.
- NSP **1.48 or later**, with the announcement specifying ECU firmware
  **V1.36** and display firmware **V2.36**.

The official announcement says GCAN is released, not beta-only. Follow the
current supported update procedure in NSP; older third-party beta-opt-in
instructions are not a requirement.

GCAN on the Haltech bus still runs at 1 Mbit/s. On Vehicle CAN it inherits the
vehicle profile's bitrate. Haltech documents a **Third-Party CAN** option with
125k, 250k, 500k and 1M choices. That option does not create another physical
CAN controller.

Proceed only if the exact ECU has a physical bus that can be assigned to
Third-Party CAN without disrupting its existing devices. If no such bus is
available, use route A rather than repurposing an occupied bus.

### Configuration worksheet

The official public announcement verifies eligibility, enablement per bus,
and bitrate choices. It does not provide a complete field-by-field transmit
editor manual. The following is the required configuration specification,
not a verified click-by-click UI walkthrough or an importable NSP map.
Use NSP's help for the installed version to locate equivalent fields.

1. Back up the map and record existing bus assignments. If an update is
   necessary, follow Haltech's firmware procedure and verify the existing
   tune/peripherals afterward.
2. Select the independent physical CAN bus for LIVI, assign the Third-Party
   CAN function, and select **500 kbit/s**. Keep the main Haltech bus unchanged.
3. Enable GCAN on the selected bus's own page.
4. Define a periodic **transmit** frame with standard ID `0x360` (`864` if the
   editor takes decimal), DLC 8, period 20 ms. Bind the live engine RPM channel
   as unsigned 16-bit, big-endian, bytes 0-1, using the encoding above.
5. Define a second periodic transmit frame with standard ID `0x370` (`880`),
   DLC 8, period 50 ms. Bind calibrated vehicle speed in km/h as unsigned
   16-bit, big-endian, bytes 0-1, with `raw = km/h * 10`.
6. Set unused bytes to zero on this dedicated link. Do not add a counter or
   checksum in bytes 0-1. Confirm no other transmitter owns these IDs.
7. Save/write the configuration using the installed NSP version's procedure.
   Reconnect and verify that the bus assignment, rate and messages persisted.
8. Capture the output and compare it with the byte checks above before
   enabling telemetry in LIVI.

If the editor cannot provide this source selection or encoding, stop and
check the model-specific documentation. Do not assume that selecting a
predefined 500 kbit/s vehicle profile emits these two Haltech-layout frames.

## 5. Wiring and listen-only commissioning

With power disconnected, wire CAN H to CAN H and CAN L to CAN L using twisted
pair, and follow both devices' signal-ground/reference requirements. Use the
manufacturer's connector pinout; never connect vehicle 12 V to Pi GPIO.

There should be two 120 ohm terminators, one at each physical end of the bus,
not one per device. The documented CarPiHAT already contains 120 ohm termination.
Do not add it as a third terminator on an already terminated network. With the
network unpowered, two parallel terminators normally measure about 60 ohms
between CAN H and CAN L; confirm the topology and device-specific requirements.

**ACK caveat:** a listen-only receiver does not acknowledge CAN frames. A
dedicated link containing only a transmitting ECU and listen-only CarPiHAT
has no acknowledging receiver and may produce ACK errors/retransmissions.
Include a correctly configured normal-mode receiver that acknowledges without
sending application frames, or have the installer establish another supported
topology. Do not silently disable LIVI's listen-only requirement to hide this.

On a prepared Linux target with `iproute2`, `can-utils`, the correct driver,
and a dedicated interface, stop capture/LIVI before bring-up. For route B:

```sh
sudo ip link set can0 down
sudo ip link set can0 type can bitrate 500000 listen-only on
sudo ip link set can0 up
ip -details -statistics link show can0
candump -L can0,360:7FF,370:7FF
```

For route A, use `bitrate 1000000` instead. Do not run these commands against
an interface used by another service. Stop if configuration fails or the
reported bitrate/listen-only state is wrong; do not fall back to normal mode.
Some commands/tools are not yet shipped in this repository's image.

At 3,000 RPM and 100.0 km/h the relevant bytes in `candump -L` output are:

```text
(1234567890.000000) can0 360#0BB8000000000000
(1234567890.000000) can0 370#03E8000000000000
```

These are illustrative receive lines, **not commands to transmit on the ECU
bus**. On route A, bytes 2-7 will contain other real Haltech channels.

Verify:

- Both IDs arrive continuously, near 50 Hz and 20 Hz respectively.
- Reported bitrate and listen-only mode are correct; no growing error/drop
  counters or bus-off events occur.
- Captured bytes decode to the live ECU values, including stationary zero
  speed and a safe nonzero speed check on suitable test equipment.
- A cold boot restores the same interface name, bitrate and capture mode.
- Enabling **Settings > Car > Receive Haltech CAN V2 telemetry** updates LIVI.
- Disconnecting the signal produces stale telemetry after about 1.5 seconds,
  and reconnecting restores updates. LIVI's dashboard can display missing
  readings as zero, so a displayed zero alone does not prove reception.

Keep the vehicle stationary for initial checks. Do not operate a laptop or
adjust ECU settings while driving.

## 6. OS integration still required

The combined image includes SPI/MCP2515 support, firmware overlays,
`iproute2`, a receive-only capture helper and a CAN startup service. However,
`livi-can.service` fixes the bitrate at 1000000, which the stock 8 MHz
CarPiHAT controller cannot achieve. ECU configuration alone does not make
this image a working CarPiHAT solution. Remaining requirements are:

- Verify the selected adapter's driver and firmware overlays on hardware.
  Resolve SPI0 CS1's conflict with the CarPiHAT reverse input on BCM7.
- Include `can-utils` and `iproute2` with CAN configuration support.
- Validate the shipped root-owned, no-argument `/usr/libexec/livi-can-capture`
  helper and restricted sudoers permission against the
  [LIVI OS contract][contract]. It must verify the interface and remain receive-only.
- Ensure that the actual adapter is consistently `can0`.
- Hardware-test the shipped contract-v2 helper set; `LIVI_OS=1` affects more
  than CAN capture.
- For route B, deliberately document/support **500000** in the image's
  startup/helper configuration. The published contract specifies **1000000**
  when bringing a down interface up. The decoder does not set bitrate itself;
  this requires OS policy/integration, not different RPM/speed decoding.
- Validate the actual installed AppImage; it persists across OS upgrades.

Do not implement this by making the privileged helper accept arbitrary
interface names, bitrates or shell commands from LIVI.

## Sources and evidence boundaries

1. [Haltech: Introducing Generic CAN][gcan] - primary source for supported
   models, firmware/software baseline, per-bus enablement and bitrate choices.
2. [Haltech ECU Broadcast CAN Protocol][protocol] - download document version
   2.0 from the article. Its key-information section specifies 1 Mbit/s,
   11-bit IDs and big-endian data; its broadcast table specifies `0x360`
   and `0x370`, units, conversion and rates.
3. [CarPiHAT Quick Start Guide][carpihat] - hardware oscillator, GPIO and
   onboard termination. Its example bitrate is not a Haltech configuration.
4. [LIVI receiver][receiver] and [OS contract][contract] - implementation
   reviewed at app revision `8044abb3`: accepted frames, freshness, `can0`,
   capture command and privileged-helper requirements.

No exact ECU model, NSP screen session or physical CAN capture was available
for this guide. Route B is therefore a researched configuration recipe that
still requires model-specific confirmation and bench validation, not a
hardware-tested solution.

[gcan]: https://www.haltech.com/introducing-generic-can/
[protocol]: https://support.haltech.com/portal/en/kb/articles/haltech-can-ecu-broadcast-protocol
[carpihat]: https://github.com/SamT-J/CarPiHat/wiki/Quick-Start-Guide
[receiver]: https://github.com/DrSkunk/LIVI/blob/8044abb3/native/crates/livi-core/src/haltech_can.rs
[contract]: https://github.com/DrSkunk/LIVI/blob/8044abb3/docs/LIVI-OS.md
