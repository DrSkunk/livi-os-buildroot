#!/bin/bash
set -euo pipefail

BOARD="${2:-${1:-rpi5}}"
BOARD_DIR="${BR2_EXTERNAL_LIVI_OS_PATH}/board/drskunk/livi"
GENIMAGE_CFG="${BINARIES_DIR}/genimage-livi.cfg"
GENIMAGE_TMP="${BUILD_DIR}/genimage-livi.tmp"
ROOTPATH_TMP="$(mktemp -d)"
DATA_SEED="$(mktemp -d)"
trap 'rm -rf "$ROOTPATH_TMP" "$DATA_SEED"' EXIT

mkdir -p "$DATA_SEED/livi/app" "$DATA_SEED/livi/config" "$DATA_SEED/livi/cache" \
  "$DATA_SEED/livi/log" "$DATA_SEED/livi/update" "$DATA_SEED/os-update" \
  "$DATA_SEED/games/roms" "$DATA_SEED/games/saves" "$DATA_SEED/games/states" \
  "$DATA_SEED/games/retroarch/cores" "$DATA_SEED/games/retroarch/playlists" "$DATA_SEED/games/retroarch/thumbnails" \
  "$DATA_SEED/bluetooth" "$DATA_SEED/network" "$DATA_SEED/machine"
touch "$DATA_SEED/.livi-data"

rm -f "${BINARIES_DIR}/livi-data.ext4"
truncate -s 2G "${BINARIES_DIR}/livi-data.ext4"
"${HOST_DIR}/sbin/mkfs.ext4" -F -L LIVI_DATA -U d38e4e2e-3f14-4b0a-886a-66d44c131703 \
  -E lazy_itable_init=0,lazy_journal_init=0 -d "$DATA_SEED" "${BINARIES_DIR}/livi-data.ext4"

cp "$BOARD_DIR/config-$BOARD.txt" "${BINARIES_DIR}/rpi-firmware/config.txt"
cp "$BOARD_DIR/cmdline-$BOARD.txt" "${BINARIES_DIR}/rpi-firmware/cmdline.txt"
rm -f "${BINARIES_DIR}/rpi-firmware/cmdline-root-a.txt" \
  "${BINARIES_DIR}/rpi-firmware/cmdline-root-b.txt"
FILES=()
for file in "${BINARIES_DIR}"/*.dtb "${BINARIES_DIR}"/rpi-firmware/*; do
  if [ -e "$file" ]; then
    FILES+=("${file#"${BINARIES_DIR}"/}")
  fi
done
KERNEL="$(sed -n 's/^kernel=//p' "${BINARIES_DIR}/rpi-firmware/config.txt")"
FILES+=("$KERNEL")

ROOT_A=8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2
ROOT_B=4af7b146-2c77-4808-881b-1e3ad8d15be8
CMDLINE="${BINARIES_DIR}/rpi-firmware/cmdline.txt"
grep -Eq "(^| )root=PARTUUID=${ROOT_A}( |$)" "$CMDLINE" || {
  echo "cmdline.txt does not name root slot A" >&2
  exit 1
}
cp "$CMDLINE" "${BINARIES_DIR}/rpi-firmware/cmdline-root-a.txt"
sed "s/root=PARTUUID=${ROOT_A}/root=PARTUUID=${ROOT_B}/" "$CMDLINE" \
  > "${BINARIES_DIR}/rpi-firmware/cmdline-root-b.txt"
FILES+=("rpi-firmware/cmdline-root-a.txt" "rpi-firmware/cmdline-root-b.txt")
cat >> "${BINARIES_DIR}/rpi-firmware/config.txt" <<'EOF'

[boot_partition=2]
cmdline=cmdline-root-a.txt
[boot_partition=3]
cmdline=cmdline-root-b.txt
[all]
EOF
cp "$BOARD_DIR/autoboot.txt" "${BINARIES_DIR}/autoboot.txt"

while IFS= read -r line; do
  if [[ "$line" == *'#BOOT_FILES#'* ]]; then
    printf '\t\t\t"%s",\n' "${FILES[@]}"
  else
    printf '%s\n' "${line//#BOARD#/$BOARD}"
  fi
done < "$BOARD_DIR/genimage.cfg.in" > "$GENIMAGE_CFG"

rm -rf "$GENIMAGE_TMP"
"${HOST_DIR}/bin/genimage" --rootpath "$ROOTPATH_TMP" --tmppath "$GENIMAGE_TMP" \
  --inputpath "$BINARIES_DIR" --outputpath "$BINARIES_DIR" --config "$GENIMAGE_CFG"
