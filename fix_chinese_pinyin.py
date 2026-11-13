#!/usr/bin/env python3
"""
Normalize every Chinese entry in the database to Traditional Chinese with pinyin.

Fixes rows like:
    能力                         -> 能力 (nénglì)
    收购 / 获得  (Simplified)     -> 收購 / 獲得 (shōugòu / huòdé)
    成績 (cheng4ji4)             -> 成績 (chéngjì)  [kept/normalized pinyin]

Entries that are already Traditional with correct pinyin are left untouched,
so this script is safe to run again at any time (idempotent).

Requires:  pip install opencc-python-reimplemented pypinyin
Usage:
    python3 fix_chinese_pinyin.py                # default vocabulary.db
    python3 fix_chinese_pinyin.py path/to/db     # other database file
"""

import os
import sys

import vocapp  # reuse the exact normalization the GUI uses


def fix_database(db_file):
    if not os.path.exists(db_file):
        print(f"Error: database not found: {db_file}")
        return

    con = sqlite3_connect(db_file)
    rows = con.execute(
        "SELECT id, chinese FROM words WHERE chinese IS NOT NULL AND chinese != ''"
    ).fetchall()

    updated = 0
    samples = []
    for word_id, cn in rows:
        fixed = vocapp.normalize_chinese_entry(cn)
        if fixed != cn:
            con.execute("UPDATE words SET chinese=? WHERE id=?", (fixed, word_id))
            updated += 1
            if len(samples) < 10:
                samples.append((cn, fixed))

    con.commit()
    con.close()

    print(f"Checked {len(rows)} Chinese entries")
    print(f"Updated {updated} row(s) to Traditional Chinese + pinyin")
    for old, new in samples:
        print(f"  {old!r} -> {new!r}")
    if updated == 0:
        print("All entries already use Traditional Chinese + pinyin.")


def sqlite3_connect(db_file):
    import sqlite3
    con = sqlite3.connect(db_file)
    try:
        con.execute("PRAGMA journal_mode=WAL")
    except Exception:
        pass
    return con


def main():
    db_file = sys.argv[1] if len(sys.argv) > 1 else vocapp.DB_FILE
    print(f"Database: {db_file}\n")
    fix_database(db_file)


if __name__ == "__main__":
    main()
