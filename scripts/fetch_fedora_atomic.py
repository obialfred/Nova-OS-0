#!/usr/bin/env python3
"""Fetch Fedora Atomic release metadata and optionally download images.

This helper focuses on aarch64 Atomic images (e.g. Fedora 43) that Nova OS uses
as its upstream base. It parses Fedora's releases.json feed, selects the desired
entry, prints metadata, and can download the image when requested.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys
import textwrap
from dataclasses import dataclass
from typing import Iterable, List, Optional
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

RELEASES_INDEX = "https://fedoraproject.org/releases.json"
DEFAULT_VARIANT_KEYWORDS = ("Atomic",)
CHUNK_SIZE = 1 << 20  # 1 MiB
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF = 2.0


@dataclass
class ReleaseEntry:
    version: str
    arch: str
    variant: str
    subvariant: str
    link: str
    sha256: str
    size: Optional[int]

    @classmethod
    def from_json(cls, payload: dict) -> "ReleaseEntry":
        size = payload.get("size")
        if isinstance(size, str):
            try:
                size_int = int(size)
            except ValueError:
                size_int = None
        else:
            size_int = size

        return cls(
            version=payload.get("version", ""),
            arch=payload.get("arch", ""),
            variant=payload.get("variant", ""),
            subvariant=payload.get("subvariant", ""),
            link=payload.get("link", ""),
            sha256=payload.get("sha256", ""),
            size=size_int,
        )

    @property
    def channel(self) -> str:
        version_lower = self.version.lower()
        if "beta" in version_lower:
            return "beta"
        if any(tag in version_lower for tag in ("alpha", "rc")):
            return "pre"
        return "stable"

    @property
    def major_version(self) -> Optional[int]:
        head = self.version.split()[0]
        try:
            return int(head)
        except ValueError:
            return None

    def matches_keywords(self, keywords: Iterable[str]) -> bool:
        value = f"{self.variant} {self.subvariant}".lower()
        return all(keyword.lower() in value for keyword in keywords)


class ReleaseIndex:
    def __init__(self, entries: List[ReleaseEntry]):
        self.entries = entries

    @classmethod
    def fetch(
        cls,
        url: str = RELEASES_INDEX,
        *,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
    ) -> "ReleaseIndex":
        attempt = 0
        while True:
            attempt += 1
            try:
                with urlopen(url) as response:
                    data = json.load(response)
                break
            except (HTTPError, URLError) as exc:
                if attempt > retries:
                    raise
                sleep_for = backoff * attempt
                sys.stderr.write(
                    f"Failed to fetch {url} ({exc}); retrying in {sleep_for:.1f}s...\n"
                )
                sys.stderr.flush()
                time.sleep(sleep_for)

        entries = [ReleaseEntry.from_json(item) for item in data]
        return cls(entries)

    def filter(
        self,
        *,
        arch: Optional[str] = None,
        keywords: Iterable[str] = (),
        version: Optional[int] = None,
        channel: str = "any",
    ) -> List[ReleaseEntry]:
        channel = channel.lower()
        results: List[ReleaseEntry] = []
        for entry in self.entries:
            if arch and entry.arch != arch:
                continue
            if keywords and not entry.matches_keywords(keywords):
                continue
            if version is not None and entry.major_version not in (version, None):
                continue
            if channel != "any" and entry.channel != channel:
                if not (channel == "stable" and entry.channel == "stable"):
                    continue
            results.append(entry)
        # Sort with highest version first and stable preferred over beta
        stage_score = {"stable": 2, "beta": 1, "pre": 0}
        results.sort(
            key=lambda item: (
                item.major_version or -1,
                stage_score.get(item.channel, -1),
                item.version,
            ),
            reverse=True,
        )
        return results


def human_size(value: Optional[int]) -> str:
    if not value:
        return "unknown"
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    idx = int(math.log(value, 1024)) if value > 0 else 0
    idx = min(idx, len(units) - 1)
    scaled = value / (1024 ** idx)
    return f"{scaled:.2f} {units[idx]}"


def download(
    url: str,
    destination: pathlib.Path,
    *,
    retries: int = DEFAULT_RETRIES,
    backoff: float = DEFAULT_BACKOFF,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        attempt += 1
        try:
            with urlopen(url) as response, destination.open("wb") as handle:
                total = int(response.getheader("Content-Length") or 0)
                read = 0
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    handle.write(chunk)
                    read += len(chunk)
                    if total:
                        percent = read / total * 100
                        sys.stderr.write(
                            f"\rDownloaded {read:,} / {total:,} bytes ({percent:5.1f}%)"
                        )
                        sys.stderr.flush()
            sys.stderr.write("\n")
            break
        except (HTTPError, URLError) as exc:
            if attempt > retries:
                raise
            sleep_for = backoff * attempt
            sys.stderr.write(
                f"Download failed ({exc}); retrying in {sleep_for:.1f}s...\n"
            )
            sys.stderr.flush()
            time.sleep(sleep_for)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Locate and optionally download Fedora Atomic releases",
    )
    parser.add_argument("--version", type=int, default=43, help="Fedora major version to match (default: 43)")
    parser.add_argument(
        "--arch", default="aarch64", help="CPU architecture to match (default: aarch64)",
    )
    parser.add_argument(
        "--keywords",
        nargs="*",
        default=list(DEFAULT_VARIANT_KEYWORDS),
        help="Variant keywords to search for (default: Atomic)",
    )
    parser.add_argument(
        "--channel",
        choices=["stable", "beta", "any"],
        default="any",
        help="Release channel preference. Defaults to any available.",
    )
    parser.add_argument(
        "--download",
        action="store_true",
        help="Download the selected artifact instead of printing metadata only.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("artifacts"),
        help="Output directory for downloads (default: ./artifacts)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Limit the number of matching releases to show (default: 1)",
    )
    parser.add_argument(
        "--link-contains",
        default=None,
        help="Only include results whose download URL contains this substring.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    index = ReleaseIndex.fetch()
    matches = index.filter(
        arch=args.arch,
        keywords=args.keywords,
        version=args.version,
        channel=args.channel,
    )
    if args.link_contains:
        matches = [m for m in matches if args.link_contains in m.link]
    if not matches:
        print("No matching releases found.", file=sys.stderr)
        return 1

    for entry in matches[: args.limit]:
        summary = textwrap.dedent(
            f"""
            Selected release
              Version : {entry.version}
              Variant : {entry.variant} ({entry.subvariant})
              Arch    : {entry.arch}
              Channel : {entry.channel}
              Size    : {human_size(entry.size)}
              SHA256  : {entry.sha256}
              URL     : {entry.link}
            """
        ).strip()
        print(summary)

        if args.download:
            filename = pathlib.Path(entry.link).name
            destination = args.output / filename
            print(f"\nDownloading to {destination}...", file=sys.stderr)
            download(entry.link, destination)
            print(f"Saved to {destination.resolve()}")

    if len(matches) > args.limit:
        print(
            f"\n{len(matches) - args.limit} additional matches suppressed; use --limit to show more.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
