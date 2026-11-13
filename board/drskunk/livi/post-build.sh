#!/bin/sh
set -eu

TARGET="${1:?target directory missing}"
case "${LIVI_CARPIHAT-1}" in
  1|0|'') ;;
  *) echo "LIVI_CARPIHAT must be 1, 0 or empty" >&2; exit 1 ;;
esac

(
  cd "$TARGET"
  sha256sum -c usr/lib/livi/factory-appimage.sha256
) || {
  echo "Factory AppImage changed during target finalization; exclude LIVI.AppImage from stripping" >&2
  exit 1
}

for keymap in rules/evdev symbols/us keycodes/evdev types/complete compat/complete; do
  [ -s "$TARGET/usr/share/X11/xkb/$keymap" ] || {
    echo "Required keyboard layout data missing: $keymap" >&2
    exit 1
  }
done

for modules in "$TARGET"/lib/modules/*; do
  [ -d "$modules/kernel" ] || continue
  if find "$modules/kernel" -name '*.ko.xz' -print -quit | grep -q .; then
    if ! "${HOST_DIR:?Buildroot host directory missing}/bin/kmod" --version | grep -q '+XZ'; then
      echo "Host kmod lacks XZ support required to index compressed kernel modules: $modules" >&2
      echo "Rebuild it with: make -C buildroot O=\"$(dirname "$TARGET")\" host-kmod-reconfigure" >&2
      exit 1
    fi
  fi
  [ -s "$modules/modules.dep" ] && [ -s "$modules/modules.alias.bin" ] || {
    echo "Kernel modules have no dependency/alias index: $modules" >&2
    exit 1
  }
  if find "$modules/kernel" -name '*.ko.xz' -print -quit | grep -q .; then
    grep -q '\.ko\.xz:' "$modules/modules.dep" || {
      echo "XZ-compressed modules missing from dependency index: $modules" >&2
      exit 1
    }
  fi
done

# Fail image creation if Kconfig silently dropped a runtime dependency.
for executable in bin/bash usr/bin/stat usr/bin/dbus-run-session usr/bin/pipewire \
  usr/bin/psplash usr/bin/psplash-write usr/bin/timeout \
  usr/libexec/livi-splash-start usr/libexec/livi-splash-stop usr/libexec/livi-os-update-helper \
  usr/libexec/livi-power-helper usr/bin/flock usr/bin/systemctl usr/bin/sudo \
  usr/libexec/livi-media-storage usr/libexec/livi-media-eject \
  bin/mount bin/umount \
  usr/bin/pipewire-pulse usr/bin/wireplumber usr/bin/jq usr/bin/unsquashfs \
  usr/bin/pactl usr/bin/xdg-user-dir usr/libexec/livi-helperd usr/bin/pkill usr/bin/pgrep \
  usr/bin/python3 usr/libexec/livi-carpihat-power usr/libexec/livi-can-capture usr/libexec/livi-ssh-hostkey \
  usr/libexec/livi-ssh-keys usr/sbin/sshd usr/bin/ssh-keygen \
  usr/libexec/livi-obd2 \
  usr/local/lib/livi/livi-touch-filter usr/bin/retroarch; do
  [ -x "$TARGET/$executable" ] || {
    echo "Required runtime executable missing: /$executable" >&2
    exit 1
  }
done

if [ "${LIVI_CARPIHAT-1}" = 1 ]; then
  found_gpiod=0
  for module in "$TARGET"/usr/lib/python*/site-packages/gpiod*.so; do
    [ ! -f "$module" ] || found_gpiod=1
  done
  [ "$found_gpiod" = 1 ] || {
    echo "CarPiHAT ignition control requires the libgpiod 1.x Python binding" >&2
    exit 1
  }
fi

ap_unit="$TARGET/etc/systemd/system/livi-wifi-ap.service"
for setting in \
  'Environment=SUDO_USER=livi' \
  'Requires=livi-data-setup.service' \
  'After=livi-data-setup.service' \
  'ExecStartPre=/usr/libexec/livi-helperd --wifi-ap-claim' \
  'ExecStart=/usr/libexec/livi-helperd --wifi-ap' \
  'ExecStop=/usr/libexec/livi-helperd --wifi-ap-teardown'; do
  grep -qx "$setting" "$ap_unit" || {
    echo "Missing native projection AP setting: $setting" >&2
    exit 1
  }
done

for library in libEGL.so.1 libGLESv2.so.2 libgbm.so.1 libdrm.so.2 \
  libinput.so.10 libseat.so.1 libxkbcommon.so.0 libwayland-client.so.0 \
  libwayland-server.so.0 libgudev-1.0.so.0 libva.so.2; do
  [ -e "$TARGET/usr/lib/$library" ] || {
    echo "Required Rust graphics/media runtime library missing: $library" >&2
    exit 1
  }
done

helper_dynamic="$("${HOST_DIR:?Buildroot host directory missing}/bin/aarch64-linux-readelf" \
  -d "$TARGET/usr/libexec/livi-helperd")"
if printf '%s\n' "$helper_dynamic" | grep -Eq '\((RPATH|RUNPATH)\)'; then
  echo "Immutable Rust helper must not use a bundled library search path" >&2
  exit 1
fi
for library in $(printf '%s\n' "$helper_dynamic" | sed -n 's/.*(NEEDED).*\[\([^]]*\)\].*/\1/p'); do
  case "$library" in
    *[!A-Za-z0-9._+-]*|'') echo "Invalid Rust helper library name: $library" >&2; exit 1 ;;
  esac
  [ -e "$TARGET/usr/lib/$library" ] || [ -e "$TARGET/lib/$library" ] || {
    echo "Immutable Rust helper dependency missing: $library" >&2
    exit 1
  }
done

for asset in glui/font.ttf glui/back.png ozone/regular.ttf; do
  [ -s "$TARGET/usr/share/retroarch/assets/$asset" ] || {
    echo "Required RetroArch menu asset missing: $asset" >&2
    exit 1
  }
done

# The immutable root owns defaults; mutable state is created only after
# LIVI_DATA is checked and mounted (systemd units under multi-user.target).
chmod 0755 "$TARGET"/usr/bin/livi-* 2>/dev/null || true
chmod 0755 "$TARGET"/usr/libexec/livi-*
chmod 0644 "$TARGET/usr/libexec/livi-can-capture.py"
chmod 0644 "$TARGET/usr/libexec/livi-obd2.py"
chmod 0440 "$TARGET/etc/sudoers.d/99-livi"
mkdir -p "$TARGET/data" "$TARGET/home/livi" "$TARGET/var/lib"
mkdir -p "$TARGET/var/lib/bluetooth" "$TARGET/var/lib/systemd/timesync" "$TARGET/etc/bluetooth" \
  "$TARGET/var/lib/lockdown" "$TARGET/etc/udev/rules.d" \
  "$TARGET/etc/NetworkManager/system-connections" "$TARGET/etc/NetworkManager/conf.d"
ln -snf /data/livi/config "$TARGET/home/livi/.config"
ln -snf /data/games "$TARGET/home/livi/Games"

# These are runtime files and must not accidentally be baked into SquashFS.
rm -f "$TARGET/etc/machine-id" "$TARGET/var/lib/dbus/machine-id"
: > "$TARGET/etc/machine-id"

mkdir -p "$TARGET/etc/systemd/system/multi-user.target.wants"
for unit in seatd.service minidsp.service livi-data-grow.service livi-data-setup.service livi-os-slot.service livi-os-apply.service livi-pipewire.service livi-pipewire-pulse.service livi-wireplumber.service livi.service livi-qemu-check.service; do
  ln -snf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done
rm -f "$TARGET/etc/systemd/system/multi-user.target.wants/livi-can.service"

mkdir -p "$TARGET/etc/systemd/system/sysinit.target.wants"
if [ "${LIVI_CARPIHAT-1}" = 1 ]; then
  ln -snf /usr/lib/systemd/system/livi-carpihat-power.service \
    "$TARGET/etc/systemd/system/sysinit.target.wants/livi-carpihat-power.service"
else
  rm -f "$TARGET/etc/systemd/system/sysinit.target.wants/livi-carpihat-power.service"
fi
ln -snf /usr/lib/systemd/system/livi-splash.service \
  "$TARGET/etc/systemd/system/sysinit.target.wants/livi-splash.service"
for unit in psplash-start.service psplash-systemd.service; do
  ln -snf /dev/null "$TARGET/etc/systemd/system/$unit"
done
ln -snf /dev/null "$TARGET/etc/systemd/system/getty@tty1.service"
ln -snf /usr/lib/systemd/system/livi-boot-deadline.timer \
  "$TARGET/etc/systemd/system/sysinit.target.wants/livi-boot-deadline.timer"

mkdir -p "$TARGET/usr/lib/livi"

# OS identity used by livi-os-update for board matching and downgrade refusal.
# SERIAL must increase between releases; CI passes the commit time.
BOARD="${2:?board argument missing}"
EXTERNAL="${BR2_EXTERNAL_LIVI_OS_PATH:?external tree missing}"
VERSION="${LIVI_OS_VERSION:-$(git -C "$EXTERNAL" describe --tags --always --dirty 2>/dev/null || echo dev)}"
SERIAL="${LIVI_OS_SERIAL:-$(git -C "$EXTERNAL" log -1 --format=%ct 2>/dev/null || date -u +%s)}"
case "$SERIAL" in ''|*[!0-9]*) echo "LIVI_OS_SERIAL must be an integer" >&2; exit 1;; esac
case "$VERSION" in *[!A-Za-z0-9._+-]*) echo "LIVI_OS_VERSION has unsupported characters" >&2; exit 1;; esac
printf 'BOARD=%s\nVERSION=%s\nSERIAL=%s\n' "$BOARD" "$VERSION" "$SERIAL" > "$TARGET/usr/lib/livi/os-release"

# The OS-update trust anchor lives on the immutable root, never on /data.
PUBKEY="${LIVI_OS_UPDATE_PUBKEY:-$EXTERNAL/board/drskunk/livi/os-update.pem}"
rm -f "$TARGET/usr/lib/livi/os-update.pem"
if [ -f "$PUBKEY" ]; then
  install -m 0644 "$PUBKEY" "$TARGET/usr/lib/livi/os-update.pem"
else
  echo "WARNING: no OS-update public key at $PUBKEY; signed OS updates are disabled in this image" >&2
fi
