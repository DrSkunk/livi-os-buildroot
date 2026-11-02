#!/usr/bin/env python3
"""Exercise recovery scripts in temporary directories, without target devices."""

import os
import runpy
import json
from unittest import mock
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "board/drskunk/livi/rootfs-overlay/usr/bin"


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
                     'assets_directory = "/usr/share/retroarch/assets"',
                     'input_menu_toggle_gamepad_combo = "4"',
                     'savefile_directory = "/data/games/saves"']:
            self.assertIn(line, config)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertTrue(self.marker.exists())

    def test_existing_menu_is_backed_up_and_unrelated_settings_survive(self):
        original = (' menu_driver="ozone"\nmenu_pointer_enable = "false"\n'
                    'audio_volume = "-12"\nsavefile_directory = "/data/custom"\n')
        self.config.write_text(original)
        config = self.setup_menu()
        self.assertIn('menu_driver = "glui"', config)
        self.assertIn('menu_pointer_enable = "true"', config)
        self.assertIn('audio_volume = "-12"', config)
        self.assertIn('savefile_directory = "/data/custom"', config)
        self.assertEqual(self.config.with_name("retroarch.cfg.before-touch-v1").read_text(),
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
        self.config.parent.mkdir()
        self.backup.write_text('{"volume":42}\n')
        # Ownership changes require root on the target. Record the requested
        # owner here while exercising the real validation/copy/rename logic.
        chown = self.path / "chown"
        chown.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$OWNERSHIP_LOG"\n')
        chown.chmod(0o755)
        self.script = self.path / "guard"
        self.script.write_text(
            (SCRIPTS / "livi-config-guard").read_text()
            .replace("/data/livi/config/LIVI/config.json", str(self.config))
            .replace("/data/livi/config/config.json.last-good", str(self.backup))
        )

    def restore(self):
        subprocess.run(
            ["sh", str(self.script), "restore"], check=True,
            env={**os.environ, "PATH": f"{self.path}:{os.environ['PATH']}",
                 "OWNERSHIP_LOG": str(self.path / "owners")},
            capture_output=True,
        )

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
    def run_health_window(self, ready, fatal=False):
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
su() {{ return 0; }}
sleep() {{ command sleep 0.02; }}
hash_file() {{ echo good; }}
slot() {{ echo "$1" >> '{path}/slots'; }}
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
    def run_check(self, transform="90", enabled=True, audio=True):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "pulse").mkdir()
            data = [{"name": "HDMI-A-1", "enabled": enabled, "transform": transform,
                     "scale": 1, "modes": [{"width": 400, "height": 1280, "current": True}]}]
            (path / "outputs").write_text(json.dumps(data))
            for name, body in (("wlr-randr", 'cat "$OUTPUTS"'), ("timeout", 'shift; exec "$@"')):
                stub = path / name
                stub.write_text("#!/bin/sh\n" + body + "\n")
                stub.chmod(0o755)
            script = path / "ready"
            script.write_text((SCRIPTS.parent / "libexec/livi-kiosk-ready").read_text()
                              .replace("/run/user/1000", str(path)))
            with socket.socket(socket.AF_UNIX) as pipewire, socket.socket(socket.AF_UNIX) as pulse:
                if audio:
                    pipewire.bind(str(path / "pipewire-0"))
                    pulse.bind(str(path / "pulse/native"))
                return subprocess.run(["sh", str(script)], capture_output=True,
                                      env={**os.environ, "PATH": f"{path}:{os.environ['PATH']}",
                                           "OUTPUTS": str(path / "outputs")}).returncode

    def test_landscape_and_audio_ready(self):
        self.assertEqual(self.run_check(), 0)

    def test_portrait_is_not_ready(self):
        self.assertNotEqual(self.run_check(transform="normal"), 0)

    def test_disabled_display_is_not_ready(self):
        self.assertNotEqual(self.run_check(enabled=False), 0)

    def test_missing_audio_is_not_ready(self):
        self.assertNotEqual(self.run_check(audio=False), 0)


class TrialBoot(unittest.TestCase):
    ROOT_A = "8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2"
    ROOT_B = "4af7b146-2c77-4808-881b-1e3ad8d15be8"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        for name in ("boot", "run", "bin"):
            (self.path / name).mkdir()
        self.default = self.path / "boot/cmdline.txt"
        self.default.write_text(f"root=PARTUUID={self.ROOT_A} video=HDMI-A-1:400x1280@60D\n")
        self.cmdline = self.path / "proc-cmdline"
        self.cmdline.write_text(self.default.read_text())
        self.trial = self.path / "trial"
        self.trial.write_bytes(b"\0\0\0\0")
        for command in ("mount", "sync", "flock", "reboot"):
            stub = self.path / "bin" / command
            stub.write_text('#!/bin/sh\nprintf "%s %s\\n" "${0##*/}" "$*" >> "$COMMAND_LOG"\n')
            stub.chmod(0o755)
        script = (SCRIPTS / "livi-os-slot").read_text()
        script = (script.replace("/data/os-update", str(self.path / "data"))
                  .replace("/boot/", str(self.path / "boot") + "/")
                  .replace("/run/", str(self.path / "run") + "/")
                  .replace("/proc/cmdline", str(self.cmdline))
                  .replace("/proc/device-tree/chosen/bootloader/tryboot", str(self.trial)))
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
        original = self.default.read_text()
        self.stage()
        self.slot("reboot")
        self.assertEqual(self.default.read_text(), original)
        self.assertIn(self.ROOT_B, (self.path / "boot/cmdline-tryboot.txt").read_text())
        self.assertIn("reboot 0 tryboot", (self.path / "commands").read_text())
        self.assertEqual((self.path / "data/pending").read_text().splitlines()[2], "1")

    def test_only_healthy_trial_commits_default(self):
        self.stage()
        self.slot("reboot")
        self.cmdline.write_text(f"root=PARTUUID={self.ROOT_B}\n")
        self.slot("mark-good", success=False)
        self.trial.write_bytes(b"\0\0\0\1")
        self.slot("boot-check")
        self.slot("mark-good")
        self.assertIn(self.ROOT_B, self.default.read_text())
        self.assertFalse((self.path / "data/pending").exists())
        self.assertTrue((self.path / "run/livi-os-confirmed").exists())

    def test_failure_before_userspace_returns_to_previous_root(self):
        self.stage()
        self.slot("reboot")
        self.slot("boot-check")
        self.assertIn(self.ROOT_A, self.default.read_text())
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


if __name__ == "__main__":
    unittest.main()
