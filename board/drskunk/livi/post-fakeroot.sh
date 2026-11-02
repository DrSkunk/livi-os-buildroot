#!/bin/sh
set -eu

TARGET="${1:?target directory missing}"
external_dir="${3:?Buildroot external path missing}"
ssh_authorized_keys="$external_dir/artifacts/livi-debug-authorized_keys"
ssh_service="$TARGET/etc/systemd/system/multi-user.target.wants/livi-ssh.service"
default_ssh_service="$TARGET/etc/systemd/system/multi-user.target.wants/sshd.service"
ssh_keys_dir="$TARGET/etc/ssh/authorized_keys"

for executable in usr/lib/livi/livi-helperd usr/libexec/livi-projection-helper; do
  [ -f "$TARGET/$executable" ] && [ ! -L "$TARGET/$executable" ] || {
    echo "Missing regular immutable Rust helper: /$executable" >&2
    exit 1
  }
  chown 0:0 "$TARGET/$executable"
  chmod 0755 "$TARGET/$executable"
done

rm -f "$ssh_service" "$default_ssh_service" "$ssh_keys_dir/livi"
[ -f "$ssh_authorized_keys" ] || exit 0

for executable in usr/bin/ssh-keygen usr/sbin/sshd; do
  [ -x "$TARGET/$executable" ] || {
    echo "Debug SSH key supplied but OpenSSH is missing: /$executable" >&2
    exit 1
  }
done

if ! awk '
  NR > 2 || NF < 2 || NF > 3 ||
    $1 != "ssh-ed25519" || $2 !~ /^[A-Za-z0-9+\/=]+$/ { exit 1 }
  END { if (NR < 1 || NR > 2) exit 1 }
' "$ssh_authorized_keys"; then
  echo "Debug SSH access accepts one or two Ed25519 public keys" >&2
  exit 1
fi

mkdir -p "$ssh_keys_dir" "$TARGET/var/empty" "$TARGET/etc/systemd/system/multi-user.target.wants"
install -m 0644 "$ssh_authorized_keys" "$ssh_keys_dir/livi"
chmod 0755 "$ssh_keys_dir" "$TARGET/var/empty"
chown 0:0 "$ssh_keys_dir" "$ssh_keys_dir/livi" "$TARGET/var/empty"

if [ ! -x "${HOST_DIR:?Buildroot host directory missing}/bin/openssl" ]; then
  echo "OpenSSL host tool required to provision key-only SSH account" >&2
  exit 1
fi
random_password="$("$HOST_DIR/bin/openssl" rand -hex 32)"
password_hash="$(printf '%s\n' "$random_password" | "$HOST_DIR/bin/openssl" passwd -6 -stdin)"
unset random_password
[ -n "$password_hash" ] || {
  echo "Could not generate an SSH-only account password hash" >&2
  exit 1
}
shadow_tmp="$(mktemp "$TARGET/etc/.shadow.ssh.XXXXXX")"
trap 'rm -f "$shadow_tmp"' EXIT
awk -F: -v hash="$password_hash" '
  BEGIN { OFS = ":" }
  $1 == "livi" { $2 = hash; found = 1 }
  { print }
  END { if (!found) exit 1 }
' "$TARGET/etc/shadow" > "$shadow_tmp"
mv "$shadow_tmp" "$TARGET/etc/shadow"
chmod 0600 "$TARGET/etc/shadow"
chown 0:0 "$TARGET/etc/shadow"
unset password_hash

chown 0:0 "$TARGET/etc/systemd/system/multi-user.target.wants"
ln -snf /usr/lib/systemd/system/livi-ssh.service "$ssh_service"
