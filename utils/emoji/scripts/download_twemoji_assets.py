from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


TWEMOJI_VERSION = "14.0.2"
TWEMOJI_BASE_URL = (
    f"https://cdn.jsdelivr.net/gh/twitter/twemoji@{TWEMOJI_VERSION}/assets/72x72"
)
EMOJI_TEST_URL = "https://unicode.org/Public/emoji/14.0/emoji-test.txt"
DEFAULT_OUTPUT_DIR = Path("utils/emoji/twemoji")

VARIATION_SELECTOR_TEXT = 0xFE0E
VARIATION_SELECTOR_EMOJI = 0xFE0F
ZERO_WIDTH_JOINER = 0x200D
SKIN_TONE_START = 0x1F3FB
SKIN_TONE_END = 0x1F3FF


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Twemoji PNG assets into utils/emoji/twemoji."
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        type=Path,
        help="Directory where PNG assets will be stored.",
    )
    parser.add_argument(
        "--emoji-test-url",
        default=EMOJI_TEST_URL,
        help="Unicode emoji-test.txt URL used to discover emoji sequences.",
    )
    parser.add_argument(
        "--text",
        action="append",
        default=[],
        help="Download assets for emoji found in this text. Can be used multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Download at most this many assets. Useful for testing.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Concurrent download workers.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Redownload files that already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be downloaded without writing files.",
    )
    args = parser.parse_args()

    if args.text:
        asset_groups = asset_groups_from_text(" ".join(args.text))
    else:
        asset_groups = asset_groups_from_emoji_test(args.emoji_test_url)

    if args.limit is not None:
        asset_groups = asset_groups[:args.limit]

    if args.dry_run:
        for filenames in asset_groups:
            print(", ".join(filenames))
        print(f"total={len(asset_groups)}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    skipped = 0
    missing = []
    failed = []

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = [
            executor.submit(download_asset_group, filenames, args.output_dir, args.force)
            for filenames in asset_groups
        ]

        for future in as_completed(futures):
            result, filename = future.result()
            if result == "downloaded":
                downloaded += 1
            elif result == "skipped":
                skipped += 1
            elif result == "missing":
                missing.append(filename)
            else:
                failed.append(filename)

    print(f"downloaded={downloaded}")
    print(f"skipped={skipped}")
    print(f"missing={len(missing)}")
    print(f"failed={len(failed)}")

    if missing:
        missing_path = args.output_dir / "missing.txt"
        missing_path.write_text("\n".join(sorted(missing)) + "\n", encoding="utf-8")
        print(f"missing_list={missing_path}")

    if failed:
        failed_path = args.output_dir / "failed.txt"
        failed_path.write_text("\n".join(sorted(failed)) + "\n", encoding="utf-8")
        print(f"failed_list={failed_path}")
        return 1

    return 0


def asset_groups_from_emoji_test(url: str) -> list[list[str]]:
    content = read_url(url).decode("utf-8")
    asset_groups = []
    seen = set()

    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "; fully-qualified" not in line:
            continue

        codepoint_text = line.split(";", 1)[0].strip()
        codepoints = [int(part, 16) for part in codepoint_text.split()]
        filenames = candidate_filenames(codepoints)
        key = tuple(filenames)
        if key not in seen:
            asset_groups.append(filenames)
            seen.add(key)

    return asset_groups


def asset_groups_from_text(text: str) -> list[list[str]]:
    asset_groups = []
    seen = set()

    for token in iter_emoji_tokens(text):
        filenames = candidate_filenames([ord(char) for char in token])
        key = tuple(filenames)
        if key not in seen:
            asset_groups.append(filenames)
            seen.add(key)

    return asset_groups


def iter_emoji_tokens(text: str):
    index = 0
    while index < len(text):
        char = text[index]
        token = char
        is_emoji = is_emoji_char(char)
        index += 1

        while is_emoji and index < len(text):
            next_char = text[index]
            if is_emoji_modifier(next_char):
                token += next_char
                index += 1
                continue
            if ord(next_char) == ZERO_WIDTH_JOINER and index + 1 < len(text):
                token += next_char + text[index + 1]
                index += 2
                continue
            break

        if is_emoji:
            yield token


def candidate_filenames(codepoints: list[int]) -> list[str]:
    without_text_variation = [
        codepoint for codepoint in codepoints
        if codepoint != VARIATION_SELECTOR_TEXT
    ]
    without_emoji_variation = [
        codepoint for codepoint in without_text_variation
        if codepoint != VARIATION_SELECTOR_EMOJI
    ]

    candidates = [
        without_text_variation,
        without_emoji_variation,
        [
            codepoint for codepoint in without_emoji_variation
            if codepoint != ZERO_WIDTH_JOINER
        ],
        [
            codepoint for codepoint in without_emoji_variation
            if not SKIN_TONE_START <= codepoint <= SKIN_TONE_END
        ],
    ]

    filenames = []
    for candidate in candidates:
        if not candidate:
            continue
        filename = "-".join(f"{codepoint:x}" for codepoint in candidate) + ".png"
        if filename not in filenames:
            filenames.append(filename)
    return filenames


def download_asset_group(
        filenames: list[str],
        output_dir: Path,
        force: bool,
) -> tuple[str, str]:
    for filename in filenames:
        output_path = output_dir / filename
        if output_path.exists() and not force:
            return "skipped", filename

    had_failure = False
    for filename in filenames:
        output_path = output_dir / filename

        try:
            image_bytes = read_url(f"{TWEMOJI_BASE_URL}/{filename}")
        except HTTPError as exc:
            if exc.code == 404:
                continue
            had_failure = True
            continue
        except (OSError, URLError):
            had_failure = True
            continue

        output_path.write_bytes(image_bytes)
        return "downloaded", filename

    return ("failed" if had_failure else "missing"), filenames[0]


def read_url(url: str) -> bytes:
    with urlopen(url, timeout=20) as response:
        return response.read()


def is_emoji_char(char: str) -> bool:
    codepoint = ord(char)
    if char in {"©", "®", "™", "#", "*"}:
        return True
    if 0x1F000 <= codepoint <= 0x1FAFF:
        return True
    if 0x2600 <= codepoint <= 0x27BF:
        return True
    return bool(re.search(r"EMOJI", char_name(char)))


def is_emoji_modifier(char: str) -> bool:
    codepoint = ord(char)
    return (
        SKIN_TONE_START <= codepoint <= SKIN_TONE_END
        or codepoint in {
            VARIATION_SELECTOR_TEXT,
            VARIATION_SELECTOR_EMOJI,
            ZERO_WIDTH_JOINER,
            0x20E3,
        }
    )


def char_name(char: str) -> str:
    try:
        import unicodedata

        return unicodedata.name(char, "")
    except ValueError:
        return ""


if __name__ == "__main__":
    sys.exit(main())
