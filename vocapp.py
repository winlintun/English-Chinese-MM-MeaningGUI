import html
import json
import os
import re
import sqlite3
import threading
import tkinter as tk
import unicodedata
import urllib.parse
import urllib.request
from tkinter import ttk, messagebox
import tkinter.font as tkfont

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


def get_myanmar_font_family():
    available_fonts = set(tkfont.families())
    for family in ("Padauk", "Noto Sans Myanmar", "Noto Sans Myanmar UI", "Myanmar Text", "Myanmar3"):
        if family in available_fonts:
            return family, None

    if os.path.isdir(FONT_DIR):
        font_candidates = []
        for filename in sorted(os.listdir(FONT_DIR)):
            if filename.lower().endswith(".ttf"):
                lower = filename.lower()
                if "regular" in lower or "normal" in lower:
                    font_candidates.insert(0, filename)
                else:
                    font_candidates.append(filename)
        if font_candidates:
            return "CustomMyanmar", os.path.join(FONT_DIR, font_candidates[0])

    return "Arial", None


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


def configure_default_fonts(root, font_family):
    for name in ("TkDefaultFont", "TkTextFont", "TkFixedFont"):
        try:
            tkfont.nametofont(name).configure(family=font_family, size=11)
        except tk.TclError:
            pass

    try:
        tkfont.nametofont("TkEntryFont").configure(family=font_family, size=11)
    except tk.TclError:
        pass

    root.option_add("*Font", "{{{}}} 11".format(font_family))


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
    conn.commit()
    conn.close()


class VocabApp:
    def __init__(self, root):
        self.root = root
        self.editing_id = None
        self.sort_col = "id"
        self.sort_desc = True
        self.search_placeholder_active = False

        root.title("VocApp | Vocabulary Workspace")
        root.geometry("1060x700")
        root.minsize(700, 480)
        root.configure(bg=COLORS["bg"])

        self.myanmar_font_family, self.myanmar_font_file = get_myanmar_font_family()
        if self.myanmar_font_file:
            self.myanmar_font = tkfont.Font(family="CustomMyanmar", size=12, file=self.myanmar_font_file)
            self.heading_font = tkfont.Font(family="CustomMyanmar", size=10, weight="bold", file=self.myanmar_font_file)
            configure_default_fonts(root, "CustomMyanmar")
        else:
            self.myanmar_font = tkfont.Font(family=self.myanmar_font_family, size=12)
            self.heading_font = tkfont.Font(family=self.myanmar_font_family, size=10, weight="bold")
            configure_default_fonts(root, self.myanmar_font_family)

        self.word_count_var = tk.StringVar(value="0 words")
        self.status_var = tk.StringVar(value="Ready")

        self._setup_style()

        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        self._build_header()
        self._build_editor()
        self._build_library()
        self._build_statusbar()

        root.bind("<Control-f>", self._focus_search)
        root.bind("<Escape>", self._escape_search)

        self.reset_search(refresh=False)
        self.load_words()

    def _setup_style(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure("App.TFrame", background=COLORS["bg"])
        style.configure("Header.TFrame", background=COLORS["header"])
        style.configure("Card.TLabelframe", background=COLORS["card"], bordercolor=COLORS["border"],
                        relief="solid", borderwidth=1)
        style.configure("Card.TLabelframe.Label", background=COLORS["card"], foreground=COLORS["header"],
                        font=self.heading_font)
        style.configure("Title.TLabel", background=COLORS["header"], foreground=COLORS["header_text"],
                        font=(self.myanmar_font_family, 22, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["header"], foreground=COLORS["header_muted"],
                        font=(self.myanmar_font_family, 10))
        style.configure("Chip.TLabel", background=COLORS["accent"], foreground="#ffffff",
                        font=(self.myanmar_font_family, 10, "bold"), padding=(14, 5))
        style.configure("Section.TLabel", background=COLORS["card"], foreground=COLORS["muted"],
                        font=self.heading_font)
        style.configure("Muted.TLabel", background=COLORS["bg"], foreground=COLORS["muted"],
                        font=(self.myanmar_font_family, 10))
        style.configure("Hint.TLabel", background=COLORS["card"], foreground=COLORS["muted"],
                        font=(self.myanmar_font_family, 9))
        style.configure("Status.TLabel", background=COLORS["border"], foreground=COLORS["muted"],
                        font=(self.myanmar_font_family, 9), padding=(24, 6))

        style.configure("Accent.TButton", background=COLORS["accent"], foreground="#ffffff",
                        padding=(16, 8), borderwidth=0, font=self.heading_font, focusthickness=0)
        style.map("Accent.TButton", background=[("active", COLORS["accent_dark"]),
                                                ("pressed", COLORS["accent_dark"])])
        style.configure("Soft.TButton", background=COLORS["soft"], foreground=COLORS["header"],
                        padding=(12, 8), borderwidth=0)
        style.map("Soft.TButton", background=[("active", COLORS["soft_hover"]),
                                              ("pressed", COLORS["soft_hover"])])
        style.configure("Danger.TButton", background=COLORS["danger"], foreground=COLORS["danger_text"],
                        padding=(12, 8), borderwidth=0)
        style.map("Danger.TButton", background=[("active", COLORS["danger_hover"]),
                                                ("pressed", COLORS["danger_hover"])])

        style.configure("Treeview", background=COLORS["card"], fieldbackground=COLORS["card"],
                        foreground=COLORS["text"], font=self.myanmar_font, rowheight=36,
                        borderwidth=0)
        style.map("Treeview", background=[("selected", COLORS["selected"])],
                  foreground=[("selected", COLORS["header"])])
        style.configure("Treeview.Heading", background=COLORS["soft"], foreground=COLORS["header"],
                        font=self.heading_font, padding=(6, 7), borderwidth=0)
        style.map("Treeview.Heading", background=[("active", COLORS["soft_hover"])])

        style.configure("TEntry", fieldbackground=COLORS["card"], foreground=COLORS["text"], padding=8,
                        bordercolor=COLORS["border"], insertcolor=COLORS["text"])
        style.map("TEntry", bordercolor=[("focus", COLORS["accent"])],
                  lightcolor=[("focus", COLORS["accent"])])
        style.configure("TCombobox", fieldbackground=COLORS["card"], foreground=COLORS["text"],
                        padding=6, bordercolor=COLORS["border"], arrowcolor=COLORS["header"])
        style.map("TCombobox", bordercolor=[("focus", COLORS["accent"])],
                  lightcolor=[("focus", COLORS["accent"])])

    def _build_header(self):
        header = ttk.Frame(self.root, style="Header.TFrame", padding=(28, 20))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        title_row = ttk.Frame(header, style="Header.TFrame")
        title_row.grid(row=0, column=0, sticky="ew")
        ttk.Label(title_row, text="VocApp", style="Title.TLabel").pack(side="left")
        ttk.Label(title_row, textvariable=self.word_count_var, style="Chip.TLabel").pack(side="left", padx=(18, 0))

        ttk.Label(header, text="Build your vocabulary, one word at a time",
                  style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))

    def _build_editor(self):
        editor = ttk.LabelFrame(self.root, text="  Word details  ", style="Card.TLabelframe",
                                padding=(20, 14))
        editor.grid(row=1, column=0, sticky="ew", padx=24, pady=(18, 12))
        editor.columnconfigure(0, weight=3)
        editor.columnconfigure(1, weight=3)
        editor.columnconfigure(2, weight=3)
        editor.columnconfigure(3, weight=2)
        editor.columnconfigure(4, weight=0)

        form = ttk.Frame(editor, style="Card.TLabelframe")
        form.grid(row=0, column=0, columnspan=4, sticky="ew")
        form.columnconfigure(0, weight=3)
        form.columnconfigure(1, weight=3)
        form.columnconfigure(2, weight=3)
        form.columnconfigure(3, weight=2)

        ttk.Label(form, text="English", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 10))
        ttk.Label(form, text="Myanmar", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=5)
        ttk.Label(form, text="Chinese (optional)", style="Section.TLabel").grid(row=0, column=2, sticky="w", padx=5)
        ttk.Label(form, text="Category", style="Section.TLabel").grid(row=0, column=3, sticky="w", padx=(10, 0))

        self.ent_eng = ttk.Entry(form, font=self.myanmar_font)
        self.ent_eng.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(6, 0))
        self.ent_mm = ttk.Entry(form, font=self.myanmar_font)
        self.ent_mm.grid(row=1, column=1, sticky="ew", padx=5, pady=(6, 0))
        self.ent_cn = ttk.Entry(form, font=self.myanmar_font)
        self.ent_cn.grid(row=1, column=2, sticky="ew", padx=5, pady=(6, 0))
        self.combo_cat = ttk.Combobox(form, values=CATEGORIES, state="readonly", font=self.myanmar_font)
        self.combo_cat.current(0)
        self.combo_cat.grid(row=1, column=3, sticky="ew", padx=(10, 0), pady=(6, 0))

        for entry in (self.ent_eng, self.ent_mm, self.ent_cn):
            entry.bind("<Return>", lambda e: self.save_word())
        self.ent_eng.bind("<FocusOut>", self._auto_lookup)

        form_actions = ttk.Frame(editor, style="Card.TLabelframe")
        form_actions.grid(row=0, column=4, rowspan=2, padx=(18, 0), sticky="ns")
        self.save_button = ttk.Button(form_actions, text="Save Word", command=self.save_word,
                                      style="Accent.TButton")
        self.save_button.pack(fill="x")
        self.cancel_button = ttk.Button(form_actions, text="Cancel Edit", command=self.cancel_edit,
                                        state="disabled", style="Soft.TButton")
        self.cancel_button.pack(fill="x", pady=(7, 0))
        self.hint_label = ttk.Label(form_actions, text="Enter = save\nDouble-click a row to edit",
                                    style="Hint.TLabel", justify="left")
        self.hint_label.pack(pady=(10, 0), anchor="w")

        self._editor = editor
        self._form_actions = form_actions
        self._editor_compact = False
        editor.bind("<Configure>", self._editor_reflow)

    def _editor_reflow(self, event):
        compact = event.width < 820
        if compact == self._editor_compact:
            return
        self._editor_compact = compact
        if compact:
            self._form_actions.grid_configure(row=2, column=0, columnspan=4, rowspan=1,
                                              padx=(0, 0), pady=(12, 0), sticky="e")
            self.hint_label.pack_forget()
        else:
            self._form_actions.grid_configure(row=0, column=4, columnspan=1, rowspan=2,
                                              padx=(18, 0), pady=0, sticky="ns")
            self.hint_label.pack(pady=(10, 0), anchor="w")

    def _build_library(self):
        library = ttk.Frame(self.root, style="App.TFrame", padding=(24, 0, 24, 16))
        library.grid(row=2, column=0, sticky="nsew")
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)

        toolbar = ttk.Frame(library, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(2, weight=1)
        ttk.Label(toolbar, text="Your vocabulary", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text="Search", style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(20, 8))
        self.ent_search = ttk.Entry(toolbar, width=32, font=self.myanmar_font,
                                    foreground=COLORS["muted"])
        self.ent_search.grid(row=0, column=2, sticky="ew")
        self.ent_search.bind("<KeyRelease>", self.load_words)
        self.ent_search.bind("<FocusIn>", self._search_focus_in)
        self.ent_search.bind("<FocusOut>", self._search_focus_out)
        ttk.Button(toolbar, text="Clear", command=self.reset_search,
                   style="Soft.TButton").grid(row=0, column=3, padx=(8, 0))
        ttk.Button(toolbar, text="Refresh", command=self.load_words,
                   style="Soft.TButton").grid(row=0, column=4, padx=(4, 0))

        table_frame = ttk.Frame(library, style="App.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree_cols = ("id", "english", "chinese", "category", "myanmar")
        self.tree = ttk.Treeview(table_frame, columns=self.tree_cols, show="headings",
                                 selectmode="extended")
        widths = {"id": 48, "english": 240, "chinese": 200, "category": 110, "myanmar": 270}
        minwidths = {"id": 40, "english": 90, "chinese": 80, "category": 70, "myanmar": 90}
        for c in self.tree_cols:
            self.tree.heading(c, text=c.capitalize(), command=lambda col=c: self.sort_by(col))
            self.tree.column(c, width=widths[c], minwidth=minwidths[c],
                             anchor="center" if c == "id" else "w", stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.tag_configure("odd", background=COLORS["card"])
        self.tree.tag_configure("even", background=COLORS["stripe"])
        self.tree.tag_configure("empty", foreground=COLORS["muted"])
        self.tree.bind("<Double-1>", lambda e: self.edit_word())
        self.tree.bind("<Delete>", lambda e: self.delete_word())
        self.update_sort_headings()

        actions = ttk.Frame(library, style="App.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Edit Selected (Enter)", command=self.edit_word,
                   style="Soft.TButton").pack(side="left")
        ttk.Button(actions, text="Delete Selected", command=self.delete_word,
                   style="Danger.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Add Chinese to Selected", command=self.add_chinese,
                   style="Soft.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Open Quiz", command=self.open_quiz,
                   style="Accent.TButton").pack(side="right")

    def _build_statusbar(self):
        statusbar = ttk.Label(self.root, textvariable=self.status_var, style="Status.TLabel")
        statusbar.grid(row=3, column=0, sticky="ew")

    def _search_focus_in(self, _event=None):
        if self.search_placeholder_active:
            self.ent_search.delete(0, "end")
            self.ent_search.configure(foreground=COLORS["text"])
            self.search_placeholder_active = False

    def _search_focus_out(self, _event=None):
        if not self.ent_search.get():
            self.reset_search(refresh=False)

    def _focus_search(self, _event=None):
        self.ent_search.focus_set()

    def _escape_search(self, _event=None):
        if self.root.focus_get() is self.ent_search:
            self.reset_search()
            self.root.focus_set()

    def reset_search(self, refresh=True):
        self.search_placeholder_active = True
        self.ent_search.delete(0, "end")
        self.ent_search.insert(0, SEARCH_PLACEHOLDER)
        self.ent_search.configure(foreground=COLORS["muted"])
        if refresh:
            self.load_words()

    def _search_term(self):
        if self.search_placeholder_active:
            return ""
        return normalize_myanmar_text(self.ent_search.get())

    def sort_by(self, col):
        if col == self.sort_col:
            self.sort_desc = not self.sort_desc
        else:
            self.sort_col = col
            self.sort_desc = False
        self.update_sort_headings()
        self.load_words()

    def update_sort_headings(self):
        for c in self.tree_cols:
            arrow = ""
            if c == self.sort_col:
                arrow = " ▼" if self.sort_desc else " ▲"
            self.tree.heading(c, text=c.capitalize() + arrow)

    def _selected_word(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Please select a word in the table first.")
            return None
        values = self.tree.item(sel[0])["values"]
        try:
            word_id = int(values[0])
        except (TypeError, ValueError):
            return None
        return word_id, values

    def _normalize_category(self, value):
        value = (value or "").strip().lower()
        for cat in CATEGORIES:
            if value == cat.lower():
                return cat
        return CATEGORIES[0]

    def _auto_lookup(self, _event=None):
        eng = normalize_myanmar_text(self.ent_eng.get())
        if not eng:
            return
        needs_mm = not self.ent_mm.get().strip()
        needs_cn = not self.ent_cn.get().strip()
        if not needs_mm and not needs_cn:
            return
        self.status_var.set(f"Looking up “{eng}” online…")
        threading.Thread(target=self._lookup_worker, args=(eng, needs_mm, needs_cn),
                         daemon=True).start()

    def _lookup_worker(self, eng, needs_mm, needs_cn):
        mm = lookup_myanmar(eng) if needs_mm else None
        cn = lookup_chinese(eng) if needs_cn else None
        self.root.after(0, lambda: self._apply_lookup(eng, mm, cn))

    def _apply_lookup(self, eng, mm, cn):
        if normalize_myanmar_text(self.ent_eng.get()) != eng:
            return
        filled = []
        if mm and not self.ent_mm.get().strip():
            self.ent_mm.delete(0, "end")
            self.ent_mm.insert(0, normalize_myanmar_text(mm))
            filled.append("Myanmar")
        if cn and not self.ent_cn.get().strip():
            self.ent_cn.delete(0, "end")
            self.ent_cn.insert(0, cn)
            filled.append("Chinese")
        if filled:
            self.status_var.set(f"Auto-filled {' & '.join(filled)} for “{eng}”")
        else:
            self.status_var.set(f"No online result found for “{eng}”")

    def save_word(self):
        eng = normalize_myanmar_text(self.ent_eng.get())
        mm = normalize_myanmar_text(self.ent_mm.get())
        cn = normalize_myanmar_text(self.ent_cn.get())
        cat = self._normalize_category(self.combo_cat.get())
        if not eng or not mm:
            messagebox.showwarning("Warning", "English and Myanmar text are required!")
            return
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO words (english, chinese, myanmar, category) VALUES (?,?,?,?)",
                     (eng, cn, mm, cat))
        conn.commit()
        conn.close()
        self.clear_form()
        self.load_words()
        self.status_var.set(f"Saved “{eng}” as {cat}")
        self.ent_eng.focus_set()

    def add_chinese(self):
        found = self._selected_word()
        if not found:
            return
        word_id, _values = found
        cn = normalize_myanmar_text(self.ent_cn.get())
        if not cn:
            messagebox.showwarning("Warning", "Type the Chinese definition first.")
            return
        conn = sqlite3.connect(DB_FILE)
        conn.execute("UPDATE words SET chinese=? WHERE id=?", (cn, word_id))
        conn.commit()
        conn.close()
        self.ent_cn.delete(0, "end")
        self.load_words()
        self.status_var.set(f"Added Chinese to word #{word_id}")

    def edit_word(self):
        found = self._selected_word()
        if not found:
            return
        word_id, values = found
        self.ent_eng.delete(0, "end")
        self.ent_eng.insert(0, values[1])
        self.ent_cn.delete(0, "end")
        self.ent_cn.insert(0, values[2])
        self.ent_mm.delete(0, "end")
        self.ent_mm.insert(0, values[4])
        self.combo_cat.set(self._normalize_category(values[3]))
        self.editing_id = word_id
        self.save_button.configure(text="Update", command=self.update_word)
        self.cancel_button.configure(state="normal")
        self.ent_eng.focus_set()
        self.status_var.set(f"Editing word #{word_id} — press Update to save")

    def update_word(self):
        eng = normalize_myanmar_text(self.ent_eng.get())
        mm = normalize_myanmar_text(self.ent_mm.get())
        cn = normalize_myanmar_text(self.ent_cn.get())
        cat = self._normalize_category(self.combo_cat.get())
        if not eng or not mm:
            messagebox.showwarning("Warning", "English and Myanmar text are required!")
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
        self.status_var.set(f"Updated word #{word_id}")

    def cancel_edit(self):
        self.editing_id = None
        self.save_button.configure(text="Save Word", command=self.save_word)
        self.cancel_button.configure(state="disabled")
        self.combo_cat.set(CATEGORIES[0])
        self.clear_form()

    def clear_form(self):
        self.ent_eng.delete(0, "end")
        self.ent_mm.delete(0, "end")
        self.ent_cn.delete(0, "end")

    def delete_word(self):
        sel = self.tree.selection()
        if not sel:
            return
        items = []
        for i in sel:
            values = self.tree.item(i)["values"]
            try:
                items.append(int(values[0]))
            except (TypeError, ValueError):
                return
        if not messagebox.askyesno("Confirm", f"Delete {len(items)} selected word(s)?"):
            return
        conn = sqlite3.connect(DB_FILE)
        for word_id in items:
            conn.execute("DELETE FROM words WHERE id=?", (word_id,))
        conn.commit()
        conn.close()
        self.load_words()
        self.status_var.set(f"Deleted {len(items)} word(s)")

    def load_words(self, *_args):
        for i in self.tree.get_children():
            self.tree.delete(i)
        term = self._search_term()
        q = f"%{term}%"
        order = "DESC" if self.sort_desc else "ASC"
        if self.sort_col == "id":
            sql_order = f"words.id {order}"
        else:
            sql_order = f"{self.sort_col} COLLATE NOCASE {order}, words.id DESC"
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT * FROM words WHERE english LIKE ? OR myanmar LIKE ? OR chinese LIKE ? OR category LIKE ? "
            f"ORDER BY {sql_order}",
            (q, q, q, q),
        ).fetchall()
        conn.close()

        for idx, r in enumerate(rows):
            word_id, english, chinese, myanmar = r[0], r[1], r[2], r[3]
            category = r[4] if len(r) > 4 and r[4] else CATEGORIES[0]
            tag = "even" if idx % 2 == 0 else "odd"
            self.tree.insert("", "end", values=(word_id, english, chinese, category, myanmar),
                             tags=(tag,))

        if len(rows) == 0:
            if term:
                message = "No words match \u201c%s\u201d — try another search" % term
            else:
                message = "Your library is empty — add your first word above"
            self.tree.insert("", "end", tags=("empty",), values=("", message, "", "", ""))

        total = self._total_count()
        self.word_count_var.set(f"{total} words")
        self.status_var.set(f"{len(rows)} shown" + (f" • filter: \u201c{term}\u201d" if term else ""))

    def _total_count(self):
        conn = sqlite3.connect(DB_FILE)
        total = conn.execute("SELECT COUNT(*) FROM words").fetchone()[0]
        conn.close()
        return total

    def open_quiz(self):
        quiz = tk.Toplevel(self.root)
        quiz.title("VocApp | Quick Quiz")
        quiz.geometry("900x520")
        quiz.minsize(780, 420)
        quiz.configure(bg=COLORS["bg"])

        quiz_header = ttk.Frame(quiz, style="Header.TFrame", padding=(24, 16))
        quiz_header.pack(fill="x")
        ttk.Label(quiz_header, text="Quick Quiz", style="Title.TLabel").pack(anchor="w")
        ttk.Label(quiz_header, text="A fresh set of 10 words from your library",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

        body = ttk.Frame(quiz, style="App.TFrame", padding=20)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        quiz_tree = ttk.Treeview(body, columns=("number", "english", "category", "myanmar", "chinese"),
                                 show="headings", selectmode="none")
        widths = {"number": 48, "english": 230, "category": 110, "myanmar": 250, "chinese": 200}
        for c in ("number", "english", "category", "myanmar", "chinese"):
            quiz_tree.heading(c, text=c.capitalize())
            quiz_tree.column(c, width=widths[c], minwidth=40, anchor="center" if c == "number" else "w",
                             stretch=True)
        quiz_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=quiz_tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        quiz_tree.configure(yscrollcommand=scrollbar.set)
        quiz_tree.tag_configure("odd", background=COLORS["card"])
        quiz_tree.tag_configure("even", background=COLORS["stripe"])

        def refresh_quiz():
            for item in quiz_tree.get_children():
                quiz_tree.delete(item)
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
                tag = "odd" if number % 2 else "even"
                quiz_tree.insert("", "end", values=(number,) + tuple(row), tags=(tag,))

        ttk.Button(quiz, text="Refresh Items", command=refresh_quiz,
                   style="Accent.TButton").pack(pady=(0, 18))
        refresh_quiz()


if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = VocabApp(root)
    root.mainloop()
