# LIVI OS for Raspberry Pi 4 and 5

Buildroot-based automotive image for [DrSkunk/LIVI](https://github.com/DrSkunk/LIVI).
The operating system is immutable, LIVI keeps its built-in AppImage updater, and
persistent configuration and ROM files live on a separate journaled filesystem.

## Status

This project produces separate ARM64 images for Raspberry Pi 4 and Raspberry Pi
5. The userspace and update/recovery design are shared; separate kernels are used
because the boards have different SoCs and kernel defconfigs.

The configuration includes:

- A/B SquashFS read-only roots and a normally read-only FAT boot partition
- ext4 `LIVI_DATA` partition for application/configuration/ROM state
- systemd, NetworkManager, BlueZ, hostapd, dnsmasq and Avahi
- Mesa V3D/VC4, DRM/KMS, Wayland, Cage, seatd and libinput
- PipeWire, its PulseAudio compatibility server, and WirePlumber
- Python 3, dbus-python, GObject and smbus2 for LIVI helpers
- RetroArch 1.22.2 with pinned NES, SNES, GB/GBC, GBA, Genesis and Master System cores
- minidsp-rs 0.1.12 daemon and loopback API on port 5380
- writable AppImage updates plus signed A/B OS updates and rollback
- last-known-good `config.json` recovery

The immutable image includes Nestopia UE (NES), Snes9x (SNES), Gambatte
(Game Boy and Game Boy Color), mGBA (Game Boy Advance), and Genesis Plus GX
(Genesis/Mega Drive and Master System). LIVI's importer resolves these exact
core filenames from `/usr/lib/libretro`; ROMs, playlists, thumbnails, saves and
user-installed cores remain writable under `/data/games`.

Genesis Plus GX is the core currently hard-coded by LIVI for both Genesis and
Master System. Its upstream license is non-commercial. Do not distribute this
core in a commercial product without separate permission; replace it and update
LIVI's core mapping for a commercial deployment.
Android Auto and the common wireless stack are included, but wired native CarPlay
must not be considered complete until the `pymobiledevice3` dependency set has
been cross-built and hardware-tested. Native CarPlay also requires a physical
Apple MFi authentication coprocessor.

## Host requirements

An x86-64 Linux build host (required by the prebuilt Bootlin toolchain) with Git, GNU Make, GCC, `curl`, `readelf`, and normal
Buildroot host prerequisites is required. Expect a substantial first build: the
LIVI AppImage is approximately 307 MiB and the graphics/audio stack is compiled
from source.

## Build

Buildroot is pinned to `2026.05.1` and its exact commit is verified by the wrapper.

```sh
make bootstrap

# DrSkunk/LIVI currently publishes the ARM64 build on its nightly release tag.
make fetch-livi LIVI_CHANNEL=nightly

make pi4
make pi5
```

Outputs:

```text
output/pi4/images/livi-os-rpi4.img
output/pi5/images/livi-os-rpi5.img
```

`make fetch-livi` validates the AppImage type and AArch64 ELF machine and writes
a local SHA-256 file. For a reproducible production release, archive the exact
AppImage and its hash rather than resolving the rolling nightly tag again.

Validate both Buildroot defconfigs and shell syntax with:

```sh
make check
python3 support/test-runtime.py
```

Recovery tests require Python 3, Bash and `jq`. `make check` resolves the
x86-64 CI configuration on any host; it does not compile or boot an image.

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
400×1280 mode; the Cage hardware patch applies a 90° output transform at startup
and after reconnection. USB touch devices map to `HDMI-A-1`, so wlroots applies
the same transform to touch coordinates. Do not add a separate libinput
calibration rotation: that would rotate touches twice. HDMI1 is disabled by Cage.
The console uses `fbcon=rotate:1` independently of the application.

Both Pi images use full KMS and the panel's EDID for detailed timings. The wiki's
legacy `hdmi_group`, `hdmi_mode` and `hdmi_timings` settings are not used. Connect
HDMI and USB before boot; if the native mode is missing, inspect the EDID and
cable rather than substituting generic CVT timings. The previous DSI panel
configuration and automatic DSI detection are disabled.

The startup health check verifies the compositor's active native mode, 90°
transform and scale, plus the PipeWire/PulseAudio sockets. Verify all four touch
corners on the physical panel before installation.

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
/data/network/system-connections/
```

LIVI-required mutable system configuration (`/etc/bluetooth`, NetworkManager
profiles, LIVI udev rules and locally generated systemd units) is bind-mounted
from `/data`. Factory configuration is migrated before mounting: untouched
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
same filesystem as the destination.

At boot, `livi-supervisor` compares the current AppImage with the recorded healthy
hash. A new hash is a candidate. If Cage and LIVI remain alive for 60 seconds, the
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
