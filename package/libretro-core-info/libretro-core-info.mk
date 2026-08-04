LIBRETRO_CORE_INFO_VERSION = f105af2925f70f2d72a8676d04a5f2282c1d01ba
LIBRETRO_CORE_INFO_SITE = $(call github,libretro,libretro-core-info,$(LIBRETRO_CORE_INFO_VERSION))
LIBRETRO_CORE_INFO_LICENSE = BSD-3-Clause
LIBRETRO_CORE_INFO_LICENSE_FILES = COPYING

define LIBRETRO_CORE_INFO_INSTALL_TARGET_CMDS
	$(INSTALL) -d $(TARGET_DIR)/usr/share/libretro/info
	$(INSTALL) -m 0644 $(@D)/*.info $(TARGET_DIR)/usr/share/libretro/info/
endef
$(eval $(generic-package))
