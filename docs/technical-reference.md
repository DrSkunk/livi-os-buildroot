# LIVI OS technical reference

System design and implementation notes. For installation and common commands,
start with the [README](../README.md). Hardware setup is in the
[Pi 5 guide](hardware-setup-pi5.md); CAN setup is in the
[Haltech guide](HALTECH-CAN.md); the app interface is specified in the
[AppImage contract](rust-appimage-contract.md).

## Status

The images target Raspberry Pi 4 and Pi 5 with the Waveshare 7.9-inch
1280×400 HDMI/USB-touch display. They use a custom Rust/Slint AppImage
implementing [LIVI OS API 2](rust-appimage-contract.md), direct DRM/KMS
rendering and an immutable OS-owned helper. An unmodified upstream AppImage is
not compatible. Native Apple CarPlay is outside the acceptance scope.

The image includes A/B SquashFS roots, writable ext4 data, systemd,
NetworkManager, Bluetooth, Wayland, PipeWire, RetroArch, local music and signed
OS updates. AppImage updates remain writable and have a separate rollback path.
ROMs and saves live under `/data/games`; internal music lives under
`/data/livi/music`.

The bundled RetroArch cores are Nestopia UE, Snes9x, Gambatte, mGBA and Genesis
Plus GX. The latter is non-commercial; obtain separate permission before using
it in a commercial product. Starter ROMs and their licenses are documented
under `/usr/share/doc/livi-homebrew`.

Boot/storage behavior has been exercised in QEMU, but that does not validate
the Pi's display, touch, audio, radios, phone projection or firmware rollback.
Physical hardware acceptance is still required.

## Boot and shutdown splash

The early psplash service displays the compiled white logo on black, rotated for
the Waveshare panel. LIVI stops psplash before starting the DRM compositor, so
a brief black handoff is possible. Changing the artwork requires an OS rebuild.

On poweroff, halt or reboot, `livi-shutdown-splash@.service` redraws the same
logo once LIVI has released the display, with "Shutting down..." or
"Restarting..." in the black margin below the logo. It stays until the kernel
powers off or resets. Before that,
LIVI can show its own overlay from `/run/livi-power/state` (see the
[app contract](rust-appimage-contract.md#host-power-controls)).
The media bundle includes libva, libssh and Vulkan runtime libraries required by
its GStreamer plugin; their presence does not imply hardware decoding support.

## Local music

With the matching Local Music AppImage, open **Media → Local Music** to browse
folders and relative M3U/M3U8 playlists using the existing playback controls.
Put internal music in `/data/livi/music`, or insert a FAT32/exFAT USB stick.
The OS mounts music volumes read-only at `/run/livi-media/<device>` and never
copies or modifies their files. LIVI notices inserted and pulled drives within
a few seconds; pulling the drive that is playing stops playback.
Only the selected folder's tracks or selected playlist are queued.

USB volumes containing `livi-update/livi-os-rpi4-update.json` or
`livi-update/livi-os-rpi5-update.json` are reserved for the signed updater,
not the music library. The updater still verifies signatures before accepting
an update. ext4 sticks remain supported for OS updates, not portable music.
Never use an update stick as a music/sync destination. The USB media mount
helper and narrow safe-eject command require an OS update; installing only
the AppImage does not add mounting support.

The matching app can also transfer music to internal storage from the
[LIVI Music](https://drskunk.github.io/livi-music/) website over an explicitly
paired and approved WebRTC session. Signaling uses the public PeerJS Cloud
service, so the device needs internet access; the OS installs no server. Open
the link LIVI shows, enter its pairing code, and approve only if both screens
show the same verification code. Optional ICE/TURN settings live in
`/data/livi/config/LIVI/music-sync.json`; see the app README's
**Wireless music transfer** section for details and transfer limits.
USB volumes are not writable destinations. Interrupted internal transfers may
leave partial files under `/data/livi/.livi-music-transfer`.

Physical USB audio playback, phone interruption/resume and surprise removal
still need Pi hardware acceptance; host tests do not establish that acceptance.

## Build

Use the x86-64 Linux build host or Docker setup in the
[README](../README.md#building). Buildroot is pinned to `2026.05.1`.
After `make bootstrap`, provide a Rust AppImage that meets the API-2 contract,
run `make check-livi`, then `make pi4` or `make pi5`. Outputs are under
`output/<board>/images/`.

`make fetch-livi` downloads a selected release and records its SHA-256, but
does not make an incompatible AppImage usable. `make check-livi` validates the
API-2 payload. If the selected release fails, supply the compatible AppImage
and `.sha256` sidecar in `artifacts/`. Archive the exact pair for reproducible
releases. Use a fresh output tree when migrating from Electron; incremental
Buildroot builds retain removed packages. `LIVI_CARPIHAT=0` builds for USB-C
bench power; use the same setting for OS updates.

Run `make check` and `make test-runtime` before building. These validate project
configuration and host-side behavior; they do not compile or accept the image.
For build prerequisites, compiler-cache details and the macOS/Docker commands,
see the README.

### Pi 4 emulator smoke test

With QEMU support for `raspi4b`, the helper boots the built kernel and DTB with
a disposable copy-on-write disk:

```sh
./support/qemu-pi4 output/pi4/images
```

It preserves the source image and checks boot, read-only system partitions,
persistent storage and first-boot data expansion. `--preview` opens a window,
but QEMU does not emulate Pi graphics, the Waveshare panel, radios or phone
projection. Treat this as a boot/storage test only; never weaken readiness
checks to make the emulator pass.

### Pi 4 UART boot diagnostics

Connect a **3.3 V TTL** USB-UART adapter with the Pi powered off:

| Pi 4 pin | Signal | Adapter |
| --- | --- | --- |
| 8 (BCM14) | TX | RX |
| 10 (BCM15) | RX | TX |
| 6 | Ground | Ground |

Use 115200 baud, 8N1. Do not connect adapter power pins, use RS-232, or confuse
UART with the CAN connector. Confirm the HAT leaves BCM14/15 free. This provides
boot output only; it does not enable a login shell.

### Appliance security profile

There is no shared password or root login. SSH is off by default; the
[README procedure](../README.md#debugging-over-ssh) enables key-only access for
`livi`. The OS is not secure boot: anyone who can replace or edit the SD card
can alter the system.

The supervisor and configuration guard run unprivileged. The app can call only
immutable, narrowly scoped OS helpers; writable AppImage helpers and arbitrary
commands are not granted sudo. Helper/API details are in the
[AppImage contract](rust-appimage-contract.md). Changes to helpers, udev rules
or system services require an OS update. AppImage updates are not signed by the
OS, so rollback protects availability, not authenticity.

Fresh installs seed a random Wi-Fi password, country `CA` and the Waveshare
display defaults. Set the correct regulatory country in LIVI. These measures
are hardening, not a security certification.

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

For illustrated first-boot steps, two mounting options and optional audio/vehicle
wiring, see the [Pi 5 quick-start guide](hardware-setup-pi5.md).

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

### Display

The target panel is the Waveshare 7.9-inch HDMI/USB-touch display. Its native
scanout is 400×1280; the app rotates it to a 1280×400 landscape desktop and
applies the same transform to touch. Connect to HDMI0 and USB TOUCH. See the
[hardware guide](hardware-setup-pi5.md) for setup and physical acceptance.

### Haltech CAN V2 telemetry

See the [Haltech CAN guide](HALTECH-CAN.md) for supported hardware, clock
configuration, wiring and commissioning. V2 capture is 1 Mbit/s listen-only;
identify the HAT crystal before enabling its MCP2515 overlay.

### Optional Haltech OBD-II polling

OBD-II is a separate active, read-only Service 01 backend. It is disabled until
the user selects it, verifies the bus and acknowledges the setup. See the
[OBD-II section](HALTECH-CAN.md#7-optional-elite-obd-ii-backend) for its
limits and commissioning procedure.

## Disk layout and power-loss behaviour

### CarPiHAT ignition control

By default, the HAT holds power until shutdown completes. Its BCM12 ignition
input requests shutdown after ten seconds off; ignition returning during the
countdown cancels it. The countdown is published to `/run/livi-power/state`
so LIVI can display it. Keep permanent power and ACC separate. See the
[wiring and commissioning guide](hardware-setup-pi5.md#carpihat--wire-power-and-ignition).

| Partition | Size / filesystem | Purpose |
|---|---|---|
| 1 `LIVI_BTCTL` | 64 MiB FAT | Boot selection and optional SSH key |
| 2–3 boot A/B | 128 MiB FAT each | Firmware, DTBs and kernel |
| 4–5 root A/B | 1536 MiB SquashFS each | Read-only OS slots |
| 6 `LIVI_DATA` | 2 GiB ext4, grows to fill media | App, settings, music, games and logs |

The data filesystem uses journaling, barriers, `noatime`, a five-second commit
interval and `errors=remount-ro`; `/run`, `/tmp` and `/var/log` are tmpfs. On
first boot, the final data partition and filesystem grow to use remaining card
or NVMe capacity.

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

Mutable Bluetooth, NetworkManager, udev and service configuration persists under
`/data`. OS upgrades migrate unmodified factory defaults while preserving local
edits; conflicting defaults are saved under `incoming/<revision>` and listed in
`conflicts.json`. Wired iPhone pairing records are stored root-only.

## Clock

| Board | Time source at boot | Notes |
|---|---|---|
| Pi 5 | On-board RTC | Install its backup battery. Charging is off by default; only enable it for a rechargeable ML-2020, never a CR2032. |
| Pi 4 | Last time saved by `systemd-timesyncd` | No RTC; network time is needed after a cold start. |

Both use NTP when connected. The clock must be synchronized before sunrise/sunset
night mode can operate reliably.

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

The custom Rust app also exposes signed OS updates alongside application updates
under **Settings -> System -> Software Update**. The image ships the root-owned
`/usr/libexec/livi-os-update-helper` and a narrowly scoped `NOSETENV` sudo grant.
It accepts only status, stable/nightly checking and staging, and applying a staged
trial; it cannot select a manifest path or bypass signature/downgrade/failed-trial
checks. Download progress counts verified whole images, followed by inactive-slot
write/readback phases. **Download and stage** does not reboot. **Reboot...** opens
a separate confirmation; **Later** keeps the OS staged for the next power-on.
The app channel and OS channel are independent. Older images without this helper
need a new OS image to bootstrap the UI integration, not broader sudo permissions.

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

For CarPiHAT hardware compatibility, Elite 2500 auxiliary-port configuration,
decoded signals and listen-only commissioning, see
[Haltech CAN telemetry](HALTECH-CAN.md).

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
