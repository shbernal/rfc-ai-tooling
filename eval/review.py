#!/usr/bin/env python3
"""Walk the items the author has not validated and record a verdict on each.

Items a model reviewed are included, so the author's reading can replace the
model's.

Shows the query beside the text of every gold section, then asks:

    a  accept — stamps validated_on with today's date and validated_by "author"
    e  edit the item in $EDITOR (add an acceptable section, sharpen the query),
       then show it again
    r  reject — removes the item from the file
    s  skip — leave it for later
    q  quit

The file is rewritten after every verdict, so quitting loses nothing and the
next run resumes at the first item the author has not validated.

    python3 eval/review.py [--mirror PATH] [--items PATH] [--stratum NAME]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "core"))
sys.path.insert(0, str(HERE))

import rfc  # noqa: E402
from check_gold import ITEMS, Corpus, check_item, load_items  # noqa: E402

# Long enough to judge a section by, short enough to keep the query on screen.
PREVIEW_LINES = 60


def save(path: Path, items: list[dict]) -> None:
    text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in items)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def show(item: dict, corpus: Corpus, full: bool) -> None:
    print("\n" + "=" * 78)
    print(f"{item['id']}  [{item['stratum']}, {item['split']}]")
    print(f"\n  Q: {item['query']}\n")
    if item["avoid"]:
        print(f"  avoid: {', '.join(f'RFC {n}' for n in item['avoid'])}")
    for problem in check_item(item, corpus, allow_unvalidated=True):
        print(f"  !! {problem}")
    for g in item["gold"]:
        number, section = g["rfc"], g["section"]
        where = f"§{section}" if section else "whole document"
        print("\n" + "-" * 78)
        print(f"{g['grade'].upper()}: RFC {number} {where}")
        record = corpus.index.get(number)
        if record:
            print(record.header())
        try:
            lines = rfc.split_lines(rfc.read_document(corpus.mirror, number))
            if section:
                start, end, _ = rfc.section_range(rfc.find_sections(lines), section, len(lines))
            else:
                start, end = 1, len(lines)
            text = rfc.slice_lines(lines, start, end, raw=False).splitlines()
        except rfc.RFCError as exc:
            print(f"  (cannot read: {exc})")
            continue
        shown = text if full else text[:PREVIEW_LINES]
        print("\n".join(shown))
        if len(shown) < len(text):
            print(f"  … {len(text) - len(shown)} more lines (f to show in full)")


def edit(item: dict) -> dict:
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as handle:
        json.dump(item, handle, indent=2, ensure_ascii=False)
        name = handle.name
    try:
        subprocess.run([*shlex.split(editor), name], check=False)
        return json.loads(Path(name).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"not saved — the edit is not valid JSON: {exc}")
        return item
    finally:
        os.unlink(name)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mirror", help="mirror directory (default: as the core resolves it)")
    parser.add_argument("--items", default=str(ITEMS), help="items file")
    parser.add_argument("--stratum", help="review only this stratum")
    args = parser.parse_args(argv)

    path = Path(args.items)
    corpus = Corpus(rfc.resolve_mirror(args.mirror))
    items = load_items(path)
    pending = [
        item["id"]
        for item in items
        if item["validated_by"] != "author" and args.stratum in (None, item["stratum"])
    ]
    print(f"{len(pending)} item(s) to review")

    for position, item_id in enumerate(pending, 1):
        full = False
        while True:
            index = next(i for i, item in enumerate(items) if item["id"] == item_id)
            show(items[index], corpus, full)
            prompt = f"\n[{position}/{len(pending)}] a)ccept e)dit r)eject s)kip f)ull q)uit: "
            choice = input(prompt).strip().lower()
            if choice == "a":
                items[index]["validated_on"] = datetime.date.today().isoformat()
                items[index]["validated_by"] = "author"
            elif choice == "r":
                del items[index]
            elif choice == "e":
                items[index] = edit(items[index])
                item_id = items[index]["id"]
                save(path, items)
                continue
            elif choice == "f":
                full = True
                continue
            elif choice == "q":
                return 0
            elif choice != "s":
                continue
            save(path, items)
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
