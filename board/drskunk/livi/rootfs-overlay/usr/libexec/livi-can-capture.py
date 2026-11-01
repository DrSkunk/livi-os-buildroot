#!/usr/bin/env python3

import socket
import struct

CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_SFF_MASK = 0x7FF
CAN_IDS = (0x360, 0x370)


def main():
    can_socket = socket.socket(socket.PF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    filters = b"".join(struct.pack("=II", can_id, CAN_SFF_MASK) for can_id in CAN_IDS)
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
    main()
