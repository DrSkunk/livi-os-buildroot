#!/usr/bin/env python3
"""Bounded Service 01 diagnostics on can0. No writes, controls or arbitrary requests."""

import fcntl
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time


# PID: (normalized key, unit, period in seconds, number of data bytes).
PIDS = {
    0x0C: ("rpm", "rpm", 0.2, 2),
    0x0D: ("speedKph", "km/h", 0.2, 1),
    0x05: ("coolantC", "C", 1.0, 1),
    0x0F: ("iatC", "C", 1.0, 1),
    0x0B: ("mapKpa", "kPa absolute", 0.5, 1),
    0x11: ("throttlePct", "%", 0.5, 1),
    0x0E: ("timingAdvanceDeg", "deg", 1.0, 1),
    0x42: ("batteryV", "V", 1.0, 2),
    0x1F: ("engineRunTimeS", "s", 5.0, 2),
    0x2F: ("fuelPct", "%", 5.0, 1),
    0x5C: ("oilC", "C", 5.0, 1),
    0x52: ("ethanolPct", "%", 5.0, 1),
}
DISCOVERY = (0x00, 0x20, 0x40)
REQUEST_INTERVAL = 0.1  # At most ten requests/second, including discovery/retries.
RESPONSE_TIMEOUT = 0.3
FILTER_MASK = 0xE00007FF


class Stopped(Exception):
    pass


def decode(pid, data):
    spec = PIDS.get(pid)
    if spec is None or len(data) != spec[3]:
        raise ValueError("unapproved PID or wrong data length")
    a = data[0]
    raw = int.from_bytes(data, "big")
    if pid == 0x0C:
        return raw / 4
    if pid in (0x05, 0x0F, 0x5C):
        return a - 40
    if pid in (0x11, 0x2F, 0x52):
        return a * 100 / 255
    if pid == 0x0E:
        return a / 2 - 64
    if pid == 0x42:
        return raw / 1000
    return raw


def response(frame, pid, ecu=None):
    """Validate a standard classic CAN ISO-TP Single Frame for Service 01."""
    if len(frame) != 16:
        return None
    can_id, dlc, payload = struct.unpack("=IB3x8s", frame)
    if not 0x7E8 <= can_id <= 0x7EF or (ecu is not None and can_id != ecu):
        return None
    if not 4 <= dlc <= 8 or payload[0] >> 4 != 0:
        return None
    size = payload[0]
    expected = 6 if pid in DISCOVERY else 2 + PIDS[pid][3]
    if size != expected or size + 1 > dlc or payload[1:3] != bytes((0x41, pid)):
        return None
    return can_id, payload[3:size + 1]


def supported(base, data):
    if base not in DISCOVERY or len(data) != 4:
        raise ValueError("invalid capability bitmap")
    bitmap = int.from_bytes(data, "big")
    return {base + bit for bit in range(1, 33) if bitmap & (1 << (32 - bit))}


def request_frame(pid, ecu=None):
    if pid not in PIDS and pid not in DISCOVERY:
        raise ValueError("PID is not on the immutable Service 01 allowlist")
    if ecu is not None and not 0x7E8 <= ecu <= 0x7EF:
        raise ValueError("invalid ECU response address")
    request_id = 0x7DF if ecu is None else ecu - 8
    return struct.pack("=IB3x8s", request_id, 8, bytes((2, 1, pid, 0, 0, 0, 0, 0)))


def command(*args):
    subprocess.run(args, check=True, capture_output=True, text=True, timeout=5)


def stop(*_):
    raise Stopped()


def check_interface(bitrate):
    links = json.loads(subprocess.run(
        ["/usr/sbin/ip", "-details", "-json", "link", "show", "dev", "can0"],
        check=True, capture_output=True, text=True, timeout=5,
    ).stdout)
    if len(links) != 1:
        raise RuntimeError("expected exactly one can0 interface")
    link = links[0]
    info = link.get("linkinfo", {})
    data = info.get("info_data", {})
    if ("UP" not in link.get("flags", []) or info.get("info_kind") != "can"
            or data.get("bittiming", {}).get("bitrate") != bitrate
            or "LISTEN-ONLY" in data.get("ctrlmode", [])
            or data.get("state") not in ("ERROR-ACTIVE", "ERROR-WARNING", "ERROR-PASSIVE")):
        raise RuntimeError("can0 is not ready at the requested bitrate in normal mode")


class Poller:
    def __init__(self, can_socket, bitrate, lifeline=0):
        self.can = can_socket
        self.bitrate = bitrate
        self.lifeline = lifeline
        self.ecu = None
        self.last_request = float("-inf")
        self.last_response = None
        self.timeouts = 0
        self.errors = 0
        self.requests = 0
        self.supported = set()
        self.seen = {}
        self.disabled = set()
        self.status = "connecting"
        self.error = None

    def wait(self, seconds, receive=False):
        readable, _, _ = select.select(
            [self.lifeline, self.can] if receive else [self.lifeline], [], [], max(0, seconds),
        )
        if self.lifeline in readable:
            if not os.read(self.lifeline, 1):
                raise Stopped()
            raise RuntimeError("OBD lifeline accepts EOF only, not commands")
        return self.can in readable

    def emit(self, patch=None):
        now = time.monotonic()
        signals = {}
        for pid, (key, unit, period, _) in PIDS.items():
            at = self.seen.get(pid)
            signals[key] = {
                "unit": unit,
                "state": (
                    "unsupported" if self.status == "unsupported" or (
                        self.ecu is not None and pid not in self.supported
                    ) else "disconnected" if self.status in ("disconnected", "canError")
                    else "stale" if at is None or now - at >= max(1.5, period * 3)
                    else "available"
                ),
                "ageMs": None if at is None else round((now - at) * 1000),
            }
        out = dict(patch or {})
        out["obd2"] = {
            "status": self.status, "interface": "can0", "bitrate": self.bitrate,
            "ecu": None if self.ecu is None else f"{self.ecu:03X}",
            "supportedPids": [f"{pid:02X}" for pid in sorted(self.supported & PIDS.keys())],
            "lastResponseAgeMs": (
                None if self.last_response is None else round((now - self.last_response) * 1000)
            ),
            "requests": self.requests, "timeouts": self.timeouts, "errors": self.errors,
            "error": self.error, "signals": signals,
            "timestampMonotonicMs": round(now * 1000),
        }
        print(json.dumps(out, separators=(",", ":")), flush=True)

    def query(self, pid):
        self.wait(self.last_request + REQUEST_INTERVAL - time.monotonic())
        # Discard queued frames before sending; never decode an old reply as a new sample.
        for _ in range(256):
            self.wait(0)
            if not select.select([self.can], [], [], 0)[0]:
                break
            self.can.recv(16)
        else:
            raise RuntimeError("CAN response queue is continuously flooded")
        self.wait(0)
        self.can.send(request_frame(pid, self.ecu))
        self.requests += 1
        self.last_request = time.monotonic()
        deadline = self.last_request + RESPONSE_TIMEOUT
        while time.monotonic() < deadline:
            if not self.wait(deadline - time.monotonic(), receive=True):
                break
            result = response(self.can.recv(16), pid, self.ecu)
            if result is not None:
                self.last_response = time.monotonic()
                return result
        self.timeouts += 1
        return None

    def discover(self):
        self.ecu = None
        self.supported.clear()
        self.disabled.clear()
        for base in DISCOVERY:
            reply = self.query(base)
            if reply is None:
                return False
            self.ecu, data = reply
            found = supported(base, data)
            self.supported.update(found)
            if base + 32 not in found:
                break
        return True

    def expire(self):
        now = time.monotonic()
        patch = {}
        for pid, at in list(self.seen.items()):
            key, _, period, _ = PIDS[pid]
            if now - at >= max(1.5, period * 3):
                patch[key] = None
                del self.seen[pid]
        return patch

    def run(self):
        backoff = 2
        while True:
            check_interface(self.bitrate)
            self.status = "connecting"
            self.emit()
            if not self.discover():
                self.status = "disconnected"
                self.seen.clear()
                self.emit({spec[0]: None for spec in PIDS.values()})
                self.wait(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 2
            active = sorted(self.supported & PIDS.keys())
            self.status = "available" if active else "unsupported"
            self.emit()
            if not active:
                self.wait(30)
                continue
            due = {pid: time.monotonic() for pid in active}
            failures = {pid: 0 for pid in active}
            checked_at = time.monotonic()
            while due:
                pid = min(due, key=due.get)
                self.wait(min(max(0, due[pid] - time.monotonic()), 0.5))
                if time.monotonic() - checked_at >= 1:
                    check_interface(self.bitrate)
                    checked_at = time.monotonic()
                patch = self.expire()
                if time.monotonic() >= due[pid]:
                    reply = self.query(pid)
                    if reply is not None:
                        _, data = reply
                        key = PIDS[pid][0]
                        patch[key] = decode(pid, data)
                        self.seen[pid] = time.monotonic()
                        failures[pid] = 0
                    else:
                        failures[pid] += 1
                    if failures[pid] >= 3:
                        patch[PIDS[pid][0]] = None
                        self.seen.pop(pid, None)
                        self.disabled.add(pid)
                        del due[pid]
                    else:
                        due[pid] = time.monotonic() + PIDS[pid][2] * (2 ** failures[pid])
                if self.last_response is not None and time.monotonic() - self.last_response > 5:
                    self.status = "disconnected"
                    break
                self.status = "available" if self.seen else "stale"
                self.emit(patch)
            self.seen.clear()
            self.emit({spec[0]: None for spec in PIDS.values()})
            self.wait(5)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("500000", "1000000"):
        raise ValueError("requires bitrate 500000 or 1000000")
    bitrate = int(sys.argv[1])
    signal.signal(signal.SIGTERM, stop)
    with open("/run/lock/livi-can.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Stop passive configuration before taking exclusive ownership of can0.
        command("/usr/bin/systemctl", "stop", "livi-can.service")
        command("/usr/sbin/ip", "link", "set", "dev", "can0", "down")
        poller = None
        try:
            command("/usr/sbin/ip", "link", "set", "dev", "can0", "type", "can",
                    "bitrate", str(bitrate), "listen-only", "off")
            command("/usr/sbin/ip", "link", "set", "dev", "can0", "up")
            check_interface(bitrate)
            with socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW) as can:
                can.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, b"".join(
                    struct.pack("=II", can_id, FILTER_MASK) for can_id in range(0x7E8, 0x7F0)
                ))
                can.setblocking(False)
                can.bind(("can0",))
                poller = Poller(can, bitrate)
                poller.wait(0)
                poller.run()
        except Stopped:
            if poller is not None:
                poller.status = "disconnected"
                poller.seen.clear()
                poller.emit({spec[0]: None for spec in PIDS.values()})
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            if poller is not None:
                poller.status = "canError"
                poller.errors += 1
                poller.error = str(error)
                poller.seen.clear()
                poller.emit({spec[0]: None for spec in PIDS.values()})
            raise
        finally:
            command("/usr/sbin/ip", "link", "set", "dev", "can0", "down")


if __name__ == "__main__":
    try:
        main()
    except Stopped:
        pass
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"livi-obd2: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr, end="")
        sys.exit(1)
