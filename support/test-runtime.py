#!/usr/bin/env python3
"""Exercise recovery scripts in temporary directories, without target devices."""

import os
import runpy
import shutil
import hashlib
import json
import configparser
from unittest import mock
from pathlib import Path
import socket
import struct
import sys
import subprocess
import tempfile
import time
import threading
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "board/drskunk/livi/rootfs-overlay/usr/bin"
DISPLAY_DEFAULTS = {
    "projectionWidth": 1280,
    "projectionHeight": 400,
    "clusterWidth": 1280,
    "clusterHeight": 400,
}


class BootSplash(unittest.TestCase):
    def run_start(self, framebuffer):
        source = (SCRIPTS.parent / "libexec/livi-splash-start").read_text()
        source = source.replace("[ ! -c /dev/fb0 ]", f"[ {int(not framebuffer)} = 1 ]")
        source = source.replace("sleep 0.1", ":")
        source = source.replace("exec /usr/bin/psplash", "printf '%s\\n'")
        return subprocess.run(["sh", "-c", source], capture_output=True, text=True)

    def test_draws_rotated_without_console_switch(self):
        result = self.run_start(True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["-n", "-a", "90"])

    def test_missing_framebuffer_fails_with_bounded_wait(self):
        result = self.run_start(False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no framebuffer", result.stderr)

    def test_no_fifo_stop_returns_without_delaying_app(self):
        source = (SCRIPTS.parent / "libexec/livi-splash-stop").read_text()
        source = source.replace("[ -p /run/psplash_fifo ]", "false")
        result = subprocess.run(["sh", "-c", source], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_live_fifo_gets_bounded_quit_request(self):
        source = (SCRIPTS.parent / "libexec/livi-splash-stop").read_text()
        source = source.replace("[ -p /run/psplash_fifo ]", "true")
        source = source.replace("exec /usr/bin/timeout", "printf '%s\\n'")
        result = subprocess.run(["sh", "-c", source], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.splitlines(), ["2", "/usr/bin/psplash-write", "QUIT"])

    def test_early_service_releases_display_before_app(self):
        units = SCRIPTS.parent / "lib/systemd/system"
        # systemd permits repeated directives, such as After= in livi.service.
        splash = configparser.ConfigParser(interpolation=None)
        splash.read(units / "livi-splash.service")
        self.assertEqual(splash["Unit"]["DefaultDependencies"], "no")
        self.assertIn("sysinit.target", splash["Unit"]["Before"].split())
        self.assertEqual(splash["Unit"]["RequiresMountsFor"], "/run")
        self.assertEqual(splash["Service"]["Type"], "simple")
        app = (units / "livi.service").read_text().splitlines()
        self.assertIn("After=livi-splash.service", app)
        conflicts = [line for line in app if line.startswith("Conflicts=")]
        self.assertFalse(any("livi-splash.service" in line for line in conflicts))
        self.assertIn("ExecStartPre=+/usr/bin/systemctl stop livi-splash.service", app)

    def test_panel_asset_and_boot_console_policy(self):
        board = ROOT / "board/drskunk/livi"
        header = (board / "boot-splash.png").read_bytes()[:24]
        self.assertEqual(header[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(struct.unpack(">II", header[16:24]), (1280, 400))
        for model in ("rpi4", "rpi5"):
            self.assertIn("disable_splash=1", (board / f"config-{model}.txt").read_text())
            command = (board / f"cmdline-{model}.txt").read_text().split()
            self.assertNotIn("console=tty1", command)
            self.assertIn("logo.nologo", command)
            self.assertIn("systemd.show_status=false", command)
            self.assertTrue(any(arg.startswith("console=tty") for arg in command))


class ProjectionPrivilegeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        interpreter = self.path / "helperd"
        interpreter.write_text(
            '#!/bin/sh\nprintf "args:%s\\n" "$*"\n'
            'printf "user:%s\\nkey:%s\\npairing:%s\\n" "$SUDO_USER" "$LIVI_CP_PK" "$LIVI_CP_PI"\n'
            'printf "api:%s:%s:%s\\nflags:%s:%s:%s:%s\\n" "$LIVI_OS" "$LIVI_OS_API" "$LIVI_LIFELINE" "$LIVI_AA_WIRELESS" "$LIVI_CP_WIRELESS" "$LIVI_CP_DEBUG" "$DEBUG"\n'
            'printf "injected:%s:%s:%s\\n" "${PYTHONPATH-unset}" "${LD_PRELOAD-unset}" "${BASH_ENV-unset}"\n'
        )
        interpreter.chmod(0o755)
        script = (SCRIPTS.parent / "libexec/livi-projection-helper").read_text()
        script = (script.replace('$(/usr/bin/id -u)', "0")
                  .replace("/usr/lib/livi/livi-helperd", str(interpreter)))
        self.script = self.path / "launcher"
        self.script.write_text(script)
        self.key = "ab" * 32

    def launch(self, *args):
        return subprocess.run(
            ["sh", str(self.script), *args], capture_output=True, text=True,
            env={**os.environ, "PYTHONPATH": "/untrusted", "BASH_ENV": "/untrusted",
                 "SUDO_USER": "attacker"},
        )

    def test_only_validated_arguments_reach_immutable_rust_helper(self):
        result = self.launch("1", "0", self.key, "pairing-123", "0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("args:\n", result.stdout)
        self.assertIn("user:livi", result.stdout)
        self.assertIn("api:1:2:1", result.stdout)
        self.assertIn("flags:1:0:0:0", result.stdout)
        self.assertIn(f"key:{self.key}", result.stdout)
        self.assertIn("pairing:pairing-123", result.stdout)
        self.assertIn("injected:unset:unset:unset", result.stdout)

    def test_rejects_extra_interpreter_arguments(self):
        self.assertNotEqual(self.launch("1", "0", self.key, "id", "0", "-c").returncode, 0)

    def test_rejects_invalid_wireless_flags(self):
        self.assertNotEqual(self.launch("yes", "0", self.key, "id", "0").returncode, 0)

    def test_rejects_invalid_public_key(self):
        for key in ("", "ab", "g" * 64):
            with self.subTest(key=key):
                self.assertNotEqual(self.launch("1", "0", key, "id", "0").returncode, 0)

    def test_rejects_pairing_id_with_control_characters(self):
        self.assertNotEqual(self.launch("1", "0", self.key, "id\nPATH=/tmp", "0").returncode, 0)

    def test_rejects_installer_switch_and_oversized_pairing_id(self):
        self.assertNotEqual(self.launch("--install-udev-rule").returncode, 0)
        self.assertNotEqual(self.launch("1", "0", self.key, "x" * 65, "0").returncode, 0)


class PowerPrivilegeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        self.systemctl = path / "systemctl"
        self.systemctl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@"\n'
            'printf "env:%s:%s\\n" "${BASH_ENV-unset}" "${LIVI_OS_UPDATE_REPO-unset}"\n'
        )
        self.systemctl.chmod(0o755)
        self.flock = path / "flock"
        self.flock.write_text('#!/bin/sh\n[ "$1" = -n ] && [ "$2" = 9 ]\n')
        self.flock.chmod(0o755)
        source = (SCRIPTS.parent / "libexec/livi-power-helper").read_text()
        self.script = path / "launcher"
        self.script.write_text(
            source.replace('$(/usr/bin/id -u)', "0")
            .replace("/usr/bin/systemctl", str(self.systemctl))
            .replace("/usr/bin/flock", str(self.flock))
            .replace("/run/livi-os-update.lock", str(path / "lock"))
        )

    def launch(self, *args):
        return subprocess.run(
            ["sh", str(self.script), *args], capture_output=True, text=True,
            env={**os.environ, "BASH_ENV": "/untrusted",
                 "LIVI_OS_UPDATE_REPO": "attacker/repo"},
        )

    def test_only_exact_poweroff_and_reboot_reach_systemctl_with_clean_environment(self):
        for action in ("poweroff", "reboot"):
            result = self.launch(action)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.splitlines(), ["--no-block", action, "env:unset:unset"])

    def test_rejects_extra_arguments_services_and_shell_commands(self):
        for args in [(), ("halt",), ("reboot", "--force"), ("start", "sshd"),
                     ("poweroff;id",), ("sh", "-c", "id")]:
            with self.subTest(args=args):
                self.assertNotEqual(self.launch(*args).returncode, 0)

    def test_systemctl_failure_reaches_caller(self):
        self.systemctl.write_text('#!/bin/sh\necho "systemd refused" >&2\nexit 1\n')
        result = self.launch("poweroff")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("systemd refused", result.stderr)

    def test_an_active_os_update_prevents_host_power_changes(self):
        self.flock.write_text('#!/bin/sh\nexit 1\n')
        result = self.launch("reboot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OS update operation is running", result.stderr)
        self.assertEqual(result.stdout, "")


class OsUpdatePrivilegeBoundary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name)
        updater = path / "updater"
        updater.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$@"\n'
            'printf "repo:%s\\nenv:%s\\n" "${LIVI_OS_UPDATE_REPO-unset}" "${BASH_ENV-unset}"\n'
        )
        updater.chmod(0o755)
        source = (SCRIPTS.parent / "libexec/livi-os-update-helper").read_text()
        source = (source.replace('$(/usr/bin/id -u)', "0")
                  .replace("/usr/bin/livi-os-update", str(updater)))
        self.script = path / "launcher"
        self.script.write_text(source)

    def launch(self, *args):
        return subprocess.run(
            ["sh", str(self.script), *args], capture_output=True, text=True,
            env={**os.environ, "LIVI_OS_UPDATE_REPO": "attacker/repo",
                 "BASH_ENV": "/untrusted"},
        )

    def test_only_fixed_operations_and_channels_reach_updater(self):
        for args, expected in [
            (("status",), ["status"]),
            (("check", "stable"), ["check", "--channel", "stable"]),
            (("check", "nightly"), ["check", "--channel", "nightly"]),
            (("stage", "nightly"), ["update", "--channel", "nightly", "--progress"]),
            (("stage", "stable"), ["update", "--channel", "stable", "--progress"]),
            (("apply",), ["apply"]),
        ]:
            with self.subTest(args=args):
                result = self.launch(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected + ["repo:unset", "env:unset"])

    def test_rejects_paths_downgrades_retries_injections_and_extra_arguments(self):
        for args in [
            (), ("install", "/tmp/manifest"), ("check",), ("stage", "dev"),
            ("status", "extra"), ("apply", "--retry-failed"),
            ("stage", "stable", "--allow-downgrade"), ("stage", "stable;reboot"),
            ("sh", "-c", "id"), ("cancel",),
        ]:
            with self.subTest(args=args):
                self.assertNotEqual(self.launch(*args).returncode, 0)


class RustPayload(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "app"
        self.module = runpy.run_path(str(ROOT / "support/check-rust-payload"))
        for relative in self.module["BINARIES"]:
            path = self.path / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            header = bytearray(64)
            header[:6] = b"\x7fELF\x02\x01"
            struct.pack_into("<H", header, 18, 183)
            path.write_bytes(header)
            path.chmod(0o755)
        for relative in self.module["RESOURCES"]:
            (self.path / relative).write_text("2\n")

    def check(self):
        self.module["check"](self.path)

    def test_valid_arm64_api2_layout(self):
        self.check()

    def test_old_api_is_rejected(self):
        (self.path / "resources/livi-os-helper-api").write_text("1\n")
        with self.assertRaises(ValueError):
            self.check()

    def test_missing_or_nonexecutable_binary_is_rejected(self):
        path = self.path / "livi-ui"
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            self.check()
        path.unlink()
        with self.assertRaises(ValueError):
            self.check()

    def test_x64_binary_is_rejected(self):
        (self.path / "livi-ui").write_bytes(b"\x7fELF\x02\x01" + b"\x00" * 12 + b"\x3e\x00")
        with self.assertRaises(ValueError):
            self.check()

    def test_helper_symlink_is_rejected(self):
        helper = self.path / "resources/driver/livi-helperd"
        helper.unlink()
        helper.symlink_to(self.path / "livi-ui")
        with self.assertRaises(ValueError):
            self.check()

    def test_parent_directory_symlink_is_rejected(self):
        driver = self.path / "resources/driver"
        outside = self.path.parent / "outside"
        driver.rename(outside)
        driver.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.check()

    def test_marker_symlink_is_rejected(self):
        marker = self.path / "resources/livi-os-helper-api"
        marker.unlink()
        outside = self.path.parent / "api"
        outside.write_text("2\n")
        marker.symlink_to(outside)
        with self.assertRaises(ValueError):
            self.check()

    def test_type2_extraction_and_checksum_preflight(self):
        squashfs = self.path.parent / "payload.squashfs"
        subprocess.run(["mksquashfs", str(self.path), str(squashfs), "-noappend",
                        "-no-progress", "-processors", "1"],
                       check=True, capture_output=True)
        # Structural fixture only: none of these synthetic ELF files can run.
        header = bytearray((self.path / "livi-ui").read_bytes())
        header[8:11] = b"AI\x02"
        struct.pack_into("<Q", header, 40, 64)
        image = self.path.parent / "fixture.AppImage"
        image.write_bytes(header + squashfs.read_bytes())
        sidecar = Path(f"{image}.sha256")
        sidecar.write_text(hashlib.sha256(image.read_bytes()).hexdigest() + "\n")
        command = [sys.executable, str(ROOT / "support/check-rust-payload"),
                   "--appimage", str(image)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        sidecar.write_text("0" * 64 + "\n")
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch", result.stderr)


class ApplianceFirstBootDefaults(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.data = self.path / "data"
        self.config = self.data / "livi/config/LIVI/config.json"
        self.backup = self.data / "livi/config/config.json.last-good"
        self.config.parent.mkdir(parents=True)
        (self.data / ".livi-data").touch()
        sync = self.path / "sync"
        sync.write_text("#!/bin/sh\nexit 0\n")
        sync.chmod(0o755)
        source = (SCRIPTS.parent / "libexec/livi-data-setup").read_text()
        source = source[:source.index("\nmerge_dir()")]
        self.script = self.path / "setup"
        self.script.write_text(source.replace("/data/", f"{self.data}/")
                               .replace("/usr/share/livi/config-default.json",
                                        str(SCRIPTS.parent / "share/livi/config-default.json"))
                               .replace("/run/user/1000", str(self.path / "runtime")))

    def seed(self):
        subprocess.run(["sh", str(self.script)], check=True, capture_output=True,
                       env={**os.environ, "PATH": f"{self.path}:{os.environ['PATH']}"})

    def test_seeds_country_panel_and_unique_private_password(self):
        self.seed()
        config = json.loads(self.config.read_text())
        self.assertEqual(config["country"], "CA")
        self.assertEqual((config["mainScreenWidth"], config["mainScreenHeight"]), (1280, 400))
        for key, value in DISPLAY_DEFAULTS.items():
            self.assertEqual(config[key], value)
        self.assertTrue(config["kiosk"]["main"])
        self.assertRegex(config["wifiPassword"], r"^[0-9a-f]{32}$")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_preserves_existing_configuration(self):
        self.config.write_text('{"country":"NL","wifiPassword":"custom-passphrase"}')
        original = self.config.read_text()
        self.seed()
        self.assertEqual(self.config.read_text(), original)

    def test_does_not_mask_a_missing_config_with_a_last_good_backup(self):
        self.backup.write_text('{"country":"NL"}')
        self.seed()
        self.assertFalse(self.config.exists())

    def test_does_not_follow_predictable_temporary_file_symlinks(self):
        victim = self.path / "victim"
        victim.write_text("preserve")
        self.config.with_name("config.json.new").symlink_to(victim)
        self.seed()
        self.assertEqual(victim.read_text(), "preserve")


class RetroArchSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = self.path / "retroarch.cfg"
        self.marker = self.path / "state/menu-v1"
        self.defaults = SCRIPTS.parent / "share/livi/retroarch.cfg"
        self.script = SCRIPTS.parent / "libexec/livi-retroarch-setup"

    def setup_menu(self):
        subprocess.run(["sh", str(self.script), str(self.config),
                        str(self.defaults), str(self.marker)], check=True,
                       capture_output=True, text=True)
        return self.config.read_text()

    def test_new_menu_has_touch_assets_and_persistent_saves(self):
        config = self.setup_menu()
        for line in ['menu_driver = "glui"', 'menu_pointer_enable = "true"',
                     'input_driver = "wayland"', 'video_fullscreen = "true"',
                     'assets_directory = "/usr/share/retroarch/assets"',
                     'input_menu_toggle_gamepad_combo = "4"',
                     'savefile_directory = "/data/games/saves"']:
            self.assertIn(line, config)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.marker.exists())

    def test_existing_menu_is_backed_up_and_unrelated_settings_survive(self):
        original = (' menu_driver="ozone"\nmenu_pointer_enable = "false"\n'
                    'input_driver = "udev"\nvideo_fullscreen = "false"\n'
                    'audio_volume = "-12"\nsavefile_directory = "/data/custom"\n')
        self.config.write_text(original)
        config = self.setup_menu()
        self.assertIn('menu_driver = "glui"', config)
        self.assertIn('menu_pointer_enable = "true"', config)
        self.assertIn('input_driver = "wayland"', config)
        self.assertIn('video_fullscreen = "true"', config)
        self.assertEqual(config.count('input_driver ='), 1)
        self.assertIn('audio_volume = "-12"', config)
        self.assertIn('savefile_directory = "/data/custom"', config)
        self.assertEqual(self.config.with_name("retroarch.cfg.before-touch-v2").read_text(),
                         original)

    def test_later_user_edits_are_not_reset_on_boot(self):
        self.setup_menu()
        self.config.write_text('menu_driver = "rgui"\n')
        self.assertEqual(self.setup_menu(), 'menu_driver = "rgui"\n')


class ConfigurationRecovery(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.config = self.path / "LIVI/config.json"
        self.backup = self.path / "last-good.json"
        self.factory = self.path / "factory-config.json"
        self.config.parent.mkdir()
        self.backup.write_text('{"volume":42}\n')
        self.factory.write_text(json.dumps(DISPLAY_DEFAULTS))
        # Ownership changes require root on the target. Record the requested
        # owner here while exercising the real validation/copy/rename logic.
        chown = self.path / "chown"
        chown.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$OWNERSHIP_LOG"\n')
        chown.chmod(0o755)
        sync = self.path / "sync"
        sync.write_text("#!/bin/sh\nexit 0\n")
        sync.chmod(0o755)
        self.script = self.path / "guard"
        self.script.write_text(
            (SCRIPTS / "livi-config-guard").read_text()
            .replace("/data/livi/config/LIVI/config.json", str(self.config))
            .replace("/data/livi/config/config.json.last-good", str(self.backup))
            .replace("/usr/share/livi/config-default.json", str(self.factory))
        )
        self.script.chmod(0o755)

    def environment(self):
        return {**os.environ, "PATH": f"{self.path}:{os.environ['PATH']}",
                "OWNERSHIP_LOG": str(self.path / "owners")}

    def restore(self):
        subprocess.run(
            ["sh", str(self.script), "restore"], check=True, env=self.environment(),
            capture_output=True, text=True,
        )

    def start_configuration(self, check=True):
        source = (SCRIPTS / "livi-supervisor").read_text()
        start = source.index("/usr/bin/livi-config-guard restore")
        end = source.index('runtime="$(mktemp', start)
        commands = source[start:end].replace("/usr/bin/livi-config-guard", "guard")
        return subprocess.run(
            ["bash", "-c", commands], check=check, env=self.environment(),
            capture_output=True, text=True,
        )

    def test_factory_defaults_match_panel_and_do_not_freeze_other_settings(self):
        path = SCRIPTS.parent / "share/livi/config-default.json"
        self.assertEqual(json.loads(path.read_text()), DISPLAY_DEFAULTS)

    def test_first_start_initializes_projection_and_cluster(self):
        self.backup.unlink()
        self.start_configuration()
        self.assertEqual(json.loads(self.config.read_text()), DISPLAY_DEFAULTS)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.config.stat().st_uid, os.getuid())
        self.assertEqual(list(self.config.parent.glob("config.json.new.*")), [])
        before = self.config.read_bytes()
        self.start_configuration()
        self.assertEqual(self.config.read_bytes(), before)

    def test_existing_configuration_is_not_replaced_by_defaults(self):
        original = '{"projectionWidth":800,"projectionHeight":480,"volume":17}\n'
        self.config.write_text(original)
        self.start_configuration()
        self.assertEqual(self.config.read_text(), original)

    def test_backup_is_restored_before_first_run_defaults(self):
        self.start_configuration()
        self.assertEqual(self.config.read_text(), self.backup.read_text())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)

    def test_invalid_configuration_without_backup_is_not_replaced(self):
        self.backup.unlink()
        self.config.write_text("broken")
        self.start_configuration()
        self.assertEqual(self.config.read_text(), "broken")

    def test_invalid_backup_is_not_ignored_for_initialization(self):
        self.backup.write_text("broken")
        self.start_configuration()
        self.assertFalse(self.config.exists())
        self.assertEqual(self.backup.read_text(), "broken")

    def test_dangling_configuration_and_backup_links_are_preserved(self):
        self.backup.unlink()
        self.config.symlink_to(self.path / "missing-config")
        self.start_configuration()
        self.assertTrue(self.config.is_symlink())
        self.config.unlink()
        self.backup.symlink_to(self.path / "missing-backup")
        self.start_configuration()
        self.assertFalse(self.config.exists())
        self.assertTrue(self.backup.is_symlink())

    def test_invalid_factory_defaults_stop_startup(self):
        self.backup.unlink()
        self.factory.write_text("[]")
        result = self.start_configuration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("defaults", result.stderr.lower())
        self.assertFalse(self.config.exists())

    def test_failed_installation_stops_startup_and_cleans_temporary_file(self):
        self.backup.unlink()
        link = self.path / "ln"
        link.write_text("#!/bin/sh\nexit 1\n")
        link.chmod(0o755)
        result = self.start_configuration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.config.exists())
        self.assertEqual(list(self.config.parent.glob("config.json.new.*")), [])

    def test_configuration_created_during_initialization_is_preserved(self):
        self.backup.unlink()
        link = self.path / "ln"
        link.write_text(
            '#!/bin/sh\n'
            'printf \'{"volume":17}\\n\' > "$2"\n'
            'exec /bin/ln "$@"\n'
        )
        link.chmod(0o755)
        result = self.start_configuration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(), '{"volume":17}\n')
        self.assertEqual(list(self.config.parent.glob("config.json.new.*")), [])
        self.start_configuration()
        self.assertEqual(self.config.read_text(), '{"volume":17}\n')

    def test_failed_recovery_stops_startup(self):
        self.config.write_text("broken")
        chown = self.path / "chown"
        chown.write_text("#!/bin/sh\nexit 1\n")
        result = self.start_configuration(check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(), "broken")

    def test_missing_configuration_is_restored(self):
        self.restore()
        self.assertEqual(self.config.read_text(), self.backup.read_text())
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertIn(f"livi:livi {self.config}.new", (self.path / "owners").read_text())

    def test_truncated_configuration_is_restored(self):
        self.config.write_text('{"volume":')
        self.restore()
        self.assertEqual(self.config.read_text(), self.backup.read_text())

    def test_valid_configuration_is_preserved(self):
        self.config.write_text('{"volume":10}')
        self.restore()
        self.assertEqual(self.config.read_text(), '{"volume":10}')

    def test_invalid_backup_does_not_replace_configuration(self):
        self.config.write_text("broken")
        self.backup.write_text("[]")
        self.restore()
        self.assertEqual(self.config.read_text(), "broken")


class KioskRecovery(unittest.TestCase):
    def run_health_window(self, ready, fatal=False, fail_after_commit=False):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            log = path / "log"
            log.write_text("fatal error\n" if fatal else "started\n")
            if fatal:
                (path / "fatal").touch()
            # Run the actual health/recovery portion with a live child process.
            # A live but unhealthy child used to block in wait indefinitely.
            source = (SCRIPTS / "livi-supervisor").read_text()
            source = source[source.index("healthy=0\n"):]
            source = source.replace("/run/user/1000/wayland-0", str(path / "wayland-0"))
            source = source.replace("/usr/bin/livi-os-slot", "slot")
            source = source.replace("/usr/bin/sudo", "sudo")
            source = source.replace("/usr/libexec/livi-kiosk-ready", "ready_check")
            with socket.socket(socket.AF_UNIX) as sock:
                sock.bind(str(path / "wayland-0"))
                preamble = f'''
set -u
HEALTH_SECONDS=1
STARTUP_SECONDS=1
LOG='{log}'
fatal_log='{path / "fatal"}'
logger_pid=$$
CURRENT=/nonexistent
current_hash=good
good_hash=good
STATE='{path}'
pgrep() {{ return {0 if ready else 1}; }}
ready_check() {{ [ '{int(ready)}' = 1 ] && test ! -e '{path}/health-lost'; }}
sudo() {{ shift; "$@"; }}
sleep() {{ command sleep 0.02; }}
hash_file() {{ echo good; }}
slot() {{
  echo "$1" >> '{path}/slots'
  if [ "$1" = mark-good ] && [ '{int(fail_after_commit)}' = 1 ]; then
    touch '{path}/health-lost'
  fi
}}
command sleep 0.2 &
kiosk_pid=$!
command sleep 10 &
guard_pid=$!
trap 'kill "$kiosk_pid" "$guard_pid" 2>/dev/null || true' EXIT
'''
                result = subprocess.run(["bash", "-c", preamble + source],
                                        capture_output=True, text=True, timeout=3)
            return result.returncode, (path / "slots").read_text()

    def test_live_kiosk_without_readiness_is_restarted(self):
        code, slots = self.run_health_window(ready=False)
        self.assertEqual(code, 1)
        self.assertEqual(slots, "boot-failed\n")

    def test_fatal_diagnostic_prevents_commit(self):
        code, slots = self.run_health_window(ready=True, fatal=True)
        self.assertEqual(code, 1)
        self.assertEqual(slots, "boot-failed\n")

    def test_healthy_kiosk_commits(self):
        code, slots = self.run_health_window(ready=True)
        self.assertEqual(code, 0)
        self.assertEqual(slots, "mark-good\n")

    def test_loss_of_readiness_after_commit_restarts_kiosk(self):
        code, slots = self.run_health_window(ready=True, fail_after_commit=True)
        self.assertEqual(code, 1)
        self.assertEqual(slots, "mark-good\n")



class DefaultsMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.source, self.target, self.state = [self.path / n for n in ("factory", "live", "state")]
        self.source.mkdir()
        self.target.mkdir()
        module = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-merge-defaults"))
        self.merge_defaults = module["merge"]
        patcher = mock.patch.object(module["os"], "sync")
        patcher.start()
        self.addCleanup(patcher.stop)

    def merge(self):
        self.merge_defaults(self.source, self.target, self.state)

    def test_update_and_rollback_untouched_defaults(self):
        (self.source / "config").write_text("old")
        self.merge()
        (self.source / "config").write_text("new")
        self.merge()
        self.assertEqual((self.target / "config").read_text(), "new")
        (self.source / "config").write_text("old")
        self.merge()
        self.assertEqual((self.target / "config").read_text(), "old")

    def test_local_edits_survive_and_new_default_is_saved(self):
        (self.source / "config").write_text("old")
        self.merge()
        (self.target / "config").write_text("local")
        (self.source / "config").write_text("new")
        self.merge()
        self.assertEqual((self.target / "config").read_text(), "local")
        incoming = list((self.state / "incoming").glob("*/config"))
        self.assertEqual(incoming[0].read_text(), "new")
        self.assertTrue((self.state / "conflicts.json").exists())

    def test_obsolete_untouched_file_is_removed(self):
        (self.source / "obsolete").write_text("old")
        self.merge()
        (self.source / "obsolete").unlink()
        self.merge()
        self.assertFalse((self.target / "obsolete").exists())

    def test_user_deletion_is_preserved(self):
        (self.source / "config").write_text("old")
        self.merge()
        (self.target / "config").unlink()
        (self.source / "config").write_text("new")
        self.merge()
        self.assertFalse((self.target / "config").exists())

    def test_legacy_configuration_is_not_blindly_overwritten(self):
        (self.target / "config").write_text("legacy local")
        (self.source / "config").write_text("new")
        self.merge()
        self.assertEqual((self.target / "config").read_text(), "legacy local")
        self.assertTrue((self.state / "conflicts.json").exists())

    def test_local_directory_symlink_is_not_followed(self):
        elsewhere = self.path / "elsewhere"
        elsewhere.mkdir()
        (self.source / "nested").mkdir()
        (self.source / "nested/config").write_text("factory")
        (self.target / "nested").symlink_to(elsewhere, target_is_directory=True)
        self.merge()
        self.assertFalse((elsewhere / "config").exists())


class LogRotation(unittest.TestCase):
    def test_bounds_newline_free_output_and_retains_fatal_marker(self):
        capture = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-log-writer"))["capture"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            payload = b"fatal error" + b"x" * 92
            source = path / "input"
            source.write_bytes(payload)
            with source.open("rb") as stream:
                capture(stream, path / "log", path / "fatal", limit=32)
            self.assertEqual((path / "log").read_bytes(), payload[96:])
            self.assertEqual((path / "log.1").read_bytes(), payload[64:96])
            self.assertTrue((path / "fatal").exists())

    def test_legacy_oversized_logs_are_bounded(self):
        capture = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-log-writer"))["capture"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "log").write_bytes(b"x" * 100)
            (path / "log.1").write_bytes(b"y" * 100)
            (path / "input").write_bytes(b"")
            with (path / "input").open("rb") as stream:
                capture(stream, path / "log", path / "fatal", limit=32)
            self.assertEqual((path / "log").stat().st_size, 32)
            self.assertEqual((path / "log.1").stat().st_size, 32)


class DisplayReadiness(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-kiosk-ready"))
        self.report = {
            "api": 2, "session": "this-launch", "monotonic": 99,
            "core": 10, "ui": 11, "compositor": 12, "framePresented": True,
            "output": {"connector": "HDMI-A-1", "width": 400, "height": 1280,
                       "transform": "90", "scale": 1},
        }

    def validate(self):
        with (mock.patch.object(Path, "read_text", return_value="10 (livi-ui) S 1"),
              mock.patch.object(self.module["os"], "kill") as kill):
            self.module["validate"](self.report, "this-launch", 100)
            self.assertEqual(kill.call_count, 3)

    def test_live_native_output_is_ready(self):
        self.validate()

    def test_real_live_process_is_ready(self):
        with subprocess.Popen(["sleep", "30"]) as process:
            try:
                for field in ("core", "ui", "compositor"):
                    self.report[field] = process.pid
                self.module["validate"](self.report, "this-launch", 100)
            finally:
                process.terminate()

    def test_missing_process_is_rejected(self):
        with mock.patch.object(Path, "read_text", side_effect=FileNotFoundError):
            with self.assertRaises(OSError):
                self.module["validate"](self.report, "this-launch", 100)

    def test_wrong_output_and_unpresented_frame_are_rejected(self):
        for field, value in (("output", {}), ("framePresented", False), ("api", 2.0)):
            with self.subTest(field=field):
                original = self.report[field]
                self.report[field] = value
                with self.assertRaises(ValueError):
                    self.validate()
                self.report[field] = original

    def test_stale_future_nonfinite_and_other_session_reports_are_rejected(self):
        for value in (90, 101, float("nan"), float("inf"), 10 ** 400, True, "99"):
            with self.subTest(value=value):
                self.report["monotonic"] = value
                with self.assertRaises(ValueError):
                    self.validate()
        self.report["monotonic"] = 99
        self.report["session"] = "previous-launch"
        with self.assertRaises(ValueError):
            self.validate()

    def test_exited_process_is_rejected(self):
        with mock.patch.object(Path, "read_text", return_value="10 (livi-ui) Z 1"):
            with self.assertRaises(ValueError):
                self.module["validate"](self.report, "this-launch", 100)

    def test_invalid_pid_is_rejected(self):
        for value in (0, 1, -1, True, "10"):
            with self.subTest(value=value):
                self.report["core"] = value
                with self.assertRaises(ValueError):
                    self.validate()

    def test_missing_audio_and_oversized_report_fail_explicitly(self):
        main = self.module["main"]
        with mock.patch.object(Path, "stat", side_effect=FileNotFoundError("missing audio")):
            with mock.patch("sys.stderr") as stderr:
                self.assertEqual(main(), 1)
                self.assertTrue(stderr.write.called)
        with (mock.patch.object(Path, "stat", return_value=mock.Mock(st_mode=0o140755)),
              mock.patch.object(Path, "read_text", return_value="this-launch"),
              mock.patch.object(os, "open", return_value=10),
              mock.patch.object(os, "fdopen", mock.mock_open(read_data=b"x" * 16385)),
              mock.patch.object(os, "fstat", return_value=mock.Mock(st_mode=0o100644)),
              mock.patch("sys.stderr") as stderr):
            self.assertEqual(main(), 1)
            self.assertTrue(stderr.write.called)

    def test_real_report_reader_and_nonregular_file_rejection(self):
        main = self.module["main"]
        with (tempfile.TemporaryDirectory() as tmp,
              subprocess.Popen(["sleep", "30"]) as process,
              socket.socket(socket.AF_UNIX) as pipewire,
              socket.socket(socket.AF_UNIX) as pulse):
            try:
                path = Path(tmp)
                (path / "pulse").mkdir()
                pipewire.bind(str(path / "pipewire-0"))
                pulse.bind(str(path / "pulse/native"))
                (path / "livi-os-session").write_text("this-launch\n")
                for field in ("core", "ui", "compositor"):
                    self.report[field] = process.pid
                self.report["monotonic"] = time.monotonic()
                report = path / "livi-os-ready.json"
                report.write_text(json.dumps(self.report))
                with mock.patch.dict(main.__globals__, {"RUNTIME": path}):
                    self.assertEqual(main(), 0)
                    report.unlink()
                    os.mkfifo(report)
                    with mock.patch("sys.stderr"):
                        self.assertEqual(main(), 1)
                    report.unlink()
                    report.symlink_to(path / "livi-os-session")
                    with mock.patch("sys.stderr"):
                        self.assertEqual(main(), 1)
            finally:
                process.terminate()


class ApplicationRuntimeEnvironment(unittest.TestCase):
    def test_supervisor_uses_persistent_writable_home(self):
        supervisor = (SCRIPTS / "livi-supervisor").read_text()
        self.assertIn('mkdir -p "$APP_DIR" "$STATE" /data/livi/home', supervisor)
        self.assertIn("HOME=/data/livi/home", supervisor)

    def test_kiosk_has_direct_drm_and_retained_session_bus(self):
        source = (SCRIPTS / "livi-supervisor").read_text()
        source = source[source.index("HOME="):source.index("kiosk_pid=$!") + len("kiosk_pid=$!")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            preamble = '''
set -eu
CURRENT=/test/LIVI.AppImage
runtime="$TEST_DIR"
dbus-run-session() {
  echo session > "$TEST_DIR/session"
  test "$1" = --
  shift
  printf '%s\\n' "$HOME" "$XKB_CONFIG_ROOT" "$LIVI_COMPOSITOR_BACKEND" "$LIVI_MAIN_TRANSFORM" "$*" > "$TEST_DIR/environment"
}
'''
            subprocess.run(
                ["bash", "-c", preamble + source + '\nwait "$kiosk_pid"\n'],
                env={**os.environ, "TEST_DIR": str(path)}, check=True,
                capture_output=True, text=True,
            )
            self.assertTrue((path / "session").exists())
            self.assertEqual(
                (path / "environment").read_text().splitlines(),
                ["/data/livi/home", "/usr/share/X11/xkb", "drm", "90", "/test/LIVI.AppImage"],
            )


class Obd2(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-obd2.py"))

    def frame(self, pid, data, can_id=0x7E8):
        payload = bytes((len(data) + 2, 0x41, pid)) + data
        return struct.pack("=IB3x8s", can_id, 8, payload)

    def poller(self):
        can, ecu = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
        ecu.settimeout(2)
        read, write = os.pipe()
        self.addCleanup(can.close)
        self.addCleanup(ecu.close)
        self.addCleanup(os.close, read)
        self.addCleanup(os.close, write)
        return self.module["Poller"](can, 500000, read), ecu, write

    def test_decodes_every_approved_pid_and_preserves_zero(self):
        cases = [
            (0x0C, b"\x2E\xE0", 3000), (0x0D, b"\x00", 0),
            (0x05, b"\x7F", 87), (0x0F, b"\x14", -20),
            (0x0B, b"\x65", 101), (0x11, b"\xFF", 100),
            (0x0E, b"\x60", -16), (0x42, b"\x37\x14", 14.1),
            (0x1F, b"\x01\x00", 256), (0x2F, b"\x00", 0),
            (0x5C, b"\x87", 95), (0x52, b"\xFF", 100),
        ]
        self.assertEqual(len(cases), len(self.module["PIDS"]))
        for pid, data, expected in cases:
            with self.subTest(pid=pid):
                self.assertAlmostEqual(self.module["decode"](pid, data), expected)
                self.assertEqual(self.module["response"](self.frame(pid, data), pid),
                                 (0x7E8, data))
                with self.assertRaises(ValueError):
                    self.module["decode"](pid, data + b"\x00")
        for pid in (0x04, 0x09, 0x14, 0xFF):
            with self.assertRaises(ValueError):
                self.module["decode"](pid, b"\x00")
            with self.assertRaises(ValueError):
                self.module["request_frame"](pid)

    def test_requests_are_only_service_01_and_standard_diagnostic_addresses(self):
        for pid in (*self.module["PIDS"], *self.module["DISCOVERY"]):
            for ecu in (None, 0x7E8, 0x7EF):
                can_id, dlc, payload = struct.unpack(
                    "=IB3x8s", self.module["request_frame"](pid, ecu),
                )
                self.assertEqual(can_id, 0x7DF if ecu is None else ecu - 8)
                self.assertEqual(dlc, 8)
                self.assertEqual(payload, bytes((2, 1, pid, 0, 0, 0, 0, 0)))
        for ecu in (0x7E0, 0x123, 0x800007E8):
            with self.assertRaises(ValueError):
                self.module["request_frame"](0x0C, ecu)

    def test_response_rejects_wrong_pid_service_address_length_and_transport(self):
        response = self.module["response"]
        valid = self.frame(0x0C, b"\x2E\xE0")
        self.assertIsNone(response(valid, 0x42))
        self.assertIsNone(response(valid, 0x0C, 0x7E9))
        for can_id in (0x123, 0x7E0, 0x800007E8, 0x400007E8, 0x200007E8):
            self.assertIsNone(response(self.frame(0x0C, b"\x2E\xE0", can_id), 0x0C))
        for dlc, payload in (
            (9, b"\x04\x41\x0C\x2E\xE0"), (4, b"\x04\x41\x0C\x2E\xE0"),
            (8, b"\x10\x08\x41\x0C\x2E\xE0"), (8, b"\x03\x41\x0C\x2E\xE0"),
            (8, b"\x04\x42\x0C\x2E\xE0"), (8, b"\x03\x7F\x01\x12"),
        ):
            self.assertIsNone(response(struct.pack("=IB3x8s", 0x7E8, dlc, payload), 0x0C))
        self.assertIsNone(response(valid[:-1], 0x0C))

    def test_bitmap_chaining_sticks_to_one_ecu(self):
        poller, _, _ = self.poller()
        replies = [
            (0x7E9, bytes.fromhex("00180001")),  # RPM, speed, next page
            (0x7E9, bytes.fromhex("00000001")),  # next page
            (0x7E9, bytes.fromhex("40000000")),  # voltage
        ]
        with mock.patch.object(poller, "query", side_effect=replies) as query:
            self.assertTrue(poller.discover())
        self.assertEqual([call.args[0] for call in query.call_args_list], [0, 0x20, 0x40])
        self.assertEqual(poller.ecu, 0x7E9)
        self.assertEqual(poller.supported & self.module["PIDS"].keys(), {0x0C, 0x0D, 0x42})
        with mock.patch.object(poller, "query", return_value=None):
            self.assertFalse(poller.discover())

    def test_socket_exchange_rate_limit_timeout_and_lifeline(self):
        poller, ecu, write = self.poller()
        requests = []
        def responder():
            for _ in range(2):
                frame = ecu.recv(16)
                requests.append((time.monotonic(), frame))
                ecu.send(self.frame(0x0C, b"\x2E\xE0"))
        thread = threading.Thread(target=responder)
        thread.start()
        for _ in range(2):
            self.assertEqual(poller.query(0x0C), (0x7E8, b"\x2E\xE0"))
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        self.assertGreaterEqual(requests[1][0] - requests[0][0], 0.095)
        self.assertEqual(poller.requests, 2)
        self.assertIsNone(poller.query(0x05))
        self.assertEqual(poller.timeouts, 1)
        os.write(write, b"not a command")
        with self.assertRaisesRegex(RuntimeError, "EOF only"):
            poller.wait(0)
        with mock.patch("os.read", return_value=b""), \
                mock.patch("select.select", return_value=([poller.lifeline], [], [])), \
                self.assertRaises(self.module["Stopped"]):
            poller.query(0x0C)
        self.assertEqual(poller.requests, 3, "no transmission after lifeline EOF")

    def test_stale_values_clear_independently_and_health_distinguishes_unsupported(self):
        poller, _, _ = self.poller()
        poller.ecu = 0x7E8
        poller.supported = {0x0C, 0x0D, 0x42, 0x5C}
        poller.status = "available"
        poller.seen = {0x0C: 10, 0x42: 11, 0x5C: 0}
        with mock.patch("time.monotonic", return_value=12), mock.patch("builtins.print") as output:
            self.assertEqual(poller.expire(), {"rpm": None})
            poller.emit({"speedKph": 0})
        message = json.loads(output.call_args.args[0])
        self.assertEqual(message["speedKph"], 0)
        self.assertEqual(message["obd2"]["signals"]["batteryV"]["state"], "available")
        self.assertEqual(message["obd2"]["signals"]["rpm"]["state"], "stale")
        self.assertEqual(message["obd2"]["signals"]["coolantC"]["state"], "unsupported")

    def test_helper_has_fixed_bitrates_environment_and_no_user_requests(self):
        helper = SCRIPTS.parent / "libexec/livi-obd2"
        for args in ([], ["250000"], ["500000", "7DF"], ["500000;reboot"]):
            result = subprocess.run(["sh", str(helper), *args], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
        source = helper.read_text()
        self.assertIn("env -i", source)
        self.assertIn('500000|1000000)', source)
        sudoers = (SCRIPTS.parents[1] / "etc/sudoers.d/99-livi").read_text()
        self.assertIn("/usr/libexec/livi-obd2 500000, /usr/libexec/livi-obd2 1000000", sudoers)
        passive = (SCRIPTS.parent / "libexec/livi-can-capture").read_text()
        self.assertIn("/usr/bin/flock -n 9", passive)

    def test_normal_mode_readiness_rejects_wrong_bitrate_and_bus_off(self):
        link = {
            "flags": ["UP"],
            "linkinfo": {
                "info_kind": "can",
                "info_data": {"bittiming": {"bitrate": 500000}, "state": "ERROR-ACTIVE"},
            },
        }
        def verify():
            with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
                [], 0, stdout=json.dumps([link]),
            )):
                self.module["check_interface"](500000)
        verify()
        data = link["linkinfo"]["info_data"]
        for field, value in (("ctrlmode", ["LISTEN-ONLY"]), ("state", "BUS-OFF"),
                             ("bittiming", {"bitrate": 1000000})):
            previous = data.get(field)
            data[field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                verify()
            if previous is None:
                del data[field]
            else:
                data[field] = previous

    def test_scheduler_suppresses_repeatedly_missing_pids_without_losing_live_zero(self):
        poller, _, _ = self.poller()
        clock = [0.0]
        requested = []
        messages = []
        def wait(seconds, receive=False):
            clock[0] += max(0.01, seconds)
            if clock[0] > 20:
                raise self.module["Stopped"]()
        def discover():
            poller.ecu = 0x7E8
            poller.supported = {0x0C, 0x0D}
            return True
        def query(pid):
            requested.append(pid)
            clock[0] += 0.1
            poller.requests += 1
            if pid == 0x0C:
                poller.timeouts += 1
                return None
            poller.last_response = clock[0]
            return 0x7E8, b"\x00"
        with mock.patch.object(poller, "wait", side_effect=wait), \
                mock.patch.object(poller, "discover", side_effect=discover), \
                mock.patch.object(poller, "query", side_effect=query), \
                mock.patch.dict(poller.run.__globals__, check_interface=mock.Mock()), \
                mock.patch("time.monotonic", side_effect=lambda: clock[0]), \
                mock.patch("builtins.print", side_effect=lambda message, **_: messages.append(json.loads(message))), \
                self.assertRaises(self.module["Stopped"]):
            poller.run()
        self.assertEqual(requested.count(0x0C), 3)
        self.assertIn(0x0C, poller.disabled)
        self.assertTrue(any(message.get("speedKph") == 0 for message in messages))
        self.assertTrue(any("rpm" in message and message["rpm"] is None for message in messages))
        self.assertEqual(poller.timeouts, 3)

    def test_shutdown_brings_can_down_and_lock_conflict_never_configures_it(self):
        fake = mock.Mock()
        fake.run.side_effect = self.module["Stopped"]()
        calls = []
        with mock.patch("builtins.open", mock.mock_open()), \
                mock.patch("fcntl.flock"), mock.patch("signal.signal"), \
                mock.patch("sys.argv", ["livi-obd2.py", "500000"]), \
                mock.patch.dict(self.module["main"].__globals__, {
                    "command": lambda *args: calls.append(args),
                    "check_interface": mock.Mock(),
                    "Poller": mock.Mock(return_value=fake),
                }), mock.patch("socket.socket"):
            self.module["main"]()
        self.assertIn((
            "/usr/sbin/ip", "link", "set", "dev", "can0", "type", "can",
            "bitrate", "500000", "listen-only", "off",
        ), calls)
        self.assertEqual(calls[-1], ("/usr/sbin/ip", "link", "set", "dev", "can0", "down"))
        configure = mock.Mock()
        with mock.patch("builtins.open", mock.mock_open()), \
                mock.patch("fcntl.flock", side_effect=BlockingIOError("busy")), \
                mock.patch("signal.signal"), \
                mock.patch("sys.argv", ["livi-obd2.py", "500000"]), \
                mock.patch.dict(self.module["main"].__globals__, command=configure), \
                self.assertRaises(BlockingIOError):
            self.module["main"]()
        configure.assert_not_called()


class CanCapture(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-can-capture.py"))

    def link(self):
        return {
            "flags": ["UP", "NOARP"],
            "linkinfo": {
                "info_kind": "can",
                "info_data": {
                    "bittiming": {"bitrate": 1000000},
                    "ctrlmode": ["LISTEN-ONLY"],
                    "state": "ERROR-ACTIVE",
                },
            },
        }

    def check_link(self, links):
        with mock.patch("subprocess.run", return_value=subprocess.CompletedProcess(
            [], 0, stdout=json.dumps(links),
        )) as run:
            self.module["check_interface"]()
        run.assert_called_once_with(
            ["/usr/sbin/ip", "-details", "-json", "link", "show", "dev", "can0"],
            check=True, capture_output=True, text=True,
        )

    def test_requires_real_can_at_1mbit_listen_only(self):
        self.check_link([self.link()])
        for field, value in (
            ("bittiming", {"bitrate": 500000}),
            ("bittiming", {}),
            ("ctrlmode", []),
            ("state", "BUS-OFF"),
            ("state", "STOPPED"),
            ("state", "SLEEPING"),
        ):
            link = self.link()
            link["linkinfo"]["info_data"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                self.check_link([link])
        link = self.link()
        link["flags"] = []
        with self.assertRaises(RuntimeError):
            self.check_link([link])
        link = self.link()
        link["linkinfo"]["info_kind"] = "vcan"
        with self.assertRaises(RuntimeError):
            self.check_link([link])
        for links in ([], [self.link(), self.link()]):
            with self.assertRaises(RuntimeError):
                self.check_link(links)
        with mock.patch("subprocess.run", side_effect=subprocess.CalledProcessError(
            1, "ip", stderr="interface unavailable",
        )), self.assertRaises(subprocess.CalledProcessError):
            self.module["check_interface"]()

    def test_filters_all_seven_ids_and_emits_only_standard_data_frames(self):
        ids = (0x360, 0x361, 0x368, 0x36A, 0x370, 0x372, 0x3E0)
        self.assertEqual(self.module["CAN_IDS"], ids)
        frames = [struct.pack("=IB3x8s", can_id, 4, b"\x04\xD2\x09\x29")
                  for can_id in ids]
        for can_id, length in (
            (0x123, 4), (0x80000360, 4), (0x40000360, 4),
            (0x20000360, 4), (0x360, 0), (0x360, 1), (0x360, 9),
        ):
            frames.append(struct.pack("=IB3x8s", can_id, length, b""))
        frames.extend([b"short", RuntimeError("end capture")])
        receiver = mock.Mock()
        receiver.recv.side_effect = frames
        ready = mock.Mock()
        with mock.patch.dict(self.module["main"].__globals__, check_interface=ready), \
                mock.patch("socket.socket", return_value=receiver) as constructor, \
                mock.patch("builtins.print") as output, \
                self.assertRaisesRegex(RuntimeError, "end capture"):
            self.module["main"]()
        ready.assert_called_once_with()
        constructor.assert_called_once_with(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        receiver.bind.assert_called_once_with(("can0",))
        receiver.setsockopt.assert_called_once_with(
            socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER,
            b"".join(struct.pack("=II", can_id, 0xE00007FF) for can_id in ids),
        )
        self.assertEqual(output.call_args_list, [
            mock.call(f"can0 {can_id:03X}#04D20929", flush=True) for can_id in ids
        ])

    def test_service_and_hotplug_use_the_same_fixed_configuration(self):
        unit = (SCRIPTS.parent / "lib/systemd/system/livi-can.service").read_text()
        self.assertIn("type can bitrate 1000000 listen-only on", unit)
        self.assertIn("BindsTo=sys-subsystem-net-devices-can0.device", unit)
        self.assertNotIn("WantedBy=multi-user.target", unit)
        rules = (SCRIPTS.parents[1] / "etc/udev/rules.d/80-livi-can.rules").read_text()
        self.assertIn('KERNEL=="can0"', rules)
        self.assertIn('ENV{SYSTEMD_WANTS}+="livi-can.service"', rules)
        wrapper = (SCRIPTS.parent / "libexec/livi-can-capture").read_text()
        self.assertIn('/usr/bin/systemctl start livi-can.service || fail', wrapper)
        self.assertIn('[ "$#" = 0 ] || fail', wrapper)


class PostImage(unittest.TestCase):
    def test_builds_boot_control_and_matching_slot_cmdlines(self):
        self.check_image("rpi5")

    def test_pi4_refreshes_stale_firmware_cmdline(self):
        self.check_image("rpi4")

    def test_disables_carpihat_on_both_boards(self):
        for board in ("rpi4", "rpi5"):
            for setting in ("0", ""):
                with self.subTest(board=board, setting=setting):
                    self.check_image(board, setting)

    def test_carpihat_defaults_on_without_an_environment_override(self):
        for board in ("rpi4", "rpi5"):
            with self.subTest(board=board):
                self.check_image(board, None)

    def test_invalid_carpihat_setting_fails_both_build_hooks(self):
        for script, args in (("post-build.sh", ["/unused", "rpi5"]),
                             ("post-image.sh", ["rpi5"])):
            result = subprocess.run(
                ["bash", str(ROOT / "board/drskunk/livi" / script), *args],
                env={**os.environ, "LIVI_CARPIHAT": "yes"},
                capture_output=True, text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("LIVI_CARPIHAT must be", result.stderr)

    def test_can_uses_verified_crystal_and_only_spi_cs0_on_both_boards(self):
        for board in ("rpi4", "rpi5"):
            for clock in ("8000000", "16000000", "20000000"):
                with self.subTest(board=board, clock=clock):
                    self.check_image(board, oscillator=clock)

    def test_can_rejects_impossible_or_unverified_clock_before_image_creation(self):
        for clock in ("16000000,interrupt=25", "0", "yes"):
            with self.subTest(clock=clock):
                result = subprocess.run(
                    ["bash", str(ROOT / "board/drskunk/livi/post-image.sh"), "rpi5"],
                    env={**os.environ, "LIVI_CARPIHAT": "1", "LIVI_CAN_OSCILLATOR": clock},
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("LIVI_CAN_OSCILLATOR", result.stderr)

    def check_image(self, board, carpihat="1", oscillator=""):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            binaries = path / "images"
            firmware = binaries / "rpi-firmware"
            host = path / "host"
            firmware.mkdir(parents=True)
            (host / "sbin").mkdir(parents=True)
            (host / "bin").mkdir()
            (binaries / "Image").write_text("kernel")
            (binaries / "board.dtb").write_text("dtb")
            (firmware / "config.txt").write_text("kernel=Image\n")
            (firmware / "cmdline.txt").write_text(
                "root=PARTUUID=8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2 rootfstype=squashfs ro\n")
            (firmware / "start.elf").write_text("firmware")
            mkfs = host / "sbin/mkfs.ext4"
            mkfs.write_text('#!/bin/sh\nfor last; do :; done\n: > "$last"\n')
            mkfs.chmod(0o755)
            genimage = host / "bin/genimage"
            genimage.write_text(
                '#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
                '  if [ "$1" = --config ]; then cp "$2" "$CAPTURE"; fi\n'
                '  shift\ndone\n')
            genimage.chmod(0o755)
            capture = path / "genimage.cfg"
            env = {
                **os.environ,
                "BR2_EXTERNAL_LIVI_OS_PATH": str(ROOT),
                "BINARIES_DIR": str(binaries),
                "BUILD_DIR": str(path / "build"),
                "HOST_DIR": str(host),
                "CAPTURE": str(capture),
                "LIVI_CAN_OSCILLATOR": oscillator,
            }
            if carpihat is None:
                env.pop("LIVI_CARPIHAT", None)
            else:
                env["LIVI_CARPIHAT"] = carpihat
            script = ROOT / "board/drskunk/livi/post-image.sh"
            for _ in range(2):
                result = subprocess.run(["bash", str(script), board], env=env,
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

            generated = capture.read_text()
            self.assertIn('image = "boot-control.vfat"', generated)
            self.assertIn('image = "boot.vfat"', generated)
            self.assertIn('partition boot-a', generated)
            self.assertIn('partition boot-b', generated)
            self.assertIn('"rpi-firmware/cmdline-root-a.txt"', generated)
            self.assertIn('"rpi-firmware/cmdline-root-b.txt"', generated)
            config = (firmware / "config.txt").read_text()
            self.assertEqual(config.count("dtoverlay=spi0-1cs"), int(bool(oscillator)))
            self.assertEqual(config.count("dtoverlay=mcp2515-can0"), int(bool(oscillator)))
            self.assertNotIn("spi-bcm2835-overlay", config)
            if oscillator:
                self.assertIn(
                    f"dtoverlay=mcp2515-can0,oscillator={oscillator},interrupt=23", config,
                )
            enabled = carpihat in ("1", None)
            self.assertEqual(config.count("gpio=25=op,dh"), int(enabled))
            self.assertEqual(
                config.count("dtoverlay=gpio-poweroff,gpiopin=25,active_low"),
                int(enabled),
            )
            self.assertEqual(config.count("[boot_partition=2]"), 1)
            self.assertIn("cmdline=cmdline-root-a.txt", config)
            self.assertIn("cmdline=cmdline-root-b.txt", config)
            self.assertIn("root=PARTUUID=8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2",
                          (firmware / "cmdline-root-a.txt").read_text())
            self.assertIn("root=PARTUUID=4af7b146-2c77-4808-881b-1e3ad8d15be8",
                          (firmware / "cmdline-root-b.txt").read_text())
            expected = (ROOT / f"board/drskunk/livi/cmdline-{board}.txt").read_text()
            self.assertEqual((firmware / "cmdline.txt").read_text(), expected)
            self.assertEqual((firmware / "cmdline-root-a.txt").read_text(), expected)
            self.assertEqual(
                (firmware / "cmdline-root-b.txt").read_text(),
                expected.replace(TrialBoot.ROOT_A, TrialBoot.ROOT_B),
            )
            self.assertTrue((binaries / "autoboot.txt").exists())


class CarPiHATPostBuild(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)
        self.target = path / "target"
        shutil.copytree(ROOT / "board/drskunk/livi/rootfs-overlay", self.target,
                        symlinks=True)
        for name in (
            "bin/bash", "usr/bin/stat", "usr/bin/dbus-run-session", "usr/bin/pipewire",
            "usr/bin/psplash", "usr/bin/psplash-write", "usr/bin/timeout",
            "usr/bin/pipewire-pulse", "usr/bin/wireplumber", "usr/bin/jq",
            "usr/bin/unsquashfs", "usr/bin/pactl", "usr/bin/xdg-user-dir",
            "usr/lib/livi/livi-helperd", "usr/bin/python3",
            "usr/bin/flock", "usr/bin/systemctl", "usr/bin/sudo",
            "usr/local/lib/livi/livi-touch-filter", "usr/bin/retroarch",
        ):
            file = self.target / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("#!/bin/sh\nexit 1\n")
            file.chmod(0o755)
        for name in (
            "usr/share/X11/xkb/rules/evdev", "usr/share/X11/xkb/symbols/us",
            "usr/share/X11/xkb/keycodes/evdev", "usr/share/X11/xkb/types/complete",
            "usr/share/X11/xkb/compat/complete",
            "usr/share/retroarch/assets/glui/font.ttf",
            "usr/share/retroarch/assets/glui/back.png",
            "usr/share/retroarch/assets/ozone/regular.ttf",
        ):
            file = self.target / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("fixture")
        for name in (
            "libEGL.so.1", "libGLESv2.so.2", "libgbm.so.1", "libdrm.so.2",
            "libinput.so.10", "libseat.so.1", "libxkbcommon.so.0",
            "libwayland-client.so.0", "libwayland-server.so.0", "libgudev-1.0.so.0",
            "libva.so.2",
        ):
            (self.target / "usr/lib" / name).touch()
        (self.target / "usr/lib/livi/LIVI.AppImage").write_bytes(b"fixture")
        (self.target / "usr/lib/livi/factory-appimage.sha256").write_text(
            hashlib.sha256(b"fixture").hexdigest() + "  usr/lib/livi/LIVI.AppImage\n")
        self.binding = self.target / "usr/lib/python3.14/site-packages/gpiod.so"
        self.binding.parent.mkdir(parents=True)
        self.binding.touch()
        host = path / "host"
        (host / "bin").mkdir(parents=True)
        readelf = host / "bin/aarch64-linux-readelf"
        readelf.write_text("#!/bin/sh\nexit 0\n")
        readelf.chmod(0o755)
        self.env = {
            **os.environ,
            "HOST_DIR": str(host),
            "BR2_EXTERNAL_LIVI_OS_PATH": str(ROOT),
            "LIVI_OS_VERSION": "test",
            "LIVI_OS_SERIAL": "1",
        }

    def build(self, board, setting):
        env = self.env.copy()
        env.pop("LIVI_CARPIHAT", None)
        if setting is not None:
            env["LIVI_CARPIHAT"] = setting
        return subprocess.run(
            ["sh", str(ROOT / "board/drskunk/livi/post-build.sh"), str(self.target), board],
            env=env, capture_output=True, text=True,
        )

    def test_enable_disable_and_reenable_without_stale_service_links(self):
        link = self.target / "etc/systemd/system/sysinit.target.wants/livi-carpihat-power.service"
        can_link = self.target / "etc/systemd/system/multi-user.target.wants/livi-can.service"
        can_link.parent.mkdir(parents=True, exist_ok=True)
        for board in ("rpi4", "rpi5"):
            for setting in ("1", "0", "1", "", None):
                with self.subTest(board=board, setting=setting):
                    can_link.symlink_to("/usr/lib/systemd/system/livi-can.service")
                    result = self.build(board, setting)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertFalse(can_link.is_symlink())
                    self.assertEqual(link.is_symlink(), setting in ("1", None))
                    if link.is_symlink():
                        self.assertEqual(
                            str(link.readlink()),
                            "/usr/lib/systemd/system/livi-carpihat-power.service",
                        )

    def test_missing_binding_fails_enabled_build_but_not_disabled_build(self):
        self.binding.unlink()
        result = self.build("rpi5", "1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires the libgpiod 1.x Python binding", result.stderr)
        result = self.build("rpi5", "0")
        self.assertEqual(result.returncode, 0, result.stderr)


class TrialBoot(unittest.TestCase):
    ROOT_A = "8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2"
    ROOT_B = "4af7b146-2c77-4808-881b-1e3ad8d15be8"
    BOOT_A = 2
    BOOT_B = 3

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        for name in ("boot", "run", "bin"):
            (self.path / name).mkdir()
        self.autoboot = self.path / "boot/autoboot.txt"
        self.autoboot.write_text(
            "[all]\ntryboot_a_b=1\nboot_partition=2\n[tryboot]\nboot_partition=3\n")
        self.cmdline = self.path / "proc-cmdline"
        self.cmdline.write_text(f"root=PARTUUID={self.ROOT_A}\n")
        self.trial = self.path / "tryboot"
        self.trial.write_bytes(b"\0\0\0\0")
        self.partition = self.path / "partition"
        self.partition.write_bytes(bytes.fromhex("00000002"))
        for command in ("mount", "sync", "flock", "reboot"):
            stub = self.path / "bin" / command
            stub.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$COMMAND_LOG"\n')
            stub.chmod(0o755)
        script = (SCRIPTS / "livi-os-slot").read_text()
        script = (script.replace("/data/os-update", str(self.path / "data"))
                  .replace("/boot/", str(self.path / "boot") + "/")
                  .replace("/run/", str(self.path / "run") + "/")
                  .replace("/proc/cmdline", str(self.cmdline))
                  .replace("/proc/device-tree/chosen/bootloader/",
                           str(self.path) + "/"))
        self.script = self.path / "slot"
        self.script.write_text(script)

    def slot(self, *args, success=True):
        result = subprocess.run(["sh", str(self.script), *args],
                                env={**os.environ, "PATH": f"{self.path}/bin:{os.environ['PATH']}",
                                     "COMMAND_LOG": str(self.path / "commands")},
                                capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        return result

    def stage(self):
        self.slot("stage", self.ROOT_B, "test-hash")

    def test_staging_and_reboot_do_not_change_default(self):
        original = self.autoboot.read_text()
        self.stage()
        self.slot("reboot")
        self.assertEqual(self.autoboot.read_text(), original)
        self.assertIn("reboot 0 tryboot", (self.path / "commands").read_text())
        self.assertEqual((self.path / "data/pending").read_text().splitlines()[2], "1")

    def test_only_healthy_trial_commits_default(self):
        self.stage()
        self.slot("reboot")
        self.cmdline.write_text(f"root=PARTUUID={self.ROOT_B}\n")
        self.slot("mark-good", success=False)
        self.trial.write_bytes(b"\0\0\0\1")
        self.partition.write_bytes(bytes.fromhex("00000003"))
        self.slot("boot-check")
        self.slot("mark-good")
        self.assertIn("boot_partition=3", self.autoboot.read_text())
        self.assertIn("[tryboot]\nboot_partition=2", self.autoboot.read_text())
        self.assertFalse((self.path / "data/pending").exists())
        self.assertTrue((self.path / "run/livi-os-confirmed").exists())

    def test_failure_before_userspace_returns_to_previous_root(self):
        self.stage()
        self.slot("reboot")
        self.slot("boot-check")
        self.assertIn("boot_partition=2", self.autoboot.read_text())
        self.assertFalse((self.path / "data/pending").exists())
        self.assertEqual(len(list((self.path / "data").glob("failed-*"))), 1)

    def test_timeout_does_not_require_data_partition(self):
        self.trial.write_bytes(b"\0\0\0\1")
        self.slot("boot-timeout")
        self.assertIn("reboot -f", (self.path / "commands").read_text())
        self.assertFalse((self.path / "data").exists())

    def test_confirmed_trial_does_not_reboot_on_deadline(self):
        self.trial.write_bytes(b"\0\0\0\1")
        (self.path / "run/livi-os-confirmed").touch()
        self.slot("boot-timeout")
        self.assertFalse((self.path / "commands").exists())

    def test_refuses_active_slot_and_overlapping_updates(self):
        self.slot("stage", self.ROOT_A, "hash", success=False)
        self.stage()
        self.slot("stage", self.ROOT_B, "hash", success=False)

    def reboots(self):
        commands = self.path / "commands"
        return commands.read_text().count("reboot ") if commands.exists() else 0

    def test_staged_update_is_tried_once_at_boot(self):
        self.slot("apply-pending")
        self.assertEqual(self.reboots(), 0)
        self.stage()
        self.slot("apply-pending")
        self.assertIn("reboot 0 tryboot", (self.path / "commands").read_text())
        self.assertEqual((self.path / "data/pending").read_text().splitlines()[2], "1")
        self.slot("apply-pending")
        self.assertEqual(self.reboots(), 1)


class OsUpdate(unittest.TestCase):
    ROOT_A = TrialBoot.ROOT_A
    ROOT_B = TrialBoot.ROOT_B
    BOOT_A = "cbd67f9c-d8df-4ac4-a7bd-4da6f7a60316"
    BOOT_B = "62194703-ff6d-4c28-9182-6ecdc15203bf"

    @classmethod
    def setUpClass(cls):
        cls.keys = tempfile.TemporaryDirectory()
        keys = Path(cls.keys.name)
        cls.private = keys / "private.pem"
        cls.public = keys / "public.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt",
                        "ec_paramgen_curve:P-256", "-out", str(cls.private)], check=True,
                       capture_output=True)
        subprocess.run(["openssl", "pkey", "-in", str(cls.private), "-pubout", "-out", str(cls.public)],
                       check=True, capture_output=True)

    @classmethod
    def tearDownClass(cls):
        cls.keys.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        for name in ("lib", "state", "bin", "byuuid", "usbmnt", "fixtures", "stick/livi-update"):
            (self.path / name).mkdir(parents=True)
        self.lib = self.path / "lib"
        self.state = self.path / "state"
        (self.lib / "os-release").write_text("BOARD=rpi5\nVERSION=v1.0.0\nSERIAL=100\n")
        (self.lib / "os-update.pem").write_text(self.public.read_text())
        self.slot_b = self.path / "slot-b"
        self.slot_b.write_bytes(b"\0" * 65536)
        self.slot_a = self.path / "slot-a"
        self.slot_a.write_bytes(b"\0" * 65536)
        self.boot_slot_b = self.path / "boot-slot-b"
        self.boot_slot_b.write_bytes(b"\0" * 65536)
        self.boot_slot_a = self.path / "boot-slot-a"
        self.boot_slot_a.write_bytes(b"\0" * 65536)
        (self.path / "byuuid" / self.ROOT_B).symlink_to(self.slot_b)
        (self.path / "byuuid" / self.ROOT_A).symlink_to(self.slot_a)
        (self.path / "byuuid" / self.BOOT_B).symlink_to(self.boot_slot_b)
        (self.path / "byuuid" / self.BOOT_A).symlink_to(self.boot_slot_a)
        (self.path / "current").write_text(self.ROOT_A + "\n")
        (self.path / "default").write_text(self.ROOT_A + "\n")
        stubs = {
            "livi-os-slot": 'case "$1" in current) cat "$T/current";; default) cat "$T/default";;'
                            ' *) echo "$*" >> "$T/slot-log";; esac',
            "flock": "exit 0",
            "blockdev": 'case "$1" in --getsize64) wc -c < "$2" | tr -d " ";; esac',
            "mount": 'for last; do :; done; rmdir "$last"; ln -s "$T/stick" "$last"',
            "umount": 'rm -f "$1"',
            "curl": 'out=""; url=""\nwhile [ $# -gt 0 ]; do case "$1" in -o) out="$2"; shift;;'
                    ' http*) url="$1";; esac; shift; done\n'
                    'src="$T/fixtures/${url##*/}"; [ -f "$src" ] || exit 22; cp "$src" "$out"',
        }
        for name, body in stubs.items():
            stub = self.path / "bin" / name
            stub.write_text("#!/bin/sh\n" + body + "\n")
            stub.chmod(0o755)
        script = ((SCRIPTS / "livi-os-update").read_text()
                  .replace("/data/os-update", str(self.state))
                  .replace("/usr/lib/livi", str(self.lib))
                  .replace("/dev/disk/by-partuuid", str(self.path / "byuuid"))
                  .replace("/run/livi-os-usb", str(self.path / "usbmnt"))
                  .replace("/run/livi-os-update.lock", str(self.path / "lock"))
                  .replace('[ -b "$root_device" ]', '[ -f "$root_device" ]')
                  .replace('[ -b "$boot_device" ]', '[ -f "$boot_device" ]'))
        self.script = self.path / "livi-os-update"
        self.script.write_text(script)

    def bundle(self, directory, image=None, **overrides):
        image = image if image is not None else b"hsqs" + os.urandom(8188)
        boot_image = b"boot" + os.urandom(8188)
        directory = Path(directory)
        (directory / "livi-os-rpi5-rootfs.squashfs").write_bytes(image)
        (directory / "livi-os-rpi5-boot.vfat").write_bytes(boot_image)
        manifest = {"format": 2, "board": "rpi5", "version": "v1.1.0", "serial": 200,
                    "rootfs": {"file": "livi-os-rpi5-rootfs.squashfs", "size": len(image),
                               "sha256": hashlib.sha256(image).hexdigest()},
                    "bootfs": {"file": "livi-os-rpi5-boot.vfat", "size": len(boot_image),
                               "sha256": hashlib.sha256(boot_image).hexdigest()}}
        rootfs = overrides.pop("rootfs", {})
        bootfs = overrides.pop("bootfs", {})
        manifest.update(overrides)
        manifest["rootfs"].update(rootfs)
        manifest["bootfs"].update(bootfs)
        target = directory / "livi-os-rpi5-update.json"
        target.write_text(json.dumps(manifest))
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(self.private), "-out",
                        f"{target}.sig", str(target)], check=True)
        return target, image, boot_image

    def run_update(self, *args, success=True):
        result = subprocess.run(["sh", str(self.script), *args], capture_output=True, text=True,
                                env={**os.environ, "T": str(self.path),
                                     "PATH": f"{self.path}/bin:{os.environ['PATH']}"})
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stderr)
        return result

    def slot_log(self):
        log = self.path / "slot-log"
        return log.read_text() if log.exists() else ""

    def assert_installed(self, image, boot_image):
        self.assertEqual(self.slot_b.read_bytes()[:len(image)], image)
        self.assertEqual(self.boot_slot_b.read_bytes()[:len(boot_image)], boot_image)
        sha = hashlib.sha256(image).hexdigest()
        self.assertIn(f"stage {self.ROOT_B} {sha}", self.slot_log())
        self.assertEqual(json.loads((self.state / "staged.json").read_text())["version"], "v1.1.0")

    def test_signed_update_is_written_to_inactive_slot_and_staged(self):
        manifest, image, boot_image = self.bundle(self.path)
        self.run_update("install", str(manifest))
        self.assert_installed(image, boot_image)
        self.assertNotIn("reboot", self.slot_log())

    def test_update_from_slot_b_targets_boot_and_root_slot_a(self):
        (self.path / "current").write_text(self.ROOT_B + "\n")
        (self.path / "default").write_text(self.ROOT_B + "\n")
        manifest, image, boot_image = self.bundle(self.path)
        self.run_update("install", str(manifest))
        self.assertEqual(self.slot_a.read_bytes()[:len(image)], image)
        self.assertEqual(self.boot_slot_a.read_bytes()[:len(boot_image)], boot_image)
        self.assertIn(f"stage {self.ROOT_A} {hashlib.sha256(image).hexdigest()}",
                      self.slot_log())

    def test_tampered_manifest_is_rejected(self):
        manifest, _, _ = self.bundle(self.path)
        manifest.write_text(manifest.read_text().replace("v1.1.0", "v9.9.9"))
        self.run_update("install", str(manifest), success=False)
        self.assertEqual(self.slot_b.read_bytes(), b"\0" * 65536)
        self.assertEqual(self.slot_log(), "")

    def test_modified_image_is_not_staged(self):
        manifest, image, _ = self.bundle(self.path)
        (self.path / "livi-os-rpi5-rootfs.squashfs").write_bytes(image[:-1] + b"x")
        result = self.run_update("install", str(manifest), success=False)
        self.assertIn("readback", result.stderr)
        self.assertEqual(self.slot_log(), "")

    def test_modified_boot_image_is_not_staged(self):
        manifest, _, boot_image = self.bundle(self.path)
        (self.path / "livi-os-rpi5-boot.vfat").write_bytes(boot_image[:-1] + b"x")
        result = self.run_update("install", str(manifest), success=False)
        self.assertIn("readback", result.stderr)
        self.assertEqual(self.slot_log(), "")

    def test_downgrade_requires_explicit_permission(self):
        manifest, image, boot_image = self.bundle(self.path, serial=50)
        self.run_update("install", str(manifest), success=False)
        self.run_update("install", str(manifest), "--allow-downgrade")
        self.assert_installed(image, boot_image)

    def test_installed_version_is_a_no_op(self):
        manifest, _, _ = self.bundle(self.path, version="v1.0.0", serial=100)
        self.run_update("install", str(manifest))
        self.assertEqual(self.slot_log(), "")

    def test_other_board_is_rejected(self):
        manifest, _, _ = self.bundle(self.path, board="rpi4")
        self.run_update("install", str(manifest), success=False)
        self.assertEqual(self.slot_log(), "")

    def test_unsafe_file_name_is_rejected(self):
        manifest, _, _ = self.bundle(self.path, rootfs={"file": "../slot-b"})
        self.run_update("install", str(manifest), success=False)
        self.assertEqual(self.slot_log(), "")

    def test_image_that_failed_its_trial_is_not_retried_implicitly(self):
        manifest, image, boot_image = self.bundle(self.path)
        sha = hashlib.sha256(image).hexdigest()
        (self.state / "failed-1").write_text(f"{self.ROOT_B}\n{self.ROOT_A}\n1\n{sha}\n")
        self.run_update("install", str(manifest), success=False)
        self.run_update("install", str(manifest), "--retry-failed")
        self.assert_installed(image, boot_image)

    def test_refuses_while_update_pending_or_trial_unconfirmed(self):
        manifest, _, _ = self.bundle(self.path)
        (self.state / "pending").write_text("x\n")
        self.run_update("install", str(manifest), success=False)
        (self.state / "pending").unlink()
        (self.path / "current").write_text(self.ROOT_B + "\n")
        self.run_update("install", str(manifest), success=False)
        self.assertEqual(self.slot_log(), "")

    def test_github_update_downloads_verifies_and_stages(self):
        fixtures = self.path / "fixtures"
        _, image, boot_image = self.bundle(fixtures)
        assets = [{"name": n, "browser_download_url": f"https://example.invalid/{n}"}
                  for n in ("livi-os-rpi5-update.json", "livi-os-rpi5-update.json.sig",
                            "livi-os-rpi5-rootfs.squashfs", "livi-os-rpi5-boot.vfat")]
        (fixtures / "latest").write_text(json.dumps({"assets": assets}))
        (fixtures / "nightly").write_text(json.dumps({"assets": assets}))
        check = json.loads(self.run_update("check").stdout)
        self.assertEqual(check, {"channel": "stable", "installed": "v1.0.0",
                                 "available": "v1.1.0", "update": True})
        nightly = json.loads(self.run_update("check", "--channel", "nightly").stdout)
        self.assertEqual(nightly, {**check, "channel": "nightly"})
        result = self.run_update("update", "--channel", "nightly", "--progress")
        progress = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([p["phase"] for p in progress],
                         ["downloading", "downloading", "downloading", "staging", "staging"])
        self.assertEqual(progress[0]["received"], 0)
        self.assertEqual(progress[1]["received"], len(image))
        self.assertEqual(progress[2]["received"], len(image) + len(boot_image))
        self.assertEqual(progress[2]["received"], progress[2]["total"])
        self.assert_installed(image, boot_image)
        self.assertNotIn("reboot", self.slot_log())
        self.assertFalse((self.state / "download").exists())

    def test_usb_stick_update_is_staged_and_tried_immediately(self):
        _, image, boot_image = self.bundle(self.path / "stick/livi-update")
        self.run_update("usb", "sda1")
        self.assert_installed(image, boot_image)
        self.assertTrue(self.slot_log().endswith("reboot\n"))

    def test_usb_stick_without_update_is_ignored(self):
        self.run_update("usb", "sda1")
        self.assertEqual(self.slot_log(), "")

    @unittest.skipUnless(subprocess.run(["sh", "-c", "command -v mksquashfs"],
                                        capture_output=True).returncode == 0, "needs mksquashfs")
    def test_release_bundle_tool_output_installs(self):
        rootfs = self.path / "rootfs"
        (rootfs / "usr/lib/livi").mkdir(parents=True)
        (rootfs / "usr/lib/livi/os-release").write_text("BOARD=rpi5\nVERSION=v1.1.0\nSERIAL=200\n")
        (rootfs / "usr/lib/livi/os-update.pem").write_text(self.public.read_text())
        out = self.path / "output"
        (out / "images").mkdir(parents=True)
        subprocess.run(["mksquashfs", str(rootfs), str(out / "images/rootfs.squashfs"),
                        "-noappend", "-quiet"], check=True, capture_output=True)
        (out / "images/boot.vfat").write_bytes(b"bootfs-image")
        self.slot_b.write_bytes(b"\0" * (out / "images/rootfs.squashfs").stat().st_size * 2)
        make = ROOT / "support/make-os-update"
        subprocess.run([str(make), str(out), str(self.private), str(out / "update")],
                       check=True, capture_output=True)
        self.run_update("install", str(out / "update/livi-os-rpi5-update.json"))
        self.assert_installed((out / "images/rootfs.squashfs").read_bytes(), b"bootfs-image")
        other = self.path / "other.pem"
        subprocess.run(["openssl", "genpkey", "-algorithm", "EC", "-pkeyopt",
                        "ec_paramgen_curve:P-256", "-out", str(other)], check=True, capture_output=True)
        refused = subprocess.run([str(make), str(out), str(other), str(self.path / "x")],
                                 capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("does not match", refused.stderr)


class CarPiHATPower(unittest.TestCase):
    def setUp(self):
        self.module = runpy.run_path(str(SCRIPTS.parent / "libexec/livi-carpihat-power"))
        self.monitor = self.module["monitor"]
        self.clock = 0.0
        self.stopped = mock.Mock()
        self.stopped.is_set.return_value = False

    def run_monitor(self, readings):
        values = iter(readings)

        def read():
            return next(values)

        with mock.patch.object(self.module["time"], "monotonic",
                               side_effect=lambda: self.clock):
            with mock.patch.object(self.module["subprocess"], "run") as shutdown:
                self.monitor(read, self.stopped)
                return shutdown

    def test_exact_ten_second_threshold_including_ignition_off_at_boot(self):
        def wait(_interval):
            self.clock = {0.0: 9.999, 9.999: 10.0}[self.clock]

        self.stopped.wait.side_effect = wait
        shutdown = self.run_monitor([0, 0, 0])
        self.assertEqual(self.clock, 10.0)
        shutdown.assert_called_once_with(
            ["/usr/bin/systemctl", "--no-block", "poweroff"], check=True, timeout=10,
        )
        self.assertEqual(self.stopped.wait.call_count, 2)

    def test_ignition_return_resets_the_full_countdown(self):
        times = iter([9.0, 9.1, 19.0, 19.1])
        self.stopped.wait.side_effect = lambda _interval: setattr(self, "clock", next(times))
        shutdown = self.run_monitor([0, 1, 0, 0, 0])
        self.assertEqual(self.clock, 19.1)
        shutdown.assert_called_once()

    def test_ignition_high_never_requests_shutdown_and_stop_is_clean(self):
        self.stopped.wait.side_effect = lambda _interval: setattr(
            self.stopped.is_set, "return_value", True)
        shutdown = self.run_monitor([1])
        shutdown.assert_not_called()

    def test_stop_during_countdown_does_not_poweroff(self):
        self.stopped.wait.side_effect = lambda _interval: setattr(
            self.stopped.is_set, "return_value", True)
        shutdown = self.run_monitor([0])
        shutdown.assert_not_called()

    def test_invalid_gpio_value_and_read_failure_do_not_poweroff(self):
        for error in (ValueError, OSError):
            with self.subTest(error=error):
                read = mock.Mock(return_value=2) if error is ValueError else mock.Mock(
                    side_effect=OSError("GPIO read failed"))
                with mock.patch.object(self.module["subprocess"], "run") as shutdown:
                    with self.assertRaises(error):
                        self.monitor(read, self.stopped)
                    shutdown.assert_not_called()

    def test_rejected_shutdown_is_not_reported_as_success(self):
        readings = iter([0, 0])
        self.stopped.wait.side_effect = lambda _interval: setattr(self, "clock", 10.0)
        with mock.patch.object(self.module["time"], "monotonic",
                               side_effect=lambda: self.clock):
            with mock.patch.object(self.module["subprocess"], "run",
                                   side_effect=subprocess.CalledProcessError(1, "systemctl")):
                with self.assertRaises(subprocess.CalledProcessError):
                    self.monitor(lambda: next(readings), self.stopped)

    def gpio_fixture(self, latch_consumer="power_ctrl"):
        gpiod = mock.MagicMock()
        chip = gpiod.Chip.return_value.__enter__.return_value
        ignition = mock.Mock()
        latch = mock.Mock()
        latch.consumer.return_value = latch_consumer
        chip.find_line.side_effect = lambda name: {"GPIO12": ignition, "GPIO25": latch}[name]
        return gpiod, chip, ignition, latch

    def test_discovers_bank_by_line_names_not_gpiochip_number(self):
        for chip_number in (0, 4):
            with self.subTest(chip_number=chip_number):
                gpiod, _, ignition, latch = self.gpio_fixture()
                run = self.module["run"]
                with mock.patch.dict(sys.modules, {"gpiod": gpiod}):
                    with mock.patch.object(Path, "glob",
                                           return_value=[Path(f"/dev/gpiochip{chip_number}")]):
                        with mock.patch.dict(run.__globals__, {"monitor": mock.Mock()}) as env:
                            run(self.stopped)
                            env["monitor"].assert_called_once_with(
                                ignition.get_value, self.stopped)
                gpiod.Chip.assert_called_once_with(f"/dev/gpiochip{chip_number}")
                ignition.request.assert_called_once_with(
                    consumer="livi-carpihat-ignition",
                    type=gpiod.LINE_REQ_DIR_IN,
                    flags=gpiod.LINE_REQ_FLAG_BIAS_PULL_DOWN,
                )
                ignition.release.assert_called_once()
                latch.request.assert_not_called()
                latch.set_value.assert_not_called()

    def test_missing_or_wrong_latch_fails_without_requesting_ignition(self):
        for chips, owner in (([], "power_ctrl"), ([Path("/dev/gpiochip0")], "other")):
            gpiod, _, ignition, _ = self.gpio_fixture(owner)
            with mock.patch.dict(sys.modules, {"gpiod": gpiod}):
                with mock.patch.object(Path, "glob", return_value=chips):
                    with self.assertRaisesRegex(RuntimeError, "kernel's"):
                        self.module["run"](self.stopped)
            ignition.request.assert_not_called()

    def test_missing_line_or_ambiguous_banks_are_rejected(self):
        for missing in ("GPIO12", "GPIO25", None):
            with self.subTest(missing=missing):
                gpiod, chip, ignition, latch = self.gpio_fixture()
                lines = {"GPIO12": ignition, "GPIO25": latch}
                if missing:
                    lines[missing] = None
                chip.find_line.side_effect = lines.get
                with mock.patch.dict(sys.modules, {"gpiod": gpiod}):
                    with mock.patch.object(Path, "glob", return_value=[
                            Path("/dev/gpiochip0"), Path("/dev/gpiochip4")]):
                        with self.assertRaises(RuntimeError):
                            self.module["run"](self.stopped)
                ignition.request.assert_not_called()

    def test_gpio_request_failure_is_propagated_without_touching_latch(self):
        gpiod, _, ignition, latch = self.gpio_fixture()
        ignition.request.side_effect = OSError("GPIO already in use")
        with mock.patch.dict(sys.modules, {"gpiod": gpiod}):
            with mock.patch.object(Path, "glob", return_value=[Path("/dev/gpiochip4")]):
                with self.assertRaisesRegex(OSError, "already in use"):
                    self.module["run"](self.stopped)
        ignition.release.assert_not_called()
        latch.request.assert_not_called()

    def test_gpio_is_released_on_monitor_failure_but_latch_is_not_touched(self):
        gpiod, _, ignition, latch = self.gpio_fixture()
        run = self.module["run"]
        with mock.patch.dict(sys.modules, {"gpiod": gpiod}):
            with mock.patch.object(Path, "glob", return_value=[Path("/dev/gpiochip4")]):
                with mock.patch.dict(run.__globals__, {
                        "monitor": mock.Mock(side_effect=OSError("read failed"))}):
                    with self.assertRaises(OSError):
                        run(self.stopped)
        ignition.release.assert_called_once()
        latch.release.assert_not_called()

    def test_service_starts_early_and_leaves_latch_to_kernel_on_stop(self):
        unit = configparser.ConfigParser(interpolation=None)
        unit.read(SCRIPTS.parent / "lib/systemd/system/livi-carpihat-power.service")
        self.assertEqual(unit["Unit"]["DefaultDependencies"], "no")
        self.assertIn("sysinit.target", unit["Unit"]["Before"].split())
        self.assertIn("shutdown.target", unit["Unit"]["Conflicts"].split())
        self.assertEqual(unit["Service"]["Restart"], "on-failure")
        self.assertNotIn("ExecStop", unit["Service"])
        self.assertEqual(unit["Service"]["RestrictAddressFamilies"], "AF_UNIX")
        postbuild = (ROOT / "board/drskunk/livi/post-build.sh").read_text()
        self.assertIn('"${LIVI_CARPIHAT-1}" = 1', postbuild)
        self.assertIn("sysinit.target.wants/livi-carpihat-power.service", postbuild)


if __name__ == "__main__":
    unittest.main()
