#!/bin/sh
set -eu

TARGET="${1:?target directory missing}"

# The immutable root owns defaults; mutable state is created only after
# LIVI_DATA is checked and mounted (systemd units under multi-user.target).
chmod 0755 "$TARGET"/usr/bin/livi-* 2>/dev/null || true
chmod 0755 "$TARGET/usr/libexec/livi-data-setup"
chmod 0440 "$TARGET/etc/sudoers.d/99-livi"
mkdir -p "$TARGET/data" "$TARGET/home/livi" "$TARGET/var/lib"
mkdir -p "$TARGET/var/lib/bluetooth" "$TARGET/etc/bluetooth" \
  "$TARGET/etc/udev/rules.d" "$TARGET/etc/NetworkManager/system-connections"
ln -snf /data/livi/config "$TARGET/home/livi/.config"
ln -snf /data/games "$TARGET/home/livi/Games"

# These are runtime files and must not accidentally be baked into SquashFS.
rm -f "$TARGET/etc/machine-id" "$TARGET/var/lib/dbus/machine-id"
: > "$TARGET/etc/machine-id"

mkdir -p "$TARGET/etc/systemd/system/multi-user.target.wants"
for unit in seatd.service minidsp.service livi-data-grow.service livi-data-setup.service livi-os-slot.service livi-pipewire.service livi-pipewire-pulse.service livi-wireplumber.service livi.service; do
  ln -snf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done
