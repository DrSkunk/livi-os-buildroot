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
for unit in seatd.service minidsp.service livi-data-grow.service livi-data-setup.service livi-os-slot.service livi-pipewire.service livi-pipewire-pulse.service livi-wireplumber.service livi.service; do
  ln -snf "/usr/lib/systemd/system/$unit" "$TARGET/etc/systemd/system/multi-user.target.wants/$unit"
done

mkdir -p "$TARGET/etc/systemd/system/sysinit.target.wants"
ln -snf /usr/lib/systemd/system/livi-boot-deadline.timer \
  "$TARGET/etc/systemd/system/sysinit.target.wants/livi-boot-deadline.timer"

# A root-only update must match the shared kernel, DTBs and boot configuration.
mkdir -p "$TARGET/usr/lib/livi"
(
  cd "${BINARIES_DIR:?images directory missing}"
  sha256sum Image ./*.dtb rpi-firmware/config.txt rpi-firmware/cmdline.txt
) > "$TARGET/usr/lib/livi/boot-files.sha256"
sha256sum "$TARGET/usr/lib/livi/boot-files.sha256" | awk '{print $1}' > "$TARGET/usr/lib/livi/boot-id"
