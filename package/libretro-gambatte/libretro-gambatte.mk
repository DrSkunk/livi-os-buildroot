LIBRETRO_GAMBATTE_VERSION = 96174369b3c30d9fc57c926fa3379c273dc6a9a5
LIBRETRO_GAMBATTE_SITE = $(call github,libretro,gambatte-libretro,$(LIBRETRO_GAMBATTE_VERSION))
LIBRETRO_GAMBATTE_LICENSE = GPL-2.0
LIBRETRO_GAMBATTE_LICENSE_FILES = COPYING

define LIBRETRO_GAMBATTE_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) -f Makefile.libretro platform=unix \
		CC="$(TARGET_CC)" CXX="$(TARGET_CXX)" LD="$(TARGET_CXX)" AR="$(TARGET_AR)"
endef
define LIBRETRO_GAMBATTE_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/gambatte_libretro.so $(TARGET_DIR)/usr/lib/libretro/gambatte_libretro.so
endef
$(eval $(generic-package))
