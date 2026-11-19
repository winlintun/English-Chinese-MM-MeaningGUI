# VocApp

VocApp is a small desktop vocabulary manager built with Python and PySide6 (Qt). It is designed for English, Chinese, and Myanmar vocabulary and stores words in a local SQLite database.

## Features

- Add English, Chinese, and Myanmar vocabulary.
- Search words across all three language fields.
- Edit and delete saved vocabulary.
- Add or update a Chinese definition for a selected word.
- Open a quiz window with up to 10 randomly selected words.
- Use Myanmar-compatible fonts when available.
- Package the application as a Windows executable with PyInstaller.
- Pronunciation audio: word sounds are downloaded from MyOrdbok automatically
  when a word is saved (existing words are backfilled at startup) and stored
  inside `vocabulary.db`, so they replay offline. Play them with the
  🔊 buttons in the word list / editor or with `Ctrl+P`.
- Chinese character breakdown: tap the **Chinese** column (or the 字 button in
  the editor) to see the meaning of each character next to the meaning of the
  whole word — e.g. 成績 (chéngjì) → 成 (chéng) "to complete" → ပြည့်စုံသော … +
  績 (jì) "achievement" → အောင်မြင်မှု. Words that should not be split
  (transliterations, erhua like 藏貓兒) are kept whole; the dialog's
  "Show as one word" toggle remembers that choice per word. Myanmar meanings
  can be fixed per character right in the dialog.

## Requirements

- Windows or Linux with a desktop session
- Python 3.10 or newer
- Packages listed in `requirements.txt` (`PySide6`, plus optional `opencc`, `pypinyin`, `openpyxl`)

The database, exports and font handling use the Python standard library (`sqlite3`, `os`, `unicodedata`).

## Installation

Open PowerShell in the project directory:

```powershell
cd C:\Users\%username%\Desktop\VocApp
py -m venv env
.\env\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, run the application with the virtual-environment interpreter directly:

```powershell
.\env\Scripts\python.exe vocapp.py
```

## Run

With the virtual environment activated:

```powershell
python vocapp.py
```

On first launch, the application creates the `words` table in the SQLite database automatically.

## Linux Desktop Shortcut

Create the virtualenv first (the menu entry runs the app through it):

```bash
python3 -m venv .env
.env/bin/python -m pip install -r requirements.txt
```

Then add VocApp to the applications menu (with its icon):

```bash
./install-desktop.sh
```

The menu entry starts `vocapp.py` from this repository using the local `.env`
virtualenv. That means new features are available the next time you launch it
after `git pull` or an edit — there is nothing to rebuild. Only re-run
`.env/bin/python -m pip install -r requirements.txt` when `requirements.txt`
changes, and re-run `./install-desktop.sh` if you move the repository.

Remove the menu entry with:

```bash
./install-desktop.sh --uninstall
```

## Using VocApp

1. Enter English and Myanmar text. Chinese is optional.
2. Select **Save Word** to add the vocabulary.
3. Use the search field to filter the vocabulary table.
4. Select a row and choose **Edit Selected** to update it.
5. Choose **Cancel Edit** to leave edit mode without saving changes.
6. Choose **Delete Selected** to remove selected words.
7. Choose **Add Chinese to Selected** to add a Chinese definition to the selected row.
8. Choose **Open Quiz**, then **Refresh Items** to display a new random set of up to 10 words.

## Database Location

`vocabulary.db` lives next to `vocapp.py` (or next to the executable in a PyInstaller build). It is created automatically on first start, so there is nothing to configure. This project commits the database to Git on purpose — it holds your curated vocabulary; commit a checkpointed copy (quit the app first so `-wal` transactions are folded in).

## Myanmar Fonts

VocApp first checks for an installed Myanmar-compatible font. If one is not available, it registers a bundled `.ttf` from the `fonts/` folder (the static Noto Sans Myanmar Regular; variable fonts are skipped). Keep `fonts/` beside `vocapp.py`, and ship it inside PyInstaller builds (`--add-data "fonts;fonts"`) so PDF export can use it too.

## Build a Windows Executable

Install PyInstaller in the active environment if needed:

```powershell
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name VocabApp --add-data "fonts;fonts" --add-data "assets;assets" vocapp.py
```

No spec file is tracked in the repo — build directly with the command above (add more `--add-data` entries as needed; on Linux/macOS use `:` instead of `;` as the separator). The executable is created in the `dist` directory; `vocapp.py` reads bundled fonts and the window icon from `sys._MEIPASS` and keeps `vocabulary.db` beside the executable.

## The Chinese Character Breakdown (build-time data)

The per-character data (pinyin, English glosses, Myanmar glosses) is precomputed
and stored inside `vocabulary.db` (tables `hanzi` and `word_chars`). To
regenerate it:

```bash
# 1. Download CC-CEDICT once (about 5 MB)
curl -L -o cedict.txt.gz \
  "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz"
gunzip cedict.txt.gz

# 2. Import the dictionary + curated glosses and rebuild the breakdown rows
python3 build_chinese_breakdown.py --cedict cedict.txt

# 3. Optional: auto-suggest Myanmar glosses from the local Ornagai dictionary
#    (offline, instant). Results are marked "auto" in the UI until reviewed.
#    Without ornagai.db, the online MyOrdbok suggester still works:
#    --suggest-mdbg --suggest-limit 300
python3 build_chinese_breakdown.py --suggest-ornagai --suggest-limit 300
python3 build_chinese_breakdown.py --suggest-ornagai --resuggest  # redo source='auto'

# 4. Only recompute the breakdown rows (after editing data/hanzi_myanmar.csv)
python3 build_chinese_breakdown.py --rebuild-only
```

- **Local English→Myanmar dictionary (`ornagai.db`)** — optional, not
  committed (56 MB third-party export). Put it next to `vocapp.py` or point
  `VOCAPP_ORNAGAI_DB` / `--ornagai PATH` at it. When present:
  - `lookup_myanmar()` (the app's auto-fill) answers offline first, then
    falls back to MyOrdbok; no network delay, no Cloudflare blocks.
  - `--suggest-ornagai` fills character glosses from CC-CEDICT's English
    glosses. It skips curated/tombstoned rows, prefers ordinary senses over
    capitalised names, and stores the result as `source='auto'`
    (reviewable in the UI). `--resuggest` regenerates every existing auto row
    (ignoring `--suggest-limit`) and clears auto glosses the dictionary cannot
    back any more; curated rows are still untouched.
  - Data shape: `entries(id, headword, headword_lc)` →
    `senses(entry_id, sense_no, pos, pron_my, definition_my)` →
    `examples(text_en)`.

- `data/hanzi_myanmar.csv` (`hanzi,pinyin,myanmar,reading_note`) holds the
  human-curated Myanmar glosses; curated rows are never overwritten by
  generated data. `reading_note` marks special cases such as
  `erhua — နောက်ဆက် "-r" အသံ`.
- Special `myanmar` cells in the CSV:
  - `-` — tombstone: the character is intentionally gloss-less. It clears
    the gloss, blocks auto-suggestion, and is sticky (deleting the CSV row
    does not restore auto-suggestion; add a real gloss row to undo).
  - empty with a `reading_note` — note-only row: never wipes an existing
    gloss or pinyin; the character stays eligible for auto-suggestion.
  - duplicate rows: the LAST NON-EMPTY row wins (a row with an empty
    gloss AND an empty note is ignored; use `-` to clear a gloss).
- `python3 build_chinese_breakdown.py --report-myanmar [--report-limit N]`
  prints the Myanmar-gloss coverage report: [1] missing-but-visible
  characters ranked by usage, [2] auto glosses awaiting review, [3] most
  frequent missing characters. It first applies CSV edits and refreshes
  snapshots, so it always reflects the current curated file.
- Words that must not be split can be fixed permanently with
  `--whole-word "english text"` (repeatable), or per word in the dialog.

### CC-CEDICT attribution

English per-character glosses are derived from
[CC-CEDICT](https://www.mdbg.net/chinese/dictionary), edited by MDBG,
licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
Myanmar glosses are original content of this project.

## Project Files

```text
vocapp.py                     Main PySide6 application
build_chinese_breakdown.py    Generator for the per-character data
install-desktop.sh            Linux applications-menu entry (install/uninstall)
data/hanzi_myanmar.csv        Curated Myanmar glosses per character
requirements.txt              Python package requirements
assets/icon.png               Application icon
fonts/                        Optional Myanmar font files
vocabulary.db                 Local database created at runtime
```

## Notes

- The database path follows the application folder; `DB_FILE` can be reassigned before `init_db()` when embedding or testing.
- `build/`, `dist/`, `env/`, `.env/` and Python cache files are ignored by Git.
