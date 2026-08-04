################################################################################
# LIVI - local prebuilt AppImage payload
################################################################################

LIVI_VERSION = 1
LIVI_SITE_METHOD = local
LIVI_SITE = $(BR2_EXTERNAL_LIVI_OS_PATH)/package/livi/src
LIVI_LICENSE = GPL-3.0-or-later
LIVI_LICENSE_FILES = LICENSE
LIVI_APPIMAGE = $(call qstrip,$(BR2_PACKAGE_LIVI_APPIMAGE))

define LIVI_INSTALL_TARGET_CMDS
	test -f "$(LIVI_APPIMAGE)" || { echo "Missing LIVI AppImage: $(LIVI_APPIMAGE). Run make fetch-livi." >&2; exit 1; }
	$(INSTALL) -D -m 0755 "$(LIVI_APPIMAGE)" $(TARGET_DIR)/opt/livi-factory/LIVI.AppImage
endef

$(eval $(generic-package))
