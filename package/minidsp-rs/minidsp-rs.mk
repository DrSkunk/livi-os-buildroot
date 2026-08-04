################################################################################
# minidsp-rs - pinned upstream ARM64 release payload
################################################################################

MINIDSP_RS_VERSION = 0.1.12-1
MINIDSP_RS_SOURCE = minidsp_$(MINIDSP_RS_VERSION)_arm64.deb
MINIDSP_RS_SITE = https://github.com/mrene/minidsp-rs/releases/download/v0.1.12
MINIDSP_RS_LICENSE = MIT
MINIDSP_RS_LICENSE_FILES = usr/share/doc/minidsp/copyright
MINIDSP_RS_DEPENDENCIES = libusb

define MINIDSP_RS_EXTRACT_CMDS
	mkdir -p $(@D)
	cd $(@D) && ar x $(MINIDSP_RS_DL_DIR)/$(MINIDSP_RS_SOURCE)
	cd $(@D) && tar -xf data.tar.*
endef

define MINIDSP_RS_INSTALL_TARGET_CMDS
	$(INSTALL) -D -m 0755 $(@D)/usr/bin/minidsp $(TARGET_DIR)/usr/bin/minidsp
	$(INSTALL) -D -m 0755 $(@D)/usr/bin/minidspd $(TARGET_DIR)/usr/bin/minidspd
	$(INSTALL) -D -m 0644 $(@D)/etc/minidsp/config.toml $(TARGET_DIR)/etc/minidsp/config.toml
	$(INSTALL) -D -m 0644 $(@D)/lib/udev/rules.d/99-minidsp.rules $(TARGET_DIR)/usr/lib/udev/rules.d/99-minidsp.rules
	$(INSTALL) -D -m 0644 $(@D)/lib/systemd/system/minidsp.service $(TARGET_DIR)/usr/lib/systemd/system/minidsp.service
endef

$(eval $(generic-package))
