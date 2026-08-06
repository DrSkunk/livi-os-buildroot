################################################################################
# RetroArch for the LIVI kiosk
################################################################################

RETROARCH_VERSION = 1.22.2
RETROARCH_SITE = $(call github,libretro,RetroArch,v$(RETROARCH_VERSION))
RETROARCH_LICENSE = GPL-3.0
RETROARCH_LICENSE_FILES = COPYING
RETROARCH_DEPENDENCIES = host-pkgconf alsa-lib dbus libdrm libegl libgles libusb pipewire systemd wayland zlib

# RetroArch's qb configure only looks for ${CROSS_COMPILE}pkg-config in PATH
# and ignores Buildroot's PKG_CONFIG; it must be pointed at the host wrapper
# through its own PKG_CONF_PATH variable.
define RETROARCH_CONFIGURE_CMDS
	(cd $(@D) && $(TARGET_CONFIGURE_OPTS) \
		PKG_CONF_PATH="$(PKG_CONFIG_HOST_BINARY)" \
		./configure \
		--host=$(GNU_TARGET_NAME) --prefix=/usr \
		--with-assets_dir=/usr/share/retroarch/assets \
		--with-core_info_dir=/usr/share/libretro/info \
		--enable-wayland --disable-x11 --enable-egl --enable-opengles3 \
		--enable-udev --enable-alsa --enable-pipewire --enable-dbus \
		--enable-systemd --enable-libusb --enable-neon --disable-qt \
		--disable-vulkan --disable-ffmpeg --disable-pulse)
endef

define RETROARCH_BUILD_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) $(TARGET_CONFIGURE_OPTS) -C $(@D)
endef

define RETROARCH_INSTALL_TARGET_CMDS
	$(TARGET_MAKE_ENV) $(MAKE) -C $(@D) DESTDIR=$(TARGET_DIR) install
endef

$(eval $(generic-package))
