################################################################################
# Redistributable starter games
################################################################################

LIVI_HOMEBREW_VERSION = 1.0.0
LIVI_HOMEBREW_SITE = https://github.com/Koronewan/GameBoy-RedRodRacing/releases/download/v$(LIVI_HOMEBREW_VERSION)
LIVI_HOMEBREW_SOURCE = redrodracing.gb
LIVI_HOMEBREW_EXTRA_DOWNLOADS = https://raw.githubusercontent.com/gbdev/database/94368e51470f14fe5c495e6e65c994f2c3b6c661/entries/tobutobugirl/tobu.gb
LIVI_HOMEBREW_LICENSE = MIT, CC-BY-4.0
LIVI_HOMEBREW_LICENSE_FILES = LICENSE.redrod LICENSE.tobu

define LIVI_HOMEBREW_EXTRACT_CMDS
	cp $(LIVI_HOMEBREW_DL_DIR)/redrodracing.gb $(@D)/
	cp $(LIVI_HOMEBREW_DL_DIR)/tobu.gb $(@D)/
	cp $(LIVI_HOMEBREW_PKGDIR)/LICENSE.* $(@D)/
endef

define LIVI_HOMEBREW_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0644 $(@D)/redrodracing.gb \
		"$(TARGET_DIR)/usr/share/livi/games/roms/gameboy/Red Rod Racing.gb"
	$(INSTALL) -D -m 0644 $(@D)/tobu.gb \
		"$(TARGET_DIR)/usr/share/livi/games/roms/gameboy/Tobu Tobu Girl.gb"
	$(INSTALL) -D -m 0644 $(LIVI_HOMEBREW_PKGDIR)/gameboy.lpl \
		"$(TARGET_DIR)/usr/share/livi/games/retroarch/playlists/Nintendo - Game Boy.lpl"
	$(INSTALL) -D -m 0644 $(LIVI_HOMEBREW_PKGDIR)/CREDITS \
		$(TARGET_DIR)/usr/share/doc/livi-homebrew/CREDITS
	$(INSTALL) -m 0644 $(@D)/LICENSE.* $(TARGET_DIR)/usr/share/doc/livi-homebrew/
endef

$(eval $(generic-package))
