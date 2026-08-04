BUILDROOT_VERSION := 2026.05.1
BUILDROOT_COMMIT := cb857ba4c87a93e5265a9e4a3f32071abf39e14a
BUILDROOT_DIR := $(CURDIR)/buildroot
OUTPUT_BASE := $(CURDIR)/output
LIVI_REPO ?= DrSkunk/LIVI
LIVI_CHANNEL ?= stable

.PHONY: help bootstrap pi4_defconfig pi5_defconfig pi4 pi5 menuconfig linux-menuconfig clean fetch-livi check

help:
	@echo "make bootstrap       Clone and verify Buildroot $(BUILDROOT_VERSION)"
	@echo "make fetch-livi      Download the current ARM64 LIVI AppImage"
	@echo "make pi4             Build output/pi4/images/livi-os-rpi4.img"
	@echo "make pi5             Build output/pi5/images/livi-os-rpi5.img"
	@echo "make check           Validate both defconfigs and project scripts"

bootstrap:
	@test -d "$(BUILDROOT_DIR)/.git" || git clone --depth 1 --branch "$(BUILDROOT_VERSION)" https://gitlab.com/buildroot.org/buildroot.git "$(BUILDROOT_DIR)"
	@test "$$(git -C "$(BUILDROOT_DIR)" rev-parse HEAD)" = "$(BUILDROOT_COMMIT)" || { echo "Unexpected Buildroot revision" >&2; exit 1; }

fetch-livi:
	@mkdir -p artifacts
	@./support/fetch-livi "$(LIVI_REPO)" "$(LIVI_CHANNEL)" artifacts/LIVI-arm64.AppImage

pi4_defconfig pi5_defconfig: bootstrap
	@board="$(@:_defconfig=)"; \
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/$$board" BR2_EXTERNAL="$(CURDIR)" "livi_r$${board}_defconfig"

pi4: pi4_defconfig
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi4" BR2_EXTERNAL="$(CURDIR)"

pi5: pi5_defconfig
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" BR2_EXTERNAL="$(CURDIR)"

menuconfig linux-menuconfig: bootstrap
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" BR2_EXTERNAL="$(CURDIR)" $@

check: bootstrap
	./support/check-project

clean:
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi4" clean 2>/dev/null || true
	$(MAKE) -C "$(BUILDROOT_DIR)" O="$(OUTPUT_BASE)/pi5" clean 2>/dev/null || true
