#!/usr/bin/env python3
"""
Import TOCEI .md vocabulary files into the SQLite database.

Expected .md format (all files use the same format):
    # Category "TOCEI" change to "TOCEI-Banking&Finance"
    adequacy,လုံလောက်မှု,充分 / 足夠
    adequate,လုံလောက်သော,足夠的 / 適當的
    ...

- The first line starting with "# Category" gives the category name
  (the text inside the last quotes).
- Every other non-empty line is: english,myanmar,chinese

Skips words that are already in the database (same english + category),
so you can safely re-run it when you add new data / new files.

Usage:
    python3 import_tocei_md.py                     # default folder + db
    python3 import_tocei_md.py <md_folder>         # change md folder
    python3 import_tocei_md.py <md_folder> <db>    # change folder + db
"""

import os
import re
import sqlite3
import sys

# ===== Change these defaults if you want =====
MD_FOLDER = "data/tocei"
DB_FILE = "vocabulary.db"


def get_category(line):
    """Extract the category name from the '# Category ...' header line."""
    # e.g. # Category "TOCEI" change to "TOCEI-Banking&Finance"
    quotes = re.findall(r'"([^"]+)"', line)
    if quotes:
        # Use the text in the LAST pair of quotes (after "change to")
        return quotes[-1].strip()
    # Fallback: text after "change to"
    m = re.search(r"change\s+to\s+(.+)$", line, re.IGNORECASE)
    return m.group(1).strip() if m else None


def parse_md_file(path):
    """Return (category, rows) where rows = [(english, myanmar, chinese), ...]."""
    category = None
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                if "category" in line.lower():
                    cat = get_category(line)
                    if cat:
                        category = cat
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue  # not a valid data line
            english = parts[0].strip()
            myanmar = parts[1].strip()
            chinese = ",".join(parts[2:]).strip() if len(parts) > 2 else ""
            if english and myanmar:
                rows.append((english, myanmar, chinese))
    return category, rows


def word_exists(cur, english, category):
    """Check if this word already exists in the database for this category."""
    cur.execute(
        "SELECT 1 FROM words WHERE lower(english) = lower(?) AND category = ? LIMIT 1",
        (english, category),
    )
    return cur.fetchone() is not None


def import_folder(md_folder, db_file):
    md_folder = os.path.abspath(md_folder)
    if not os.path.isdir(md_folder):
        print(f"Error: folder not found: {md_folder}")
        return

    con = sqlite3.connect(db_file)
    cur = con.cursor()
    # Make sure the table exists (same schema as vocabulary.db)
    cur.execute(
        """CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT NOT NULL,
            chinese TEXT DEFAULT '',
            myanmar TEXT NOT NULL,
            category TEXT DEFAULT 'TOEIC'
        )"""
    )

    total_new = total_skip = total_bad = 0

    md_files = sorted(
        f for f in os.listdir(md_folder) if f.lower().endswith(".md")
    )
    if not md_files:
        print(f"No .md files found in {md_folder}")
        con.close()
        return

    for name in md_files:
        path = os.path.join(md_folder, name)
        category, rows = parse_md_file(path)
        if category is None:
            category = os.path.splitext(name)[0]
            print(f"  [warn] no '# Category' header in {name}, using '{category}'")

        added = skipped = bad = 0
        for english, myanmar, chinese in rows:
            if word_exists(cur, english, category):
                skipped += 1
                continue
            cur.execute(
                "INSERT INTO words (english, chinese, myanmar, category) VALUES (?, ?, ?, ?)",
                (english, chinese, myanmar, category),
            )
            added += 1

        total_new += added
        total_skip += skipped
        total_bad += bad
        print(f"{name}  [category: {category}]  added={added}  skipped(existing)={skipped}")

    con.commit()
    con.close()
    print(f"\nDone. New words added: {total_new}, already in DB (skipped): {total_skip}")


def main():
    md_folder = sys.argv[1] if len(sys.argv) > 1 else MD_FOLDER
    db_file = sys.argv[2] if len(sys.argv) > 2 else DB_FILE
    print(f"MD folder : {md_folder}")
    print(f"Database  : {db_file}\n")
    import_folder(md_folder, db_file)


if __name__ == "__main__":
    main()
