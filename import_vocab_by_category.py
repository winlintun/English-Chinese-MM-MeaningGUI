#!/usr/bin/env python3
"""
Import data/vocab_by_category.csv into the SQLite database.

CSV format: category_zh,category_en,english,chinese

- Chinese is converted to the app's "Traditional (pinyin)" format.
- Myanmar is filled from the local Ornagai dictionary; words it does not
  cover are queried online with --online (1 s between site hits).
- Rows already present (same english + category, case-insensitive) are
  skipped, so the import is safe to re-run. Existing rows with an empty
  Myanmar gloss get it filled.

Usage:
    python3 import_vocab_by_category.py
    python3 import_vocab_by_category.py data/vocab_by_category.csv vocabulary.db
    python3 import_vocab_by_category.py --online
    python3 import_vocab_by_category.py --dry-run
"""

import argparse
import csv
import os
import sqlite3
import sys
import time

import vocapp

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(SCRIPT_DIR, "data", "vocab_by_category.csv")
ONLINE_DELAY = 1  # seconds between requests to the same site


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_file", nargs="?", default=CSV_FILE)
    parser.add_argument("db_file", nargs="?", default=vocapp.DB_FILE)
    parser.add_argument("--online", action="store_true",
                        help="query MyOrdbok for words missing from ornagai.db")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would change without writing")
    return parser.parse_args()


def has_myanmar(text):
    return any("\u1000" <= ch <= "\u109f" for ch in text or "")


def normalize_chinese(raw):
    raw = (raw or "").strip().replace("；", ",").replace(";", ",")
    return vocapp.normalize_chinese_entry(raw) if raw else ""


def lookup_myanmar(english, online):
    """Return (myanmar, source) for an English headword."""
    compact = english.replace("-", "").replace(" ", "")
    candidates = [english]
    if compact.lower() != english.lower():
        candidates.append(compact)
    for candidate in candidates:
        value = vocapp.lookup_myanmar_local(candidate)
        if value and has_myanmar(value):
            return vocapp.normalize_myanmar_text(value), "offline"
    if not online:
        return "", None
    value = vocapp._lookup_myanmar_online(english)
    time.sleep(ONLINE_DELAY)
    if value and has_myanmar(value):
        return vocapp.normalize_myanmar_text(value), "online"
    return "", None


def load_existing_words(conn):
    """(english.lower(), category.lower()) -> [(id, myanmar), ...]."""
    existing = {}
    for word_id, english, category, myanmar in conn.execute(
        "SELECT id, english, category, myanmar FROM words"
    ):
        key = ((english or "").lower(), (category or "").lower())
        existing.setdefault(key, []).append((word_id, myanmar))
    return existing


def main():
    args = parse_args()
    csv_file = os.path.abspath(args.csv_file)
    db_file = os.path.abspath(args.db_file)
    if not os.path.isfile(csv_file):
        print(f"error: file not found: {csv_file}", file=sys.stderr)
        return 1

    with open(csv_file, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        if "english" not in fields or not fields & {"category_en", "category_zh"}:
            print("error: CSV needs 'english' and 'category_en' or 'category_zh' "
                  f"columns, found: {reader.fieldnames}", file=sys.stderr)
            return 1
        rows = list(reader)

    if not rows:
        print("No rows found in", csv_file)
        return 1

    if args.dry_run:
        if os.path.isfile(db_file):
            conn = sqlite3.connect(vocapp._sqlite_ro_uri(db_file), uri=True)
        else:
            conn = None
    else:
        vocapp.DB_FILE = db_file
        try:
            vocapp.init_db(backup=False)
            conn = sqlite3.connect(db_file)
        except sqlite3.Error as exc:
            print(f"error: cannot open database {db_file}: {exc}", file=sys.stderr)
            return 1
        conn.execute("PRAGMA busy_timeout=30000")

    try:
        existing = load_existing_words(conn) if conn is not None else {}
    except sqlite3.DatabaseError as exc:
        if conn is not None:
            conn.close()
        if "no such table" in str(exc):
            print(f"error: database is not initialized ({exc}); "
                  "run once without --dry-run", file=sys.stderr)
        else:
            print(f"error: cannot read database {db_file}: {exc}",
                  file=sys.stderr)
        return 1

    planned_inserts = []  # (english, chinese, myanmar, category)
    planned_updates = []  # (myanmar, word_id)
    seen_keys = set()
    added = updated = skipped = 0
    missing = []
    per_category = {}

    for row in rows:
        english = (row.get("english") or "").strip()
        category = (row.get("category_en") or row.get("category_zh") or "").strip()
        if not english or not category:
            continue
        key = (english.lower(), category.lower())
        if key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(key)

        counts = per_category.setdefault(category, [0, 0])
        matches = existing.get(key, [])
        empty_ids = [word_id for word_id, gloss in matches
                     if not (gloss or "").strip()]
        if matches and not empty_ids:
            skipped += 1
            counts[1] += 1
            continue

        chinese = normalize_chinese(row.get("chinese"))
        myanmar, source = lookup_myanmar(english, args.online)
        print(f"  {english:<20} {category:<16} [{source or 'no gloss'}] {myanmar}")
        if not myanmar:
            missing.append(f"{category}: {english}")

        if matches:
            if myanmar:
                planned_updates.extend((myanmar, word_id) for word_id in empty_ids)
                updated += 1
            skipped += 1
            counts[1] += 1
        else:
            planned_inserts.append((english, chinese, myanmar, category))
            added += 1
            counts[0] += 1

    rebuilt = 0
    if not args.dry_run and (planned_inserts or planned_updates):
        touched_ids = []
        try:
            for values in planned_inserts:
                conn.execute(
                    "INSERT INTO words (english, chinese, myanmar, category) "
                    "VALUES (?,?,?,?)",
                    values,
                )
                touched_ids.append(conn.execute(
                    "SELECT last_insert_rowid()").fetchone()[0])
            for myanmar, word_id in planned_updates:
                conn.execute("UPDATE words SET myanmar=? WHERE id=?",
                             (myanmar, word_id))
                touched_ids.append(word_id)
            rebuilt = vocapp.rebuild_word_chars(conn, touched_ids)
            conn.commit()
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    elif conn is not None:
        conn.close()

    print("\nPer category (added / already present):")
    for category in sorted(per_category):
        cat_added, cat_present = per_category[category]
        print(f"  {category:<28} {cat_added:>4} / {cat_present:>4}")

    print(
        f"\n{'Would add' if args.dry_run else 'Added'}: {added}, "
        f"filled empty translations: {updated}, already present: {skipped}"
    )
    if not args.dry_run and rebuilt:
        print(f"Rebuilt the character breakdown for {rebuilt} word(s)")
    if missing:
        print(f"Still without a Myanmar gloss ({len(missing)}):")
        for item in missing:
            print("  ", item)
    if args.dry_run:
        print("Dry run — nothing was written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
