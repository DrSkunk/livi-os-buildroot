# Haltech CAN telemetry with CarPiHAT and LIVI

Protocol: Haltech ECU Broadcast CAN Protocol 2.0. The updated OS implements
CAN bring-up and capture; install the updated LIVI AppImage for all decoders.
Real-bus acceptance and the PRO 5's physical crystal still require verification.

For the **Elite 2500 auxiliary CAN port**, route A receives Haltech broadcasts.
The optional active **OBD-II backend in section 7** instead uses Vehicle CAN
and requires separate bitrate/ECU validation. Route B below is reference
material for eligible Nexus hardware, not an Elite workaround.

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
This older guide does not establish the oscillator fitted to every PRO 5
revision. Identify the installed board's clock before applying that limit
to it. The [quick-start walkthrough](./hardware-setup-pi5.md#optional--haltech-can-telemetry)
covers direct Elite 2500 auxiliary-port wiring and standard-broadcast setup.

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

For `0x360` and `0x370`, LIVI ignores bytes 2-7. Standard Haltech frames also
carry other channels in those bytes; do not overwrite them.

The full implemented receive set is:

| Signal / telemetry key | ID | Bytes (zero-based) | Conversion from unsigned big-endian raw |
| --- | --- | --- | --- |
| RPM / `rpm` | `0x360` | 0-1 | raw |
| Speed / `speedKph` | `0x370` | 0-1 | raw / 10 |
| Battery / `batteryV` | `0x372` | 0-1 | raw / 10, V |
| Coolant / `coolantC` | `0x3E0` | 0-1 | raw / 10 - 273.15, Celsius |
| Oil pressure / `oilPressureKpa` | `0x361` | 2-3 | raw / 10 - 101.3, gauge kPa |
| Wideband sensor 1 / `lambda` | `0x368` | 0-1 | raw / 1000 |
| Knock level 1 / `knock1Db` | `0x36A` | 0-1 | raw / 100, dB |
| Knock level 2 / `knock2Db` | `0x36A` | 2-3 | raw / 100, dB |

Oil pressure and knock need at least four payload bytes; the other decoded
signals need two. Truncated, malformed, extended, RTR and CAN FD frames are
ignored. Each signal expires to `null` after 1.5 seconds without a valid frame,
and disabling reception clears all received values. Knock levels are not knock
counts or ignition retard. Lambda uses sensor 1, not a sensor average; AFR
is fuel-dependent and is not inferred using a hardcoded gasoline ratio.
The ECU must have valid configured sensors. Dashboard themes choose which
fields to display; a decoder does not automatically add gauges.

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

1. In **ESP**, press **F4 / Setup > Devices**. Under **Bus Selection / Port**,
   select **Aux CAN Bus Port** for the Haltech CAN devices/output. The
   auxiliary port is the ECU's 4-pin Deutsch DTM connector, not the CarPiHAT
   AUX connector. Keep the Haltech protocol at **1 Mbit/s**.
2. Under **Displays**, enable **Haltech CAN supported dash**, then save/write
   the map. These labels are from Haltech's [Devices documentation][devices];
   use the corresponding help for firmware using NSP instead of ESP.
   Verify the map persisted and the normal broadcast is present. GCAN is not
   needed and is not supported on Elite.
3. Check live engine RPM and vehicle speed in the ECU software first.
4. Connect an appropriate CAN adapter, then capture all seven IDs above.
   Validate battery, temperatures, oil, lambda and knock against the live
   ECU channels too. Do not alter existing sensor or peripheral assignments.

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

Haltech's [auxiliary-port documentation][aux] specifies pin 1 = +12V,
2 = signal ground, 3 = CAN-H, 4 = CAN-L. Identify cavity numbers from the
manufacturer's connector-view drawing. Connect to the HAT's CAN socket
through the matching DTM lead and Nano-Fit pigtail; insulate unused +12V.

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
Route B needs a deliberately different OS policy; the shipped service only
supports route A. For route A's full seven-ID capture use the helper in section 6.

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
- Selecting **Settings > Car > CAN Telemetry > Haltech V2** and switching on
  **Enable CAN telemetry** updates LIVI.
- Disconnecting the signal produces stale telemetry after about 1.5 seconds,
  and reconnecting restores updates. LIVI's dashboard can display missing
  readings as zero, so a displayed zero alone does not prove reception.

Keep the vehicle stationary for initial checks. Do not operate a laptop or
adjust ECU settings while driving.

## 6. OS configuration and acceptance

Both images include MCP2515 and `gs_usb` drivers, `iproute2`, `can-utils`,
hotplug configuration and a root-owned no-argument capture helper.
`livi-can.service` uses **1000000 bit/s, listen-only**. The device starts the
service through udev; removing the device stops the service, allowing clean
USB reconnects. A missing optional CAN interface does not delay normal boot.
The capture helper starts the fixed service and verifies UP, bitrate,
listen-only and bus state before opening the receive socket. Errors go to
stderr and return nonzero; LIVI retries with bounded backoff.

Set the HAT's **actual** crystal when building, for example:

```sh
# Only for a confirmed physical 16 MHz crystal:
make pi5 LIVI_CAN_OSCILLATOR=16000000
```

`20000000` supports an actual 20 MHz crystal. This works for `make pi4` too.
The generated config enables SPI0 CS0, MCP2515 interrupt BCM23 and the
`spi0-1cs` overlay, leaving BCM7 free for the reverse input. The obsolete
`spi-bcm2835-overlay` is not used. Rebuilding replaces rather than duplicates
the CAN configuration.

The empty default leaves the SPI CAN overlay disabled instead of guessing
an unknown PRO 5 crystal. Use a compatible 1 Mbit/s listen-only `gs_usb`
adapter as `can0` in that case, keeping the HAT for power. Multiple adapters
need explicit stable naming before use. `8000000` is supported for a verified
500 kbit/s OBD-II bus (section 7), **not** for 1 Mbit/s V2. Declaring 16 MHz
for an 8 MHz crystal cannot solve the hardware limit. Selecting the ECU
auxiliary connector does not change it.

On the target:

```sh
systemctl restart livi-can.service
ip -details -statistics link show can0
journalctl -u livi-can.service -b
sudo -n /usr/libexec/livi-can-capture
```

Capture accepts only the seven standard data IDs in section 2. Install both
the updated AppImage and OS: old OS filters discard the additional frames,
and an old app ignores them even with the new OS. Existing helper arguments
and output framing remain compatible; no broader sudo permission is needed.
The image intentionally does not implement route B's 500 kbit/s policy.

Bench tests cover decoding, expiry, enable/disable, frame filters, readiness
failures and generated configuration on both Pi variants. They do not prove
the physical crystal, wiring, termination, ACK topology or real ECU output.
Complete section 5's cold-boot, disconnect/reconnect and live-value checks.

## 7. Optional Elite OBD-II backend

**Hardware acceptance pending.** The Elite auxiliary port can be assigned to
Vehicle CAN with OBD-II output, but its actual diagnostic bitrate and response
IDs must be established on the installed ECU. Neither the port's name nor
enabling OBD-II proves 500 kbit/s support. Do not disturb an occupied vehicle
network or change a working Haltech-peripheral assignment blindly.

Back up the map, use **ESP F4 > Devices**, assign the auxiliary connector to
Vehicle CAN where appropriate, and enable its OBD-II output. Save, reconnect,
and verify the assignment. The **Haltech CAN supported dash** checkbox is for
V2 broadcast, not OBD-II. Confirm the ECU/firmware-specific configuration
using Haltech's [Vehicle CAN documentation](https://support.haltech.com/portal/en/kb/articles/vehicle-can-system).

### Enable from LIVI

Use the updated OS and AppImage together:

1. Keep **Settings > Car > Enable CAN telemetry** off initially.
2. In **CAN Telemetry**, choose **Haltech OBD-II (active, read-only Service 01)**.
3. Select the independently verified bitrate, **500 kbit/s** or **1 Mbit/s**.
4. Acknowledge that the wiring, bitrate and ECU port assignment are validated.
5. Turn on **Enable CAN telemetry**. Without acknowledgement the status remains
   **Not configured** and no worker is launched.
6. Open **OBD-II status and live values** to check ECU ID, supported PIDs,
   response age, live values, signal freshness and request/timeout/error counts.

Changing the bitrate clears the acknowledgement. Disabling telemetry, closing
the app, switching backends or losing its stdin lifeline stops requests.
The worker leaves the interface down; selecting V2 configures listen-only
again. Existing `haltechCanEnabled` settings retain passive V2 behavior unless
the new backend is explicitly selected. No power/ignition behavior changes.

### Immutable transmission policy

`sudo -n /usr/libexec/livi-obd2 500000` (or `1000000`) is the only new
privileged entry point. Its wrapper accepts exactly that bitrate, clears
the environment and executes the immutable Python worker. It accepts no
interface, CAN ID, PID, payload, shell command or code path from the AppImage.
The app must retain stdin; EOF ends the worker. It is app-supervised, not an
autonomously enabled boot polling service.

The worker and passive capture hold an exclusive `can0` lock. OBD stops the
passive configuration service, sets the selected bitrate and **listen-only
off**, verifies real SocketCAN state, and rechecks it during polling.
Bitrates are not auto-detected or silently changed. An incompatible 8 MHz /
1 Mbit/s setup fails visibly. Startup is intentionally not an automatic
physical-layer probe.

Only Service 01 is transmitted: initial functional request `0x7DF` for PID
`00`, then physical requests `0x7E0`-`0x7E7` to the first responding ECU
(`0x7E8`-`0x7EF`). Capability pages `00`, `20`, `40` restrict subsequent
queries to supported allowlisted PIDs. Responses must match address, service,
PID and exact data length. Extended/RTR/error, malformed and multi-frame
responses are not decoded as live data.

| PID | Normalized field | Conversion |
| --- | --- | --- |
| `0C` | `rpm` | `(256*A+B)/4` |
| `0D` | `speedKph` | `A` |
| `05` | `coolantC` | `A-40` |
| `0F` | `iatC` | `A-40` |
| `0B` | `mapKpa` | `A`, absolute kPa |
| `11` | `throttlePct` | `100*A/255` |
| `0E` | `timingAdvanceDeg` | `A/2-64` |
| `42` | `batteryV` | `(256*A+B)/1000` |
| `1F` | `engineRunTimeS` | `256*A+B` |
| `2F` | `fuelPct` | `100*A/255` |
| `5C` | `oilC` | `A-40` |
| `52` | `ethanolPct` | `100*A/255` |

These are supported decoders, not a promise that every ECU sensor/PID exists.
Oil pressure and knock are not standard PIDs in this subset; use V2 for them.
Vehicle speed still requires a valid ECU speed source. GPS remains independent;
this backend does not invent a speed source or replace missing values with zero.
An actual zero reply is valid. Missing/stale readings clear to `null`.

The hard ceiling is **10 requests/second**, one outstanding request and a
300 ms response deadline. Nominal periods: RPM/speed 0.2 s, MAP/throttle 0.5 s,
temperatures/voltage/timing 1 s, other slow channels 5 s; the overall ceiling
takes priority, so achieved rates can be lower. Timeouts back off per PID;
three consecutive misses suppress it until rediscovery. A missing ECU retries
capability discovery with 2-30 s backoff. Freshness deadlines are
`max(1.5 s, 3 * nominal period)`; healthy slow sensors do not flicker stale.

Selected Service 01 responses and bitmaps all fit ISO-TP Single Frames.
VIN, diagnostic trouble codes, multi-frame services, ECU writes, security
access and actuator controls are intentionally not implemented or permitted.
`CONFIG_CAN_ISOTP` is included for future separately reviewed transport work,
not a claim of multi-frame support here. Diagnostics are not safety-critical
instrumentation. The live-values page exposes all received fields; existing
dashboard layouts still determine gauge placement.

### Acceptance

Test a stationary, correctly terminated bus. Confirm successful PID `0C`
responses and compare all supported values with ESP. Exercise unsupported
channels, no response, bus-off, cable removal/reconnect, enable/disable, backend
switching, app exit and cold boots. Check that requests cease on disable and
ignition-off shutdown; confirm power cycling remains reliable. Automated tests
simulate responses and lifecycle behavior but cannot validate the ECU bitrate,
actual controller clock, wiring, electrical safety or sensor calibration.

## Sources and evidence boundaries

1. [Haltech: Introducing Generic CAN][gcan] - primary source for supported
   models, firmware/software baseline, per-bus enablement and bitrate choices.
2. [Haltech ECU Broadcast CAN Protocol][protocol] - download document version
   2.0 from the article. Its key-information section specifies 1 Mbit/s,
   11-bit IDs and big-endian data; its broadcast tables specify the signal
   offsets, units, conversions and rates used above.
3. [CarPiHAT Quick Start Guide][carpihat] - hardware oscillator, GPIO and
   onboard termination. Its example bitrate is not a Haltech configuration.
4. [LIVI receiver][receiver] and [OS contract][contract] - update both local
   checkouts before building; remote links can lag uncommitted changes.
5. [Haltech Devices][devices] and [Auxiliary CAN Bus Port][aux] - ECU port
   selection, dash enablement and connector pinout. No live ECU session or
   physical CAN capture was available; real-hardware acceptance remains open.

[gcan]: https://www.haltech.com/introducing-generic-can/
[protocol]: https://support.haltech.com/portal/en/kb/articles/haltech-can-ecu-broadcast-protocol
[carpihat]: https://github.com/SamT-J/CarPiHat/wiki/Quick-Start-Guide
[receiver]: https://github.com/DrSkunk/LIVI/blob/main/native/crates/livi-core/src/haltech_can.rs
[contract]: https://github.com/DrSkunk/LIVI/blob/main/docs/LIVI-OS.md
[devices]: https://support.haltech.com/portal/en/kb/articles/devices
[aux]: https://support.haltech.com/portal/en/kb/articles/auxiliary-can-bus-port-7-4-2020
