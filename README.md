# LIVI OS for Raspberry Pi 4 and 5

Buildroot-based automotive image for [DrSkunk/LIVI](https://github.com/DrSkunk/LIVI).
The operating system is immutable, LIVI keeps its built-in AppImage updater, and
persistent configuration and ROM files live on a separate journaled filesystem.

## Status

The confirmed deployment scope is **Pi 4, Waveshare 7.9-inch HDMI/USB touch,
Canada (`CA`), dongle-based CarPlay/Android Auto, and native Android Auto without
a dongle**. Native Apple CarPlay is not part of this acceptance target.

**Rust migration in progress:** this source tree now requires a custom
Rust/Slint AppImage implementing [LIVI OS API 2](docs/rust-appimage-contract.md).
It launches Smithay directly on DRM/KMS, without Electron or Cage. The custom
AppImage must implement rotation, the immutable helper boundary and the readiness
heartbeat; an unmodified upstream Rust AppImage is not sufficient. No Rust
image or hardware acceptance has been completed yet.

Historical validation of the previous Electron image: the ARM64 LIVI AppImage and
full Buildroot disk image built successfully, and the actual Pi 4 kernel/root
boot under QEMU with read-only SquashFS/FAT, writable ext4, first-boot data
expansion and persistent-data setup passing. A separate Ubuntu ARM64 VM renders
LIVI's UI at 1280×400 using software rendering. Neither result validates physical
Pi graphics, touch, audio, radios, phone projection or firmware rollback.
The Pi-model emulator correctly fails kiosk readiness without the required
display/audio hardware; it is not an application acceptance pass.

This project produces separate ARM64 images for Raspberry Pi 4 and Raspberry Pi
5. The userspace and update/recovery design are shared; separate kernels are used
because the boards have different SoCs and kernel defconfigs.

The configuration includes:

- A/B SquashFS read-only roots and a normally read-only FAT boot partition
- ext4 `LIVI_DATA` partition for application/configuration/ROM state
- systemd, NetworkManager, BlueZ, hostapd, dnsmasq and Avahi
- Mesa V3D/VC4, DRM/KMS, Wayland, seatd and libinput for the Rust compositor
- PipeWire, its PulseAudio compatibility server, and WirePlumber
- Python 3 for OS recovery, readiness and CAN capture tools; immutable Rust projection helper
- SPI/MCP2515 drivers and listen-only CAN tooling; the fixed 1 Mbit/s service
  still needs adaptation for stock 8 MHz CarPiHAT hardware (see below)
- libxkbcommon, libgudev and libva for the Rust graphics/media runtime
- PulseAudio client tools for volume control, and SBC for PipeWire Bluetooth audio
- RetroArch 1.22.2 with pinned NES, SNES, GB/GBC, GBA, Genesis and Master System cores
- minidsp-rs 0.1.12 daemon and loopback API on port 5380
- writable AppImage updates plus signed A/B OS updates and rollback
- last-known-good `config.json` recovery

The immutable image includes Nestopia UE (NES), Snes9x (SNES), Gambatte
(Game Boy and Game Boy Color), mGBA (Game Boy Advance), and Genesis Plus GX
(Genesis/Mega Drive and Master System). LIVI's importer resolves these exact
core filenames from `/usr/lib/libretro`; ROMs, playlists, thumbnails, saves and
user-installed cores remain writable under `/data/games`.

mGBA's optional link-time optimization is disabled because the pinned GCC 14.3
toolchain hit an internal `jobserver_info::return_token` compiler error at the
final link during Linux-container validation. Normal compiler optimization and
the core's features remain enabled.

RetroArch uses the `glcore` video driver and the touch-oriented **GLUI** menu,
with bundled fonts/icons and touch-pointer navigation enabled. It runs fullscreen
with the `wayland` input driver so taps and swipes arrive through LIVI's
compositor in screen coordinates; gamepads still use the `udev` joypad driver.
RetroArch is patched so menu drag/swipe keeps working on panels whose EDID
reports no physical size. The legacy `gl` driver crashes during Wayland/EGL
startup on the Pi. On the first boot after this update, existing settings are
backed up as `retroarch.cfg.before-touch-v2` and
the graphics/menu/input/asset settings are repaired once. Other settings,
including custom save directories, are preserved; subsequent user edits are not
reset on boot. Configuration lives in `/data/games/retroarch/retroarch.cfg`.

The starter library includes **Red Rod Racing** (Game Boy, MIT) and **Tobu Tobu
Girl** (Game Boy, MIT code / CC BY 4.0 assets). ROM downloads are pinned and
SHA-256 verified, with attribution under `/usr/share/doc/livi-homebrew`.
Red Rod Racing uses Start to begin, A to select/accelerate, and the D-pad to
steer. Use a gamepad for gameplay; touch is for the menus.
Standard Linux gamepad profiles are included. Press **Start + Select** together
to open the RetroArch menu during a game, then choose **Quit RetroArch** to
return to LIVI.

In native LIVI, keep using the Games cards to launch games. **Add games → Browse**
copies an extracted ROM from local storage or a mounted USB drive; **Rescan**
imports ROMs placed directly in `/data/games/roms`. **Basic settings** opens
LIVI's Games settings, while **RetroArch** opens the full emulator configuration.

Genesis Plus GX is the core currently hard-coded by LIVI for both Genesis and
Master System. Its upstream license is non-commercial. Do not distribute this
core in a commercial product without separate permission; replace it and update
LIVI's core mapping for a commercial deployment.
Android Auto and the common wireless OS stack are included. Native Apple CarPlay
remains outside the acceptance scope and requires separate hardware and protocol
integration. Python projection drivers and their pip dependencies are no longer
used. Actual Rust phone/dongle sessions still require hardware testing.

## Boot splash

Both boards use the supplied `ZIP_TIE_TUNING_LOGO-14.eps` vector artwork,
rendered as an antialiased white logo on a black 1280x400 RGB canvas in
`board/drskunk/livi/boot-splash.png`. Empty source margins are removed without
cropping the artwork; the logo is fitted to 651x320 pixels and centered with
40-pixel top/bottom margins. An early
`livi-splash.service` draws it with psplash as soon as Linux exposes `/dev/fb0`,
without waiting for networking or the data partition. It rotates the framebuffer
90 degrees for the Waveshare panel. The Pi firmware rainbow and Linux penguin
logo are disabled; normal boot messages stay off the HDMI screen. Serial
diagnostics and the system journal remain available.

LIVI explicitly stops the splash before starting its supervisor so it cannot
compete with the Rust DRM compositor. The two services must not conflict:
requesting both during boot can otherwise discard the splash start job.
Image assembly refreshes the board's kernel command line on every build,
including incremental builds, so stale firmware-package output cannot
restore HDMI console text.
A brief black handoff is possible; this does not promise a
first-frame-seamless transition. No image can be displayed by this service
before Linux/KMS has initialized, and panel timing must be checked on the Pi.
The artwork is compiled into psplash and requires an OS rebuild to change.
This is included in the next image build, not the previously flashed image.

The bundled GStreamer libav plugin needs libva (including its X11 library),
libssh and the Vulkan loader even when decoding H.264 or H.265 in software.
Both images include these runtime libraries; they do not imply VA-API or
Vulkan hardware decoding support, and the kiosk continues to use Wayland.

## Host requirements

An x86-64 Linux build host (required by the prebuilt Bootlin toolchain) with Git, GNU Make, GCC, Python 3.11+, `curl`, `readelf`, `unsquashfs`, and normal
Buildroot host prerequisites is required. Expect a substantial first build: the
AppImage includes its Rust UI/media payload and the graphics/audio stack is compiled
from source.

## Build

Buildroot is pinned to `2026.05.1` and its exact commit is verified by the wrapper.

```sh
make bootstrap

# DrSkunk/LIVI currently publishes the ARM64 build on its nightly release tag.
make fetch-livi
make check-livi

make pi4
make pi5
```

Outputs:

```text
output/pi4/images/livi-os-rpi4.img
output/pi5/images/livi-os-rpi5.img
```

`make fetch-livi` (or `support/fetch-livi` with no arguments) defaults to
`nightly`, matching the published ARM64 release and CI. Override it with
`LIVI_CHANNEL=stable` for GitHub's latest non-prerelease (currently unavailable),
or `LIVI_CHANNEL=<tag>` for a specific release. Run `make test-fetch-livi` to
check release selection offline.

`make fetch-livi` validates the AppImage type and AArch64 ELF machine and writes
a local SHA-256 file. Both fetch and package installation reject payloads without
the Rust/API-2 layout; the nightly download cannot be used until your app
publishes that integration. You can instead supply the custom AppImage and its
SHA-256 sidecar under `artifacts/`. `make check-livi` validates that local payload
before a lengthy build. Start with a **fresh output tree** when migrating from
Electron: Buildroot does not remove obsolete packages from incremental targets.
For a reproducible production release, archive the exact
AppImage and its hash rather than resolving the rolling nightly tag again.

Validate both Buildroot defconfigs and shell syntax with:

```sh
make check
make test-runtime
```

Recovery and payload tests require Python 3.11+, Bash, `jq`, `mksquashfs` and
`unsquashfs` (the latter two come from `squashfs-tools`). `make check` resolves the
x86-64 CI configuration on any host; it does not compile or boot an image.

### Building on macOS / Apple Silicon

Use Docker's Linux VM with x86-64 emulation for the Bootlin toolchain. Keep the
Buildroot checkout and all compiled output on the Linux volume: macOS-generated
host tools cannot run in Linux, and source builds require a case-sensitive
filesystem. Do not reuse `output/` across different host operating systems.

```sh
docker build --platform linux/amd64 -t livi-build -f support/Dockerfile .
docker volume create livi-build
docker run --rm --platform linux/amd64 \
  -v "$PWD:/workspace" -v livi-build:/build livi-build \
  sh -ec 'make fetch-livi;
          make pi4 BUILDROOT_DIR=/build/buildroot OUTPUT_BASE=/build/output'
```

Builds run as an unprivileged user and do not need privileged containers or host
device access. The image is `/build/output/pi4/images/livi-os-rpi4.img` inside the
volume. Preserve that volume to resume builds. Allow ample disk space for
downloads, compiler output and the multi-gigabyte disk image; emulated x86-64
compilation is significantly slower than native Linux.

To limit compilation concurrency, pass `BR2_JLEVEL=4` to `make` rather than
invoking the wrapper with `make -j4`. This leaves package-level parallelism to
Buildroot and avoids passing an outer jobserver into Kconfig's recursive Make
probes. The latter failed with `write jobserver: Bad file descriptor` during
BusyBox configuration in the x86-64 container validation.

### Pi 4 emulator smoke test

With QEMU supporting `raspi4b`, export the Linux build's images to the host
without mixing its compiled host tools into the macOS output tree:

```sh
docker create --name livi-export -v livi-build:/build:ro livi-build true
mkdir -p output/pi4
docker cp livi-export:/build/output/pi4/images output/pi4/
docker rm livi-export
./support/qemu-pi4 output/pi4/images
```

The test uses the built Pi 4 kernel and DTB with a disposable 8 GiB copy-on-write
SD card, preserving the original image. It allows five minutes to observe the
guest's `LIVI_QEMU_STORAGE_OK` marker after checking systemd's persistent-data
setup, read-only SquashFS/FAT mounts, writable ext4 and first-boot data growth.
The guest check runs only with `livi.qemu_test=1` on the kernel command line.
A timeout or early emulator exit fails the test and preserves the serial log.
The direct-DTB test selects the emulated PL011 console at `ttyAMA1` and disables
systemd's runtime watchdog via `systemd.watchdog_sec=0`: initializing the
emulated BCM watchdog reset QEMU before data setup completed. These overrides
apply only to the emulator command line; the production watchdog stays enabled
and must be checked on a real Pi.

For a visible window at the panel's 1280×400 pixel size, run:

```sh
./support/qemu-pi4 --preview output/pi4/images
```

This selects Cocoa on macOS (GTK or SDL on Linux) and attaches generic USB
keyboard and absolute-pointer tablet devices. After the storage check passes,
the window stays open until closed or interrupted. The five-minute failure
deadline still applies before that check passes. The framebuffer dimensions are
not HDMI EDID/timing emulation; the tablet is not a Waveshare multitouch device.
QEMU's Pi framebuffer does not implement the VC4/V3D DRM hardware required by
the production Wayland kiosk, so a visible window may show only boot output or
a blank framebuffer, not LIVI. A blank window is not an application test pass.
No host microphone, USB phone, dongle or radio is passed through by this command.

An interactive LIVI UI preview needs a separate generic ARM64 VM with a VirtIO
GPU and software rendering; it is not a boot of this Buildroot image. For example,
Ubuntu 24.04 ARM64 can run Sway with a custom 1280×400 output mode and launch LIVI
with `LIVI_NO_COMPOSITOR=1`, `--disable-gpu` and `--disable-gpu-rasterization`.
These are preview-only settings: they bypass LIVI's custom video compositor and
do not validate the production VC4/V3D/projection path. Do not apply them to the
Pi appliance. QEMU's bundled UEFI may assert on a 400-pixel-high boot console;
boot the virtual GPU at 1280×800 and set 1280×400 in the guest compositor instead.
Generic USB keyboard/tablet/audio devices and NAT networking can exercise guest
input, sound routing and network clients, not Waveshare multitouch, Pi radios or
CarPlay/Android Auto phone protocols.

**This is a storage/boot smoke test, not a complete Raspberry Pi or LIVI acceptance
test.** Direct kernel loading bypasses EEPROM/firmware and tryboot. QEMU cannot
establish correct VC4/V3D acceleration, Waveshare HDMI timings/touch mapping,
physical audio, Bluetooth/Wi-Fi, USB phone projection or MFi authentication.
Do not relax kiosk health checks just to make an emulator report success.

### Pi 4 UART boot diagnostics

Kernel modules are XZ-compressed. Both the build host's `depmod` and target
module loader must support XZ; image validation rejects an empty or incompatible
module dependency index. VC4's SoC-audio dependency is built in so Kconfig does
not silently downgrade the display driver to a module.

Both board defconfigs enable `BR2_PACKAGE_XZ`, which enables target kmod's
XZ support. `BR2_PACKAGE_HOST_KMOD_XZ` only affects the build host's tools.
Without target support, compressed drivers such as HDMI's DDC I2C driver
cannot load, leaving VC4 waiting for a dependency and the display black.
For an existing build configured without target XZ support, rebuild kmod
before assembling the image again (use `pi5` instead of `pi4` for Pi 5):

```sh
make pi4_defconfig
make -C buildroot O="$PWD/output/pi4" kmod-dirclean
make pi4
```

After flashing, `modprobe --version` must report `+XZ`.

New Pi 4 builds enable the GPIO mini UART at **115200 baud, 8N1, no flow
control** (`enable_uart=1`, `console=ttyS0,115200`). Bluetooth retains its
PL011 UART; do not add `disable-bt` or `miniuart-bt` overlays to this setup.
Enabling the mini UART fixes its clock through the Raspberry Pi firmware.
Kernel informational messages are enabled for boot diagnostics. Password login
remains disabled: this provides boot output, not a passwordless debug shell.

With the Pi powered off, connect a **3.3 V TTL** USB-UART adapter (or Flipper
Zero in GPIO USB-UART bridge mode):

| Pi 4 physical header pin | Function | Adapter connection |
| --- | --- | --- |
| 8 (BCM14) | TX | RX |
| 10 (BCM15) | RX | TX |
| 6 | Ground | Ground |

Do not connect adapter 5 V/3.3 V power pins, use an RS-232 adapter, or connect
UART to the CAN port. Confirm the HAT leaves BCM14/15 free before connecting
through a stacked header. Power the Pi normally, connect the adapter to the
computer, and start serial capture before powering on the Pi.

These changes apply to the next image build, not an already flashed SD card.
The boot-file compatibility checks require an OS rebuild; editing boot files
on an existing appliance is not a production update.

### Appliance security profile

Root and LIVI password logins are disabled; there is no shared factory console
password. Recovery requires trusted physical media access or a deliberately
provisioned development image. This is not Raspberry Pi secure boot and does not
protect against an attacker who can replace the boot media.

Pi 4 images enable SSH only when the local, git-ignored
`artifacts/livi-debug-authorized_keys` file contains one or two Ed25519 public
keys. SSH permits those keys for the `livi` account only; SSH password/root login
and all forwarding are disabled. A per-build random password hash (with its
plaintext discarded) lets OpenSSH accept public-key authentication for the
otherwise locked account. Keep the Pi on a trusted LAN and do not forward port
22 from the internet. Connect from the same LAN with
`ssh -i ~/.ssh/livi-debug livi@livi.local`. Remove the key artifact and rebuild
to disable SSH; changing the authorized key requires another OS image build.
The host key is generated on first boot and stored on the writable data partition.

The application supervisor, logger and configuration guard run as `livi`, not
root, so writable AppImage/configuration paths cannot turn their file operations
into privileged writes. Native API-2 LIVI starts the immutable
`/usr/libexec/livi-helperd` with `sudo -n`, no arguments and a command-scoped
environment allowlist. Only its Wi-Fi teardown switch, exact stale-helper
cleanup patterns, AP service controls, CAN capture and boot-health commands
are additionally permitted. Installer switches, arbitrary commands and writable
helpers are not authorized, and there is no `SETENV` permission. Helper code changes
require an OS update, independently of writable AppImage updates.
The OS also installs the factory AppImage's canonical USB allowlist and
dual-interface touchscreen filter; a writable app update cannot install a new
udev policy without an OS update.

The ARM64 AppImage must include the matching launcher integration from the LIVI
app repository and declare helper API `2` in `resources/livi-os-helper-api`.
See the [complete Rust app contract](docs/rust-appimage-contract.md), including
wireless service integration, helper lifeline and readiness reporting.
The obsolete five-argument projection wrapper is not the native API-2 interface.
Image creation rejects older payloads; there is no Electron compatibility mode.
The factory payload is checksum-checked at installation and reinstalled when its
file/checksum changes during an incremental build.
It is excluded from ELF stripping, which would discard the appended AppImage
filesystem. Post-build validation verifies the installed payload's checksum
after target finalization and checks keyboard layout data and Rust runtime libraries.

Fresh installations seed a random 32-character Wi-Fi password, Canadian
regulatory country (`CA`), and a 1280×400 main kiosk window for the confirmed
Waveshare panel. Set the correct country in LIVI before operating elsewhere. Existing
configuration and last-known-good backups are preserved; change legacy/default
passwords in LIVI's Wi-Fi settings. GTK/NSS/CUPS and Chromium namespace/sandbox
launch logic have been removed. These are hardening measures, not a security certification:
unsigned upstream AppImage updates and the privileged helper's broader interfaces
still require review before production deployment.

## Continuous integration and releases

GitHub Actions builds the Pi 4 and Pi 5 images in parallel on every push to
`main`. Buildroot downloads and a board-specific 2 GiB compiler cache are kept
between runs. Main-branch builds publish images to the rolling `nightly` release.

Push a semantic version tag to create a release:

```sh
git tag v1.0.0
git push origin v1.0.0
```

The workflow first creates a draft release, builds and validates both images,
uploads XZ-compressed images and SHA-256 files, and publishes the release only
after both parallel jobs succeed. If either board fails, the incomplete release
remains a draft and can safely be retried; successful uploads use `--clobber`.

Manual workflow runs can select `pi4`, `pi5` or both and a specific LIVI release
tag (including prereleases). Every build uploads the compressed flashable image
and checksum as a workflow artifact, without replacing the nightly release when
building a topic branch.

## Flashing

Double-check the destination device. Writing an image destroys its existing
partition table and filesystems.

```sh
sudo dd if=output/pi5/images/livi-os-rpi5.img of=/dev/DEVICE \
  bs=4M conv=fsync status=progress
```

Use the Pi 4 image only on Pi 4/CM4-class boards and the Pi 5 image on Pi 5.
The same Pi 5 image can be written to microSD or NVMe.

### Pi 5 NVMe boot

The Pi EEPROM boot order must include NVMe boot mode `6`. Configure that from a
known-good Raspberry Pi OS installation (`raspi-config` Advanced Options / Boot
Order) before relying on NVMe. The image enables the Pi 5 PCIe controller in
`config.txt`; a standards-compliant HAT+ remains recommended. PCIe Gen 2 is kept
at the supported default.

### Waveshare 7.9inch HDMI LCD

Both images target the [Waveshare 7.9inch HDMI LCD](https://www.waveshare.com/wiki/7.9inch_HDMI_LCD)
with HDMI video and five-point USB capacitive touch. Connect the LCD's HDMI
input to the Pi's HDMI0 port (`HDMI-A-1`, nearest the USB-C power connector),
and its TOUCH port to a Pi USB port before powering on.

The desktop is **1280×400 landscape**. HDMI still scans out the panel's native
400×1280 mode; the API-2 Rust compositor must apply the requested 90° output
transform at startup and after reconnection, map USB touch to `HDMI-A-1` with the
same transform, and keep HDMI1 disabled. Do not add a second libinput
calibration rotation. This is a custom-app requirement, not an upstream guarantee.
The console uses `fbcon=rotate:1` independently of the application.

On a fresh data partition, LIVI's main projection and instrument-cluster
stream default to **1280×400**. The cluster map can therefore extend behind
the gauges rather than being confined to a centered 16:9 image. Android Auto
may still transmit a standard 1280×720 video frame with margins. Existing
configuration and last-known-good backups are preserved; change the projection
and cluster dimensions in LIVI if a different display is used.

Both Pi images use full KMS and the panel's EDID for detailed timings. The wiki's
legacy `hdmi_group`, `hdmi_mode` and `hdmi_timings` settings are not used. Connect
HDMI and USB before boot; if the native mode is missing, inspect the EDID and
cable rather than substituting generic CVT timings. The previous DSI panel
configuration and automatic DSI detection are disabled.

The startup health check verifies the compositor's active native mode, 90°
transform and scale, plus the PipeWire/PulseAudio sockets and a live connection
to LIVI's internal compositor. These checks continue after startup so a dead
internal compositor cannot leave an apparently healthy black screen. Verify all
four touch corners on the physical panel before installation.

### Haltech CAN V2 telemetry

The Pi 4 image includes a receive-only CAN service, but its fixed 1 Mbit/s
setting is incompatible with the stock 8 MHz CarPiHAT MCP2515 controller.
See the [Haltech CAN wiring and setup guide](docs/HALTECH-CAN.md) for hardware
limitations, supported ECU routes and remaining OS integration requirements.
Do not treat the current image as a verified CarPiHAT telemetry solution.
QEMU cannot verify MCP2515 electrical behavior or the vehicle bus.

## Disk layout and power-loss behaviour

| Partition | Filesystem | Normal mount | Purpose |
|---|---|---|---|
| `LIVI_BOOT` | FAT32, 256 MiB | `/boot` read-only | Firmware, DTBs, kernel |
| root A | SquashFS | `/` read-only when active | Immutable Buildroot OS slot A |
| root B | SquashFS | `/` read-only when active | Immutable Buildroot OS slot B |
| `LIVI_DATA` | ext4, initially 2 GiB | `/data` read-write | Updates, config, pairing, ROMs, saves, logs |

The data filesystem uses journaling, barriers, `noatime`, a five-second commit
interval, and `errors=remount-ro`. `/run`, `/tmp`, and `/var/log` are tmpfs. On
the first boot, `livi-data-grow` extends the final data partition over unused SD
or NVMe capacity and grows ext4 online. It saves the pre-change GPT dump in
`/run`, updates only the known final partition, and records `/data/.expanded`
after `resize2fs` and `sync` complete.

Important persistent paths:

```text
/data/livi/app/LIVI.AppImage
/data/livi/app/LIVI.AppImage.previous
/data/livi/config/LIVI/config.json
/data/livi/log/LIVI.log
/data/livi/update/
/data/os-update/
/data/games/roms/
/data/games/saves/
/data/games/states/
/data/games/retroarch/
/data/etc/minidsp/config.toml
/data/bluetooth/
/data/lockdown/
/data/network/system-connections/
/data/etc/NetworkManager/conf.d/
```

LIVI-required mutable system configuration (`/etc/bluetooth`, NetworkManager
profiles, LIVI udev rules and locally generated systemd units) is bind-mounted
from `/data`. NetworkManager's AP ownership drop-in directory is also writable
and migrated; wired iPhone lockdown pairing records persist in a root-only
`/data/lockdown` bind mount. Factory configuration is migrated before mounting: untouched
files follow new defaults, obsolete untouched files are removed, and local edits
or deletions are preserved. The baseline is stored under `/data/etc-defaults`.
Conflicting new defaults are saved under each directory's `incoming/<revision>`
folder and listed in `conflicts.json`. Review these conflicts during OS upgrades.
Legacy installations without a baseline retain their existing files and receive
conflict proposals instead of having potentially customized files overwritten.
The same migration supports returning to an older OS's defaults after rollback.

## Clock and time sync

LIVI's sunrise/sunset night mode needs a correct wall clock, and only switches
day/night once the clock is confirmed by an RTC or NTP.

| Board | Time source at boot | Notes |
|---|---|---|
| Pi 5 | On-board RTC (`rtc0`) via kernel `hctosys` | Needs the RTC backup battery; without it the RTC resets on power-off |
| Pi 4 | Last synced time from `systemd-timesyncd` | No RTC; time is stale until NTP syncs over Wi-Fi/hotspot |

- The kernel restores system time from the RTC at boot (`CONFIG_RTC_HCTOSYS`)
  and writes NTP-synced time back to it (`CONFIG_RTC_SYSTOHC`).
- `systemd-timesyncd` syncs via NTP whenever a network is available. Its state
  (`/var/lib/systemd/timesync`) is bind-mounted from `/data/timesync`.
- Pi 5 battery charging is off by default. With the official rechargeable
  ML-2020 battery, uncomment `dtparam=rtc_bbat_vchg=3000000` in
  `board/drskunk/livi/config-rpi5.txt`. Never charge a CR2032.
- Pi 4 test rig: either keep Wi-Fi up for NTP or pick Day/Night manually in
  LIVI. An optional DS3231 module can be enabled in `config-rpi4.txt`.

Check on the device:

```sh
timedatectl                       # "System clock synchronized: yes"
cat /sys/class/rtc/rtc0/since_epoch
ls /run/systemd/timesync/synchronized
```

## LIVI updates and rollback

LIVI discovers the stable or nightly GitHub release itself. Its Linux updater:

1. downloads an ARM64 AppImage;
2. writes `LIVI.AppImage.new` next to the running payload;
3. changes its mode to executable;
4. atomically renames it over `LIVI.AppImage`; and
5. restarts the application.

This image launches LIVI from `/data/livi/app`, so that upstream update sequence
continues to work even though `/` is immutable. `TMPDIR` points at
`/data/livi/update`, keeping the 300+ MiB download off RAM-backed `/tmp` and on the
same filesystem as the destination. The app's home directory is
`/data/livi/home`, so home-relative application state remains writable on the immutable root.
The foreground Rust core runs under `dbus-run-session` so its children retain
a session bus. `XDG_DATA_HOME=/data/livi/state` preserves the Rust config backup.
`XKB_CONFIG_ROOT`
points bundled keyboard libraries at `/usr/share/X11/xkb`.

At boot, `livi-supervisor` compares the current AppImage with the recorded healthy
hash. A new hash is a candidate. If the API-2 frame/output heartbeat, live core,
UI and compositor processes, and audio sockets stay ready for 60 seconds, the
candidate is committed. After three failed candidate boots, the supervisor
atomically restores `LIVI.AppImage.previous`. If that copy is missing or does not
match the known-good hash, it restores `/opt/livi-factory/LIVI.AppImage` from
SquashFS.

An application rollback never rolls back user configuration or ROMs. The factory
copy is only updated when a new complete OS image is flashed.

### Update security

Upstream LIVI currently downloads its executable over HTTPS but does not verify a
separate project signature or signed checksum. Rollback protects availability,
not authenticity. Production deployment should add signed release metadata and an
immutable verification key, ideally by changing LIVI to hand the downloaded file
to an OS-provided installer helper before replacement.

### Manual recovery

From a root console, use this atomic recovery sequence:

```sh
cp /opt/livi-factory/LIVI.AppImage /data/livi/app/LIVI.AppImage.new
chmod 0755 /data/livi/app/LIVI.AppImage.new
sync
mv -f /data/livi/app/LIVI.AppImage.new /data/livi/app/LIVI.AppImage
rm -f /data/livi/update/pending /data/livi/update/good.sha256
sync
systemctl start livi
```

Removing `good.sha256` causes the next supervisor start to accept the restored
factory image as the initial known-good version.

## Operating-system A/B updates

The disk has paired boot and SquashFS root slots plus a boot-control partition:

| Partition | Purpose |
|---|---|
| 1 | FAT boot control, including `autoboot.txt` |
| 2 / 3 | Boot slots A / B (firmware, DTBs, kernel and slot-specific cmdline) |
| 4 / 5 | SquashFS root slots A / B |
| 6 | Persistent data |

The bootloader selects slot A by default and slot B for a one-shot tryboot. The
boot image chooses the matching root by boot-partition number. An update writes
the inactive boot and root images, verifies both by readback, and stages the pair
for trial. Only after health checks pass does the OS swap the default and
tryboot boot-partition numbers in `autoboot.txt`.

Updates come from a GitHub release or a USB stick and use the same signed bundle,
one per board:

```text
livi-os-rpi5-update.json        manifest: board, version, serial and both image hashes
livi-os-rpi5-update.json.sig    signature over the manifest
livi-os-rpi5-rootfs.squashfs    root image named by the manifest
livi-os-rpi5-boot.vfat          boot image named by the manifest
```

This partition layout changes the full disk image. Devices flashed with the
earlier single-boot-partition layout need a one-time full reflash before they
can install these updates.

### Signing setup

Create a key pair once on a trusted machine. Store the private key securely outside
the repository and commit only the public key; the image embeds it read-only at
`/usr/lib/livi/os-update.pem`. Images built without it cannot install OS updates.

```sh
(
  set -eu
  umask 077
  pub=board/drskunk/livi/os-update.pem
  [ ! -e "$pub" ] || { echo "Public key exists; not overwriting it" >&2; exit 1; }
  key_dir="$(mktemp -d "${TMPDIR:-/tmp}/livi-os-signing.XXXXXX")"
  printf 'Private key: %s/private.pem\n' "$key_dir"
  openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 \
    -out "$key_dir/private.pem"
  openssl pkey -in "$key_dir/private.pem" -pubout -out "$pub"
)
```

After backing up and verifying the private key in your secure storage, set the
repository secret from its local file using the GitHub CLI:

```sh
gh secret set LIVI_OS_SIGNING_KEY -R DrSkunk/livi-os-buildroot \
  < /path/to/livi-os-private.pem
```

This keeps the key out of the repository, but GitHub will hold its own encrypted
copy. The workflow uses it only on `main` and
version-tag builds and skips signed update assets if the secret or public key is
missing. Protect `main` and the `v*` release tags, and limit who can change workflows
or trigger those builds: code running in an eligible workflow can use the signing
secret. CI then attaches the signed bundle for each board to the nightly or tagged
release.

Locally, after `make pi5`:

```sh
make pi5-update LIVI_OS_SIGNING_KEY=livi-os-private.pem   # output/pi5/update/
```

The tool refuses to sign when the key does not match the image's embedded public key.
`LIVI_OS_VERSION` and `LIVI_OS_SERIAL` override the version (default `git describe`)
and the ordering serial (default commit time).

### Installing

```sh
livi-os-update status              # installed version, slot, staged update
livi-os-update check               # newest release on the channel
livi-os-update update              # download, verify and stage it
livi-os-update apply               # try it now instead of at the next power-on
```

The channel is `stable` (latest GitHub release) unless `/data/os-update/channel`
contains `nightly`, or `--channel` is given. Downloads go to `/data/os-update/download`
and resume after interruption. `/data/os-update/repo` overrides the release
repository; only bundles signed with the embedded key are accepted.

For a USB update, copy the four files of the device's board into `livi-update/` on a
FAT32, exFAT or ext4 stick and insert it. The stick is mounted read-only, the update
is staged, and the trial boot starts immediately. Remove the stick afterwards; a stick
holding the installed version is ignored. A manually copied bundle can also be
installed with `livi-os-update install /path/livi-os-rpi5-update.json`.

The updater verifies the manifest signature, checks the board, refuses older
serials (unless `--allow-downgrade`) and images whose trial already failed (unless
`--retry-failed`). It writes the inactive boot and root slots and verifies both
readbacks against the signed hashes. Concurrent updates and updates from an
unconfirmed root are rejected.

A staged update is tried once at the next power-on, before LIVI starts, through
the Raspberry Pi bootloader's A/B tryboot mode (`livi-os-update apply` or
`livi-os-slot reboot` starts it immediately). The new boot/root pair becomes the
default only after 60 consecutive successful application/display/audio health
checks, with an initial startup allowance of 60 seconds. A failed trial returns
to the previous default on reset, including failures before userspace. Use
`livi-os-slot cancel` from the previous root to discard a staged update.

Critical service failures and an unconfirmed trial's three-minute boot deadline
request a reset. Both images enable `kernel_watchdog_timeout=120` and systemd's
runtime watchdog; `panic=10` also reboots after a kernel panic. Provision a current
Pi 4 EEPROM bootloader with A/B tryboot support and `BOOT_WATCHDOG_TIMEOUT=120`
for watchdog coverage before the kernel starts. EEPROM configuration is separate
from the disk image and must be verified on each board. See the [Raspberry Pi
`autoboot.txt` documentation](https://www.raspberrypi.com/documentation/computers/config_txt.html#autoboot-txt)
and [watchdog documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html).

The control FAT filesystem is remounted writable only while committing a
confirmed update. The active boot slot is never modified during an update, but
the small control partition remains a single point of failure. Test reset and
power-loss recovery on the deployment hardware.

## Configuration recovery

`livi-config-guard` validates LIVI's JSON every five seconds and stores the last
valid copy using copy/sync/atomic-rename. On startup, a missing, truncated or malformed
configuration is restored automatically with ownership returned to LIVI. It does not overwrite a valid older
configuration merely because its schema changed; LIVI remains responsible for
schema migration.

Systemd feeds the BCM2835 hardware watchdog with a 15-second runtime deadline.
The journal is volatile, rate-limited and capped at 24 MiB. A dedicated log
writer continuously rotates LIVI output at 4 MiB, retaining one previous file
(8 MiB total), including output without newline characters. Startup fatal
messages are tracked separately so rotation cannot erase a failed health check.

## Diagnostics

For CarPiHAT hardware compatibility, Haltech ECU configuration, required
RPM/speed frames and listen-only commissioning, see
[Haltech CAN telemetry](docs/HALTECH-CAN.md). The guide distinguishes the
standard 1 Mbit/s connection from a conditional Nexus GCAN setup at 500 kbit/s;
the image's CAN integration is not yet complete.

On the target:

```sh
livi-health
systemctl status livi livi-pipewire livi-wireplumber NetworkManager bluetooth
systemctl status minidsp
journalctl -u livi -b
tail -F /data/livi/log/LIVI.log
```

Before automotive deployment, test the exact display, touchscreen, audio device,
Wi-Fi/Bluetooth adapters, USB topology and power supply on both cold and warm boot.
Perform repeated hard-power-cut testing while idle, during configuration writes,
and during AppImage download/install. Hardware validation is required before this
image should be considered production-safe.
