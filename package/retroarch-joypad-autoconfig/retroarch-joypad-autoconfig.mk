################################################################################
# Standard Linux gamepad mappings
################################################################################

RETROARCH_JOYPAD_AUTOCONFIG_VERSION = 2e3b8a2728d5efd00fa0207d07ba2488b89e87b2
RETROARCH_JOYPAD_AUTOCONFIG_SITE = $(call github,libretro,retroarch-joypad-autoconfig,$(RETROARCH_JOYPAD_AUTOCONFIG_VERSION))
RETROARCH_JOYPAD_AUTOCONFIG_LICENSE = MIT
RETROARCH_JOYPAD_AUTOCONFIG_LICENSE_FILES = COPYING

define RETROARCH_JOYPAD_AUTOCONFIG_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/usr/share/retroarch/autoconfig
	cp -a $(@D)/udev $(@D)/linuxraw $(@D)/hid \
		$(TARGET_DIR)/usr/share/retroarch/autoconfig/
	$(INSTALL) -m 0644 $(@D)/COPYING $(TARGET_DIR)/usr/share/retroarch/autoconfig/COPYING
endef

$(eval $(generic-package))
