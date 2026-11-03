#!/usr/bin/env python3

import json
import socket
import struct
import subprocess
import sys

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x7FF
CAN_IDS = (0x360, 0x361, 0x368, 0x36A, 0x370, 0x372, 0x3E0)


def check_interface():
    result = subprocess.run(
        ["/usr/sbin/ip", "-details", "-json", "link", "show", "dev", "can0"],
        check=True, capture_output=True, text=True,
    )
    links = json.loads(result.stdout)
    if len(links) != 1:
        raise RuntimeError("expected exactly one can0 interface")
    link = links[0]
    info = link.get("linkinfo", {})
    data = info.get("info_data", {})
    if (
        "UP" not in link.get("flags", [])
        or info.get("info_kind") != "can"
        or data.get("bittiming", {}).get("bitrate") != 1000000
        or "LISTEN-ONLY" not in data.get("ctrlmode", [])
        or data.get("state") in ("BUS-OFF", "STOPPED", "SLEEPING")
    ):
        raise RuntimeError("can0 must be UP at 1000000 bit/s, listen-only, and not bus-off")


def main():
    check_interface()
    can_socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    filters = b"".join(
        struct.pack("=II", can_id, CAN_SFF_MASK | CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG)
        for can_id in CAN_IDS
    )
    can_socket.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, filters)
    can_socket.bind(("can0",))

    while True:
        frame = can_socket.recv(16)
        if len(frame) != 16:
            continue
        can_id, length, payload = struct.unpack("=IB3x8s", frame)
        if can_id & (CAN_EFF_FLAG | CAN_RTR_FLAG | CAN_ERR_FLAG):
            continue
        if length < 2 or length > 8:
            continue
        can_id &= CAN_SFF_MASK
        if can_id not in CAN_IDS:
            continue
        print(f"can0 {can_id:03X}#{payload[:length].hex().upper()}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"livi-can-capture: {error}", file=sys.stderr)
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            print(error.stderr, file=sys.stderr, end="")
        sys.exit(1)
