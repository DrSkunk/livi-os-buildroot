# Rust AppImage integration: LIVI OS API 2

This is the contract for the custom Rust/Slint AppImage and this Buildroot
image. It is **not** an interface already implemented by unmodified upstream.
Electron/API-1 payloads are intentionally unsupported. Do not upgrade an
existing Electron installation through its application updater: deploy a full
OS image and back up configuration first.

## Required payload

Ship these regular executable Linux AArch64 ELF files:

```
livi-ui
resources/core/livi-core
resources/compositor/livi-compositor
resources/gst-host/livi-gst-host
resources/driver/livi-helperd
```

Also ship `resources/99-LIVI.rules.template`, `resources/livi-touch-filter`,
and `resources/livi-os-helper-api` containing `2` followed by a newline.
Only advertise API 2 once the behavior below is implemented. AppRun must
foreground/supervise `livi-core`, propagate shutdown and return failure on
unrecoverable startup errors. Keep the existing ARM64 AppImage release naming.
No Rust compiler, Node, pip or distro package installer is needed on the target.

The OS extracts the factory Rust helper to `/usr/lib/livi/livi-helperd`.
It must run with system libraries and without a bundled library search path.
Any required shared libraries must be packaged into the immutable OS.
An app-only update cannot replace that privileged binary: incompatible helper
changes require a full OS update. Keep the API-2 ABI stable for app rollback.

## Display and process ownership

The OS launches the AppImage as `livi` on tty1 under a retained D-Bus session.
There is no outer Cage, Chromium sandbox, X server or Electron environment.
`WAYLAND_DISPLAY` and `DISPLAY` are unset so the app owns the display directly.

The launch environment is:

```
HOME=/data/livi/home
TMPDIR=/data/livi/update
XDG_RUNTIME_DIR=/run/user/1000
XDG_CONFIG_HOME=/data/livi/config
XDG_CACHE_HOME=/data/livi/cache
XDG_DATA_HOME=/data/livi/state
XKB_CONFIG_ROOT=/usr/share/X11/xkb
LIVI_OS=1
LIVI_OS_API=2
LIVI_KIOSK=1
LIVI_COMPOSITOR_BACKEND=drm
LIVI_MAIN_CONNECTOR=HDMI-A-1
LIVI_DISPLAY_MODE=400x1280@60
LIVI_MAIN_TRANSFORM=90
LIVI_MAIN_SCALE=1
LIVI_OS_READY_FILE=/run/user/1000/livi-os-ready.json
LIVI_OS_SESSION_FILE=/run/user/1000/livi-os-session
```

**Implement connector selection, transform and scale in the Rust compositor.**
The upstream code inspected during migration supports direct DRM but derives
orientation from connector metadata; an HDMI Waveshare panel cannot be assumed
to advertise that orientation. Select its real EDID timing near 60 Hz rather
than synthesizing CVT timings. Scan out 400x1280 and rotate to a logical
1280x400 desktop; transform USB touch coordinates once, including all corners.
Do not silently substitute a desktop-monitor mode or claim readiness on it.
Keep secondary HDMI outputs disabled unless explicitly configured.

Use the existing system PipeWire/PulseAudio/WirePlumber services; do not spawn
duplicates or assume `systemctl --user` units. Keep HOME-backed defaults and
`XDG_CONFIG_HOME` consistent, and do not attempt runtime apt/pip installation,
sudoers installation, udev installation or kiosk-unit rewriting in OS mode.
The OS owns those resources. Keep all unprivileged state under `/data`.

## Privileged projection helper

Under API 2, the core must **not** stage and sudo its writable bundled helper,
use `sudo -E`, invoke install switches, or use name-based root process killing.
Use:

```
sudo -n /usr/libexec/livi-projection-helper AA CP PUBLIC_KEY PAIRING_ID DEBUG
```

Arguments:

- AA, CP, DEBUG: `0` or `1`.
- PUBLIC_KEY: exactly 64 hexadecimal characters.
- PAIRING_ID: 1-64 characters, ASCII letters/digits, `:` or `-`.

The wrapper clears the environment, sets `SUDO_USER=livi`, `LIVI_OS=1`,
`LIVI_OS_API=2`, `LIVI_LIFELINE=1`, and maps the five arguments to
`LIVI_AA_WIRELESS`, `LIVI_CP_WIRELESS`, `LIVI_CP_PK`, `LIVI_CP_PI`,
`LIVI_CP_DEBUG`/`DEBUG`. It executes the immutable helper with **no arguments**.
The helper's stdin stays open for the core lifeline; close it to request shutdown.
The app must retain that pipe, wait/reap its owned helper, and restart it through
this same wrapper when settings change.

For OS mode the custom helper must obtain additional wireless settings from
validated configuration, not inherited root environment. Read only the fixed
`/data/livi/config/LIVI/config.json` path, constrain types/ranges and interface
names, reject symlinks, never evaluate configuration as commands, and never
load code/libraries or root installation paths from configuration. Treat the
file as untrusted input. Report invalid settings explicitly.
This additional configuration handling is an **AppImage-side requirement**;
the existing upstream `sudo -E` launch is not compatible.

Native Apple CarPlay remains outside this image's acceptance scope. Do not
enable it by default or substitute authentication bypasses.

## Readiness and recovery

Do **not** let an external health checker connect to Smithay's control socket:
upstream currently replaces its single control client on a new connection.
Instead the core must atomically replace `LIVI_OS_READY_FILE` at least once
per second with a JSON document no larger than 16 KiB:

```json
{
  "api": 2,
  "session": "<contents of LIVI_OS_SESSION_FILE, trimmed>",
  "monotonic": 1234.5,
  "core": 100,
  "ui": 101,
  "compositor": 102,
  "framePresented": true,
  "output": {
    "connector": "HDMI-A-1",
    "width": 400,
    "height": 1280,
    "transform": "90",
    "scale": 1
  }
}
```

`monotonic` is seconds from Linux `CLOCK_MONOTONIC` (not Unix time and not
elapsed time since a Rust `Instant` was created). Report the actual live
process IDs and actual committed DRM output, not requested settings.
`framePresented` must reflect a UI frame successfully presented by the
compositor, not just a socket existing. Stop publishing ready reports on UI,
compositor or display loss, even if the core remains alive. Do not replay old
reports after restarting a child.

The OS rejects reports from previous launches, reports older than five seconds,
dead/zombie processes, wrong output geometry and missing audio sockets.
It requires 60 consecutive seconds of readiness before confirming an update
and checks continuously afterwards. This is a health contract, not an
attestation boundary against the app's own user.

## Handoff and validation

1. Implement API 2 in the custom AppImage, including privilege and heartbeat
   changes, config migration and the fork's Haltech/MiniDSP/RetroArch features.
2. Provide the ARM64 AppImage and its checksum as the local artifact.
3. Use a fresh Linux Buildroot output tree: removed packages can leave stale
   files in incremental target directories. Do not reuse the Electron target.
4. Build both configs; check the extracted immutable helper's ELF dependencies
   against target libraries. QEMU verifies boot/storage/SSH, not UI rendering.
5. On the real Pi validate cold boot, Waveshare mode/rotation, touch corners,
   audio/HFP, dongle/native Android Auto, network reconnect, app restart,
   deliberate UI/compositor failure, app rollback and OS rollback.

The previous local SD image is an Electron build and does not contain these
changes. No Rust hardware acceptance or updated flashable image is implied
until an API-2 AppImage is supplied and the above checks pass.
