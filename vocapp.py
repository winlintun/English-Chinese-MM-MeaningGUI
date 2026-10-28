import html
import json
import os
import re
import sqlite3
import sys
import threading
import unicodedata
import urllib.parse
import urllib.request

from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vocabulary.db")
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")
SEARCH_PLACEHOLDER = "Search words…"
CATEGORIES = ("TOEIC", "TextBook")

MYORDBOK_URL = "https://myordbok.com/definition?q="
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
    for dirpath, _dirnames, filenames in os.walk(FONT_DIR):
        for filename in sorted(filenames):
            lower = filename.lower()
            if lower.endswith(".ttf") and "noto" in lower and (
                ("sans" in lower and "regular" in lower) or "normal" in lower
            ):
                return os.path.join(dirpath, filename)
    for dirpath, _dirnames, filenames in os.walk(FONT_DIR):
        for filename in sorted(filenames):
            lower = filename.lower()
            if lower.endswith(".ttf") and ("regular" in lower or "normal" in lower):
                return os.path.join(dirpath, filename)
    for dirpath, _dirnames, filenames in os.walk(FONT_DIR):
        for filename in sorted(filenames):
            if filename.lower().endswith(".ttf"):
                return os.path.join(dirpath, filename)
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


def _http_get(url, timeout=10):
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


def init_db():
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
    _migrate_myanmar_text(conn)
    conn.commit()
    conn.close()


def _migrate_myanmar_text(conn):
    """Normalize stored Myanmar text to clean NFC Unicode so it renders
    correctly with Noto Sans Myanmar."""
    rows = conn.execute("SELECT id, myanmar FROM words").fetchall()
    updated = 0
    for word_id, mm in rows:
        fixed = normalize_myanmar_text(mm)
        if fixed != (mm or ""):
            conn.execute("UPDATE words SET myanmar=? WHERE id=?", (fixed, word_id))
            updated += 1
    if updated:
        print("Normalized Myanmar text in %d row(s)" % updated)


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


class VocabApp(QMainWindow):
    tree_columns = ("id", "english", "chinese", "category", "myanmar")

    def __init__(self):
        super().__init__()
        self.editing_id = None
        self.sort_col = 0
        self.sort_desc = True

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

        self.reset_search(refresh=False)
        self.load_words()

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
        for col, widget in enumerate((self.ent_eng, self.ent_mm, self.ent_cn, self.combo_cat)):
            form.addWidget(widget, 1, col)
        form.setColumnStretch(0, 3)
        form.setColumnStretch(1, 3)
        form.setColumnStretch(2, 3)
        form.setColumnStretch(3, 2)

        actions = QVBoxLayout()
        actions.setSpacing(7)
        inner.addLayout(actions, 0)

        self.save_button = QPushButton("Save Word", objectName="accentButton")
        self.save_button.clicked.connect(self.save_word)
        self.cancel_button = QPushButton("Cancel Edit", objectName="softButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self.cancel_edit)
        self.hint_label = QLabel("Enter = save\nDouble-click a row to edit", objectName="hintLabel")
        actions.addWidget(self.save_button)
        actions.addWidget(self.cancel_button)
        actions.addWidget(self.hint_label)
        actions.addStretch(1)

        self.ent_eng.returnPressed.connect(self.save_word)
        self.ent_mm.returnPressed.connect(self.save_word)
        self.ent_cn.returnPressed.connect(self.save_word)
        self.ent_eng.installEventFilter(self)

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
        search_label = QLabel("Search", objectName="mutedLabel")
        toolbar.addWidget(search_label)
        self.ent_search = QLineEdit()
        self.ent_search.setPlaceholderText(SEARCH_PLACEHOLDER)
        self.ent_search.setFixedWidth(320)
        self.ent_search.textChanged.connect(self.load_words)
        toolbar.addWidget(self.ent_search)
        clear_btn = QPushButton("Clear", objectName="softButton")
        clear_btn.clicked.connect(self.reset_search)
        toolbar.addWidget(clear_btn)
        refresh_btn = QPushButton("Refresh", objectName="softButton")
        refresh_btn.clicked.connect(self.load_words)
        toolbar.addWidget(refresh_btn)
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
        header.setSortIndicator(0, Qt.SortOrder.DescendingOrder)
        header.setSectionsMovable(False)
        for i, width in enumerate((48, 240, 200, 110, 270)):
            self.tree.setColumnWidth(i, width)
        self.tree.setFrameShape(QFrame.StyledPanel)
        layout.addWidget(self.tree, 1)

        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_word())
        QShortcut(QKeySequence.Delete, self.tree, activated=self.delete_word)
        QShortcut(QKeySequence("Return"), self.tree, activated=self.edit_word)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        edit_btn = QPushButton("Edit Selected (Enter)", objectName="softButton")
        edit_btn.clicked.connect(self.edit_word)
        delete_btn = QPushButton("Delete Selected", objectName="dangerButton")
        delete_btn.clicked.connect(self.delete_word)
        add_cn_btn = QPushButton("Add Chinese to Selected", objectName="softButton")
        add_cn_btn.clicked.connect(self.add_chinese)
        quiz_btn = QPushButton("Open Quiz", objectName="accentButton")
        quiz_btn.clicked.connect(self.open_quiz)
        actions.addWidget(edit_btn)
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
        self.ent_search.clear()
        if refresh:
            self.load_words()

    def on_sort_indicator(self, col, order):
        self.sort_col = col
        self.sort_desc = order == Qt.SortOrder.DescendingOrder
        self.load_words()

    def selected_word(self):
        items = self.tree.selectedItems()
        if not items:
            QMessageBox.information(self, "Info", "Please select a word in the table first.")
            return None
        values = items[0].text(0)
        try:
            word_id = int(values)
        except ValueError:
            return None
        texts = [items[0].text(i) for i in range(5)]
        return word_id, texts

    def normalize_category(self, value):
        value = (value or "").strip().lower()
        for cat in CATEGORIES:
            if value == cat.lower():
                return cat
        return CATEGORIES[0]

    def auto_lookup(self):
        eng = normalize_myanmar_text(self.ent_eng.text())
        if not eng:
            return
        needs_mm = not self.ent_mm.text().strip()
        needs_cn = not self.ent_cn.text().strip()
        if not needs_mm and not needs_cn:
            return
        self.status_label.setText(f"Looking up “{eng}” online…")
        threading.Thread(target=self._lookup_worker, args=(eng, needs_mm, needs_cn),
                         daemon=True).start()

    def _lookup_worker(self, eng, needs_mm, needs_cn):
        mm = lookup_myanmar(eng) if needs_mm else None
        cn = lookup_chinese(eng) if needs_cn else None
        QTimer.singleShot(0, lambda: self._apply_lookup(eng, mm, cn))

    def _apply_lookup(self, eng, mm, cn):
        if normalize_myanmar_text(self.ent_eng.text()) != eng:
            return
        filled = []
        if mm and not self.ent_mm.text().strip():
            self.ent_mm.setText(normalize_myanmar_text(mm))
            filled.append("Myanmar")
        if cn and not self.ent_cn.text().strip():
            self.ent_cn.setText(cn)
            filled.append("Chinese")
        if filled:
            self.status_label.setText(f"Auto-filled {' & '.join(filled)} for “{eng}”")
        else:
            self.status_label.setText(f"No online result found for “{eng}”")

    def save_word(self):
        eng = normalize_myanmar_text(self.ent_eng.text())
        mm = normalize_myanmar_text(self.ent_mm.text())
        cn = normalize_myanmar_text(self.ent_cn.text())
        cat = self.normalize_category(self.combo_cat.currentText())
        if not eng or not mm:
            QMessageBox.warning(self, "Warning", "English and Myanmar text are required!")
            return
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO words (english, chinese, myanmar, category) VALUES (?,?,?,?)",
                     (eng, cn, mm, cat))
        conn.commit()
        conn.close()
        self.clear_form()
        self.load_words()
        self.status_label.setText(f"Saved “{eng}” as {cat}")
        self.ent_eng.setFocus()

    def add_chinese(self):
        found = self.selected_word()
        if not found:
            return
        word_id, _values = found
        cn = normalize_myanmar_text(self.ent_cn.text())
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
        self.save_button.setText("Update")
        try:
            self.save_button.clicked.disconnect(self.save_word)
        except RuntimeError:
            pass
        self.save_button.clicked.connect(self.update_word)
        self.cancel_button.setEnabled(True)
        self.ent_eng.setFocus()
        self.status_label.setText(f"Editing word #{word_id} — press Update to save")

    def update_word(self):
        eng = normalize_myanmar_text(self.ent_eng.text())
        mm = normalize_myanmar_text(self.ent_mm.text())
        cn = normalize_myanmar_text(self.ent_cn.text())
        cat = self.normalize_category(self.combo_cat.currentText())
        if not eng or not mm:
            QMessageBox.warning(self, "Warning", "English and Myanmar text are required!")
            return

        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "UPDATE words SET english=?, chinese=?, myanmar=?, category=? WHERE id=?",
            (eng, cn, mm, cat, self.editing_id),
        )
        conn.commit()
        conn.close()
        word_id = self.editing_id
        self.cancel_edit()
        self.load_words()
        self.status_label.setText(f"Updated word #{word_id}")

    def cancel_edit(self):
        self.editing_id = None
        try:
            self.save_button.clicked.disconnect()
        except RuntimeError:
            pass
        self.save_button.setText("Save Word")
        self.save_button.clicked.connect(self.save_word)
        self.cancel_button.setEnabled(False)
        self.combo_cat.setCurrentText(CATEGORIES[0])
        self.clear_form()

    def clear_form(self):
        self.ent_eng.clear()
        self.ent_mm.clear()
        self.ent_cn.clear()

    def delete_word(self):
        items = self.tree.selectedItems()
        if not items:
            return
        ids = []
        for item in items:
            try:
                ids.append(int(item.text(0)))
            except ValueError:
                return
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
        self.load_words()
        self.status_label.setText(f"Deleted {len(ids)} word(s)")

    def load_words(self, *_args):
        term = normalize_myanmar_text(self.ent_search.text())
        q = f"%{term}%"
        order = "DESC" if self.sort_desc else "ASC"
        col = self.tree_columns[self.sort_col]
        if col == "id":
            sql_order = f"words.id {order}"
        else:
            sql_order = f"{col} COLLATE NOCASE {order}, words.id DESC"
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT * FROM words WHERE english LIKE ? OR myanmar LIKE ? OR chinese LIKE ? OR category LIKE ? "
            f"ORDER BY {sql_order}",
            (q, q, q, q),
        ).fetchall()
        conn.close()

        self.tree.clear()
        for row in rows:
            word_id, english, chinese, myanmar = row[0], row[1], row[2], row[3]
            category = row[4] if len(row) > 4 and row[4] else CATEGORIES[0]
            item = QTreeWidgetItem((str(word_id), english or "", chinese or "", category, myanmar or ""))
            self.tree.addTopLevelItem(item)

        if len(rows) == 0:
            if term:
                message = "No words match \u201c%s\u201d — try another search" % term
            else:
                message = "Your library is empty — add your first word above"
            item = QTreeWidgetItem(("", message, "", "", ""))
            item.setForeground(1, self.palette().color(self.palette().ColorRole.Mid))
            self.tree.addTopLevelItem(item)

        self.tree.header().setSortIndicator(
            self.sort_col,
            Qt.SortOrder.DescendingOrder if self.sort_desc else Qt.SortOrder.AscendingOrder,
        )
        total = self._total_count()
        self.word_count_label.setText(f"{total} words")
        self.status_label.setText(f"{len(rows)} shown" + (f" • filter: \u201c{term}\u201d" if term else ""))

    def _total_count(self):
        conn = sqlite3.connect(DB_FILE)
        total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        conn.close()
        return total

    def open_quiz(self):
        quiz = QDialog(self)
        quiz.setWindowTitle("VocApp | Quick Quiz")
        quiz.resize(900, 520)
        quiz.setMinimumSize(780, 420)

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
        header_layout.addWidget(QLabel("A fresh set of 10 words from your library",
                                       objectName="subtitleLabel"))
        layout.addWidget(header)

        body = QWidget(objectName="quizBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(20, 20, 20, 20)
        body_layout.setSpacing(12)

        quiz_tree = QTreeWidget()
        cols = ("number", "english", "category", "myanmar", "chinese")
        quiz_tree.setColumnCount(5)
        quiz_tree.setHeaderLabels([c.capitalize() for c in cols])
        quiz_tree.setRootIsDecorated(False)
        quiz_tree.setAlternatingRowColors(True)
        quiz_tree.setSortingEnabled(False)
        quiz_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        body_layout.addWidget(quiz_tree, 1)

        refresh_btn = QPushButton("Refresh Items", objectName="accentButton")

        def refresh_quiz():
            quiz_tree.clear()
            conn = sqlite3.connect(DB_FILE)
            rows = conn.execute(
                "SELECT english, category, myanmar, chinese FROM words ORDER BY RANDOM() LIMIT 10"
            ).fetchall()
            conn.close()
            if not rows:
                rows = [("Add words first…", "—", "", "")]
            for number, row in enumerate(rows, start=1):
                row = list(row)
                if not row[1]:
                    row[1] = CATEGORIES[0]
                quiz_tree.addTopLevelItem(
                    QTreeWidgetItem((str(number),) + tuple(str(x or "") for x in row)))

        refresh_btn.clicked.connect(refresh_quiz)
        body_layout.addWidget(refresh_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(body, 1)
        refresh_quiz()
        quiz.setWindowModality(Qt.WindowModality.WindowModal)
        quiz.exec()


def main():
    init_db()
    app = QApplication(sys.argv)
    font_family = resolve_myanmar_font_family()
    app.setFont(QFont(font_family, 11))
    app.setStyleSheet(STYLESHEET)
    window = VocabApp()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
