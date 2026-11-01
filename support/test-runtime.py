#!/usr/bin/env python3
"""Exercise recovery scripts in temporary directories, without target devices."""

import os
import runpy
import json
import hashlib
import configparser
from unittest import mock
from pathlib import Path
import socket
import struct
import sys
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "board/drskunk/livi/rootfs-overlay/usr/bin"


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
        self.assertTrue(any("livi-splash.service" in line for line in conflicts))

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
                               .replace("/run/user/1000", str(self.path / "runtime")))

    def seed(self):
        subprocess.run(["sh", str(self.script)], check=True, capture_output=True,
                       env={**os.environ, "PATH": f"{self.path}:{os.environ['PATH']}"})

    def test_seeds_country_panel_and_unique_private_password(self):
        self.seed()
        config = json.loads(self.config.read_text())
        self.assertEqual(config["country"], "CA")
        self.assertEqual((config["mainScreenWidth"], config["mainScreenHeight"]), (1280, 400))
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
