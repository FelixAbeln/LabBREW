from __future__ import annotations

import argparse
import asyncio
import contextlib
import time
from typing import Any

_TILT_COLOR_UUIDS = {
    "red": "a495bb10c5b14b44b5121370f02d74de",
    "green": "a495bb20c5b14b44b5121370f02d74de",
    "black": "a495bb30c5b14b44b5121370f02d74de",
    "purple": "a495bb40c5b14b44b5121370f02d74de",
    "orange": "a495bb50c5b14b44b5121370f02d74de",
    "blue": "a495bb60c5b14b44b5121370f02d74de",
    "yellow": "a495bb70c5b14b44b5121370f02d74de",
    "pink": "a495bb80c5b14b44b5121370f02d74de",
}

_APPLE_COMPANY_ID = 0x004C


def _decode_tilt(
    manufacturer_data: dict[int, bytes], wanted_uuid: str
) -> tuple[float, float] | None:
    blob = manufacturer_data.get(_APPLE_COMPANY_ID)
    # bleak manufacturer_data bytes do not include the 2-byte company ID.
    # Standard iBeacon payload here is 23 bytes.
    if not blob or len(blob) < 23:
        return None
    if blob[0] != 0x02 or blob[1] != 0x15:
        return None
    uuid_hex = blob[2:18].hex()
    if uuid_hex.lower() != wanted_uuid.lower():
        return None
    temp_raw = float(int.from_bytes(blob[18:20], byteorder="big", signed=False))
    gravity_raw = float(int.from_bytes(blob[20:22], byteorder="big", signed=False))
    # Classic Tilt: temp is integer F, gravity thousandths.
    # Tilt Pro: temp tenths-F, gravity ten-thousandths.
    temp_f = temp_raw / 10.0 if temp_raw > 250.0 else temp_raw
    gravity_sg = (
        gravity_raw / 10000.0
        if gravity_raw >= 5000.0
        else (gravity_raw / 1000.0 if gravity_raw > 5.0 else gravity_raw)
    )
    return temp_f, gravity_sg


async def run_probe(
    color: str, timeout_s: float, address: str, cycles: int, idle_s: float
) -> int:
    try:
        from bleak import BleakScanner
    except ModuleNotFoundError:
        print("ERROR: bleak is not installed in this environment.")
        return 2

    wanted_uuid = _TILT_COLOR_UUIDS[color]
    wanted_address = address.strip().lower()

    total_seen = 0
    matched_seen = 0

    for cycle in range(1, cycles + 1):
        found_event = asyncio.Event()
        selected: dict[str, Any] = {}

        def on_detection(device: Any, adv_data: Any) -> None:
            nonlocal total_seen, matched_seen
            total_seen += 1
            if selected:
                return
            if (
                wanted_address
                and str(getattr(device, "address", "")).strip().lower()
                != wanted_address
            ):
                return
            decoded = _decode_tilt(
                getattr(adv_data, "manufacturer_data", {}) or {}, wanted_uuid
            )
            if decoded is None:
                return
            temp_f, gravity_sg = decoded
            selected.update(
                {
                    "address": str(getattr(device, "address", "")),
                    "rssi": float(
                        getattr(adv_data, "rssi", getattr(device, "rssi", 0.0))
                    ),
                    "temp_f": temp_f,
                    "gravity_sg": gravity_sg,
                }
            )
            matched_seen += 1
            found_event.set()

        scanner = BleakScanner(detection_callback=on_detection)
        t0 = time.monotonic()
        await scanner.start()
        try:
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(found_event.wait(), timeout=timeout_s)
        finally:
            await scanner.stop()
        elapsed = time.monotonic() - t0

        if selected:
            print(
                f"cycle={cycle} match=yes color={color.title()} "
                f"addr={selected['address']} "
                f"gravity={selected['gravity_sg']:.4f} temp_f={selected['temp_f']:.1f} "
                f"rssi={selected['rssi']:.0f} elapsed_s={elapsed:.2f}"
            )
        else:
            print(
                f"cycle={cycle} match=no color={color.title()} elapsed_s={elapsed:.2f}"
            )

        if idle_s > 0:
            await asyncio.sleep(idle_s)

    print(f"summary total_adv_seen={total_seen} tilt_matches={matched_seen}")
    return 0 if matched_seen > 0 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe direct Tilt BLE advertisements."
    )
    parser.add_argument(
        "--color",
        default="green",
        choices=sorted(_TILT_COLOR_UUIDS.keys()),
        help="Tilt color to search for",
    )
    parser.add_argument(
        "--timeout-s", type=float, default=8.0, help="BLE scan window per cycle"
    )
    parser.add_argument(
        "--address", default="", help="Optional BLE device address filter"
    )
    parser.add_argument("--cycles", type=int, default=5, help="Number of scan cycles")
    parser.add_argument(
        "--idle-s", type=float, default=0.0, help="Idle delay between cycles"
    )
    args = parser.parse_args()

    print(
        f"Starting Tilt BLE probe color={args.color.title()} "
        f"timeout_s={args.timeout_s} "
        f"cycles={args.cycles} idle_s={args.idle_s}"
    )
    return asyncio.run(
        run_probe(
            color=args.color,
            timeout_s=max(0.1, float(args.timeout_s)),
            address=str(args.address),
            cycles=max(1, int(args.cycles)),
            idle_s=max(0.0, float(args.idle_s)),
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
