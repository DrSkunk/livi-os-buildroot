################################################################################
# Touch menu assets and fonts for RetroArch
################################################################################

RETROARCH_ASSETS_VERSION = d9f969054dc7fbb6fa89519036d2b971e0855b51
RETROARCH_ASSETS_SITE = $(call github,libretro,retroarch-assets,$(RETROARCH_ASSETS_VERSION))
RETROARCH_ASSETS_LICENSE = CC-BY-4.0, OFL-1.1, Apache-2.0, Bitstream-Vera, mplus
RETROARCH_ASSETS_LICENSE_FILES = COPYING fonts/Metrophobic-Regular-OFL.txt fonts/TitilliumWeb-OFL.txt fonts/DejaVuSans.LICENSE.txt fonts/OpenSans-Regular_LICENSE.txt fonts/mplus-1pLICENSE_E.txt

define RETROARCH_ASSETS_INSTALL_TARGET_CMDS
	mkdir -p $(TARGET_DIR)/usr/share/retroarch/assets
	cp -a $(@D)/glui $(@D)/ozone $(@D)/fonts $(@D)/sounds \
		$(TARGET_DIR)/usr/share/retroarch/assets/
	$(INSTALL) -m 0644 $(@D)/COPYING $(TARGET_DIR)/usr/share/retroarch/assets/COPYING
endef

$(eval $(generic-package))
