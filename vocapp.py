import csv
import datetime
import hashlib
import html
import http.cookiejar
import json
import os
import re
import sqlite3
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.parse
import urllib.request

from PySide6.QtCore import QMarginsF, QSizeF, Qt, QEvent, QObject, QTimer, QUrl, Signal
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QPageLayout, QPageSize, QPdfWriter, QShortcut, QTextDocument
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

# MP3 playback needs QtMultimedia; sound downloads still work without it.
try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
    MULTIMEDIA_OK = True
except ImportError:  # playback disabled — buttons show a hint instead
    QAudioOutput = QMediaPlayer = None
    MULTIMEDIA_OK = False

# In a PyInstaller onefile build, bundled data (fonts) lives in the temp
# _MEIPASS folder, but the database must stay next to the executable so it
# survives restarts.
BUNDLE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
FONT_DIR = os.path.join(BUNDLE_DIR, "fonts")
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(sys.executable
                                                      if getattr(sys, "frozen", False)
                                                      else __file__)), "vocabulary.db")
SEARCH_PLACEHOLDER = "Search words…"
CATEGORIES = ("TOEIC", "TextBook")

MYORDBOK_URL = "https://myordbok.com/definition?q="
# Pronunciation audio: the speech endpoint only answers once a definition
# page has been fetched (it sets session cookies first).
SOUND_API_URL = "https://myordbok.com/api/speech"
SOUND_REFERER = "https://myordbok.com/definition"
SOUND_RETRY_DELAY = 1.0  # seconds between downloads — be polite to the site
ORNAGAI_URL = "https://www.ornagai.com/index.php/api/word/?q="
MDBG_URL = "https://www.mdbg.net/chinese/dictionary?client=opensearch-wdb-v1&wdqb="
HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

COLORS = {
    "bg": "#f3f6fa",
    "header": "#13293d",
    "header_text": "#ffffff",
    "header_muted": "#b9c9d8",
    "accent": "#2a9d8f",
    "card": "#ffffff",
    "border": "#d7e0e8",
    "text": "#22313f",
    "muted": "#64798e",
    "stripe": "#f7fafc",
    "accent_dark": "#0b5f59",
    "soft": "#e8eef3",
    "soft_hover": "#d6e1e9",
    "danger": "#fbe9e7",
    "danger_text": "#a33a2b",
    "danger_hover": "#f4d5d0",
    "selected": "#d8eeeb",
}

MYANMAR_FONT_PRIORITY = (
    "Noto Sans Myanmar",
    "Noto Sans Myanmar UI",
    "Myanmar Text",
    "Padauk",
    "Myanmar3",
    "Pyidaungsu",
)


def _find_local_noto_font():
    """Return path to a bundled Noto Sans Myanmar Regular .ttf, searching recursively."""
    if not os.path.isdir(FONT_DIR):
        return None

    def static_ttfs():
        for dirpath, _dirnames, filenames in os.walk(FONT_DIR):
            for filename in sorted(filenames):
                lower = filename.lower()
                # variable fonts register under odd weights in some Qt
                # versions; the static Regular is the safe target
                if lower.endswith(".ttf") and "variablefont" not in lower:
                    yield os.path.join(dirpath, filename), lower

    for path, lower in static_ttfs():
        if "noto" in lower and (("sans" in lower and "regular" in lower) or "normal" in lower):
            return path
    for path, lower in static_ttfs():
        if "regular" in lower or "normal" in lower:
            return path
    for path, _lower in static_ttfs():
        return path
    return None


def resolve_myanmar_font_family():
    """Pick the best Myanmar-capable font family, registering a bundled font if needed."""
    installed = set(QFontDatabase.families())
    for family in MYANMAR_FONT_PRIORITY:
        if family in installed:
            return family
    font_file = _find_local_noto_font()
    if font_file:
        font_id = QFontDatabase.addApplicationFont(font_file)
        if font_id != -1:
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                return families[0]
    return QFont().defaultFamily()


def normalize_myanmar_text(text):
    if text is None:
        return ""
    text = text.strip()
    text = text.replace("\u200b", "")
    text = text.replace("\u200c", "")
    text = text.replace("\u200d", "")
    return unicodedata.normalize("NFC", text)


_HANZI_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3007]")

_s2t_converter = None
_s2t_failed = False

_S2T_RUN_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff\u3007]+")


def _simplified_to_traditional(text):
    """Convert Simplified characters to Traditional; no-op with opencc missing.

    Conversion is applied per hanzi run, and only when the run contains at
    least one genuinely Simplified character. Runs that are already fully
    Traditional are passed through untouched, which protects them from
    OpenCC's phrase dictionary (it would otherwise rewrite e.g. 合家庭
    to 閤家庭) and keeps the conversion idempotent."""
    global _s2t_converter, _s2t_failed
    if _s2t_failed or not text or not _HANZI_RE.search(text):
        return text
    if _s2t_converter is None:
        try:
            from opencc import OpenCC
        except ImportError:
            _s2t_failed = True
            print("opencc is not installed — Chinese stays as typed "
                  "(pip install opencc-python-reimplemented)")
            return text
        _s2t_converter = OpenCC("s2tw")
    rebuilt = ""
    position = 0
    for match in _S2T_RUN_RE.finditer(text):
        rebuilt += text[position:match.start()]
        run = match.group(0)
        if any(_s2t_converter.convert(ch) != ch for ch in run):
            rebuilt += _s2t_converter.convert(run)
        else:
            rebuilt += run  # already Traditional — leave exactly as-is
        position = match.end()
    rebuilt += text[position:]
    return rebuilt


_pinyin_failed = False


def _generate_pinyin(hanzi):
    """Build tone-marked pinyin for a hanzi phrase; "" with pypinyin missing."""
    global _pinyin_failed
    if _pinyin_failed:
        return ""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        _pinyin_failed = True
        print("pypinyin is not installed — pinyin left empty "
              "(pip install pypinyin)")
        return ""
    # Keep only letters, tone marks, "/", spaces and apostrophes in generated
    # pinyin — no punctuation that could break re-detection on the next run.
    raw = "".join(lazy_pinyin(hanzi, style=Style.TONE, errors=lambda chunk: chunk))
    raw = raw.replace("／", "/")
    return "".join(ch for ch in raw if ch in " '/" or unicodedata.category(ch) in ("Ll", "Lu", "Mn"))


def _looks_like_pinyin(value):
    """Heuristic: pinyin is latin letters with tone marks/separators, no hanzi."""
    value = value.strip()
    if not value or not re.search(r"[A-Za-z]", value):
        return False
    for ch in value:
        if ch in " '/" or ch.isdigit() or unicodedata.category(ch) in ("Ll", "Lu", "Mn"):
            continue
        return False
    return True


def _normalize_single_chinese(text):
    """One Chinese entry -> Traditional + optional (pinyin), keeping existing pinyin."""
    if not text or not _HANZI_RE.search(text):
        return text
    pinyin = None
    core = text
    match = re.match(r"^(.*\S)\s*[（(]\s*([^（）()]*)[）)]\s*$", text)
    if match:
        candidate = match.group(2).strip()
        if candidate and _looks_like_pinyin(candidate):
            pinyin = candidate
            core = match.group(1).strip()
    traditional = _simplified_to_traditional(core)
    if not pinyin:
        pinyin = _generate_pinyin(traditional)
    return "%s (%s)" % (traditional, pinyin) if pinyin else traditional


def normalize_chinese_entry(text):
    """Normalize a whole Chinese field: comma-separated entries are
    handled individually, non-Chinese text is returned unchanged."""
    text = (text or "").strip()
    if not text or not _HANZI_RE.search(text):
        return text
    parts = re.split(r"([,，])", text)  # keep the separator tokens
    out = []
    for index, part in enumerate(parts):
        if index % 2 or not part.strip():
            out.append(part)
            continue
        strip = part.lstrip()
        out.append(part[:len(part) - len(strip)] + _normalize_single_chinese(strip))
    return "".join(out)


def _http_get(url, timeout=10):
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def _strip_tags(fragment):
    text = re.sub(r"<[^>]+>", " ", fragment)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def lookup_myanmar(term):
    try:
        page = _http_get(MYORDBOK_URL + urllib.parse.quote_plus(term))
        meanings = re.findall(r'<div class="mean">\s*<p>(.*?)</p>', page, re.S)
        candidates = [_strip_tags(m) for m in meanings if _strip_tags(m)]
        for candidate in candidates:
            if any("\u1000" <= ch <= "\u109f" for ch in candidate):
                if candidate.startswith("~"):
                    parts = [p for p in candidate[1:].split()
                             if any("\u1000" <= ch <= "\u109f" for ch in p)]
                    if parts:
                        return " ".join(parts)
                return candidate
        if candidates:
            return candidates[0]
    except Exception:
        pass
    try:
        page = _http_get(ORNAGAI_URL + urllib.parse.quote_plus(term) + "&return=json")
        data = json.loads(page)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            for key in ("definition", "myanmar", "meaning"):
                value = str(data[0].get(key) or "").strip()
                if value:
                    return value
    except Exception:
        pass
    return None


def _chinese_match_score(definition, lowered):
    segments = [s.strip().lower() for s in definition.split("/") if s.strip()]
    segments = [s for s in segments if not s.startswith("cl:")]
    best = 0
    for seg in segments:
        if seg == lowered:
            best = max(best, 5)
        elif seg == "to " + lowered:
            best = max(best, 4)
        elif re.match(r"%s\b" % re.escape(lowered), seg):
            best = max(best, 3)
    if best:
        return best
    if re.search(r"\b%s\b" % re.escape(lowered), definition.lower()):
        return 2
    if lowered in definition.lower():
        return 1
    return 0


def lookup_chinese(term):
    try:
        page = _http_get(MDBG_URL + urllib.parse.quote_plus(term))
    except Exception:
        return None
    rows = re.findall(r'<tr class="row">.*?</tr>', page, re.S)
    if not rows:
        return None
    lowered = term.strip().lower()
    candidates = []
    fallback = None
    for row in rows:
        head = re.search(r'<td class="head">(.*?)</td>', row, re.S)
        defs = re.search(r'<td class="details">\s*<div class="defs">(.*?)</div>', row, re.S)
        if not head:
            continue
        hanzi_m = re.search(r'<div class="hanzi"[^>]*>(.*?)</div>', head.group(1), re.S)
        pinyin_m = re.search(r'<div class="pinyin"[^>]*>(.*?)</div>', head.group(1), re.S)
        if not hanzi_m:
            continue
        hanzi = _strip_tags(hanzi_m.group(1)).replace(" ", "")
        pinyin = _strip_tags(pinyin_m.group(1)).replace(" ", "") if pinyin_m else ""
        definition = _strip_tags(defs.group(1)) if defs else ""
        tail = re.search(r'<td class="tail">(.*?)</td>', row, re.S)
        hsk_m = re.search(r'<div class="hsk">\s*HSK\s*([0-9]+)', tail.group(1)) if tail else None
        hsk = int(hsk_m.group(1)) if hsk_m else 99
        candidate = f"{hanzi} ({pinyin})" if pinyin else hanzi
        if fallback is None:
            fallback = candidate
        score = _chinese_match_score(definition, lowered) if lowered else 0
        if score:
            candidates.append((score, hsk, len(definition.split("/")), candidate))
    if candidates:
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        return candidates[0][3]
    return fallback


_sound_opener = None
_sound_opener_lock = threading.Lock()


def _sound_session():
    """One opener per app session so the MyOrdbok cookies are kept warm."""
    global _sound_opener
    with _sound_opener_lock:
        if _sound_opener is None:
            cookies = urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
            _sound_opener = urllib.request.build_opener(cookies)
        return _sound_opener


def _sound_http(url, referer=None, timeout=20):
    scheme = urllib.parse.urlparse(url).scheme
    if scheme not in ("http", "https"):
        raise ValueError("Only http/https URLs are allowed")
    headers = dict(HTTP_HEADERS)
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with _sound_session().open(req, timeout=timeout) as resp:
        return resp.read()


def _is_mp3(data):
    """MP3 frames start with an ID3 tag or a synchronised frame header."""
    return bool(data) and (data[:3] == b"ID3" or (data[0] == 0xFF and data[1] & 0xE0 == 0xE0))


def fetch_sound(term):
    """Download the English pronunciation MP3 for a word from MyOrdbok.

    Returns the audio bytes, or None when the word has no sound (or the
    network fails — callers treat None as "try again later")."""
    term = (term or "").strip()
    if not term:
        return None
    try:
        # Warm the session: the speech endpoint requires the definition
        # page's cookies, so fetch it first (failure is not fatal — a warm
        # cookie jar from an earlier word may already be enough).
        try:
            _sound_http(MYORDBOK_URL + urllib.parse.quote_plus(term))
        except Exception:
            pass
        url = SOUND_API_URL + "?" + urllib.parse.urlencode({"q": term, "l": "en"})
        data = _sound_http(url, referer=SOUND_REFERER)
        return data if _is_mp3(data) else None
    except Exception:
        return None


def get_sound(word_id):
    """Stored MP3 bytes for a word row (or None)."""
    conn = sqlite3.connect(DB_FILE)
    try:
        row = conn.execute("SELECT sound FROM words WHERE id=?", (word_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row and row[0] else None


def store_sound(word_id, data):
    conn = sqlite3.connect(DB_FILE)
    try:
        conn.execute("UPDATE words SET sound=? WHERE id=?", (data, word_id))
        conn.commit()
    finally:
        conn.close()


def init_db():
    _harden_db_permissions()
    conn = sqlite3.connect(DB_FILE)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            english TEXT NOT NULL,
            chinese TEXT DEFAULT '',
            myanmar TEXT NOT NULL
        )
    """)
    cur.execute("PRAGMA table_info(words)")
    columns = {row[1] for row in cur.fetchall()}
    if "category" not in columns:
        cur.execute("ALTER TABLE words ADD COLUMN category TEXT DEFAULT 'TOEIC'")
        cur.execute("UPDATE words SET category='TOEIC' WHERE category IS NULL OR category=''")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_words_english ON words (english)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_words_category ON words (category)")
    # Speed up writes/reads and keep the database recoverable on crashes.
    cur.execute("PRAGMA journal_mode=WAL")
    # Erase deleted content from disk instead of leaving it in free pages.
    cur.execute("PRAGMA secure_delete=ON")
    _migrate_myanmar_text(conn)
    _migrate_chinese_text(conn)
    _migrate_sound_column(conn)
    conn.commit()
    conn.close()
    backup_database_if_changed()


def _harden_db_permissions():
    """Restrict the database file to the current user only."""
    try:
        os.chmod(DB_FILE, 0o600)
    except OSError:
        pass  # e.g. permissions not supported on this filesystem


BACKUP_FILE = DB_FILE.replace(".db", "") + "_backup.db"
BACKUP_HASH_FILE = BACKUP_FILE + ".sha256"


def _db_data_fingerprint(conn):
    """SHA-256 over the whole words table (ordered by id) plus schema version.

    Only the content matters, so touching the file without changing data
    (indexes, WAL, metadata) does not count as a change."""
    hasher = hashlib.sha256()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    hasher.update(("user_version=%d" % version).encode("utf-8"))
    for row in conn.execute(
        "SELECT id, english, chinese, myanmar, category FROM words ORDER BY id"
    ):
        hasher.update(repr(row).encode("utf-8"))
    # Count rows that have pronunciation audio so a completed sound
    # backfill counts as a change and gets into the backup too.
    sound_count = conn.execute(
        "SELECT COUNT(*) FROM words WHERE sound IS NOT NULL"
    ).fetchone()[0]
    hasher.update(("sound=%d" % sound_count).encode("utf-8"))
    return hasher.hexdigest()


def backup_database_if_changed():
    """On startup: refresh vocabulary_backup.db only when the data changed.

    Compares a fingerprint of the words table with the one recorded at the
    last backup. If nothing changed, the backup is left untouched."""
    try:
        conn = sqlite3.connect(DB_FILE)
        fingerprint = _db_data_fingerprint(conn)
        if os.path.exists(BACKUP_HASH_FILE):
            with open(BACKUP_HASH_FILE, "r", encoding="utf-8") as handle:
                stored = handle.read().strip()
            if stored == fingerprint:
                conn.close()
                print("Database unchanged — backup is up to date")
                return False
        # SQLite's backup API copies a consistent snapshot (WAL-safe).
        with sqlite3.connect(BACKUP_FILE) as destination:
            conn.backup(destination)
        with open(BACKUP_HASH_FILE, "w", encoding="utf-8") as handle:
            handle.write(fingerprint)
        conn.close()
        print("Database changed — backup updated")
        return True
    except Exception as exc:
        print("Backup skipped (%s)" % exc)
        return False


def _migrate_myanmar_text(conn):
    """Normalize stored Myanmar text to clean NFC Unicode so it renders
    correctly with Noto Sans Myanmar. Runs once (guarded by user_version)."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 1:
        return
    rows = conn.execute("SELECT id, myanmar FROM words").fetchall()
    updated = 0
    for word_id, mm in rows:
        fixed = normalize_myanmar_text(mm)
        if fixed != (mm or ""):
            conn.execute("UPDATE words SET myanmar=? WHERE id=?", (fixed, word_id))
            updated += 1
    conn.execute("PRAGMA user_version=1")
    if updated:
        print("Normalized Myanmar text in %d row(s)" % updated)


def _migrate_chinese_text(conn):
    """Convert stored Chinese entries to Traditional characters with pinyin.
    Simplified characters become Traditional, entries missing pinyin get it
    added, and text that is already correct is left untouched. One-time,
    guarded by user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 2:
        return
    rows = conn.execute(
        "SELECT id, chinese FROM words WHERE chinese IS NOT NULL AND chinese != ''"
    ).fetchall()
    updated = 0
    samples = []
    for word_id, cn in rows:
        fixed = normalize_chinese_entry(cn)
        if fixed != (cn or ""):
            conn.execute("UPDATE words SET chinese=? WHERE id=?", (fixed, word_id))
            updated += 1
            if len(samples) < 8:
                samples.append((cn, fixed))
    conn.execute("PRAGMA user_version=2")
    if updated:
        print("Converted Chinese to Traditional + pinyin in %d row(s)" % updated)
        for old, new in samples:
            print("  %r -> %r" % (old, new))
    else:
        print("Chinese entries already use Traditional + pinyin (checked %d)" % len(rows))


def _migrate_sound_column(conn):
    """Add the pronunciation-audio column (MP3 bytes) for word sounds.
    One-time, guarded by user_version."""
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= 3:
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(words)").fetchall()}
    if "sound" not in columns:
        conn.execute("ALTER TABLE words ADD COLUMN sound BLOB")
        print("Added sound column for word pronunciations")
    conn.execute("PRAGMA user_version=3")


STYLESHEET = """
QMainWindow, QDialog, #quizBody { background: %(bg)s; }

#header { background: %(header)s; }
#header QLabel { background: transparent; }

#titleLabel {
    color: %(header_text)s;
    font-size: 22pt;
    font-weight: bold;
}

#subtitleLabel { color: %(header_muted)s; font-size: 10pt; }

#chipLabel {
    background: %(accent)s;
    color: #ffffff;
    font-weight: bold;
    font-size: 10pt;
    border-radius: 10px;
    padding: 4px 14px;
}

#card {
    background: %(card)s;
    border: 1px solid %(border)s;
    border-radius: 6px;
}

#cardTitle { color: %(header)s; font-weight: bold; font-size: 10pt; }
#sectionLabel { color: %(muted)s; font-weight: bold; font-size: 9pt; }
#hintLabel { color: %(muted)s; font-size: 9pt; }
#mutedLabel { color: %(muted)s; font-size: 10pt; }

QLineEdit {
    background: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    padding: 7px 9px;
    font-size: 11pt;
}
QLineEdit:focus { border: 1px solid %(accent)s; }

QComboBox {
    background: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    padding: 5px 9px;
    font-size: 11pt;
}
QComboBox:focus { border: 1px solid %(accent)s; }
QComboBox QAbstractItemView {
    background: %(card)s;
    color: %(text)s;
    selection-background-color: %(selected)s;
    selection-color: %(header)s;
}

#accentButton {
    background: %(accent)s;
    color: #ffffff;
    border: none;
    border-radius: 4px;
    padding: 9px 16px;
    font-weight: bold;
    font-size: 10pt;
}
#accentButton:hover { background: %(accent_dark)s; }
#accentButton:pressed { background: %(accent_dark)s; }

#softButton {
    background: %(soft)s;
    color: %(header)s;
    border: none;
    border-radius: 4px;
    padding: 9px 12px;
    font-size: 10pt;
}
#softButton:hover { background: %(soft_hover)s; }
#softButton:pressed { background: %(soft_hover)s; }

#dangerButton {
    background: %(danger)s;
    color: %(danger_text)s;
    border: none;
    border-radius: 4px;
    padding: 9px 12px;
    font-size: 10pt;
}
#dangerButton:hover { background: %(danger_hover)s; }
#dangerButton:pressed { background: %(danger_hover)s; }
#dangerButton:disabled { color: #c9b3ae; }

QTreeWidget {
    background: %(card)s;
    color: %(text)s;
    border: 1px solid %(border)s;
    border-radius: 4px;
    alternate-background-color: %(stripe)s;
    font-size: 11pt;
}
QTreeWidget::item { height: 32px; }
QTreeWidget::item:selected {
    background: %(selected)s;
    color: %(header)s;
}
QHeaderView::section {
    background: %(soft)s;
    color: %(header)s;
    border: none;
    border-right: 1px solid %(border)s;
    padding: 7px 6px;
    font-weight: bold;
    font-size: 10pt;
}
QHeaderView::section:hover { background: %(soft_hover)s; }

#statusFrame { background: %(border)s; border: none; }
#statusLabel { background: %(border)s; color: %(muted)s; font-size: 9pt; padding: 6px 24px; }
""" % COLORS


EXPORT_HEADERS = ("ID", "English", "Chinese", "Category", "Myanmar")


def export_csv(path, rows):
    """Export rows as UTF-8 CSV; the BOM lets Excel open Myanmar/Chinese correctly."""
    with open(path, "w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(EXPORT_HEADERS)
        writer.writerows(rows)


def export_markdown(path, rows):
    """Export rows as a Markdown table."""
    def md_cell(value):
        return str(value or "").replace("|", "\\|").replace("\n", " ")
    lines = [
        "# VocApp Vocabulary Export",
        "",
        "| " + " | ".join(EXPORT_HEADERS) + " |",
        "| " + " | ".join(["---"] * len(EXPORT_HEADERS)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(md_cell(v) for v in row) + " |")
    lines.append("")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def export_excel(path, rows):
    """Export rows as a formatted Excel workbook (requires openpyxl)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Vocabulary"
    sheet.append(EXPORT_HEADERS)
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(fill_type="solid", start_color="13293D", end_color="13293D")
    thin_side = Side(style="thin", color="D7E0E8")
    cell_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    for column, header in enumerate(EXPORT_HEADERS, start=1):
        cell = sheet.cell(row=1, column=column)
        cell.font = header_font
        cell.fill = header_fill
        cell.border = cell_border
        cell.alignment = Alignment(vertical="center")
    for row in rows:
        sheet.append(tuple(str(value or "") for value in row))
    for number, header in enumerate(EXPORT_HEADERS, start=1):
        width = max(len(header) + 4, 12)
        if header == "Myanmar" or header == "English":
            width = 40
        elif header == "Chinese":
            width = 30
        column_letter = sheet.cell(row=1, column=number).column_letter
        sheet.column_dimensions[column_letter].width = width
        for cell in sheet[chr(ord("A") + number - 1)][1:]:
            cell.border = cell_border
            cell.alignment = Alignment(vertical="top", wrap_text=True)
    sheet.freeze_panes = "A2"
    workbook.save(path)


def export_pdf(path, rows):
    """Export rows as a paginated PDF table using Qt's own PDF engine."""
    import html as _html
    font_family = resolve_myanmar_font_family()
    head_cells = "".join("<th>%s</th>" % _html.escape(h) for h in EXPORT_HEADERS)
    body_cells = "".join(
        "<tr>%s</tr>" % "".join(
            "<td>%s</td>" % ("<br />".join(_html.escape(line) for line in str(v or "").splitlines()) or "&nbsp;")
            for v in row)
        for row in rows
    )
    style = (
        "body{font-family:'%s';}" % font_family.replace("'", "")
        + "table{width:100%;border-collapse:collapse;font-size:9pt;}"
        # Qt sizes a fixed column from the widest cell on every page; the
        # ID column is narrow, so pin it instead of letting row "1000" push it
        "th:first-child,td:first-child{width:6%;white-space:nowrap;}"
        "th{background:#13293d;color:#ffffff;padding:5px 6px;border:1px solid #13293d;}"
        "td{border:1px solid #b9c9d8;padding:4px 6px;vertical-align:top;}"
    )
    captions = "<style>%s</style><h2>VocApp Vocabulary</h2><p>%d words &mdash; exported %s</p>" % (
        style, len(rows), html.escape(datetime.date.today().isoformat()),
    )
    doc_html = captions + "<table><thead><tr>%s</tr></thead><tbody>%s</tbody></table>" % (
        head_cells, body_cells,
    )
    writer = QPdfWriter(path)
    writer.setResolution(150)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(15, 15, 15, 15), QPageLayout.Unit.Millimeter)
    document = QTextDocument()
    # the document's own default font decides fallbacks for glyphs the CSS
    # family lacks, so it must be the Myanmar-capable one, not Qt's default
    document.setDefaultFont(QFont(font_family, 10))
    document.setDocumentMargin(0)
    document.setHtml(doc_html)
    document.setPageSize(QSizeF(writer.width(), writer.height()))
    document.print_(writer)


EXPORT_FORMATS = {
    ".csv": (export_csv, "CSV files (*.csv)"),
    ".xlsx": (export_excel, "Excel workbooks (*.xlsx)"),
    ".md": (export_markdown, "Markdown files (*.md)"),
    ".pdf": (export_pdf, "PDF files (*.pdf)"),
}
EXPORT_FILTER = ";;".join(filter_label for _fn, filter_label in EXPORT_FORMATS.values())


class _LookupSignals(QObject):
    finished = Signal(str, object, object)


class _SoundSignals(QObject):
    word_done = Signal(int, str, bool)      # word_id, english, success
    progress = Signal(int, int, int)        # done, total, failed
    play_ready = Signal(int, str, object)   # word_id, english, bytes


class VocabApp(QMainWindow):
    tree_columns = ("id", "english", "chinese", "category", "myanmar", "sound")

    def __init__(self):
        super().__init__()
        self.editing_id = None
        self.sort_col = 0
        self.sort_desc = False
        self.known_categories = list(CATEGORIES)
        self._lookup_inflight = set()
        self.lookup_signals = _LookupSignals()
        self.lookup_signals.finished.connect(self._apply_lookup)
        self._lookup_timer = QTimer(self)
        self._lookup_timer.setSingleShot(True)
        self._lookup_timer.setInterval(800)
        self._lookup_timer.timeout.connect(self._start_lookup)

        self.sound_signals = _SoundSignals()
        self.sound_signals.word_done.connect(self._on_sound_saved)
        self.sound_signals.progress.connect(self._on_sound_progress)
        self.sound_signals.play_ready.connect(self._on_play_ready)
        self._sound_downloading = set()
        self._sound_lock = threading.Lock()
        self._sound_temp_files = {}
        self._backfill_running = False
        self._media_player = None
        self._audio_output = None
        if MULTIMEDIA_OK:
            self._media_player = QMediaPlayer(self)
            self._audio_output = QAudioOutput(self)
            self._media_player.setAudioOutput(self._audio_output)

        self.setWindowTitle("VocApp | Vocabulary Workspace")
        self.resize(1060, 700)
        self.setMinimumSize(700, 480)

        self.word_count_label = QLabel("0 words")
        self.word_count_label.setObjectName("chipLabel")

        self.status_label = QLabel("Ready")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_editor())
        library = self._build_library()
        root.addWidget(library, 1)
        root.addWidget(self._build_statusbar())

        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Escape"), self, activated=self.escape_search)
        QShortcut(QKeySequence("Ctrl+P"), self, activated=self.play_selected_sound)

        self.reset_search(refresh=False)
        self._refresh_filter_options()
        self.load_words()
        # Backfill pronunciation audio for existing words once the window
        # is up; words already having audio are skipped, so this resumes
        # where the last run left off.
        QTimer.singleShot(2000, self.start_sound_backfill)

    def _build_header(self):
        header = QFrame(objectName="header")
        layout = QVBoxLayout(header)
        layout.setContentsMargins(28, 20, 28, 20)
        layout.setSpacing(4)

        title_row = QHBoxLayout()
        title_row.setSpacing(18)
        title_row.addWidget(QLabel("VocApp", objectName="titleLabel"))
        title_row.addWidget(self.word_count_label)
        title_row.addStretch(1)
        layout.addLayout(title_row)

        subtitle = QLabel("Build your vocabulary, one word at a time", objectName="subtitleLabel")
        layout.addWidget(subtitle)
        return header

    def _build_editor(self):
        card = QFrame(objectName="card")
        card.setContentsMargins(2, 2, 2, 2)
        outer = QVBoxLayout(card)
        outer.setContentsMargins(20, 14, 20, 16)

        inner = QHBoxLayout()
        inner.setSpacing(18)
        outer.addLayout(inner)

        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        inner.addLayout(form, 3)

        for col, text in enumerate(("English", "Myanmar", "Chinese (optional)", "Category")):
            label = QLabel(text, objectName="sectionLabel")
            form.addWidget(label, 0, col)

        self.ent_eng = QLineEdit()
        self.ent_mm = QLineEdit()
        self.ent_cn = QLineEdit()
        self.combo_cat = QComboBox()
        self.combo_cat.addItems(CATEGORIES)
        # The English field gets a 🔊 button to preview its pronunciation
        # (plays the stored MP3 when available, fetches online otherwise).
        self.eng_sound_btn = QPushButton("🔊", objectName="softButton")
        self.eng_sound_btn.setFixedWidth(44)
        self.eng_sound_btn.setToolTip("Play pronunciation of this word (Ctrl+P)")
        self.eng_sound_btn.setEnabled(False)
        self.eng_sound_btn.clicked.connect(self.play_editor_sound)
        eng_holder = QWidget()
        eng_row = QHBoxLayout(eng_holder)
        eng_row.setContentsMargins(0, 0, 0, 0)
        eng_row.setSpacing(6)
        eng_row.addWidget(self.ent_eng, 1)
        eng_row.addWidget(self.eng_sound_btn)
        form.addWidget(eng_holder, 1, 0)
        for col, widget in enumerate((self.ent_mm, self.ent_cn, self.combo_cat), start=1):
            form.addWidget(widget, 1, col)
        form.setColumnStretch(0, 3)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(2, 3)
        form.setColumnStretch(3, 2)

        self.mm_hint = QLabel("", objectName="hintLabel")
        self.cn_hint = QLabel("", objectName="hintLabel")
        form.addWidget(self.mm_hint, 2, 1)
        form.addWidget(self.cn_hint, 2, 2)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        inner.addLayout(actions, 0)

        self.save_button = QPushButton("Save Word", objectName="accentButton")
        self.save_button.clicked.connect(self.submit_word)
        self.cancel_button = QPushButton("Cancel Edit", objectName="softButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.hint_label = QLabel("Enter = save\nDouble-click a row to edit", objectName="hintLabel")
        actions.addWidget(self.save_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.hint_label)
        actions.addStretch(1)

        self.ent_eng.returnPressed.connect(self.submit_word)
        self.ent_mm.returnPressed.connect(self.submit_word)
        self.ent_cn.returnPressed.connect(self.submit_word)
        self.ent_eng.installEventFilter(self)
        self.ent_eng.textChanged.connect(self._english_changed)
        self.ent_mm.textChanged.connect(self._mm_typed)
        self.ent_cn.textChanged.connect(self._cn_typed)

        return card

    def eventFilter(self, watched, event):
        if watched is self.ent_eng and event.type() == QEvent.FocusOut:
            self.auto_lookup()
        return super().eventFilter(watched, event)

    def _build_library(self):
        library = QWidget()
        layout = QVBoxLayout(library)
        layout.setContentsMargins(24, 14, 24, 16)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        toolbar.addWidget(QLabel("Your vocabulary", objectName="cardTitle"))
        toolbar.addStretch(1)
        filter_label = QLabel("Filter", objectName="mutedLabel")
        toolbar.addWidget(filter_label)
        self.filter_box = QComboBox()
        self.filter_box.addItem("All categories", None)
        for cat in CATEGORIES:
            self.filter_box.addItem(cat, cat)
        self.filter_box.currentIndexChanged.connect(self.load_words)
        toolbar.addWidget(self.filter_box)
        search_label = QLabel("Search", objectName="mutedLabel")
        toolbar.addWidget(search_label)
        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.ent_search.setFixedWidth(280)
        self.ent_search.textChanged.connect(self.load_words)
        toolbar.addWidget(self.ent_search)
        clear_btn = QPushButton("Clear", objectName="softButton")
        clear_btn.clicked.connect(self.reset_search)
        toolbar.addWidget(clear_btn)
        refresh_btn = QPushButton("Refresh", objectName="softButton")
        refresh_btn.clicked.connect(self.load_words)
        toolbar.addWidget(refresh_btn)
        export_btn = QPushButton("Export…", objectName="softButton")
        export_btn.clicked.connect(self.export_words)
        toolbar.addWidget(export_btn)
        layout.addLayout(toolbar)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.tree_columns))
        self.tree.setHeaderLabels([c.capitalize() for c in self.tree_columns])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.tree.setAllColumnsShowFocus(True)
        self.tree.setSortingEnabled(False)
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.sortIndicatorChanged.connect(self.on_sort_indicator)
        header.setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        header.setSectionsMovable(False)
        for i, width in enumerate((48, 240, 200, 110, 270, 64)):
            self.tree.setColumnWidth(i, width)
        self.tree.setFrameShape(QFrame.StyledPanel)
        layout.addWidget(self.tree, 1)

        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_word())
        self.tree.itemSelectionChanged.connect(self._update_sound_buttons)
        self.tree.itemClicked.connect(self._on_item_clicked)
        for key, slot in ((QKeySequence.Delete, self.delete_word),
                          (QKeySequence("Return"), self.edit_word)):
            shortcut = QShortcut(key, self.tree, activated=slot)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        edit_btn = QPushButton("Edit Selected (Enter)", objectName="softButton")
        edit_btn.clicked.connect(self.edit_word)
        self.play_sound_btn = QPushButton("🔊 Play Sound", objectName="softButton")
        self.play_sound_btn.setToolTip("Play pronunciation of the selected word (Ctrl+P)")
        self.play_sound_btn.setEnabled(False)
        self.play_sound_btn.clicked.connect(self.play_selected_sound)
        delete_btn = QPushButton("Delete Selected", objectName="dangerButton")
        delete_btn.clicked.connect(self.delete_word)
        add_cn_btn = QPushButton("Add Chinese to Selected", objectName="softButton")
        add_cn_btn.clicked.connect(self.add_chinese)
        quiz_btn = QPushButton("Open Quiz", objectName="accentButton")
        quiz_btn.clicked.connect(self.open_quiz)
        actions.addWidget(edit_btn)
        actions.addWidget(self.play_sound_btn)
        actions.addWidget(delete_btn)
        actions.addWidget(add_cn_btn)
        actions.addStretch(1)
        actions.addWidget(quiz_btn)
        layout.addLayout(actions)

        return library

    def _build_statusbar(self):
        status_frame = QFrame(objectName="statusFrame")
        layout = QHBoxLayout(status_frame)
        layout.setContentsMargins(24, 0, 24, 0)
        layout.setSpacing(0)
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        status_frame.setFixedHeight(34)
        return status_frame

    def focus_search(self):
        self.ent_search.setFocus()

    def escape_search(self):
        if self.ent_search.hasFocus():
            self.reset_search()
            self.setFocus()

    def reset_search(self, refresh=True):
        self.filter_box.blockSignals(True)
        self.filter_box.setCurrentIndex(0)
        self.filter_box.blockSignals(False)
        self.ent_search.clear()
        if refresh:
            self.load_words()

    def current_category_filter(self):
        return self.filter_box.currentData()

    def on_sort_indicator(self, col, order):
        self.sort_col = col
        self.sort_desc = order == Qt.SortOrder.DescendingOrder
        self.load_words()

    def _item_word_id(self, item):
        """Return the real database id stored on a tree item (or None)."""
        word_id = item.data(0, Qt.ItemDataRole.UserRole)
        if word_id is None:
            try:
                word_id = int(item.text(0))
            except ValueError:
                return None
        return word_id

    def selected_word(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Info", "Please select a word in the table first.")
            return None
        word_id = self._item_word_id(items[0])
        if word_id is None:
            return None
        texts = [items[0].text(i) for i in range(5)]
        return word_id, texts

    def normalize_category(self, value):
        value = (value or "").strip()
        for cat in self.known_categories:
            if value.lower() == cat.lower():
                return cat
        return CATEGORIES[0]

    def _refresh_filter_options(self):
        """Add any category found in the database to the filter and editor combos."""
        conn = sqlite3.connect(DB_FILE)
        cats = [row[0] for row in conn.execute(
            "SELECT DISTINCT category FROM words "
            "WHERE category IS NOT NULL AND category != '' "
            "ORDER BY LOWER(category)"
        ).fetchall()]
        conn.close()
        for cat in cats:
            if cat not in self.known_categories:
                self.known_categories.append(cat)
                if self.combo_cat.findText(cat) == -1:
                    self.combo_cat.addItem(cat)
                if self.filter_box.findText(cat) == -1:
                    self.filter_box.addItem(cat, cat)

    def _set_hint(self, label, text, color):
        label.setText(text)
        label.setStyleSheet(f"color: {color};" if text else "")

    def _english_changed(self, text):
        self._set_hint(self.mm_hint, "", "")
        self._set_hint(self.cn_hint, "", "")
        self.eng_sound_btn.setEnabled(MULTIMEDIA_OK and bool(normalize_myanmar_text(text)))
        if normalize_myanmar_text(text):
            self._lookup_timer.start()
        else:
            self._lookup_timer.stop()

    def _mm_typed(self):
        self._set_hint(self.mm_hint, "", "")

    def _cn_typed(self):
        self._set_hint(self.cn_hint, "", "")

    def auto_lookup(self):
        self._lookup_timer.stop()
        self._start_lookup()

    def _start_lookup(self):
        eng = normalize_myanmar_text(self.ent_eng.text())
        if not eng:
            return
        needs_mm = not self.ent_mm.text().strip()
        needs_cn = not self.ent_cn.text().strip()
        if not needs_mm and not needs_cn:
            return
        if eng in self._lookup_inflight:
            return
        self._lookup_inflight.add(eng)
        if needs_mm:
            self._set_hint(self.mm_hint, "Searching online…", COLORS["muted"])
        if needs_cn:
            self._set_hint(self.cn_hint, "Searching online…", COLORS["muted"])
        self.status_label.setText(f"Looking up “{eng}” online…")
        threading.Thread(target=self._lookup_worker, args=(eng, needs_mm, needs_cn),
                         daemon=True).start()

    def _lookup_worker(self, eng, needs_mm, needs_cn):
        mm = lookup_myanmar(eng) if needs_mm else None
        cn = lookup_chinese(eng) if needs_cn else None
        self.lookup_signals.finished.emit(eng, mm, cn)

    def _apply_lookup(self, eng, mm, cn):
        self._lookup_inflight.discard(eng)
        if normalize_myanmar_text(self.ent_eng.text()) != eng:
            return
        filled = []
        if mm and not self.ent_mm.text().strip():
            self.ent_mm.setText(normalize_myanmar_text(mm))
            self._set_hint(self.mm_hint, "Found online ✓", COLORS["accent_dark"])
            filled.append("Myanmar")
        elif self.mm_hint.text() == "Searching online…":
            self._set_hint(self.mm_hint, "Not found — add manually", COLORS["danger_text"])
        if cn and not self.ent_cn.text().strip():
            self.ent_cn.setText(normalize_chinese_entry(cn))
            self._set_hint(self.cn_hint, "Found online ✓", COLORS["accent_dark"])
            filled.append("Chinese")
        elif self.cn_hint.text() == "Searching online…":
            self._set_hint(self.cn_hint, "Not found — add manually", COLORS["danger_text"])
        if filled:
            self.status_label.setText(f"Auto-filled {' & '.join(filled)} for “{eng}”")
        else:
            self.status_label.setText(f"No online result found for “{eng}” — add it manually")

    # ------------------------------------------------------------------ #
    # Pronunciation sounds: downloads store MP3 bytes in the words.sound
    # column; playback runs off the stored bytes (offline afterwards).
    # ------------------------------------------------------------------ #

    def _queue_sound_download(self, word_id, eng):
        """Download and store the MP3 for one word in the background."""
        if not eng or not word_id:
            return
        with self._sound_lock:
            if eng in self._sound_downloading:
                return
            self._sound_downloading.add(eng)
        self.status_label.setText(f"Downloading sound for “{eng}”…")
        threading.Thread(target=self._sound_download_worker, args=(word_id, eng),
                         daemon=True).start()

    def _sound_download_worker(self, word_id, eng):
        data = fetch_sound(eng)
        if data:
            store_sound(word_id, data)
        self.sound_signals.word_done.emit(word_id, eng, bool(data))

    def start_sound_backfill(self):
        """Download audio for every existing word that has none (startup job)."""
        if self._backfill_running:
            return
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT id, english FROM words "
            "WHERE sound IS NULL AND TRIM(english) != '' ORDER BY id"
        ).fetchall()
        conn.close()
        # Group by English term: duplicate rows share one download.
        groups = {}
        for word_id, eng in rows:
            groups.setdefault(eng.strip(), []).append(word_id)
        pending = [(eng, ids) for eng, ids in groups.items() if eng]
        if not pending:
            return
        self._backfill_running = True
        self.sound_signals.progress.emit(0, len(pending), 0)
        threading.Thread(target=self._backfill_worker, args=(pending,), daemon=True).start()

    def _backfill_worker(self, pending):
        total = len(pending)
        done = failed = 0
        for eng, word_ids in pending:
            with self._sound_lock:
                busy = eng in self._sound_downloading
                self._sound_downloading.add(eng)
            data = None
            if not busy:
                data = fetch_sound(eng)
                if data:
                    for word_id in word_ids:
                        store_sound(word_id, data)
                else:
                    failed += 1
            self.sound_signals.word_done.emit(word_ids[0], eng, bool(data))
            done += 1
            self.sound_signals.progress.emit(done, total, failed)
            time.sleep(SOUND_RETRY_DELAY)
            with self._sound_lock:
                self._sound_downloading.discard(eng)

    def _on_sound_saved(self, word_id, eng, ok):
        with self._sound_lock:
            self._sound_downloading.discard(eng)
        self._set_item_sound_icon(word_id, ok)
        if self._backfill_running:
            # The progress line is already covering the status bar.
            return
        if ok:
            self.status_label.setText(f"Sound saved for “{eng}”")
        else:
            self.status_label.setText(f"No online sound for “{eng}” — will retry next start")
        self._update_sound_buttons()

    def _on_sound_progress(self, done, total, failed):
        self._sound_progress_state = (done, total, failed)
        if total and done < total:
            # A recently played sound keeps its status line for a moment.
            if time.time() - getattr(self, "_sound_last_play", 0) < 5:
                return
            detail = f"Downloading sounds… {done}/{total}"
            if failed:
                detail += f" ({failed} missed)"
            self.status_label.setText(detail)
            return
        self._backfill_running = False
        message = f"Sound download finished — {total - failed} of {total} words have audio"
        if failed:
            message += f"; {failed} will retry on next start"
        self.status_label.setText(message)
        self._update_sound_buttons()

    def _set_item_sound_icon(self, word_id, has_sound):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if self._item_word_id(item) == word_id:
                item.setText(5, "🔊" if has_sound else "")
                return

    def _update_sound_buttons(self):
        items = self.tree.selectedItems()
        has_audio = bool(items) and bool(items[0].text(5))
        self.play_sound_btn.setEnabled(MULTIMEDIA_OK and has_audio)
        if not MULTIMEDIA_OK:
            self.play_sound_btn.setToolTip("Playback unavailable — PySide6.QtMultimedia is missing")

    def _on_item_clicked(self, item, column):
        """Clicking the Sound column cell plays that word's pronunciation."""
        if column != 5 or item is None or self._item_word_id(item) is None:
            return
        self.tree.clearSelection()
        item.setSelected(True)
        self.play_selected_sound()

    def play_selected_sound(self):
        """Play the stored MP3 for the selected list row (Ctrl+P)."""
        items = self.tree.selectedItems()
        if not items:
            self.status_label.setText("Select a word first to play its sound")
            return
        word_id = self._item_word_id(items[0])
        eng = items[0].text(1)
        data = get_sound(word_id) if word_id else None
        if data:
            self._play_sound_bytes(eng, data)
            self.status_label.setText(f"Playing sound for “{eng}”")
            return
        if not MULTIMEDIA_OK:
            self.status_label.setText("Playback unavailable — PySide6.QtMultimedia is missing")
            return
        with self._sound_lock:
            if eng in self._sound_downloading:
                return
            self._sound_downloading.add(eng)
        self.status_label.setText(f"Sound not stored yet for “{eng}” — fetching online…")
        threading.Thread(target=self._play_online_worker, args=(word_id, eng),
                         daemon=True).start()

    def play_editor_sound(self):
        """Play the pronunciation of the word being typed in the editor."""
        eng = normalize_myanmar_text(self.ent_eng.text()).strip()
        if not eng:
            self.status_label.setText("Type an English word first to hear its sound")
            return
        conn = sqlite3.connect(DB_FILE)
        try:
            row = conn.execute(
                "SELECT sound FROM words "
                "WHERE english = ? COLLATE NOCASE AND sound IS NOT NULL LIMIT 1",
                (eng,),
            ).fetchone()
        finally:
            conn.close()
        if row and row[0]:
            self._play_sound_bytes(eng, row[0])
            self.status_label.setText(f"Playing sound for “{eng}”")
            return
        if not MULTIMEDIA_OK:
            self.status_label.setText("Playback unavailable — PySide6.QtMultimedia is missing")
            return
        with self._sound_lock:
            if eng in self._sound_downloading:
                return
            self._sound_downloading.add(eng)
        self.status_label.setText(f"Fetching sound for “{eng}” online…")
        threading.Thread(target=self._play_online_worker, args=(None, eng), daemon=True).start()

    def _play_online_worker(self, word_id, eng):
        data = fetch_sound(eng)
        if data and word_id:
            store_sound(word_id, data)
        self.sound_signals.play_ready.emit(word_id or 0, eng, data)

    def _on_play_ready(self, word_id, eng, data):
        with self._sound_lock:
            self._sound_downloading.discard(eng)
        if data:
            if word_id:
                self._set_item_sound_icon(word_id, True)
                self._update_sound_buttons()
            self._play_sound_bytes(eng, data)
            self.status_label.setText(f"Playing sound for “{eng}”")
        else:
            self.status_label.setText(f"No online sound found for “{eng}”")

    def _play_sound_bytes(self, term, data):
        if not MULTIMEDIA_OK:
            self.status_label.setText("Playback unavailable — PySide6.QtMultimedia is missing")
            return
        try:
            self._sound_last_play = time.time()
            path = self._sound_temp_files.get(term)
            if path is None or not os.path.exists(path) or os.path.getsize(path) != len(data):
                handle, path = tempfile.mkstemp(prefix="vocapp_", suffix=".mp3")
                with os.fdopen(handle, "wb") as out:
                    out.write(data)
                self._sound_temp_files[term] = path
            self._media_player.stop()
            self._media_player.setSource(QUrl.fromLocalFile(path))
            self._media_player.play()
        except Exception as exc:
            self.status_label.setText(f"Could not play sound: {exc}")

    def submit_word(self):
        if self.editing_id is None:
            self.save_word()
        else:
            self.update_word()

    def _read_form(self):
        eng = normalize_myanmar_text(self.ent_eng.text())
        mm = normalize_myanmar_text(self.ent_mm.text())
        cn_raw = normalize_myanmar_text(self.ent_cn.text())
        cn = normalize_chinese_entry(cn_raw)
        if cn_raw and cn != cn_raw:
            # Show the converted text in the field (signals blocked so the hint survives).
            self.ent_cn.blockSignals(True)
            self.ent_cn.setText(cn)
            self.ent_cn.blockSignals(False)
            self._set_hint(self.cn_hint, "Auto-converted to Traditional + pinyin ✓", COLORS["accent_dark"])
        cat = self.normalize_category(self.combo_cat.currentText())
        if not eng or not mm:
            QMessageBox.warning(self, "Warning", "English and Myanmar text are required!")
            (self.ent_eng if not eng else self.ent_mm).setFocus()
            return None
        return eng, cn, mm, cat

    def save_word(self):
        values = self._read_form()
        if not values:
            return
        eng, cn, mm, cat = values
        try:
            conn = sqlite3.connect(DB_FILE)
            try:
                word_id = conn.execute(
                    "INSERT INTO words (english, chinese, myanmar, category) VALUES (?,?,?,?)",
                    (eng, cn, mm, cat),
                ).lastrowid
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Save failed", f"Could not save the word:\n{exc}")
            return
        self.clear_form()
        self._clear_filter()
        self._refresh_filter_options()
        self.load_words()
        self._reveal_word(word_id)
        self._queue_sound_download(word_id, eng)
        self.status_label.setText(f"Saved “{eng}” as {cat}")
        self.ent_eng.setFocus()

    def add_chinese(self):
        found = self.selected_word()
        if not found:
            return
        word_id, _values = found
        cn = normalize_chinese_entry(normalize_myanmar_text(self.ent_cn.text()))
        if not cn:
            QMessageBox.warning(self, "Warning", "Type the Chinese definition first.")
            return
        conn = sqlite3.connect(DB_FILE)
        conn.execute("UPDATE words SET chinese=? WHERE id=?", (cn, word_id))
        conn.commit()
        conn.close()
        self.ent_cn.clear()
        self.load_words()
        self.status_label.setText(f"Added Chinese to word #{word_id}")

    def edit_word(self):
        found = self.selected_word()
        if not found:
            return
        word_id, values = found
        self.ent_eng.setText(values[1])
        self.ent_cn.setText(values[2])
        self.ent_mm.setText(values[4])
        self.combo_cat.setCurrentText(self.normalize_category(values[3]))
        self.editing_id = word_id
        self._editing_english = values[1]
        self.save_button.setText("Update")
        self.cancel_button.setEnabled(True)
        self.ent_eng.setFocus()
        self.status_label.setText(f"Editing word #{word_id} — press Update to save")

    def update_word(self):
        values = self._read_form()
        if not values:
            return
        eng, cn, mm, cat = values
        word_id = self.editing_id
        try:
            conn = sqlite3.connect(DB_FILE)
            try:
                conn.execute(
                    "UPDATE words SET english=?, chinese=?, myanmar=?, category=? WHERE id=?",
                    (eng, cn, mm, cat, word_id),
                )
                conn.commit()
            finally:
                conn.close()
        except sqlite3.Error as exc:
            QMessageBox.critical(self, "Save failed", f"Could not update the word:\n{exc}")
            return
        previous_english = getattr(self, "_editing_english", None)
        self.cancel_edit()
        self._clear_filter()
        self._refresh_filter_options()
        self.load_words()
        self._reveal_word(word_id)
        # Re-download when the English word changed or no audio exists yet.
        if eng != previous_english or get_sound(word_id) is None:
            self._queue_sound_download(word_id, eng)
        self.status_label.setText(f"Updated word #{word_id}")
        self.ent_eng.setFocus()

    def cancel_edit(self):
        self.editing_id = None
        self._editing_english = None
        self.save_button.setText("Save Word")
        self.cancel_button.setEnabled(False)
        self.combo_cat.setCurrentText(CATEGORIES[0])
        self.clear_form()

    def _clear_filter(self):
        if self.ent_search.text():
            self.ent_search.blockSignals(True)
            self.ent_search.clear()
            self.ent_search.blockSignals(False)
        if self.filter_box.currentIndex() != 0:
            self.filter_box.blockSignals(True)
            self.filter_box.setCurrentIndex(0)
            self.filter_box.blockSignals(False)

    def _reveal_word(self, word_id):
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if self._item_word_id(item) == word_id:
                self.tree.clearSelection()
                item.setSelected(True)
                self.tree.scrollToItem(item)
                break

    def clear_form(self):
        self.ent_eng.clear()
        self.ent_mm.clear()
        self.ent_cn.clear()
        self._set_hint(self.mm_hint, "", "")
        self._set_hint(self.cn_hint, "", "")
        self._lookup_timer.stop()

    def delete_word(self):
        items = self.tree.selectedItems()
        if not items:
            return
        ids = []
        for item in items:
            word_id = self._item_word_id(item)
            if word_id is None:
                return
            ids.append(word_id)
        answer = QMessageBox.question(
            self, "Confirm", f"Delete {len(ids)} selected word(s)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        conn = sqlite3.connect(DB_FILE)
        for word_id in ids:
            conn.execute("DELETE FROM words WHERE id=?", (word_id,))
        conn.commit()
        conn.close()
        self._refresh_filter_options()
        self.load_words()
        self.status_label.setText(f"Deleted {len(ids)} word(s)")

    def _current_rows(self):
        """Run the query matching the current filter, search and sort state."""
        term = normalize_myanmar_text(self.ent_search.text())

        def like_pattern(value):
            # % and _ are LIKE wildcards; a literal % in a word must not
            # match everything (and a bare % must not match nothing)
            escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            return f"%{escaped}%"

        q = like_pattern(term)
        category = self.current_category_filter()
        order = "DESC" if self.sort_desc else "ASC"
        if not 0 <= self.sort_col < len(self.tree_columns):
            self.sort_col = 0
        col = self.tree_columns[self.sort_col]
        if col == "id":
            sql_order = f"words.id {order}"
        elif col == "sound":
            # Words that already have audio group together.
            sql_order = f"(words.sound IS NULL) {order}, words.id DESC"
        else:
            sql_order = f"{col} COLLATE NOCASE {order}, words.id DESC"
        clauses = []
        params = []
        if category:
            clauses.append("(LOWER(category) = LOWER(?))")
            params.append(category)
        if term:
            # The library stores Traditional Chinese, so always search for the
            # Simplified spelling too — users type either script.
            chinese_variants = [term]
            converted = _simplified_to_traditional(term)
            if converted != term:
                chinese_variants.append(converted)
            chinese_alts = " OR ".join(["chinese LIKE ? ESCAPE '\\'"] * len(chinese_variants))
            clauses.append(
                "(english LIKE ? ESCAPE '\\' OR myanmar LIKE ? ESCAPE '\\' "
                "OR category LIKE ? ESCAPE '\\' OR %s)" % chinese_alts
            )
            params.extend([q, q, q])
            params.extend(like_pattern(variant) for variant in chinese_variants)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            f"SELECT {', '.join(self.tree_columns)} FROM words {where} ORDER BY {sql_order}",
            params,
        ).fetchall()
        conn.close()
        return rows

    def load_words(self, *_args):
        rows = self._current_rows()
        term = normalize_myanmar_text(self.ent_search.text())
        category = self.current_category_filter()

        self.tree.clear()
        for row_number, row in enumerate(rows, start=1):
            # Query order is (id, english, chinese, category, myanmar, sound).
            word_id, english, chinese, category, myanmar, sound = (
                row[0], row[1], row[2],
                row[3] if len(row) > 4 and row[3] else CATEGORIES[0],
                row[4] if len(row) > 4 else "",
                row[5] if len(row) > 5 else None,
            )
            # Show a sequential number 1..N for the current view; keep the
            # real database id in the item's UserRole data for edit/delete.
            item = QTreeWidgetItem((
                str(row_number), english or "", chinese or "", category,
                myanmar or "", "🔊" if sound else "",
            ))
            item.setData(0, Qt.ItemDataRole.UserRole, word_id)
            item.setTextAlignment(5, Qt.AlignmentFlag.AlignCenter)
            item.setToolTip(
                5,
                "Click to play pronunciation"
                if sound else "Click to download & play pronunciation",
            )
            self.tree.addTopLevelItem(item)

        if len(rows) == 0:
            if term:
                message = "No words match \u201c%s\u201d — try another search" % term
            elif category:
                message = "No %s words yet — add one above" % category
            else:
                message = "Your library is empty — add your first word above"
            item = QTreeWidgetItem(("", message, "", "", "", ""))
            item.setForeground(1, self.palette().color(self.palette().ColorRole.Mid))
            self.tree.addTopLevelItem(item)

        self.tree.header().setSortIndicator(
            self.sort_col,
            Qt.SortOrder.DescendingOrder if self.sort_desc else Qt.SortOrder.AscendingOrder,
        )
        total = self._total_count()
        self.word_count_label.setText(f"{total} words")
        parts = []
        if category:
            parts.append(f"category: {category}")
        if term:
            parts.append(f"filter: \u201c{term}\u201d")
        self.status_label.setText(f"{len(rows)} shown" + (" • " + " • ".join(parts) if parts else ""))
        if self._backfill_running:
            # Keep the download progress visible after list refreshes.
            done, total, failed = getattr(self, "_sound_progress_state", (0, 0, 0))
            detail = f" • downloading sounds… {done}/{total}"
            if failed:
                detail += f" ({failed} missed)"
            self.status_label.setText(self.status_label.text() + detail)

    def _total_count(self):
        conn = sqlite3.connect(DB_FILE)
        total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        conn.close()
        return total

    def export_words(self):
        rows = self._current_rows()
        if not rows:
            QMessageBox.information(
                self, "Export", "There are no words to export with the current filter."
            )
            return
        path, selected_filter = QFileDialog.getSaveFileName(
            self, "Export Vocabulary", "vocabulary.csv", EXPORT_FILTER
        )
        if not path:
            return
        extension = os.path.splitext(path)[1].lower()
        if extension not in EXPORT_FORMATS:
            # Fall back to the format the user picked in the file-type dropdown.
            for extension, (_exporter, filter_label) in EXPORT_FORMATS.items():
                if filter_label == selected_filter:
                    break
            path += extension
        if extension not in EXPORT_FORMATS:
            QMessageBox.warning(self, "Export failed", "Unsupported file type: %s" % extension)
            return
        exporter, _filter_label = EXPORT_FORMATS[extension]
        try:
            exporter(path, rows)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", "Could not write %s:\n%s" % (path, exc))
            return
        word_count = len(rows)
        format_name = extension.lstrip(".").upper()
        self.status_label.setText(f"Exported {word_count} word(s) to {format_name} — {path}")

    def open_quiz(self):
        quiz = QDialog(self)
        quiz.setWindowTitle("VocApp | Quick Quiz")
        quiz.resize(1040, 680)
        quiz.setMinimumSize(860, 520)

        layout = QVBoxLayout(quiz)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame(objectName="header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        header_layout.setSpacing(3)
        title = QLabel("Quick Quiz", objectName="titleLabel")
        title.setStyleSheet("font-size: 16pt;")
        header_layout.addWidget(title)
        header_layout.addWidget(QLabel("A random set of 10 words from your library",
                                       objectName="subtitleLabel"))
        layout.addWidget(header)

        body = QWidget(objectName="quizBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(12)

        quiz_tree = QTreeWidget()
        quiz_tree.setObjectName("quizTree")
        cols = ("#", "English", "Category", "Myanmar", "Chinese")
        quiz_tree.setColumnCount(len(cols))
        quiz_tree.setHeaderLabels(cols)
        quiz_tree.setRootIsDecorated(False)
        quiz_tree.setAlternatingRowColors(True)
        quiz_tree.setSortingEnabled(False)
        # Taller rows so Myanmar script and Chinese text stay readable.
        quiz_tree.setStyleSheet("QTreeWidget::item { height: 42px; }")
        header_view = quiz_tree.header()
        header_view.setStretchLastSection(True)
        header_view.setSectionsMovable(False)
        header_view.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        for column, (width, mode) in enumerate((
                (44, QHeaderView.ResizeMode.Fixed),
                (200, QHeaderView.ResizeMode.Stretch),
                (170, QHeaderView.ResizeMode.Fixed),
                (300, QHeaderView.ResizeMode.Fixed),
                (260, QHeaderView.ResizeMode.Fixed))):
            header_view.setSectionResizeMode(column, mode)
            quiz_tree.setColumnWidth(column, width)
        body_layout.addWidget(quiz_tree, 1)

        quiz_status = QLabel("", objectName="hintLabel")
        quiz_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(quiz_status)

        refresh_btn = QPushButton("Refresh Items  (F5)", objectName="accentButton")
        refresh_btn.setMinimumWidth(220)
        refresh_shortcut = QShortcut(QKeySequence("F5"), quiz)
        refresh_shortcut.activated.connect(lambda: refresh_btn.click())

        base_font = QApplication.font()

        def refresh_quiz():
            quiz_tree.clear()
            conn = sqlite3.connect(DB_FILE)
            rows = conn.execute(
                "SELECT english, category, myanmar, chinese FROM words ORDER BY RANDOM() LIMIT 10"
            ).fetchall()
            total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
            conn.close()
            if not rows:
                rows = [("Add words first…", "—", "", "")]
            for number, row in enumerate(rows, start=1):
                row = list(row)
                if not row[1]:
                    row[1] = CATEGORIES[0]
                item = QTreeWidgetItem(
                    (str(number),) + tuple(str(x or "") for x in row))
                # Centre the number column and size Myanmar/Chinese text up.
                item.setTextAlignment(0, Qt.AlignmentFlag.AlignCenter)
                item.setFont(0, QFont(base_font.family(), 11, QFont.Weight.Bold))
                item.setFont(3, QFont(base_font.family(), 12))
                item.setFont(4, QFont(base_font.family(), 12))
                quiz_tree.addTopLevelItem(item)
            if total:
                quiz_status.setText(
                    f"Showing {len(rows)} random words of {total} — press F5 or Refresh for a new set")
            else:
                quiz_status.setText("Your library is empty — add words first")

        refresh_btn.clicked.connect(refresh_quiz)
        body_layout.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(body, 1)
        refresh_quiz()
        quiz.setWindowModality(Qt.WindowModality.WindowModal)
        quiz.exec()


# First family in the chain wins for each text run, so Latin letters are
# always drawn from a real English font instead of the Myanmar font's
# built-in (often mismatched) Latin glyphs, e.g. "ကျွန်မ Padauk ပါ။".
LATIN_FONT_CANDIDATES = (
    "Segoe UI",
    "Roboto",
    "Noto Sans",
    "Arial",
    "Helvetica",
)

# Last in the chain: covers Chinese runs that neither the Latin nor the
# Myanmar font provides.
CJK_FONT_CANDIDATES = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "SimSun",
)


def build_ui_font(myanmar_family):
    """Application font with a Latin -> Myanmar -> CJK fallback chain.

    Every run of text is rendered with the first family in the chain that
    provides its glyphs, so mixed English/Myanmar strings keep a uniform
    look instead of showing the Myanmar font's own Latin alphabet."""
    installed = set(QFontDatabase.families())
    families = [myanmar_family]
    for candidate in LATIN_FONT_CANDIDATES:
        if candidate in installed and candidate != myanmar_family:
            families.insert(0, candidate)
            break
    for candidate in CJK_FONT_CANDIDATES:
        if candidate in installed and candidate not in families:
            families.append(candidate)
            break
    font = QFont()
    font.setFamilies(families)
    font.setPointSize(11)
    font.setStyleHint(QFont.StyleHint.SansSerif)
    return font


def main():
    init_db()
    app = QApplication(sys.argv)
    font_family = resolve_myanmar_font_family()
    app.setFont(build_ui_font(font_family))
    app.setStyleSheet(STYLESHEET)
    window = VocabApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
