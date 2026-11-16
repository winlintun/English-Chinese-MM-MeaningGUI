#!/usr/bin/env python3
"""Precompute the per-character Chinese breakdown (feature-do.md).

Steps (all idempotent — rerunning only refreshes what changed):
  1. import CC-CEDICT single-character entries into the shared `hanzi` table
     (English glosses, tone-marked pinyin, simplified form)
  2. merge curated Myanmar glosses from data/hanzi_myanmar.csv
     (curated rows are never overwritten by generated data)
  3. seed hanzi.myanmar from the single-hanzi words of the library
  4. optionally suggest Myanmar glosses via MyOrdbok (--suggest-mdbg);
     results are stored as source='auto' and marked "auto" in the UI until
     reviewed
  5. (re)build word_chars for every word of the library

Usage:
  python3 build_chinese_breakdown.py --cedict cedict_1_0_ts_utf-8_mdbg.txt
  python3 build_chinese_breakdown.py --cedict ... --suggest-mdbg --suggest-limit 300
  python3 build_chinese_breakdown.py --rebuild-only

CC-CEDICT is licensed CC BY-SA 4.0 (https://www.mdbg.net/chinese/dictionary) —
see README.md for the attribution note.
"""
import argparse
import collections
import csv
import datetime
import os
import re
import sqlite3
import sys
import time

import vocapp

DEFAULT_CURATED = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "data", "hanzi_myanmar.csv")
CURATED_HEADER = ("hanzi", "pinyin", "myanmar", "reading_note")

# 中國 中国 [Zhong1 guo2] /China/Middle Kingdom/
CEDICT_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.+)$")
CEDICT_URL = ("https://www.mdbg.net/chinese/export/cedict/"
              "cedict_1_0_ts_utf-8_mdbg.txt.gz")

# gloss segments that never help a learner
_GLOSS_DROP = ("CL:", "see ", "old variant of", "variant of", "abbr. for", "abbr.")
# senses pushed to the end of the gloss list (noise, not meaning)
_SECONDARY = ("surname", "short name for", "old name for")
MAX_SENSES = 4


def _clean_pinyin(raw):
    """CC-CEDICT writes tone numbers ('cheng2') and ü as 'u:' — normalize to
    tone-marked pinyin ('chéng', 'nǚ')."""
    raw = raw.replace("u:", "ü").replace("U:", "Ü").strip()
    try:
        from pypinyin.contrib.tone_convert import to_tone
    except ImportError:
        return raw
    return to_tone(raw)


def _now():
    return datetime.datetime.now().isoformat(timespec="seconds")


def parse_cedict(path):
    """Single-character CC-CEDICT entries: char -> (simplified, pinyin, english)."""
    pinyins = collections.defaultdict(set)
    glosses = collections.defaultdict(list)
    simplified = {}
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = CEDICT_RE.match(line)
            if not match:
                continue
            trad, simp, pinyin_raw, gloss_blob = match.groups()
            if not vocapp._HANZI_RE.fullmatch(trad):
                continue
            cleaned = [g.strip() for g in gloss_blob.split("/") if g.strip()]
            # drop embedded cross-reference syllables and inline classifier notes
            cleaned = [re.sub(r"\[[^\]]*\]", "", g) for g in cleaned]
            cleaned = [re.sub(r"\(CL:[^)]*\)", "", g).strip() for g in cleaned]
            cleaned = [g for g in cleaned if g and not g.startswith(_GLOSS_DROP)
                       and not g.startswith("Taiwan pr.")]
            # modern senses first — reference/surname senses go last
            primary = [g for g in cleaned
                       if not g.lower().startswith(_SECONDARY)]
            secondary = [g for g in cleaned
                         if g.lower().startswith(_SECONDARY)]
            cleaned = primary + secondary
            if not cleaned:
                continue
            simplified[trad] = simp if simp != trad else ""
            for reading in re.split(r"[,，]", pinyin_raw.replace("u:", "ü").replace("U:", "Ü")):
                reading = _clean_pinyin(reading)
                if reading:
                    pinyins[trad].add(reading)
            for gloss in cleaned[:MAX_SENSES]:
                if gloss not in glosses[trad]:
                    glosses[trad].append(gloss)
    result = {}
    for char in simplified:
        primary = [g for g in glosses[char] if not g.lower().startswith(_SECONDARY)]
        secondary = [g for g in glosses[char] if g.lower().startswith(_SECONDARY)]
        result[char] = (
            simplified[char],
            " / ".join(sorted(pinyins[char])),
            " / ".join((primary[:MAX_SENSES] + secondary[:2])),
        )
    return result


def import_cedict(conn, path):
    entries = parse_cedict(path)
    updated = inserted = 0
    for char, (simp, pinyin, english) in entries.items():
        row = conn.execute(
            "SELECT simplified, pinyin, english, myanmar, source FROM hanzi WHERE hanzi=?",
            (char,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO hanzi (hanzi, simplified, pinyin, english, source, updated_at) "
                "VALUES (?,?,?,?, 'cedict', ?)", (char, simp, pinyin, english, _now()))
            inserted += 1
            continue
        _simp, cur_pinyin, cur_english, _mm, source = row
        # a curated pinyin wins; English always comes from the dictionary
        new_pinyin = cur_pinyin if (source == "curated" and cur_pinyin) else (pinyin or cur_pinyin)
        new_english = english or cur_english
        if (new_pinyin, new_english) != (cur_pinyin, cur_english):
            conn.execute(
                "UPDATE hanzi SET simplified=?, pinyin=?, english=?, updated_at=? WHERE hanzi=?",
                (simp, new_pinyin, new_english, _now(), char))
            updated += 1
    conn.commit()
    print("CC-CEDICT: %d characters imported (%d new, %d updated)"
          % (len(entries), inserted, updated))


def load_curated(conn, path):
    """Merge data/hanzi_myanmar.csv (hanzi,pinyin,myanmar,reading_note).

    Curated values overwrite everything — this file is the human's word."""
    if not os.path.isfile(path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(CURATED_HEADER)
        print("Created empty curated CSV: %s" % path)
        return 0
    merged = 0
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            char = (row.get("hanzi") or "").strip()
            myanmar = vocapp.normalize_myanmar_text(row.get("myanmar") or "")
            pinyin = (row.get("pinyin") or "").strip()
            note = (row.get("reading_note") or "").strip()
            if not char or not vocapp._HANZI_RE.fullmatch(char):
                continue
            if not myanmar and not note:
                continue
            conn.execute(
                "INSERT INTO hanzi (hanzi, pinyin, myanmar, reading_note, source, updated_at) "
                "VALUES (?,?,?,?, 'curated', ?) "
                "ON CONFLICT(hanzi) DO UPDATE SET pinyin=excluded.pinyin, "
                "myanmar=excluded.myanmar, reading_note=excluded.reading_note, "
                "source='curated', updated_at=excluded.updated_at",
                (char, pinyin, myanmar, note, _now()))
            merged += 1
    conn.commit()
    print("Curated CSV: %d row(s) merged from %s" % (merged, path))


def seed_from_words(conn):
    """Single-hanzi library words carry human-entered Myanmar meanings —
    import them as curated character glosses (e.g. 棋 → စစ်တုရင်ကစားနည်း)."""
    seeded = 0
    for chinese, myanmar in conn.execute("SELECT chinese, myanmar FROM words"):
        entries = vocapp.split_chinese_entries(chinese or "")
        if len(entries) != 1:
            continue
        chars = vocapp._HANZI_RE.findall(entries[0]["core"])
        if len(chars) != 1:
            continue
        myanmar = vocapp.normalize_myanmar_text(myanmar or "")
        if not myanmar:
            continue
        char = chars[0]
        row = conn.execute(
            "SELECT myanmar, source FROM hanzi WHERE hanzi=?", (char,)).fetchone()
        if row is None:
            pinyin = "".join(vocapp._contextual_pinyin(chars))
            conn.execute(
                "INSERT INTO hanzi (hanzi, pinyin, myanmar, source, updated_at) "
                "VALUES (?,?,?, 'curated', ?)", (char, pinyin, myanmar, _now()))
            seeded += 1
        elif not row[0] or row[1] == "auto":
            # the library meaning is human-entered — it beats auto suggestions
            conn.execute(
                "UPDATE hanzi SET myanmar=?, source='curated', updated_at=? WHERE hanzi=?",
                (myanmar, _now(), char))
            seeded += 1
    conn.commit()
    print("Seeded %d curated gloss(es) from single-hanzi words" % seeded)


def _translatable_term(english):
    """First English sense, cleaned up for the dictionary lookup."""
    term = english.split(" / ")[0]
    term = re.sub(r"\([^)]*\)", "", term)
    term = re.sub(r"^(to|a|an|the)\s+", "", term.strip())
    return term.strip()


def suggest_myanmar(conn, limit):
    """Auto-suggest Myanmar glosses for the most frequent characters.

    Uses MyOrdbok (English -> Myanmar) on the CC-CEDICT gloss. Results are
    stored with source='auto' so the UI marks them as unreviewed."""
    freq = collections.Counter()
    for (chinese,) in conn.execute("SELECT chinese FROM words WHERE chinese != ''"):
        for entry in vocapp.split_chinese_entries(chinese):
            for char in vocapp._HANZI_RE.findall(entry["core"]):
                freq[char] += 1
    targets = []
    for char, _count in freq.most_common():
        if len(targets) >= limit:
            break
        row = conn.execute(
            "SELECT myanmar, english, source FROM hanzi WHERE hanzi=?", (char,)).fetchone()
        if row and row[2] != "curated" and not row[0] and row[1]:
            targets.append((char, _translatable_term(row[1])))
    print("Suggesting Myanmar glosses for %d character(s)…" % len(targets))
    done = failed = 0
    for index, (char, term) in enumerate(targets, 1):
        result = vocapp.lookup_myanmar(term)
        if result and any("\u1000" <= ch <= "\u109f" for ch in result):
            conn.execute(
                "UPDATE hanzi SET myanmar=?, source='auto', updated_at=? WHERE hanzi=?",
                (vocapp.normalize_myanmar_text(result), _now(), char))
            done += 1
        else:
            failed += 1
        if index % 25 == 0:
            conn.commit()
            print("  %d/%d done (%d translated, %d missed)" % (index, len(targets), done, failed))
        time.sleep(vocapp.SOUND_RETRY_DELAY)
    conn.commit()
    print("Suggestions finished: %d translated, %d missed" % (done, failed))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default=vocapp.DB_FILE, help="database file")
    parser.add_argument("--cedict", help="path to the CC-CEDICT .txt file")
    parser.add_argument("--curated", default=DEFAULT_CURATED,
                        help="curated Myanmar gloss CSV (default: %(default)s)")
    parser.add_argument("--suggest-mdbg", action="store_true",
                        help="auto-suggest Myanmar glosses via MyOrdbok (online, slow)")
    parser.add_argument("--suggest-limit", type=int, default=300,
                        help="how many characters to suggest (default: %(default)s)")
    parser.add_argument("--rebuild-only", action="store_true",
                        help="only recompute word_chars, skip the dictionary steps")
    parser.add_argument("--whole-word", action="append", default=[],
                        metavar="ENGLISH",
                        help="mark the word with this English text as 'whole' "
                             "(no split — transliterations, proper nouns); repeatable")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    vocapp._migrate_chinese_chars(conn)
    conn.commit()
    try:
        for english in args.whole_word:
            n = conn.execute(
                "UPDATE words SET breakdown_mode='whole' WHERE english=? COLLATE NOCASE",
                (english,)).rowcount
            conn.commit()
            print("whole-mode set for %d word(s) matching %r" % (n, english))
        if not args.rebuild_only:
            if args.cedict:
                import_cedict(conn, args.cedict)
            else:
                print("No --cedict given — skipping the dictionary import")
            load_curated(conn, args.curated)
            seed_from_words(conn)
            if args.suggest_mdbg:
                suggest_myanmar(conn, args.suggest_limit)
        changed = vocapp.rebuild_word_chars(conn)
        conn.commit()
        print("word_chars rebuilt for %d word(s)" % changed)
        stats = conn.execute(
            "SELECT COUNT(*), SUM(myanmar != ''), SUM(english != '') FROM hanzi"
        ).fetchone()
        print("hanzi dictionary: %d characters (%d with Myanmar, %d with English)"
              % (stats[0], stats[1] or 0, stats[2] or 0))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
