# Chinese character breakdown (တစ်လုံးချင်း အဓိပ္ပာယ်) — implementation plan

Source request: [feature.md](feature.md). Created 2026-11-16.

> Historical spec. Written before the Android port was removed; references to
> `main.py`, APK builds, and "ship the DB in the APK" are outdated — the app
> is desktop-only now. Current behavior: see `AGENTS.md`.

## 1. What the feature asks for

For a Chinese entry, break it into individual characters and show the meaning of each
character, in addition to the meaning of the whole entry:

- 成績 (chéngjì) → whole word meaning **အောင်မြင်မှု**
  - 成 (chéng) → completed, finished, fixed → ပြည့်စုံသော, ပြီး [သော], ပုံသေ
  - 績 (jì) → spin; achievements → လှည့်သည်, အောင်မြင်မှု
- If an entry cannot (or should not) be split, keep it as one unit.
- Store the per-character data in the database in its own columns.
- In the UI, tapping the Chinese text must lead to the character-by-character view.
- Every character must carry a meaningful Myanmar meaning.

## 2. Current state (verified facts)

| Area | Current behaviour |
| --- | --- |
| Table | `words(id, english, chinese, myanmar, category, sound)`; `PRAGMA user_version=3` |
| Chinese value | One string, `"Traditional (pinyin)"`, e.g. `成績 (chéngjì)`; alternatives separated by `,` / `，` (44 rows) |
| Dataset | 1139 rows, all with Chinese: 1125 multi-hanzi entries, 14 single-hanzi entries, 1,212 unique hanzi, 4,768 hanzi occurrences, longest entry 11 characters |
| Normalization | `normalize_chinese_entry()` / `_normalize_single_chinese()` (`vocapp.py:221-253`) already split off pinyin with a regex and convert Simplified → Traditional |
| UI | `QTreeWidget` columns `(id, english, chinese, category, myanmar, sound)` (`vocapp.py:831`); Chinese cell is column index **2** |
| Click handling | `_on_item_clicked()` (`vocapp.py:1338`) handles **only** the sound column (5); any other cell click is a no-op |
| Migrations | Numbered `_migrate_*()` functions gated by `PRAGMA user_version` (`vocapp.py:455-457`), currently up to 3 |
| Backup | `_db_data_fingerprint()` (`vocapp.py:475`) hashes only `words` columns + sound count |
| Android runtime | No `pypinyin`/`opencc` on device (imports are guarded); `vocabulary.db` is copied from the packaged assets by `main.py`, so **precomputed data ships with the APK** |

Consequence: the pinyin in storage is a single run-on string (`quánshēnshígāoběngdài`),
so per-character pinyin **cannot** be recovered by splitting the stored string; it must be
generated with pypinyin from the hanzi (desktop) and stored per character.

## 3. Key design decisions

### 3.1 Data lives in new tables, not new columns on `words`

Many code paths parse `words.chinese` (search, edit form, exports, `fix_chinese_pinyin.py`).
Changing its format would ripple through all of them. Instead:

- keep `words.chinese` exactly as it is (canonical "Traditional (pinyin)" display string),
- add a per-character table `word_chars` (the actual breakdown, one row per character),
- add a shared dictionary `hanzi` (pinyin + glosses per character, reused across words),
- add `words.breakdown_mode` to record "split" vs "keep whole" per word.

This satisfies "store the data split into columns" while remaining backward compatible.

### 3.2 Definition of "split only if it can be split"

Chinese characters are always mechanically separable, so "cannot split" has to mean
"the breakdown would be misleading". A word is rendered as **one unit** when:

- it is a single character (nothing to split), or
- it is a transliteration / proper noun (`金剛狼` = Wolverine; gold + hard + wolf is wrong), or
- at least one character has no dictionary entry, or
- the characters are bound morphemes (`葡萄` — 葡 and 萄 have no standalone meaning), or
- it is an idiom/loanword where the literal characters do not compose the meaning.

Default is `breakdown_mode='auto'` (split when every character has an entry); the
breakdown dialog offers a “Show as one word” toggle that persists `'whole'`, so
exceptions are curated once and never re-guessed.

### 3.3 Erhua and particles

`藏貓兒 (cángmāor)` ends in an erhua suffix. Splitting it as 兒 = “son/child” would be
wrong. The `hanzi.reading_note` column carries a marker (`erhua`) and the UI shows a note
instead of a misleading gloss. Same treatment for 子/頭/們 when they are suffixes.

## 4. Database changes

New migration `_migrate_chinese_chars(conn)` guarded by `user_version=4`, called from
`init_db()` after `_migrate_sound_column()`:

```sql
CREATE TABLE IF NOT EXISTS hanzi (
    hanzi       TEXT PRIMARY KEY,   -- Traditional, because words.chinese is Traditional
    simplified  TEXT,
    pinyin      TEXT,               -- most common reading(s), tone-marked
    english     TEXT,               -- dictionary glosses, "/" separated
    myanmar     TEXT,               -- curated Burmese glosses
    reading_note TEXT,              -- 'erhua', 'suffix', 'archaic', … (nullable)
    source      TEXT DEFAULT 'cedict',  -- cedict | curated | auto
    updated_at  TEXT
);

CREATE TABLE IF NOT EXISTS word_chars (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id     INTEGER NOT NULL REFERENCES words(id) ON DELETE CASCADE,
    entry_index INTEGER NOT NULL,   -- which comma-separated entry in words.chinese
    position    INTEGER NOT NULL,   -- character position within that entry
    hanzi       TEXT NOT NULL,      -- one character, or the whole entry for 'whole' mode
    pinyin      TEXT,               -- contextual reading inside this word
    english     TEXT,               -- per-character gloss (snapshot from hanzi)
    myanmar     TEXT,               -- per-character Myanmar gloss (curated snapshot)
    note        TEXT,               -- erhua/particle/etc. for this occurrence
    UNIQUE(word_id, entry_index, position)
);

CREATE INDEX IF NOT EXISTS idx_word_chars_word ON word_chars(word_id);

ALTER TABLE words ADD COLUMN breakdown_mode TEXT DEFAULT 'auto';  -- auto | whole
```

Notes:

- `word_chars` snapshots `english`/`myanmar` so a word keeps a stable, reviewable
  breakdown even if the shared `hanzi` entry is later refined; the generator refreshes
  snapshots only for rows whose `source` is not `curated`.
- For `'whole'` mode store exactly one row with the full entry in `hanzi`, so the dialog
  can render a uniform list.
- `_db_data_fingerprint()` must also hash `word_chars` rows and `breakdown_mode`,
  otherwise curating meanings will not trigger a backup refresh.
- Android compatibility: the migration must be import-safe without `pypinyin`
  (guard like `_generate_pinyin()` already does). The shipped database is precomputed on
  desktop, so first install already has all breakdown rows.

## 5. Splitting and pinyin algorithm

`build_chinese_breakdown.py` (desktop, idempotent) and the migration fallback share
`vocapp.split_chinese_entries()`:

1. Split `words.chinese` on `,` / `，` exactly like `normalize_chinese_entry()` (`vocapp.py:245`).
2. For each entry, reuse the pinyin regex (`vocapp.py:227`) to separate
   `core_hanzi` from `(stored_pinyin)`.
3. Extract hanzi with `_HANZI_RE` (`vocapp.py:145`); ignore spaces/punctuation.
4. If `breakdown_mode='whole'` or the core is a single hanzi → one row.
5. Otherwise, one row per code point.
6. Contextual pinyin (desktop only, `pypinyin.pinyin(core, style=Style.TONE)`) gives one
   reading per character and handles polyphones like 行/長 better than per-character calls.
   If pypinyin is unavailable, use `_generate_pinyin(char)` per character, then leave it
   blank if that also fails — never crash.
7. Glosses: look up `hanzi`; optionally fetch and cache MDBG definitions on desktop via
   `lookup_chinese(char)` for characters missing from the shipped dictionary.
8. Write `word_chars` transactionally; recompute only for rows whose input changed
   (compare `(word_id, entry_index, hanzi)` set and stored `pinyin`/`breakdown_mode`).

## 6. Where the meanings come from

### English (automatic, build time)

- Use CC-CEDICT single-character entries (license CC BY-SA 4.0 — add attribution to
  `README.md` and an About note).
- Normalize keys to Traditional (OpenCC `s2tw`, same as the app), keep at most ~4 senses,
  drop classifier-only senses (`CL:…`) and cross-references.
- Store into `hanzi.english`, e.g. `成 → "completed / finished / to succeed"`.

### Myanmar (curated, review required)

This is the only part that cannot be generated reliably. Do **not** ship raw
machine-translated glosses as authoritative:

1. **Seed** from existing data: the 14 single-hanzi rows in `words` already carry
   Myanmar meanings (e.g. 棋 → စစ်တုရင်ကစားနည်း). Import them into `hanzi` as `source='curated'`.
2. **Curate** in `data/hanzi_myanmar.csv`:
   `hanzi,pinyin,myanmar,reading_note`
   The file is committed and merged by the generator; it survives dictionary regeneration.
3. **Optional assist**: a `--suggest-mdbg` mode may query MyOrdbok for the English gloss
   and write results as `source='auto'`. The UI must visibly mark unreviewed entries
   (e.g. a muted “auto” chip) and allow editing in the dialog.
4. **Coverage planning**: the top 100 characters cover 37% of all character occurrences,
   top 300 → 65%, top 500 → 80%. Curating the top ~300 covers most of the library.

### Ship path

All data goes into `vocabulary.db` itself, which is already in the APK
(`assets/private.tar`) and is seeded by `main.py`. No new file extension and no
`buildozer.spec` change are required. No network access is needed at runtime.

## 7. UI changes

### 7.1 Library — tap the Chinese cell

Extend `_on_item_clicked()` (`vocapp.py:1338`):

```python
if column == 2 and item is not None:
    word_id = self._item_word_id(item)
    if word_id:
        self.show_chinese_breakdown(word_id)
    return
```

- Works for mouse click and touch; double-click still opens the editor
  (`vocapp.py:1046`), so the two gestures do not conflict.
- Resolve the word through `_item_word_id()` (`vocapp.py:1113`).

### 7.2 Breakdown dialog — `ChineseBreakdownDialog(QDialog)`

Layout (top → bottom):

1. **Header** — the full entry as displayed in the library (`成績 (chéngjì)`) and the
   entry-level Myanmar meaning from `words.myanmar`, labelled as the word meaning.
2. **Character list** — a scrollable `QScrollArea`; one card per `word_chars` row:
   - large hanzi (28–32 px), contextual pinyin next to it,
   - English glosses,
   - Myanmar glosses (prominent, Myanmar font),
   - optional note (erhua/suffix/archaic).
3. **No rows case** — show `—` and a message “No character breakdown for this word”.
4. **Whole-mode toggle** — “Show as one word” persists `breakdown_mode`
   (`auto` ↔ `whole`); a “Rebuild breakdown” button reruns the split for this word.
5. **Curation (Myanmar only)** — when a character is tapped, an inline editor lets the
   user fix the Myanmar gloss; saving updates `hanzi`/`word_chars` with `source='curated'`
   and refresh state. This is the practical path to reach full coverage.
6. Mobile sizing: dialog opens maximized-ish on narrow screens, cards get large touch
   targets, text wraps; reuse `resolve_myanmar_font_family()` font so Burmese renders
   with Noto Sans Myanmar.

### 7.3 Editor

- Add a small “字” (or “Breakdown”) button beside the Chinese field
  (`_build_editor()`, `vocapp.py:933-951`) that previews the breakdown for the typed text
  before saving. Use the in-memory parser + `hanzi` cache; no DB writes.
- After `save_word()`/`update_word()`/`add_chinese()` re-run the split for that word so the
  library and editor never disagree.

### 7.4 Housekeeping

- New QSS rules in the stylesheet for the dialog cards and the marked “auto” chip.
- Status bar hint: “Tap the Chinese column to see the character breakdown.”
- Search and quiz remain unchanged; searching a single hanzi already matches because
  `words.chinese` stores the full string (`LIKE '%成%'`).

## 8. Making the Myanmar text meaningful (important)

Per-character glosses are **morpheme glosses**, not word definitions; presenting them
without context can mislead. Rules for the curated data and the dialog:

1. **Two levels, clearly labelled.** Whole-word meaning first (from `words.myanmar`),
   then “စာလုံးလိုက် အဓိပ္ပာယ်” (character by character). Never replace the word meaning
   with the sum of characters.
2. **Modern senses first.** 績 in modern usage = achievement/merit; “spin” is archaic.
   Keep at most one archaic sense, last, marked `(ရှေးဟောင်း)`, or drop it.
3. **Short and idiomatic.** 1–3 senses per character, separated by the Burmese comma
   `၊`; avoid long explanatory clauses that break the mobile layout. Follow the style of
   the request: `ပြည့်စုံသော, ပြီး [သော], ပုံသေ`.
4. **Translate meaning, not words.** Do not transliterate English glosses; write natural
   Burmese (e.g. 東西 as “ပစ္စည်း”, not “အရှေ့အနောက်”).
5. **Context matters.** Always show the contextual pinyin with the character
   (行 xíng “to go” vs háng “row/bank”). For polyphones the dictionary may hold several
   readings, but the dialog shows the reading used by this word.
6. **Do not over-split.** Transliterations, proper nouns, bound morphemes and erhua are
   whole-mode or noted, per §3.2–3.3. A wrong split is worse than no split.
7. **Script hygiene.** All Myanmar data passes through `normalize_myanmar_text()`
   (NFC, strips ZWSP/ZWNJ/ZWJ), use Unicode Burmese only (never Zawgyi), and render with
   the bundled Noto Sans Myanmar — the same rules the word-level meanings follow.
8. **Provenance.** `source='curated'` is displayed as trustworthy; `auto` suggestions are
   visibly marked until reviewed. This keeps the library honest while coverage grows.

## 9. Files to change

| File | Change |
| --- | --- |
| `vocapp.py` | new tables + `user_version=4` migration; `split_chinese_entries()` / `rebuild_word_chars()` helpers; `_db_data_fingerprint()`; `_on_item_clicked()` column 2; `ChineseBreakdownDialog`; editor “Breakdown” button; re-split after save/update/add; QSS |
| `build_chinese_breakdown.py` (new) | desktop generator: CC-CEDICT → `hanzi`, curated CSV merge, breakdown rows, `--db/--cedict/--curated/--suggest-mdbg`, idempotent |
| `data/hanzi_myanmar.csv` (new) | curated Myanmar glosses, committed, merged by the generator |
| `README.md` | document the generator + CC-CEDICT attribution |
| `buildozer.spec` | no change expected (everything lives in `vocabulary.db`) |
| `fix_chinese_pinyin.py` / `import_tocei_md.py` | after normalizing/importing, optionally call the breakdown rebuild so new rows get rows in `word_chars` |

## 10. Implementation order

1. **Schema + migration + backup fingerprint** — tables, `user_version=4`, fingerprint
   update; verify v3→v4 on a copy of the database.
2. **Generator (English only)** — CC-CEDICT import, pinyin per character, `word_chars`
   populated for all 1139 words; verify `whole`/`auto` rules on the known exceptions.
3. **Read-only dialog + click wiring** — tap the Chinese cell to open the breakdown;
   no editing yet.
4. **Myanmar curation** — top ~300 characters first, then the rest; seed + CSV merge;
   review pass against §8.
5. **Curation editing + whole-mode toggle** in the dialog.
6. **Android** — regenerate `vocabulary.db`, rebuild the APK (buildozer), install,
   verify tap → dialog, fonts, and offline behaviour.

## 11. Test cases

- `成績` → 2 characters; 成/績 glosses + word meaning အောင်မြင်မှု.
- `棋` (single) → one row, no misleading split.
- `全身石膏繃帶` (11 chars) → scrollable dialog, alignment and pinyin order correct.
- `貼紙 (tiēzhǐ), 表情包 (biǎoqíngbāo)` → two entry groups in one dialog.
- `藏貓兒` → 兒 marked as erhua, not “son”.
- `金剛狼` → whole-mode; toggle persists.
- `行` inside `銀行` vs `行走` → contextual readings differ.
- Character with no gloss → shows `—` rather than crashing; non-hanzi characters ignored.
- Search still finds words; quiz, exports and sound playback unchanged.
- Android: fresh install seeds the populated DB; no pypinyin/network needed; taps work;
  Myanmar renders with Noto Sans Myanmar.
- Backup fingerprint changes after curating a gloss.

## 12. Open questions

1. Curation scope: start with the top 300 characters (65% coverage) or all 1,212?
2. Should the dialog show Simplified alongside Traditional, or Traditional only
   (consistent with the library)?
3. For 績, keep “spin” as a marked archaic sense, or drop it?
4. Should the per-character meanings be searchable in the library search box
   (e.g. search “အောင်မြင်မှု” finds 成績 via 績)? Recommended: yes, later.
5. Who reviews `source='auto'` suggestions — is the in-dialog editor sufficient?
