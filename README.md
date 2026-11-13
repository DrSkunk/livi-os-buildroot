# LIVI OS

A Raspberry Pi 4 and Pi 5 operating system that boots straight into
[LIVI](https://github.com/DrSkunk/LIVI): CarPlay, Android Auto, local music,
games and car telemetry on a 1280×400 dashboard screen.

The system is read-only and updates itself with A/B slots, so a bad update or a
power cut cannot brick it. Your settings, music and games live on a separate
data partition.

> **Status:** built for a Pi 4 or Pi 5 with the Waveshare 7.9" HDMI touch screen.
> Still being tested on real hardware, so don't rely on it in a car yet.

## Install

1. Download the image for your board from the
   [nightly release](https://github.com/DrSkunk/livi-os-buildroot/releases/tag/nightly):
   `livi-os-rpi4.img.xz` or `livi-os-rpi5.img.xz`.
2. Flash it with [Raspberry Pi Imager](https://www.raspberrypi.com/software/)
   (**Choose OS → Use custom**, skip OS customisation) to a card of at least 8 GB.
   The Pi 5 image also works on NVMe.
3. Connect the screen's HDMI to **HDMI0** (next to the power socket) and its
   touch cable to USB, then power on.

The first boot takes a little longer: the data partition grows to fill the card.

For wiring, mounting and the CarPiHAT power board, see the
[Pi 5 hardware guide](docs/hardware-setup-pi5.md).

## First steps

- **Country:** open LIVI's settings and set your Wi-Fi country (default is `CA`).
- **Phone:** plug it in over USB, or pair it in LIVI for wireless CarPlay /
  Android Auto. LIVI's hotspot gets a random password on first boot; you can
  see and change it in LIVI's Wi-Fi settings.
- **Clock:** the Pi 5 keeps time with its RTC battery. The Pi 4 has no clock, so
  it needs Wi-Fi for the correct time (used for automatic night mode).

## Music

Open **Media → Local Music**. LIVI plays MP3, FLAC, WAV and similar files,
organised in folders, plus `.m3u` / `.m3u8` playlists. Get music onto it by:

- **USB stick:** FAT32 or exFAT. It shows up in the library; use eject before
  pulling it out. Sticks are only read, never written.
- **Wireless:** open the link LIVI shows, which goes to the
  [LIVI Music](https://drskunk.github.io/livi-music/) website. Enter the pairing
  code and accept on the Pi if both screens show the same verification code.
  Music is saved on the SD card. Needs internet on the Pi.
- **SSH:** copy files to `/data/livi/music` (see below).

## Games

The Games tab runs RetroArch with NES, SNES, Game Boy (Color/Advance), Genesis
and Master System cores, plus two free homebrew games. Add ROMs with
**Add games → Browse** (from a USB stick), or copy them to `/data/games/roms`
and press **Rescan**. Use a gamepad to play; **Start + Select** opens the
RetroArch menu.

## Updates

**Settings → System → Software Update** handles both the LIVI app and the OS.
OS updates are signed. They are written to the spare slot and tried on the next
boot. If that boot fails, the Pi goes back to the previous version by itself.

Offline: copy the four `livi-os-rpi*-update*` and `*.squashfs` / `*.vfat` files
for your board into a `livi-update/` folder on a USB stick and plug it in.

## Debugging over SSH

SSH is off until you put your public key on the SD card. There is no password
login.

**1. Make a key** (once, on your computer):

```sh
ssh-keygen -t ed25519 -f ~/.ssh/livi-debug
```

**2. Put it on the card.** With the Pi off, put the SD card in your computer. It
shows up as a drive called `LIVI_BTCTL`. Copy your **public** key there under
this exact name:

```sh
cp ~/.ssh/livi-debug.pub /Volumes/LIVI_BTCTL/livi-ssh-authorized_keys   # macOS
```

On Windows, copy `livi-debug.pub` to the `LIVI_BTCTL` drive and rename it to
`livi-ssh-authorized_keys` (no extension). Up to four keys, one per line.

**3. Connect.** Eject the card, put it back and boot. Plug the Pi into your
router with Ethernet, then from the same network:

```sh
ssh -i ~/.ssh/livi-debug livi@livi.local
```

If `livi.local` doesn't resolve, use the Pi's IP address from your router.

**Useful once you're in:**

```sh
livi-health                              # quick check of screen, storage and app
tail -F /data/livi/log/LIVI.log          # app log
systemctl status livi                    # is the app running
livi-os-update status                    # OS version and update slot
sudo /usr/libexec/livi-power-helper reboot
```

Copy files from your computer:

```sh
scp -i ~/.ssh/livi-debug -r ~/Music/Album livi@livi.local:/data/livi/music/
scp -i ~/.ssh/livi-debug game.gba livi@livi.local:/data/games/roms/
```

You log in as `livi`. That account can read logs and write anywhere under
`/data/livi` and `/data/games`. It can't get root; the OS is read-only by design.

**Turning it off:** delete `livi-ssh-authorized_keys` from `LIVI_BTCTL`. SSH stays
off from the next boot. OS updates leave the file alone.

**Not working?** Check the file name is exact (Windows likes to add `.txt`) and
that the file contains a public key starting with `ssh-ed25519`. Anything else in
the file, such as an RSA key, disables SSH entirely. Never put a private key on
the card; anyone who can read the card can see it.

## Building

Builds need an x86-64 Linux machine, or Docker on macOS. Expect the first build
to take a few hours.

```sh
make bootstrap
make fetch-livi        # downloads the LIVI nightly AppImage
make pi4               # or: make pi5
```

The image ends up in `output/pi4/images/livi-os-rpi4.img`. Run `make check` and
`make test-runtime` before pushing. Pushing to `main` builds both images in
GitHub Actions and publishes them to the nightly release; a `v*` tag creates a
versioned release.

On macOS, build inside Docker:

```sh
docker build --platform linux/amd64 -t livi-build -f support/Dockerfile .
docker volume create livi-build
docker run --rm --platform linux/amd64 -v "$PWD:/workspace" -v livi-build:/build livi-build \
  sh -ec 'make fetch-livi; make pi4 BUILDROOT_DIR=/build/buildroot OUTPUT_BASE=/build/output'
```

Build options: `LIVI_CARPIHAT=0` for a bench setup without the CarPiHAT, and
`LIVI_CAN_OSCILLATOR=16000000` (or `20000000`/`8000000`) to match a CAN HAT's
crystal.

## More docs

- [Pi 5 hardware setup](docs/hardware-setup-pi5.md): wiring, mounting, CarPiHAT power
- [Haltech CAN](docs/HALTECH-CAN.md): ECU telemetry and OBD-II
- [Technical reference](docs/technical-reference.md): partitions, update and
  rollback design, security model, signing keys, emulator and UART debugging
- [App ↔ OS contract](docs/rust-appimage-contract.md): what the LIVI AppImage must provide
