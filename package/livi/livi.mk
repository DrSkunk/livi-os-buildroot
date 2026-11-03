################################################################################
# LIVI - local prebuilt AppImage payload
################################################################################

LIVI_VERSION = 1
LIVI_SITE_METHOD = local
LIVI_SITE = $(BR2_EXTERNAL_LIVI_OS_PATH)/package/livi/src
LIVI_LICENSE = GPL-3.0-or-later
LIVI_LICENSE_FILES = LICENSE
LIVI_APPIMAGE = $(call qstrip,$(BR2_PACKAGE_LIVI_APPIMAGE))
LIVI_DEPENDENCIES = host-python3 host-squashfs

define LIVI_INSTALL_TARGET_CMDS
	test -f "$(LIVI_APPIMAGE)" || { echo "Missing LIVI AppImage: $(LIVI_APPIMAGE). Run make fetch-livi." >&2; exit 1; }
	test -f "$(LIVI_APPIMAGE).sha256" || { echo "Missing LIVI AppImage checksum" >&2; exit 1; }
	expected=`awk 'NR == 1 { print $$1 }' "$(LIVI_APPIMAGE).sha256"`; \
		actual=`sha256sum "$(LIVI_APPIMAGE)" | awk '{ print $$1 }'`; \
		test "$$expected" = "$$actual" || { echo "LIVI AppImage checksum mismatch" >&2; exit 1; }
	rm -rf $(@D)/factory
	offset=`$(HOST_DIR)/bin/python3 -c 'import struct, sys; f = open(sys.argv[1], "rb"); h = f.read(64); assert h[:5] == b"\x7fELF\x02" and h[5] == 1; print(struct.unpack_from("<Q", h, 40)[0] + struct.unpack_from("<H", h, 58)[0] * struct.unpack_from("<H", h, 60)[0])' "$(LIVI_APPIMAGE)"`; \
		$(HOST_DIR)/bin/unsquashfs -no-progress -d $(@D)/factory -o "$$offset" "$(LIVI_APPIMAGE)" \
		resources/driver resources/core resources/compositor resources/gst-host livi-ui \
		resources/livi-os-helper-api resources/99-LIVI.rules.template resources/livi-touch-filter \
		resources/livi-wifi-ap.service.template resources/livi-os-display-api
	test -f $(@D)/factory/resources/livi-os-helper-api && \
		test "$$(cat $(@D)/factory/resources/livi-os-helper-api)" = 2 || \
		{ echo "Factory AppImage must implement LIVI OS API 2 (Rust); see docs/rust-appimage-contract.md." >&2; exit 1; }
	$(HOST_DIR)/bin/python3 $(BR2_EXTERNAL_LIVI_OS_PATH)/support/check-rust-payload $(@D)/factory
	$(INSTALL) -D -m 0755 "$(LIVI_APPIMAGE)" $(TARGET_DIR)/opt/livi-factory/LIVI.AppImage
	mkdir -p $(TARGET_DIR)/usr/lib/livi
	cd $(TARGET_DIR) && sha256sum opt/livi-factory/LIVI.AppImage > usr/lib/livi/factory-appimage.sha256
	rm -f $(TARGET_DIR)/usr/lib/livi/livi-helperd $(TARGET_DIR)/usr/libexec/livi-projection-helper
	$(INSTALL) -D -m 0755 $(@D)/factory/resources/driver/livi-helperd $(TARGET_DIR)/usr/libexec/livi-helperd
	mkdir -p $(TARGET_DIR)/etc/systemd/system
	sed -e 's|/usr/local/sbin/livi-helperd|/usr/libexec/livi-helperd|g' \
		-e 's/__USERNAME__/livi/g' $(@D)/factory/resources/livi-wifi-ap.service.template | \
		awk '/^\[Unit\]$$/ { print; print "Requires=livi-data-setup.service"; print "After=livi-data-setup.service"; next } { print }' \
		> $(TARGET_DIR)/etc/systemd/system/livi-wifi-ap.service
	chmod 0644 $(TARGET_DIR)/etc/systemd/system/livi-wifi-ap.service
	$(INSTALL) -D -m 0755 $(@D)/factory/resources/livi-touch-filter $(TARGET_DIR)/usr/local/lib/livi/livi-touch-filter
	mkdir -p $(TARGET_DIR)/etc/udev/rules.d
	sed 's/__USERNAME__/livi/g' $(@D)/factory/resources/99-LIVI.rules.template > $(TARGET_DIR)/etc/udev/rules.d/99-LIVI.rules
	chmod 0644 $(TARGET_DIR)/etc/udev/rules.d/99-LIVI.rules
endef

$(eval $(generic-package))

ifeq ($(BR2_PACKAGE_LIVI),y)
$(LIVI_TARGET_INSTALL_TARGET): $(LIVI_APPIMAGE) $(LIVI_APPIMAGE).sha256
endif
