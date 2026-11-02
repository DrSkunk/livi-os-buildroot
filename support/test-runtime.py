#!/usr/bin/env python3
"""Exercise recovery scripts in temporary directories, without target devices."""

import os
import runpy
import hashlib
import json
from unittest import mock
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "board/drskunk/livi/rootfs-overlay/usr/bin"


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


class PostImage(unittest.TestCase):
    def test_builds_boot_control_and_matching_slot_cmdlines(self):
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
            }
            script = ROOT / "board/drskunk/livi/post-image.sh"
            for _ in range(2):
                result = subprocess.run(["bash", str(script), "rpi5"], env=env,
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
            self.assertEqual(config.count("[boot_partition=2]"), 1)
            self.assertIn("cmdline=cmdline-root-a.txt", config)
            self.assertIn("cmdline=cmdline-root-b.txt", config)
            self.assertIn("root=PARTUUID=8d9f2f13-5a82-4fd8-93e7-88e7ea6118d2",
                          (firmware / "cmdline-root-a.txt").read_text())
            self.assertIn("root=PARTUUID=4af7b146-2c77-4808-881b-1e3ad8d15be8",
                          (firmware / "cmdline-root-b.txt").read_text())
            self.assertTrue((binaries / "autoboot.txt").exists())


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
        check = json.loads(self.run_update("check").stdout)
        self.assertEqual(check, {"channel": "stable", "installed": "v1.0.0",
                                 "available": "v1.1.0", "update": True})
        self.run_update("update")
        self.assert_installed(image, boot_image)
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


if __name__ == "__main__":
    unittest.main()
