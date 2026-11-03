# Rust AppImage integration: LIVI OS API 2

This is the contract for the custom Rust/Slint AppImage and this Buildroot
image. It is **not** an interface already implemented by unmodified upstream.
Electron/API-1 payloads are intentionally unsupported. Do not upgrade an
existing Electron installation through its application updater: deploy a full
OS image and back up configuration first.

## Haltech CAN capture

For Haltech CAN, the updated core and OS capture helper accept standard data
IDs `360`, `361`, `368`, `36A`, `370`, `372`, `3E0` (hex). The immutable
no-argument `/usr/libexec/livi-can-capture` configures/verifies `can0` at
1 Mbit/s listen-only and emits candump-format receive lines only. Diagnostics
go to stderr, failures exit nonzero. The core decodes RPM, speed, battery,
coolant, oil gauge pressure, sensor-1 lambda and two knock levels, expiring
each value after 1.5 seconds. Install both the updated app and OS to expand
the old two-ID filter. This is additive within API 2: old apps ignore extra
frames, and no new privileged arguments are introduced.

The optional active OBD-II backend uses a separate immutable entry point:
`sudo -n /usr/libexec/livi-obd2 500000` or `1000000`, with stdin retained as a
lifeline. It permits only a fixed Service 01 PID allowlist and diagnostic IDs;
the app cannot provide frames, identifiers or commands. The app must stop/reap
one backend before enabling the other. It publishes the same normalized fields
plus `obd2` health; stderr and nonzero exit indicate failure. The app defaults
to passive V2/off and requires an explicit validated-bus acknowledgement before
OBD polling. Both the updated OS helper/sudoers and app controls are required.

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

## Optional signed OS updater integration

The app's Settings -> System -> Software Update can use the separate immutable
`/usr/libexec/livi-os-update-helper` through `sudo -n`. This interface does not
change the projection-helper ABI or permit calling writable helper binaries.
The wrapper clears the environment and accepts exactly `status`, `check stable`,
`check nightly`, `stage stable`, `stage nightly`, or `apply`. No file paths,
repository overrides, downgrade flags or failed-trial retries are exposed.

`status` returns the updater's JSON (`board`, `version`, `serial`, `slot`,
`trial`, `pending`, `staged`, `update_key`). `check` returns the signed-manifest
assessment (`channel`, `installed`, `available`, `update`). `stage` invokes
`livi-os-update update --channel CHANNEL --progress` and streams newline-delimited
JSON: `phase` (`downloading` / `staging`), `message`, `received`, `total`.
Download byte counts advance after each image's size/hash verification; staging
reports the root/boot write/readback phases. Exit status is authoritative: a
progress line is never proof of a successfully staged image. Refresh `status`
after completion, including failures.

Staging never reboots. Require explicit user confirmation before `apply` and
recheck the pending/staged identity before sending it. The OS still tries staged
updates at the next power-on. Do not expose mark-good, cancel, retry-failed or
allow-downgrade through the UI helper; preserve the OS health-based confirmation
and automatic rollback described below.

## Host power controls

The separate immutable `/usr/libexec/livi-power-helper` accepts exactly one
argument, `poweroff` or `reboot`. Its `NOSETENV` sudoers grant names those exact
two command lines. The wrapper validates arguments, clears its environment,
refuses while the OS-update lock is held, and queues
`/usr/bin/systemctl --no-block ACTION`. It cannot operate arbitrary services or
force a reset. Core must await the exit status and show failures without
quitting first. System power pages require a confirmation click, and application
update relaunches must not be interpreted as host reboot requests.

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
