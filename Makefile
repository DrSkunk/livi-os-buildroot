BUILDROOT_VERSION := 2026.05.1
BUILDROOT_COMMIT := cb857ba4c87a93e5265a9e4a3f32071abf39e14a
BUILDROOT_DIR := $(CURDIR)/buildroot
OUTPUT_BASE := $(CURDIR)/output
LIVI_REPO ?= DrSkunk/LIVI
LIVI_CHANNEL ?= nightly
LIVI_OS_SIGNING_KEY ?=
LIVI_APPIMAGE ?= artifacts/LIVI-arm64.AppImage

.PHONY: help bootstrap pi4_defconfig pi5_defconfig pi4 pi5 pi4-update pi5-update menuconfig linux-menuconfig clean fetch-livi check check-livi test-runtime test-fetch-livi

help:
	@echo "make bootstrap       Clone and verify Buildroot $(BUILDROOT_VERSION)"
	@echo "make fetch-livi      Download the current ARM64 LIVI AppImage"
	@echo "make pi4             Build output/pi4/images/livi-os-rpi4.img"
	@echo "make pi5             Build output/pi5/images/livi-os-rpi5.img"
	@echo "make pi5-update      Sign an OS update (LIVI_OS_SIGNING_KEY=private.pem)"
	@echo "make check           Validate both defconfigs and project scripts"
	@echo "make check-livi      Validate the local Rust/API-2 AppImage before building"
	@echo "make test-runtime    Test runtime configuration and recovery"
	@echo "make test-fetch-livi Test release selection without downloading an AppImage"

bootstrap:
	@if test -d "$(BUILDROOT_DIR)/.git" && test "$$(git -C "$(BUILDROOT_DIR)" rev-parse HEAD)" != "$(BUILDROOT_COMMIT)"; then \
		echo "Unexpected Buildroot revision in $(BUILDROOT_DIR); move it aside before bootstrapping." >&2; \
		exit 1; \
	fi
	@test -d "$(BUILDROOT_DIR)/.git" || git clone --depth 1 --branch "$(BUILDROOT_VERSION)" https://gitlab.com/buildroot.org/buildroot.git "$(BUILDROOT_DIR)"
	@test "$$(git -C "$(BUILDROOT_DIR)" rev-parse HEAD)" = "$(BUILDROOT_COMMIT)" || { echo "Unexpected Buildroot revision" >&2; exit 1; }

fetch-livi:
	@mkdir -p artifacts
	@./support/fetch-livi "$(LIVI_REPO)" "$(LIVI_CHANNEL)" artifacts/LIVI-arm64.AppImage

pi4_defconfig pi5_defconfig: bootstrap
	@board="$(@:_defconfig=)"; \
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/$$board" BR2_EXTERNAL="$(CURDIR)" "livi_r$${board}_defconfig"

check-livi:
	python3 support/check-rust-payload --appimage "$(LIVI_APPIMAGE)"

pi4: pi4_defconfig
	# OpenSSH configure needs the target compiler driver to supply its sysroot headers.
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi4" BR2_EXTERNAL="$(CURDIR)" \
		TARGET_CPP="$(OUTPUT_BASE)/pi4/host/bin/aarch64-linux-gcc -E"

pi5: pi5_defconfig
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" BR2_EXTERNAL="$(CURDIR)"

pi4-update pi5-update:
	@test -n "$(LIVI_OS_SIGNING_KEY)" || { echo "Set LIVI_OS_SIGNING_KEY=path/to/private.pem" >&2; exit 1; }
	sh ./support/make-os-update "$(OUTPUT_BASE)/$(@:-update=)" "$(LIVI_OS_SIGNING_KEY)" "$(OUTPUT_BASE)/$(@:-update=)/update"

menuconfig linux-menuconfig: bootstrap
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" BR2_EXTERNAL="$(CURDIR)" $@

check: bootstrap
	BUILDROOT_DIR="$(BUILDROOT_DIR)" OUTPUT_BASE="$(OUTPUT_BASE)" ./support/check-project

test-runtime:
	python3 support/test-runtime.py

test-fetch-livi:
	sh support/test-fetch-livi.sh

clean:
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi4" clean 2>/dev/null || true
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" clean 2>/dev/null || true
