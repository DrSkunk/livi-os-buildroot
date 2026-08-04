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

A Linux build host with Git, GNU Make, GCC, `curl`, `readelf`, and normal
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
```

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
profiles, LIVI udev rules and locally generated systemd units) is seeded from the
immutable root and bind-mounted from `/data`. The remainder of `/etc` stays
read-only.

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

The disk contains two equal SquashFS root slots. Normal boots use slot A; an OS
update is written only to the inactive slot. Provision an RSA or EC public key at
`/data/os-update/trusted.pem`, then install a signed SquashFS image with:

```sh
livi-os-update /data/os-update/rootfs.squashfs /data/os-update/rootfs.sig
reboot
```

Sign on a trusted development machine with the corresponding private key:

```sh
openssl dgst -sha256 -sign release-private.pem \
  -out rootfs.sig rootfs.squashfs
```

The updater verifies the signature, writes the inactive partition, hashes the
bytes back from the block device, atomically changes `cmdline.txt`, and records
the previous slot. A candidate is committed only after LIVI, Cage and the Wayland
socket survive the health window without fatal startup diagnostics. Failed boots
are retried three times and then switch back to the previous root.

The boot FAT filesystem is read-only during normal operation and remounted only
while changing slots. This userspace rollback covers failures that reach systemd;
it cannot recover a kernel that fails before userspace. Adding U-Boot bootcount
or Raspberry Pi tryboot support would be required for that final failure class.

## Configuration recovery

`livi-config-guard` validates LIVI's JSON every five seconds and stores the last
valid copy using copy/sync/atomic-rename. On startup, a truncated or malformed
configuration is restored automatically. It does not overwrite a valid older
configuration merely because its schema changed; LIVI remains responsible for
schema migration.

Systemd feeds the BCM2835 hardware watchdog with a 15-second runtime deadline.
The journal is volatile, rate-limited and capped at 24 MiB; LIVI's persistent log
rotates at 4 MiB. These bounds prevent logs from exhausting the data partition.

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
