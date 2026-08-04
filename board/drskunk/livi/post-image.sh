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

FILES=()
for file in "${BINARIES_DIR}"/*.dtb "${BINARIES_DIR}"/rpi-firmware/*; do
  [ -e "$file" ] && FILES+=("${file#${BINARIES_DIR}/}")
done
KERNEL="$(sed -n 's/^kernel=//p' "${BINARIES_DIR}/rpi-firmware/config.txt")"
FILES+=("$KERNEL")
BOOT_FILES="$(printf '\t\t\t\"%s\",\n' "${FILES[@]}")"
sed -e "s|#BOOT_FILES#|${BOOT_FILES}|" -e "s|#BOARD#|${BOARD}|g" \
  "$BOARD_DIR/genimage.cfg.in" > "$GENIMAGE_CFG"

rm -rf "$GENIMAGE_TMP"
"${HOST_DIR}/bin/genimage" --rootpath "$ROOTPATH_TMP" --tmppath "$GENIMAGE_TMP" \
  --inputpath "$BINARIES_DIR" --outputpath "$BINARIES_DIR" --config "$GENIMAGE_CFG"
