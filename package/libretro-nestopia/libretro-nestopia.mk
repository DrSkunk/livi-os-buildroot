LIBRETRO_NESTOPIA_VERSION = d0f461cee801c509748606e91c8ff0563ef62cd6
LIBRETRO_NESTOPIA_SITE = $(call github,libretro,nestopia,$(LIBRETRO_NESTOPIA_VERSION))
LIBRETRO_NESTOPIA_LICENSE = GPL-2.0+
LIBRETRO_NESTOPIA_LICENSE_FILES = COPYING

define LIBRETRO_NESTOPIA_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D)/libretro platform=unix \
		CC="$(TARGET_CC)" CXX="$(TARGET_CXX)" LD="$(TARGET_CXX)" AR="$(TARGET_AR)" \
		CPPFLAGS="$(TARGET_CPPFLAGS) -I$(@D)/libretro/libretro-common/include"
endef
define LIBRETRO_NESTOPIA_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/libretro/nestopia_libretro.so $(TARGET_DIR)/usr/lib/libretro/nestopia_libretro.so
endef
$(eval $(generic-package))
