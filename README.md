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

`vocabulary.db` lives next to `vocapp.py` (or next to the executable in a PyInstaller build). It is created automatically on first start, so there is nothing to configure. The file is not ignored by Git, because it holds your own vocabulary — do not commit it if you publish the project.

## Myanmar Fonts

VocApp first checks for an installed Myanmar-compatible font. If one is not available, it registers a bundled `.ttf` from the `fonts/` folder (the static Noto Sans Myanmar Regular; variable fonts are skipped). Keep `fonts/` beside `vocapp.py`, and ship it inside PyInstaller builds (`--add-data "fonts;fonts"`) so PDF export can use it too.

## Build a Windows Executable

Install PyInstaller in the active environment if needed:

```powershell
python -m pip install pyinstaller
pyinstaller --onefile --windowed --name VocabApp vocapp.py
```

Build using the included spec file:

```powershell
pyinstaller VocabApp.spec
```

The executable is created in the `dist` directory. Build with `--add-data "fonts;fonts"` (or `datas = [("fonts", "fonts")]` in the spec) so the Myanmar fallback font is bundled; `vocapp.py` reads it from `sys._MEIPASS` and keeps `vocabulary.db` beside the executable.

## Project Files

```text
vocapp.py          Main PySide6 application
VocabApp.spec      PyInstaller build configuration
requirements.txt   Python package requirements
fonts/             Optional Myanmar font files
vocabulary.db      Local database created at runtime
```

## Notes

- The database path follows the application folder; `DB_FILE` can be reassigned before `init_db()` when embedding or testing.
- `build/`, `dist/`, `env/`, `.env/` and Python cache files are ignored by Git.
