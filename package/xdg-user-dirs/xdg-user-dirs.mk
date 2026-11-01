################################################################################
# xdg-user-dirs
################################################################################

XDG_USER_DIRS_VERSION = 0.18
XDG_USER_DIRS_SITE = https://user-dirs.freedesktop.org/releases
XDG_USER_DIRS_LICENSE = GPL-2.0
XDG_USER_DIRS_LICENSE_FILES = COPYING
XDG_USER_DIRS_DEPENDENCIES = $(TARGET_NLS_DEPENDENCIES)
XDG_USER_DIRS_CONF_OPTS = --disable-documentation

$(eval $(autotools-package))
