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
  python3 build_chinese_breakdown.py --report-myanmar

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
        # curated/note pinyin wins (human-entered); English always comes
        # from the dictionary. Tombstones keep their pinyin too.
        new_pinyin = cur_pinyin if (source in ("curated", "note", "tombstone") and cur_pinyin) \
            else (pinyin or cur_pinyin)
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

    Curated values overwrite everything — this file is the human's word.
    Duplicate rows: the LAST NON-EMPTY row wins (a row with an empty
    gloss AND an empty note is ignored; use "-" to clear a gloss).

    A myanmar cell of "-" is a tombstone (source='tombstone'): it clears
    the gloss and blocks auto-suggestion for that character. Tombstones
    are sticky — deleting the CSV row does not un-tombstone the DB row;
    add a real gloss row to restore one. Note-only rows never wipe an
    existing gloss or pinyin.

    Returns (merged_count, cleared_characters)."""
    if not os.path.isfile(path):
        with open(path, "w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(CURATED_HEADER)
        print("Created empty curated CSV: %s" % path)
        return 0, set()
    # Resolve duplicates first: the last row for a character wins.
    entries = {}
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
            entries[char] = (myanmar, pinyin, note)
    merged = 0
    tombstones = 0
    cleared = set()
    for char, (myanmar, pinyin, note) in entries.items():
        if myanmar == "-":
            # Tombstone: explicit "no gloss", keep pinyin/notes. Only an
            # existing row is tombstoned — creating one for a character
            # unknown to the dictionary would make it count as "known"
            # for word splitting.
            cleared.add(char)
            if conn.execute("SELECT 1 FROM hanzi WHERE hanzi=?", (char,)).fetchone():
                cur = conn.execute(
                    "INSERT INTO hanzi (hanzi, pinyin, myanmar, reading_note, source, updated_at) "
                    "VALUES (?,?,'',?, 'tombstone', ?) "
                    "ON CONFLICT(hanzi) DO UPDATE SET "
                    "pinyin=COALESCE(NULLIF(excluded.pinyin,''), pinyin), "
                    "myanmar='', source='tombstone', "
                    "reading_note=COALESCE(NULLIF(excluded.reading_note,''), reading_note), "
                    "updated_at=excluded.updated_at "
                    "WHERE myanmar != '' OR source != 'tombstone' "
                    "OR COALESCE(NULLIF(excluded.pinyin,''), pinyin) IS NOT pinyin "
                    "OR COALESCE(NULLIF(excluded.reading_note,''), reading_note) "
                    "IS NOT reading_note",
                    (char, pinyin, note, _now()))
                tombstones += cur.rowcount
        elif myanmar:
            cur = conn.execute(
                "INSERT INTO hanzi (hanzi, pinyin, myanmar, reading_note, source, updated_at) "
                "VALUES (?,?,?,?, 'curated', ?) "
                "ON CONFLICT(hanzi) DO UPDATE SET "
                "pinyin=COALESCE(NULLIF(excluded.pinyin,''), pinyin), "
                "myanmar=excluded.myanmar, "
                "reading_note=COALESCE(NULLIF(excluded.reading_note,''), reading_note), "
                "source='curated', updated_at=excluded.updated_at "
                "WHERE myanmar IS NOT excluded.myanmar OR source != 'curated' "
                "OR COALESCE(NULLIF(excluded.pinyin,''), pinyin) IS NOT pinyin "
                "OR COALESCE(NULLIF(excluded.reading_note,''), reading_note) "
                "IS NOT reading_note",
                (char, pinyin, myanmar, note, _now()))
            merged += cur.rowcount
        else:
            # Note-only row: never wipe an existing gloss and never
            # mark the row curated-without-gloss (auto-suggest skips
            # curated rows, which would leave it stuck empty). Like the
            # tombstone branch, only an existing row is touched —
            # inserting one for an unknown character would make it count
            # as "known" for word splitting.
            if conn.execute("SELECT 1 FROM hanzi WHERE hanzi=?", (char,)).fetchone():
                cur = conn.execute(
                    "INSERT INTO hanzi (hanzi, pinyin, reading_note, source, updated_at) "
                    "VALUES (?,?,?, 'note', ?) "
                    "ON CONFLICT(hanzi) DO UPDATE SET "
                    "pinyin=COALESCE(NULLIF(excluded.pinyin,''), pinyin), "
                    "reading_note=COALESCE(NULLIF(excluded.reading_note,''), reading_note), "
                    "source=CASE WHEN COALESCE(myanmar,'')='' AND source='curated' "
                    "THEN 'note' ELSE source END, "
                    "updated_at=excluded.updated_at "
                    "WHERE COALESCE(NULLIF(excluded.pinyin,''), pinyin) IS NOT pinyin "
                    "OR COALESCE(NULLIF(excluded.reading_note,''), reading_note) "
                    "IS NOT reading_note "
                    "OR (source='curated' AND COALESCE(myanmar,'')='')",
                    (char, pinyin, note, _now()))
                merged += cur.rowcount
    conn.commit()
    print("Curated CSV: %d row(s) written, %d tombstone(s) from %s"
          % (merged, tombstones, path))
    return merged, cleared


def seed_from_words(conn, cleared=()):
    """Single-hanzi library words carry human-entered Myanmar meanings —
    import them as curated character glosses (e.g. 棋 → စစ်တုရင်ကစားနည်း).

    Characters tombstoned in the curated CSV are skipped — the explicit
    "no gloss" decision wins over the library meaning."""
    seeded = 0
    for chinese, myanmar in conn.execute("SELECT chinese, myanmar FROM words"):
        entries = vocapp.split_chinese_entries(chinese or "")
        if len(entries) != 1:
            continue
        chars = vocapp._HANZI_RE.findall(entries[0]["core"])
        if len(chars) != 1:
            continue
        myanmar = vocapp.normalize_myanmar_text(myanmar or "")
        char = chars[0]
        if not myanmar or char in cleared:
            continue
        row = conn.execute(
            "SELECT myanmar, source FROM hanzi WHERE hanzi=?", (char,)).fetchone()
        if row is None:
            pinyin = "".join(vocapp._contextual_pinyin(chars))
            conn.execute(
                "INSERT INTO hanzi (hanzi, pinyin, myanmar, source, updated_at) "
                "VALUES (?,?,?, 'curated', ?)", (char, pinyin, myanmar, _now()))
            seeded += 1
        elif row[1] == "tombstone":
            # a DB tombstone stays blank even if its CSV row was deleted
            continue
        elif not row[0] or row[1] == "auto":
            # the library meaning is human-entered — it beats auto suggestions
            conn.execute(
                "UPDATE hanzi SET myanmar=?, source='curated', updated_at=? WHERE hanzi=?",
                (myanmar, _now(), char))
            seeded += 1
    conn.commit()
    print("Seeded %d curated gloss(es) from single-hanzi words" % seeded)


def _translatable_candidates(english):
    """Cleaned-up lookup candidates derived from the English glosses.

    Dictionary glosses like "person; people" or "to go out; to come out"
    are no good as a dictionary query, so split them into single words and
    strip grammatical noise: most specific phrase first."""
    seen = []
    for sense in english.split(" / "):
        for part in re.split(r"[;,]", sense):
            part = re.sub(r"\([^)]*\)", "", part)          # (bound form) …
            part = re.sub(r"~[^ ]*\s*", "", part)          # ~'s, ~ber
            part = re.sub(r"^(to|a|an|the)\s+", "", part.strip())
            part = part.strip(" .…-")
            if len(part) < 2 or not re.fullmatch(r"[A-Za-z' ]+", part):
                continue
            if part.lower() not in seen:
                seen.append(part.lower())
    return seen


def suggest_myanmar(conn, limit, cleared=()):
    """Auto-suggest Myanmar glosses for the most frequent characters.

    Uses MyOrdbok (English -> Myanmar) on the CC-CEDICT gloss. Results are
    stored with source='auto' so the UI marks them as unreviewed.
    Characters tombstoned in the curated CSV are skipped."""
    freq = collections.Counter()
    for (chinese,) in conn.execute("SELECT chinese FROM words WHERE chinese != ''"):
        for entry in vocapp.split_chinese_entries(chinese):
            for char in vocapp._HANZI_RE.findall(entry["core"]):
                freq[char] += 1
    targets = []
    for char, _count in freq.most_common():
        if len(targets) >= limit:
            break
        if char in cleared:
            continue
        row = conn.execute(
            "SELECT myanmar, english, source FROM hanzi WHERE hanzi=?", (char,)).fetchone()
        if row and row[2] not in ("curated", "tombstone") and not row[0] and row[1]:
            targets.append((char, _translatable_candidates(row[1])))
    print("Suggesting Myanmar glosses for %d character(s)…" % len(targets))
    done = failed = 0
    for index, (char, candidates) in enumerate(targets, 1):
        result = None
        for term in candidates:
            result = vocapp.lookup_myanmar(term)
            if result and any("\u1000" <= ch <= "\u109f" for ch in result):
                break
            result = None
        if result:
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


def _snapshot_usage(conn):
    """How many snapshot rows show each single character."""
    usage = collections.Counter()
    for hanzi, count in conn.execute(
            "SELECT hanzi, COUNT(*) FROM word_chars "
            "WHERE LENGTH(hanzi)=1 GROUP BY hanzi"):
        usage[hanzi] = count
    return usage


def _word_frequency(conn):
    """How often each character occurs in the library's Chinese text."""
    freq = collections.Counter()
    for (chinese,) in conn.execute("SELECT chinese FROM words WHERE chinese != ''"):
        for entry in vocapp.split_chinese_entries(chinese):
            for char in vocapp._HANZI_RE.findall(entry["core"]):
                freq[char] += 1
    return freq


def report_myanmar(conn, limit=30, cleared=()):
    """Print the Myanmar-gloss coverage report.

    Section 1: characters with NO gloss that users already see in word
    breakdowns — fixing these changes what is visible today.
    Section 2: auto-suggested glosses waiting for human review, ranked by
    usage (a wrong auto gloss shows in every word using the character).
    Section 3: most frequent characters still without any gloss, ranked
    by word frequency even if no snapshot shows them yet.

    `cleared` holds CSV-tombstoned characters from this run whose hanzi
    row may not exist — they are intentional too and must not be
    reported as missing."""
    limit = max(1, int(limit))
    usage = _snapshot_usage(conn)
    freq = _word_frequency(conn)

    rows = {row[0]: row for row in conn.execute(
        "SELECT hanzi, pinyin, english, myanmar, source FROM hanzi")}
    # Tombstoned characters are intentionally blank — counted, not
    # nagged about. Note rows keep their report entry: they stay
    # eligible for auto-suggestion, so a gloss may still arrive.
    tombstoned = {char for char, row in rows.items() if row[4] == "tombstone"}
    tombstoned.update(cleared)

    print("=" * 64)
    print("Myanmar gloss coverage report")
    print("=" * 64)
    with_mm = sum(1 for r in rows.values() if r[3])
    intentionally = sum(1 for c in tombstoned if c in rows)
    print("hanzi dictionary: %d characters, %d with Myanmar (%d%%), "
          "%d missing (%d intentionally blank)" % (len(rows), with_mm,
                          100 * with_mm // max(len(rows), 1),
                          len(rows) - with_mm, intentionally))

    # Section 1 — missing but visible (including characters unknown to
    # the hanzi dictionary — single-character entries render as one row
    # even when unsplit, showing blank). Tombstones are excluded above;
    # non-CJK leftovers ("A", "_") in word_chars are not translatable.
    visible = [(uses, char) for char, uses in usage.items()
               if char not in tombstoned
               and not (rows.get(char) and rows[char][3])
               and (rows.get(char) is not None or vocapp._HANZI_RE.fullmatch(char))]
    visible.sort(reverse=True)
    print("\n[1] Missing glosses VISIBLE in breakdowns now "
          "(%d characters, ranked by usage):" % len(visible))
    for uses, char in visible[:limit]:
        row = rows.get(char)
        if row is None:
            print("  %s  %-10s uses=%-4d %-8s (not in hanzi dictionary)"
                  % (char, "?", uses, "unknown"))
            continue
        pinyin, english, source = row[1], row[2], row[4]
        print("  %s  %-10s uses=%-4d %-8s %s"
              % (char, pinyin or "?", uses, source, (english or "")[:44]))

    # Whole entries rendered as one unit (transliterations, bound phrases).
    # Their snapshot gloss is looked up as a multi-character key in the
    # hanzi table, which the curated CSV cannot supply (single-hanzi rows
    # only), so these currently cannot be fixed with the tooling below —
    # the word's own translation still shows in the word list.
    whole_missing = [(count, hanzi) for hanzi, count in conn.execute(
        "SELECT hanzi, COUNT(*) FROM word_chars "
        "WHERE LENGTH(hanzi)>1 AND COALESCE(myanmar,'')='' "
        "GROUP BY hanzi ORDER BY COUNT(*) DESC")]
    if whole_missing:
        print("\n    Whole entries with no gloss (%d, top %d) — not "
              "curatable via the character CSV (informational):"
              % (len(whole_missing), min(limit, len(whole_missing))))
        for count, hanzi in whole_missing[:limit]:
            print("  %s  uses=%-4d" % (hanzi, count))

    # Section 2 — auto glosses to review: every auto gloss, ranked by
    # snapshot usage with word frequency as fallback (an auto gloss that
    # is not yet in any snapshot still deserves review)
    auto = []
    for char, row in rows.items():
        if row[4] == "auto" and row[3]:
            auto.append((max(usage.get(char, 0), freq.get(char, 0) // 2),
                         usage.get(char, 0), char))
    auto.sort(reverse=True)
    print("\n[2] Auto-suggested glosses to REVIEW (%d characters):" % len(auto))
    for _score, uses, char in auto[:limit]:
        pinyin, myanmar = rows[char][1], rows[char][3]
        print("  %s  %-10s uses=%-4d current: %s"
              % (char, pinyin or "?", uses, myanmar[:24]))

    # Section 3 — most frequent missing overall, including characters
    # unknown to the hanzi dictionary (they render blank in breakdowns);
    # non-CJK characters are not translatable and are skipped
    freq_missing = [(count, char) for char, count in freq.most_common()
                    if char not in tombstoned
                    and not (rows.get(char) and rows[char][3])
                    and (rows.get(char) is not None
                         or vocapp._HANZI_RE.fullmatch(char))]
    print("\n[3] Most frequent characters still without any gloss "
          "(top %d of %d):" % (min(limit, len(freq_missing)), len(freq_missing)))
    for count, char in freq_missing[:limit]:
        row = rows.get(char)
        if row is None:
            print("  %s  %-10s freq=%-5d %-8s (not in hanzi dictionary)"
                  % (char, "?", count, "unknown"))
            continue
        pinyin, english, source = row[1], row[2], row[4]
        print("  %s  %-10s freq=%-5d %-8s %s"
              % (char, pinyin or "?", count, source, (english or "")[:44]))

    print("\nNext steps:")
    print("  review [2] in the app's breakdown dialog, or add rows to "
          "data/hanzi_myanmar.csv and run --rebuild-only")
    print("  auto-suggest more: python3 %s --suggest-mdbg --suggest-limit N "
          "(already usage-ranked)" % __file__)


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
                        help="recompute word_chars without the CC-CEDICT import "
                             "or online suggestions (curated CSV and library "
                             "seeding still apply)")
    parser.add_argument("--report-myanmar", action="store_true",
                        help="print the Myanmar-gloss coverage report and exit "
                             "(first applies curated CSV edits, library seeding "
                             "and --whole-word, then refreshes snapshots)")
    parser.add_argument("--report-limit", type=int, default=30,
                        help="rows per report section (default: %(default)s)")
    parser.add_argument("--whole-word", action="append", default=[],
                        metavar="ENGLISH",
                        help="mark the word with this English text as 'whole' "
                             "(no split — transliterations, proper nouns); repeatable")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    # Full migration chain (1-6), not just the breakdown tables — a
    # pre-versioned DB must not skip the Myanmar/Chinese migrations.
    # init_db() works on vocapp.DB_FILE, so point it at --db (restoring
    # the original afterwards so later backup paths stay consistent);
    # backup=False stops it from refreshing the real rolling backup with
    # this (possibly scratch) DB.
    original_db = vocapp.DB_FILE
    vocapp.DB_FILE = args.db
    try:
        vocapp.init_db(backup=False)
    finally:
        vocapp.DB_FILE = original_db
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
        # CSV curation + library seeding always apply, so a plain
        # --rebuild-only run also picks up hanzi_myanmar.csv edits.
        _merged, cleared = load_curated(conn, args.curated)
        seed_from_words(conn, cleared)
        if not args.rebuild_only and args.suggest_mdbg:
            suggest_myanmar(conn, args.suggest_limit, cleared)
        if args.report_myanmar:
            # refresh snapshots first, so the report reflects the CSV
            # and whole-word edits made by this very run
            vocapp.rebuild_word_chars(conn)
            conn.commit()
            report_myanmar(conn, limit=args.report_limit, cleared=cleared)
            return
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
