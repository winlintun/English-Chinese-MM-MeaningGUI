# VocApp

VocApp is a small desktop vocabulary manager built with Python and Tkinter. It is designed for English, Chinese, and Myanmar vocabulary and stores words in a local SQLite database.

## Features

- Add English, Chinese, and Myanmar vocabulary.
- Search words across all three language fields.
- Edit and delete saved vocabulary.
- Add or update a Chinese definition for a selected word.
- Open a quiz window with up to 10 randomly selected words.
- Use Myanmar-compatible fonts when available.
- Package the application as a Windows executable with PyInstaller.

## Requirements

- Windows
- Python 3.10 or newer
- Tkinter, normally included with the standard Python Windows installer
- Packages listed in `requirements.txt` for the project environment

The application itself uses Python standard-library modules including `tkinter`, `sqlite3`, `os`, and `unicodedata`.

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

The current application is configured to use:

```text
C:\Users\%username%\Desktop\VocApp\vocabulary.db
```

To use the project from another folder or computer, update the `DB_FILE` value near the top of `vocapp.py` before running it. The database file is ignored by Git and is created automatically when the application starts.

## Myanmar Fonts

VocApp first checks for an installed Myanmar-compatible font. If one is not available, it searches the local `fonts` directory for a `.ttf` file. Keep the `fonts` directory beside `vocapp.py` when distributing the source application.

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

The executable is created in the `dist` directory. Keep the required font files available beside the executable if Myanmar text rendering needs the bundled font fallback.

## Project Files

```text
vocapp.py          Main Tkinter application
VocabApp.spec      PyInstaller build configuration
requirements.txt   Python package requirements
fonts/             Optional Myanmar font files
vocabulary.db      Local database created at runtime
```

## Notes

- The app currently uses a fixed database path in `vocapp.py`.
- `build/`, `dist/`, `env/`, generated databases, and Python cache files are ignored by Git.
