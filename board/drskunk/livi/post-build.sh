#!/bin/sh
set -eu

TARGET="${1:?target directory missing}"

# Fail image creation if Kconfig silently dropped a runtime dependency.
for executable in bin/bash usr/bin/stat usr/bin/cage usr/bin/pipewire \
  usr/bin/pipewire-pulse usr/bin/wireplumber usr/bin/wlr-randr usr/bin/jq usr/bin/unsquashfs; do
  [ -x "$TARGET/$executable" ] || {
    echo "Required runtime executable missing: /$executable" >&2
    exit 1
  }
done

# The immutable root owns defaults; mutable state is created only after
# LIVI_DATA is checked and mounted (systemd units under multi-user.target).
chmod 0755 "$TARGET"/usr/bin/livi-* 2>/dev/null || true
chmod 0755 "$TARGET"/usr/libexec/livi-*
chmod 0440 "$TARGET/etc/sudoers.d/99-livi"
mkdir -p "$TARGET/data" "$TARGET/home/livi" "$TARGET/var/lib"
mkdir -p "$TARGET/var/lib/bluetooth" "$TARGET/var/lib/systemd/timesync" "$TARGET/etc/bluetooth" \
  "$TARGET/etc/udev/rules.d" "$TARGET/etc/NetworkManager/system-connections"
ln -snf /data/livi/config "$TARGET/home/livi/.config"
ln -snf /data/games "$TARGET/home/livi/Games"

# These are runtime files and must not accidentally be baked into SquashFS.
rm -f "$TARGET/etc/machine-id" "$TARGET/var/lib/dbus/machine-id"
: > "$TARGET/etc/machine-id"

mkdir -p "$TARGET/etc/systemd/system/multi-user.target.wants"
for unit in seatd.service minidsp.service livi-data-grow.service livi-data-setup.service livi-os-slot.service livi-os-apply.service livi-pipewire.service livi-pipewire-pulse.service livi-wireplumber.service livi.service; do
  ln -snf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done

mkdir -p "$TARGET/etc/systemd/system/sysinit.target.wants"
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
