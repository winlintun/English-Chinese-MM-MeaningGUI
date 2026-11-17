# AGENTS.md — VocApp

English–Chinese–Myanmar vocabulary manager. Single-file PySide6 desktop app (`vocapp.py`).

## Team Workflow

You are the main implementer in a 3-agent team. Two CLI agents are available
in this environment: `agy` (Antigravity CLI, planner) and `qodercli` (reviewer).
Both are installed and authenticated.

## Workflow for every task

1. **PLAN (agy):** Before writing ANY code, run:
   agy -p "Create an implementation plan for this task: <task>.
   Output the plan as a numbered step list with exact files to create/modify.
   Do not write code, only plan." --mode plan > /tmp/agy-plan.md
   Read /tmp/agy-plan.md and follow it strictly.

2. **IMPLEMENT (you):** Write the code according to the plan.

3. **REVIEW (qodercli):** After implementing, run:
   qodercli -p "Review the current uncommitted git diff for bugs,
   security vulnerabilities, and performance issues.
   List each issue with file, line, severity, and fix suggestion.
   If no issues, output exactly: LGTM" > /tmp/qoder-review.md
   (Use qodercli's headless/script mode flags — check `qodercli --help`.)

4. **FIX LOOP:** If the review is not "LGTM":
   a. Run agy again for a fix plan:
      agy -p "Here are issues found in code review: $(cat /tmp/qoder-review.md).
      Create a minimal fix plan (numbered steps, exact files)." --mode plan > /tmp/agy-fix.md
   b. Implement the fixes.
   c. Re-run the qodercli review.
   d. Maximum 3 fix iterations. If still failing after 3, report to the user
      with the remaining issues.

5. Only report the task complete when qodercli outputs LGTM, or after
   exhausting the fix loop with a clear summary.

## Run & verify

```bash
source .env/bin/activate        # venv is a folder named .env (NOT .venv)
python vocapp.py                # desktop app
```

- No test suite. Verify with `python3 -m py_compile vocapp.py` + a headless smoke:
  `QT_QPA_PLATFORM=offscreen python3 -c "import vocapp; from PySide6.QtWidgets import QApplication; app=QApplication([]); vocapp.init_db(); vocapp.VocabApp()"`.
- `pyflakes vocapp.py` should stay clean (was used for past fix passes, see `report.md`).
- `requirements.txt` is the full dependency list (PySide6, openpyxl, pypinyin, opencc-python-reimplemented — nothing else needed; online lookups use stdlib `urllib`).

## Database (vocabulary.db)

- Lives next to `vocapp.py`; `VOCAPP_DATA_DIR` env overrides the path (useful for testing on a copy).
- **The DB is committed to git on purpose** (`!*.db` in .gitignore) so curated data is versioned and shareable. The DB runs in WAL mode: **checkpoint before committing** — quit the app (or run `PRAGMA wal_checkpoint(TRUNCATE);`) so transactions sitting in `vocabulary.db-wal` are not lost from the commit.
- Startup creates a rolling backup `vocabulary_backup.db`, refreshed only when `_db_data_fingerprint()` changes. **When adding data tables, extend the fingerprint** or curation changes won't trigger backups.
- Schema changes are numbered `_migrate_*()` functions gated by `PRAGMA user_version` (currently 5). Add a new `_migrate_...`, bump the version, call it from `init_db()`; make it idempotent. No ORM — raw sqlite3 everywhere.

## Text conventions

- All Myanmar strings must pass `normalize_myanmar_text()` (NFC, strips ZWSP/ZWNJ/ZWJ). Unicode Burmese only, never Zawgyi; render with bundled `fonts/` Noto Sans Myanmar.
- Chinese entries are stored as `"Traditional (pinyin)"` via `normalize_chinese_entry()` — do not change the format of `words.chinese`; search, editor, exports, and import scripts all parse it.

## Chinese character breakdown (hanzi / word_chars tables)

- Pipeline: `python3 build_chinese_breakdown.py --cedict cedict.txt` (CC-CEDICT, ~5 MB download) → fills `hanzi` dictionary + `word_chars` per-word rows. Idempotent.
- **`data/hanzi_myanmar.csv` holds human-curated Myanmar glosses; generated data must never overwrite `source='curated'` rows.** Auto-suggested rows are `source='auto'` and visibly marked in the UI until reviewed.
- Split rule: a wrong split is worse than no split — split a word only when every character exists in the `hanzi` table; transliterations/proper nouns stay whole via `words.breakdown_mode='whole'` (dialog toggle or `--whole-word`).
- `word_chars` snapshots pinyin/english/myanmar/note per word. Curating a gloss in the dialog (`_save_gloss`) updates `hanzi`, directly patches existing `word_chars` snapshots, and rebuilds only auto-mode words that were whole because the character was unknown. Bulk edits: run `python3 build_chinese_breakdown.py --rebuild-only`.
- Keep the `pypinyin`/`opencc` imports guarded inside `_generate_pinyin` / `_simplified_to_traditional`
  (graceful degradation when the optional deps are missing).

## Online lookups

- MyOrdbok redesigned to client-side rendering: `lookup_myanmar()` reads the `og:description` meta tag. Ornagai API is Cloudflare-403 now. MDBG is used for Chinese.
- Politeness delay 1 s between site hits (`SOUND_RETRY_DELAY`); pronunciation audio is fetched once and stored in the DB.

## Spec docs

`feature.md` / `feature-do.md` are the product specs for the character-breakdown feature; `report.md` / `report-font.md` record past fix passes.
