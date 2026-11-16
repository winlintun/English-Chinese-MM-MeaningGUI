# AGENTS.md — VocApp

English–Chinese–Myanmar vocabulary manager. Single-file PySide6 desktop app (`vocapp.py`) with an Android port.

## Run & verify

```bash
source .env/bin/activate        # venv is a folder named .env (NOT .venv)
python vocapp.py                # desktop app
```

- No test suite. Verify with `python3 -m py_compile vocapp.py` + a headless smoke:
  `QT_QPA_PLATFORM=offscreen python3 -c "import vocapp; from PySide6.QtWidgets import QApplication; app=QApplication([]); vocapp.init_db(); vocapp.VocabApp()"`.
- `pyflakes vocapp.py` should stay clean (was used for past fix passes, see `report.md`).
- `requirements.txt` is polluted with unrelated ML packages (torch, vllm…). The real dependencies are the four lines at the bottom: PySide6, openpyxl, pypinyin, opencc-python-reimplemented.

## Database (vocabulary.db)

- Lives next to `vocapp.py`; `VOCAPP_DATA_DIR` env overrides the path (Android sets it in `main.py`).
- **The DB is committed to git on purpose** (`!*.db` in .gitignore) and ships inside the Android APK via `main.py` seeding — regenerate/curate data on desktop, commit, then rebuild the APK.
- Startup creates a rolling backup `vocabulary_backup.db`, refreshed only when `_db_data_fingerprint()` changes. **When adding data tables, extend the fingerprint** or curation changes won't trigger backups.
- Schema changes are numbered `_migrate_*()` functions gated by `PRAGMA user_version` (currently 4). Add a new `_migrate_...`, bump the version, call it from `init_db()`; make it idempotent. No ORM — raw sqlite3 everywhere.

## Text conventions

- All Myanmar strings must pass `normalize_myanmar_text()` (NFC, strips ZWSP/ZWNJ/ZWJ). Unicode Burmese only, never Zawgyi; render with bundled `fonts/` Noto Sans Myanmar.
- Chinese entries are stored as `"Traditional (pinyin)"` via `normalize_chinese_entry()` — do not change the format of `words.chinese`; search, editor, exports, and import scripts all parse it.

## Chinese character breakdown (hanzi / word_chars tables)

- Pipeline: `python3 build_chinese_breakdown.py --cedict cedict.txt` (CC-CEDICT, ~5 MB download) → fills `hanzi` dictionary + `word_chars` per-word rows. Idempotent.
- **`data/hanzi_myanmar.csv` holds human-curated Myanmar glosses; generated data must never overwrite `source='curated'` rows.** Auto-suggested rows are `source='auto'` and visibly marked in the UI until reviewed.
- Split rule: a wrong split is worse than no split — split a word only when every character exists in the `hanzi` table; transliterations/proper nouns stay whole via `words.breakdown_mode='whole'` (dialog toggle or `--whole-word`).
- Android has **no pypinyin/opencc** at runtime — all imports must stay guarded (see `_generate_pinyin`, `_simplified_to_traditional`); precompute everything into the shipped DB.

## Online lookups (desktop only)

- MyOrdbok redesigned to client-side rendering: `lookup_myanmar()` reads the `og:description` meta tag. Ornagai API is Cloudflare-403 now. MDBG is used for Chinese.
- Politeness delay 1 s between site hits (`SOUND_RETRY_DELAY`); pronunciation audio is fetched once and stored in the DB.

## Android build

- Built with `pysidedeploy.spec` / `pysided6-android-deploy` using prebuilt wheels in `android_wheels/` (steps in README); `buildozer.spec` also present but the working path was pysidedeploy. Entry point is `main.py`, not `vocapp.py`.
- `deployment/` and `.buildozer*/` are build artifacts — ignored.

## Spec docs

`feature.md` / `feature-do.md` are the product specs for the character-breakdown feature; `report.md` / `report-font.md` record past fix passes.
