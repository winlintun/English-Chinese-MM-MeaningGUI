# Report: Nov 2026 fix pass — VocApp

**Project:** English-Chinese-MM-MeaningGUI (VocApp, `vocapp.py`, PySide6 6.12)
**Base revision:** `c91302e`
**Date:** 2026-11-04
**Companion:** `report-font.md` (Myanmar font analysis)

---

## 1. What I checked, and how

| Check | Result |
|---|---|
| Installed Myanmar fonts | `Noto Sans Myanmar` and `Noto Sans Myanmar UI` are installed — GUI text renders |
| `resolve_myanmar_font_family()` | returns `Noto Sans Myanmar`; bundled fallback resolves to `fonts/Noto_Sans_Myanmar/static/NotoSansMyanmar-Regular.ttf` |
| PDF export font | **before:** only `NotoSansMyanmar-Regular` embedded, headings fell back to Arimo. **after:** `NotoSansMyanmar-Regular` **and** `NotoSansMyanmar-Bold` embedded |
| PDF rendering | rendered pages at 150 dpi and inspected them; Myanmar, Chinese and English all draw after the fix |
| Save → edit → update → cancel → save cycle | OK (no regression) |
| All export formats (`.csv .xlsx .md .pdf`) | OK, including `<>&"|` and Myanmar in cells |
| `pyflakes vocapp.py` | clean before and after |

Headless test command used (offscreen Qt):

```bash
cd ~/Desktop/English-Chinese-MM-MeaningGUI
QT_QPA_PLATFORM=offscreen .env/bin/python - <<'EOF'
from PySide6.QtWidgets import QApplication
app = QApplication([])
import vocapp
vocapp.DB_FILE = "/tmp/vocab_copy.db"   # never point at the real DB in tests
EOF
```

---

## 2. Fixes made

### F1 — PDF export ignored the Myanmar font (report-font.md §6.1) — `vocapp.py` `export_pdf`, line 609

- **Symptom:** exported PDFs could show empty boxes / wrong glyphs for Myanmar although the GUI was correct.
- **Root cause:** the HTML built for `QTextDocument` never named a font, and the document used Qt's default font. Qt shaped Myanmar with whatever family was enabled, so output changed with system Qt settings and weight fallback.
- **Fix:** resolve the family once and apply it in two places — the `body{font-family:…}` CSS rule and `document.setDefaultFont(QFont(font_family, 10))`.
- **Verified:** re-exported the same rows; both `NotoSansMyanmar-Regular` and `NotoSansMyanmar-Bold` are embedded and bold headings now render in Myanmar-capable bold (previously `Arimo-Bold`).

### F2 — Variable font was a registration candidate (§6.3) — `_find_local_noto_font`, line 73

- **Symptom (latent):** on machines without an installed Myanmar font, Qt could register `NotoSansMyanmar-VariableFont_wdth,wght.ttf` and expose it under odd weights (e.g. "Noto Sans Myanmar Medium"), giving inconsistent bold/regular rendering.
- **Root cause:** the directory walk's first rule matched `"sans"` + `"regular"`, which the variable file's name satisfies.
- **Fix:** the walk now skips any file with `variablefont` in its name; static `…Regular.ttf` is always chosen first.
- **Verified:** `_find_local_noto_font()` → `…/static/NotoSansMyanmar-Regular.ttf`.

### F3 — Bundled fonts lost in packaged builds (§6.4) — constants at line 25

- **Symptom:** a PyInstaller onefile build looked for `fonts/` beside the source and found nothing, so the fallback font never loaded.
- **Fix:** `BUNDLE_DIR = sys._MEIPASS or <source dir>`; `FONT_DIR` is built from it.
- **Deliberately not changed:** `DB_FILE` still resolves beside the *executable* (`sys.executable` when frozen). Putting it in `_MEIPASS` would delete the user's vocabulary on every launch — I tried that first and reverted it.

### F4 — Search box treated `%` and `_` as wildcards — `_current_rows`, line 1181

- **Symptom:** typing `%` in the search box returned **no** rows; typing `_` returned **every** row.
- **Root cause:** the term went into `LIKE '%term%'` unescaped, so `%` stayed a wildcard and `_` matched any single character. A word literally containing `%` (e.g. "50% off") could not be found.
- **Fix:** a `like_pattern()` helper escapes `\`, `%` and `_`, and every `LIKE` (English, Myanmar, category, both Chinese variants) uses `ESCAPE '\'`.
- **Verified:** `50%` → 1 row ("50% off"); `_` → only rows containing `_`; `%` → 1; `testA` still matches `testA2`. Values are still parameters (no SQL injection).

### F5 — PDF cells dropped line breaks and rendered empty cells as nothing — same function

- **Symptom:** a multi-line value collapsed to one line; empty cells had a visually different height.
- **Fix:** lines are escaped and joined with `<br />`; empty values render `&nbsp;`.
- **Verified:** a two-line English value wraps inside one cell; `<b>tag</b>` stays literal text (no HTML injection).

### F6 — PDF table misaligned with 1000+ rows — same function

- **Symptom:** the ID column widened to the widest ID anywhere in the document (Qt `fixed` table layout), clipping the header and squeezing other columns.
- **Fix:** `th:first-child,td:first-child{width:6%;white-space:nowrap;}`.
- **Verified:** 120-row export, page 2 — ID column narrow, headers aligned.

### F7 — `.gitignore` hid the font folder — `.gitignore`

- **Symptom:** `fonts` plus Windows-style `fonts\Noto_Sans_Myanmar` patterns. The fonts are already tracked, but the patterns would hide *new* font files (and their `OFL.txt` licence file) from `git status`, so a fresh clone could ship without the fallback font.
- **Fix:** removed the three `fonts*` lines; `.env/`, `env/`, `build`, `dist`, `*.spec`, caches stay ignored. Line endings kept CRLF.

### F8 — README described the wrong stack — `README.md`

- Said "built with Python and Tkinter" and listed `tkinter` requirements; the app is PySide6.
- Said the database path is hard-coded to `C:\Users\%username%\Desktop\VocApp` and must be edited in `vocapp.py`; it is derived from the app folder.
- Said the DB is ignored by Git (it is not) and that fonts must sit beside the executable (they must be bundled via `--add-data "fonts;fonts"`).
- All four sections rewritten. Line endings kept CRLF.

---

## 3. Checked and found NOT to be bugs

| Suspect | Verdict |
|---|---|
| Zawgyi input (§6.2) | No Zawgyi text in the DB; conversion needs a third-party package, so left as a documented optional improvement, not a fix |
| `%`-formatting in `export_pdf` | safe — no user text goes through `%` formatting |
| Sort column in `ORDER BY` | built from the fixed `tree_columns` tuple, not user input |
| Export with no file extension | falls back to the selected filter correctly (`out_nofilter` → `out_nofilter.pdf`) |
| CSV Excel compatibility | UTF-8 **with BOM** as intended |
| `normalize_myanmar_text` stripping ZWJ (U+200D) | correct for Unicode Burmese; ZWJ only matters for Zawgyi |
| Save / edit / update / cancel state machine | behaves correctly |

### Known but out of scope

- UI text is in English while the project targets Myanmar users.
- `_http_get` (merriam/mdbg lookups) has no retry; a slow site just returns nothing.
- No automated tests exist; the checks above were run manually.

---

## 4. Remaining recommendation

Bundle **only the static Regular/Bold** Noto Sans Myanmar in `fonts/` for the shipped build. The folder is currently 7.7 MB, mostly the variable font and 9-width × 9-weight static family, and the app only ever registers the Regular. Removing the rest shrinks the PyInstaller package and the repository.

---

## 5. Files changed

| File | Change |
|---|---|
| `vocapp.py` | F1–F6 |
| `.gitignore` | F7 |
| `README.md` | F8 |

Uncommitted: run `git diff` in `~/Desktop/English-Chinese-MM-MeaningGUI` to review.
