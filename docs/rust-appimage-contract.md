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
`resources/livi-wifi-ap.service.template`,
and `resources/livi-os-helper-api` containing `2` followed by a newline.
Also require `resources/livi-os-display-api` containing `1` followed by a newline.
This additional capability marker covers DRM rotation, touch and presented-frame
readiness. API-2 helper compatibility alone is insufficient: older nightlies
declared API 2 while ignoring the appliance's rotation request. Image builds
and downloads reject such payloads instead of producing a wrongly oriented image.
Only advertise API 2 once the behavior below is implemented. AppRun must
foreground/supervise `livi-core`, propagate shutdown and return failure on
unrecoverable startup errors. Keep the existing ARM64 AppImage release naming.
No Rust compiler, Node, pip or distro package installer is needed on the target.

The OS extracts the factory Rust helper to `/usr/libexec/livi-helperd`.
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
LIVI_GST_HEVC_LEGACY_SLICE=1
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

The pinned 6.12 `rpi-hevc-dec` driver interprets HEVC `bit_size` as the end of
slice data relative to the queued buffer; it subtracts `data_byte_offset`.
The media bundle's newer GStreamer backport instead uses payload lengths.
That ABI mismatch produced green video even after correcting capture-layout
and Wayland stride handling. The bundled V4L2 plugin must honor
`LIVI_GST_HEVC_LEGACY_SLICE=1` to send the legacy end offset, accounting for
preceding slices in the queued buffer. Matching this ABI restored smooth
hardware H.265 Android Auto video on the Pi.

The app's API-2 launcher must set the same flag for app-only updates on older
images. Desktop launches retain the modern default. Reassess the compatibility
flag when upgrading the kernel driver. `LIVI_GST_SWDEC=1` remains an explicit
software fallback and must affect both codec probing and playback.

Use the existing system PipeWire/PulseAudio/WirePlumber services; do not spawn
duplicates or assume `systemctl --user` units. Keep HOME-backed defaults and
`XDG_CONFIG_HOME` consistent, and do not attempt runtime apt/pip installation,
sudoers installation, udev installation or kiosk-unit rewriting in OS mode.
The OS owns those resources. Keep all unprivileged state under `/data`.

## Privileged projection helper

The native application's API-2 contract uses the immutable helper directly,
not the older five-argument `/usr/libexec/livi-projection-helper` wrapper.
The core must not stage and sudo its writable bundled helper, use `sudo -E`
or invoke install switches. Use:

```
sudo -n /usr/libexec/livi-helperd
/usr/libexec/livi-helperd --wifi-ap-status
sudo -n /usr/libexec/livi-helperd --wifi-ap-teardown
```

The core clears its environment and supplies PATH plus these command-scoped
sudo `env_keep` settings:

```
LIVI_LIFELINE DEBUG LIVI_AA_WIRELESS LIVI_CP_WIRELESS LIVI_CP_NAME LIVI_CP_FUELS
LIVI_CP_CONNECTORS LIVI_CP_THEME LIVI_BT_ADAPTER LIVI_MFI_FILES LIVI_WIFI_IFACE
LIVI_PASSPHRASE LIVI_WIFI_TYPE LIVI_CHANNEL LIVI_COUNTRY LIVI_CP_DEBUG LIVI_CP_DEVICE_ID
LIVI_CP_PK LIVI_CP_PI LIVI_CP_AIRPLAY_PORT
```

The native app also supports these optional developer overrides:

```
LIVI_AP_IP LIVI_PORT LIVI_DONGLE LIVI_CP_WIRED LIVI_AA_USB LIVI_BT_VIA_DONGLE
LIVI_CHANNEL_WIDTH LIVI_CP_USB_IFACE LIVI_LOCKDOWN_STORE LIVI_CP_MFI_POWER_GPIO
LIVI_CP_AVAILABLE_CURRENT_MA LIVI_CP_SOURCE_VERSION
```

Sudo sets `SUDO_USER=livi`. The helper resolves
`/home/livi/.config/LIVI/config.json`, which the image links to
`/data/livi/config/LIVI/config.json`. Its stdin stays open with
`LIVI_LIFELINE=1`; close it to request shutdown. The core retains that pipe,
waits/reaps its helper and restarts it when settings change. Native stale-process
cleanup is authorized only for `/usr/bin/pkill -TERM -f /usr/libexec/livi-helperd$`
and the corresponding `-KILL` invocation, never an arbitrary process pattern.

The image renders the factory AppImage's Wi-Fi AP unit to
`/etc/systemd/system/livi-wifi-ap.service`, replacing its helper path with
`/usr/libexec/livi-helperd` and username with `livi`. The unit is not enabled
by default. It requires and follows `livi-data-setup.service` so persisted
configuration is mounted before a dedicated AP starts at boot.
The app may start, stop, restart, enable or disable only this AP unit.
The service's claim/start/teardown switches run as root through systemd;
they are not general sudo permissions. The existing persistent, root-owned
systemd and NetworkManager configuration mounts support these operations.

This replaces the OS's incompatible five-argument launcher contract; an OS
rebuild is required. Do not repair it with a symlink alone: the environment,
sudo permissions and Wi-Fi service must match as well. The native helper
trusts the listed projection settings, including optional file paths; this
is a different privilege interface from the old argument-validating wrapper.

For an existing Buildroot output tree, force the LIVI package to reinstall
before generating the new image (use `pi5` instead of `pi4` for Pi 5):

```sh
make -C buildroot O="$PWD/output/pi4" livi-dirclean
make pi4
```

Back up the data partition before reflashing. These source changes do not
repair an already flashed card or the downloaded image in place.

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
