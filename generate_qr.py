"""
Generate printable QR codes for each wedding event.

Usage:
    python generate_qr.py --base-url https://photos.yourdomain.com --out ./out

Produces one PNG per event in ./out, e.g. qr_wedding.png, ready to print
and place on tables / entry points.
"""

import argparse
import os

import qrcode

EVENTS = ["haldi", "mehendi", "sangeet", "wedding", "reception"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True, help="Public URL of your deployed backend, e.g. https://photos.yourdomain.com")
    parser.add_argument("--out", default="./out", help="Output directory for PNGs")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)

    for event in EVENTS:
        url = f"{args.base_url}/app/index.html?event={event}"
        img = qrcode.make(url, box_size=10, border=4)
        path = os.path.join(args.out, f"qr_{event}.png")
        img.save(path)
        print(f"[{event}] {url} -> {path}")


if __name__ == "__main__":
    main()
