LIBRETRO_GENESIS_PLUS_GX_VERSION = ca93fec870378f3bff65931bcd828d5e756cce75
LIBRETRO_GENESIS_PLUS_GX_SITE = $(call github,libretro,Genesis-Plus-GX,$(LIBRETRO_GENESIS_PLUS_GX_VERSION))
LIBRETRO_GENESIS_PLUS_GX_LICENSE = Non-commercial
LIBRETRO_GENESIS_PLUS_GX_LICENSE_FILES = LICENSE.txt
LIBRETRO_GENESIS_PLUS_GX_DEPENDENCIES = zlib

define LIBRETRO_GENESIS_PLUS_GX_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) -f Makefile.libretro platform=unix \
		CC="$(TARGET_CC)" CXX="$(TARGET_CXX)" LD="$(TARGET_CXX)" AR="$(TARGET_AR)"
endef
define LIBRETRO_GENESIS_PLUS_GX_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/genesis_plus_gx_libretro.so $(TARGET_DIR)/usr/lib/libretro/genesis_plus_gx_libretro.so
endef
$(eval $(generic-package))
