#!/bin/sh
set -eu

root="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin"
ln -s "$root/support" "$tmp/support"
unset LIVI_CHANNEL LIVI_REPO

cat > "$tmp/bin/curl" <<'EOF'
#!/bin/sh
set -eu
url=''
output=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    https://*) url="$1" ;;
    -o) shift; output="$1" ;;
  esac
  shift
done
printf '%s\n' "$url" >> "$FETCH_LOG"
case "$url" in
  https://api.github.com/*)
    printf '  "browser_download_url": "https://example.invalid/LIVI-arm64.AppImage"\n' > "$output"
    ;;
  *) exit 42 ;;
esac
EOF
chmod +x "$tmp/bin/curl"
PATH="$tmp/bin:$PATH"
FETCH_LOG="$tmp/requests"
export PATH FETCH_LOG

check_release() {
  expected="$1"
  expected_status="$2"
  shift 2
  : > "$FETCH_LOG"
  status=0
  (cd "$tmp" && "$@") > "$tmp/output" 2>&1 || status="$?"
  if [ "$status" -ne "$expected_status" ]; then
    cat "$tmp/output" >&2
    echo "Unexpected fetch exit status: $status (expected $expected_status)" >&2
    exit 1
  fi
  printf '%s\n' "$expected" 'https://example.invalid/LIVI-arm64.AppImage' > "$tmp/expected"
  if ! cmp -s "$tmp/expected" "$FETCH_LOG"; then
    echo "Unexpected release/download URLs for: $*" >&2
    cat "$FETCH_LOG" >&2
    exit 1
  fi
}

api='https://api.github.com/repos/DrSkunk/LIVI/releases'
check_release "$api/tags/nightly" 42 "$root/support/fetch-livi"
check_release "$api/tags/nightly" 2 make -s -f "$root/Makefile" fetch-livi
check_release "$api/latest" 42 "$root/support/fetch-livi" DrSkunk/LIVI stable
check_release "$api/latest" 2 make -s -f "$root/Makefile" fetch-livi LIVI_CHANNEL=stable
check_release "$api/tags/nightly" 42 "$root/support/fetch-livi" DrSkunk/LIVI nightly
check_release "$api/tags/v10.3.0" 42 "$root/support/fetch-livi" DrSkunk/LIVI v10.3.0
check_release "$api/tags/v10.3.0" 2 make -s -f "$root/Makefile" fetch-livi LIVI_CHANNEL=v10.3.0
check_release 'https://api.github.com/repos/example/LIVI/releases/tags/nightly' 42 \
  "$root/support/fetch-livi" example/LIVI

echo "fetch-livi release selection tests passed"
