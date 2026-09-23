import os
import sqlite3
import tkinter as tk
import unicodedata
from tkinter import ttk, messagebox
import tkinter.font as tkfont

DB_FILE = "C:\\Users\\wangyi\\Desktop\\VocApp\\vocabulary.db"
FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")


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

    # Font names with spaces must be wrapped in braces, otherwise Tk parses the second word as a number.
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
    conn.commit()
    conn.close()

class VocabApp:
    def __init__(self, root):
        self.root = root
        self.editing_id = None
        self.root.title("VocApp | Vocabulary Workspace")
        self.root.geometry("980x680")
        self.root.minsize(820, 560)
        self.root.configure(bg="#eef2f6")

        self.myanmar_font_family, self.myanmar_font_file = get_myanmar_font_family()
        if self.myanmar_font_file:
            self.myanmar_font = tkfont.Font(family="CustomMyanmar", size=12, file=self.myanmar_font_file)
            self.heading_font = tkfont.Font(family="CustomMyanmar", size=10, weight="bold", file=self.myanmar_font_file)
            configure_default_fonts(root, "CustomMyanmar")
        else:
            self.myanmar_font = tkfont.Font(family=self.myanmar_font_family, size=12)
            self.heading_font = tkfont.Font(family=self.myanmar_font_family, size=10, weight="bold")
            configure_default_fonts(root, self.myanmar_font_family)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("App.TFrame", background="#eef2f6")
        style.configure("Header.TFrame", background="#17324d")
        style.configure("Card.TLabelframe", background="#ffffff", bordercolor="#d7e0e8", relief="solid")
        style.configure("Card.TLabelframe.Label", background="#ffffff", foreground="#17324d", font=self.heading_font)
        style.configure("Title.TLabel", background="#17324d", foreground="#ffffff", font=(self.myanmar_font_family, 22, "bold"))
        style.configure("Subtitle.TLabel", background="#17324d", foreground="#b9c9d8", font=(self.myanmar_font_family, 10))
        style.configure("Section.TLabel", background="#ffffff", foreground="#526579", font=self.heading_font)
        style.configure("Muted.TLabel", background="#eef2f6", foreground="#6b7b8c", font=(self.myanmar_font_family, 10))
        style.configure("Accent.TButton", background="#0f766e", foreground="#ffffff", padding=(14, 8), font=self.heading_font)
        style.map("Accent.TButton", background=[("active", "#0b5f59")])
        style.configure("Soft.TButton", background="#e8eef3", foreground="#17324d", padding=(12, 8))
        style.map("Soft.TButton", background=[("active", "#d6e1e9")])
        style.configure("Danger.TButton", background="#fbe9e7", foreground="#a33a2b", padding=(12, 8))
        style.map("Danger.TButton", background=[("active", "#f4d5d0")])
        style.configure("Treeview", background="#ffffff", fieldbackground="#ffffff", foreground="#263746", font=self.myanmar_font, rowheight=34, borderwidth=0)
        style.map("Treeview", background=[("selected", "#d8eeeb")], foreground=[("selected", "#17324d")])
        style.configure("Treeview.Heading", background="#e8eef3", foreground="#17324d", font=self.heading_font, padding=(8, 9))
        style.configure("TEntry", fieldbackground="#f8fafc", foreground="#263746", padding=8)

        root.columnconfigure(0, weight=1)
        root.rowconfigure(2, weight=1)

        header = ttk.Frame(root, style="Header.TFrame", padding=(28, 22))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        ttk.Label(header, text="VocApp", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Build your vocabulary, one word at a time", style="Subtitle.TLabel").grid(row=1, column=0, sticky="w", pady=(4, 0))
        ttk.Label(header, text="WORD LIBRARY", style="Subtitle.TLabel").grid(row=0, column=1, rowspan=2, sticky="e")

        editor = ttk.LabelFrame(root, text="  Word details  ", style="Card.TLabelframe", padding=(18, 14))
        editor.grid(row=1, column=0, sticky="ew", padx=24, pady=(20, 12))
        editor.columnconfigure(0, weight=1)
        editor.columnconfigure(1, weight=1)
        editor.columnconfigure(2, weight=1)

        ttk.Label(editor, text="English", style="Section.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Label(editor, text="Myanmar", style="Section.TLabel").grid(row=0, column=1, sticky="w", padx=6)
        ttk.Label(editor, text="Chinese", style="Section.TLabel").grid(row=0, column=2, sticky="w", padx=(12, 0))
        self.ent_eng = ttk.Entry(editor, font=self.myanmar_font)
        self.ent_eng.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(5, 0))
        self.ent_mm = ttk.Entry(editor, font=self.myanmar_font)
        self.ent_mm.grid(row=1, column=1, sticky="ew", padx=6, pady=(5, 0))
        self.ent_cn = ttk.Entry(editor, font=self.myanmar_font)
        self.ent_cn.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(5, 0))

        form_actions = ttk.Frame(editor, style="Card.TLabelframe")
        form_actions.grid(row=0, column=3, rowspan=2, padx=(20, 0))
        self.save_button = ttk.Button(form_actions, text="Save Word", command=self.save_word, style="Accent.TButton")
        self.save_button.pack(fill="x")
        self.cancel_button = ttk.Button(form_actions, text="Cancel Edit", command=self.cancel_edit, state="disabled", style="Soft.TButton")
        self.cancel_button.pack(fill="x", pady=(7, 0))

        library = ttk.Frame(root, style="App.TFrame", padding=(24, 0, 24, 20))
        library.grid(row=2, column=0, sticky="nsew")
        library.columnconfigure(0, weight=1)
        library.rowconfigure(2, weight=1)
        toolbar = ttk.Frame(library, style="App.TFrame")
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        toolbar.columnconfigure(1, weight=1)
        ttk.Label(toolbar, text="Your vocabulary", style="Section.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(toolbar, text="Search", style="Muted.TLabel").grid(row=0, column=1, sticky="e", padx=(20, 8))
        self.ent_search = ttk.Entry(toolbar, width=30, font=self.myanmar_font)
        self.ent_search.grid(row=0, column=2, sticky="e")
        self.ent_search.bind("<KeyRelease>", lambda e: self.load_words())
        ttk.Button(toolbar, text="Refresh", command=self.load_words, style="Soft.TButton").grid(row=0, column=3, padx=(8, 0))

        table_frame = ttk.Frame(library, style="App.TFrame")
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        cols = ("id", "english", "chinese", "myanmar")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="extended")
        for c, w in zip(cols, (55, 220, 250, 300)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w, minwidth=55, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=scrollbar.set)

        actions = ttk.Frame(library, style="App.TFrame")
        actions.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(actions, text="Edit Selected", command=self.edit_word, style="Soft.TButton").pack(side="left")
        ttk.Button(actions, text="Delete Selected", command=self.delete_word, style="Danger.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Add Chinese to Selected", command=self.add_chinese, style="Soft.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Open Quiz", command=self.open_quiz, style="Accent.TButton").pack(side="right")

        self.load_words()

    def save_word(self):
        eng = normalize_myanmar_text(self.ent_eng.get())
        mm = normalize_myanmar_text(self.ent_mm.get())
        cn = normalize_myanmar_text(self.ent_cn.get())
        if not eng or not mm:
            messagebox.showwarning("Warning", "English and Myanmar text are required!")
            return
        conn = sqlite3.connect(DB_FILE)
        conn.execute("INSERT INTO words (english, chinese, myanmar) VALUES (?,?,?)", (eng, cn, mm))
        conn.commit(); conn.close()
        self.ent_eng.delete(0, "end"); self.ent_mm.delete(0, "end"); self.ent_cn.delete(0, "end")
        self.load_words()

    def add_chinese(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Please select a word in the table first.")
            return
        cn = normalize_myanmar_text(self.ent_cn.get())
        if not cn:
            messagebox.showwarning("Warning", "Type the Chinese definition first.")
            return
        word_id = self.tree.item(sel[0])["values"][0]
        conn = sqlite3.connect(DB_FILE)
        conn.execute("UPDATE words SET chinese=? WHERE id=?", (cn, word_id))
        conn.commit(); conn.close()
        self.ent_cn.delete(0, "end")
        self.load_words()

    def edit_word(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Please select a word in the table first.")
            return

        word = self.tree.item(sel[0])["values"]
        self.ent_eng.delete(0, "end")
        self.ent_eng.insert(0, word[1])
        self.ent_cn.delete(0, "end")
        self.ent_cn.insert(0, word[2])
        self.ent_mm.delete(0, "end")
        self.ent_mm.insert(0, word[3])
        self.editing_id = word[0]
        self.save_button.configure(text="Update", command=self.update_word)
        self.cancel_button.configure(state="normal")
        self.ent_eng.focus_set()

    def update_word(self):
        eng = normalize_myanmar_text(self.ent_eng.get())
        mm = normalize_myanmar_text(self.ent_mm.get())
        cn = normalize_myanmar_text(self.ent_cn.get())
        if not eng or not mm:
            messagebox.showwarning("Warning", "English and Myanmar text are required!")
            return

        conn = sqlite3.connect(DB_FILE)
        conn.execute(
            "UPDATE words SET english=?, chinese=?, myanmar=? WHERE id=?",
            (eng, cn, mm, self.editing_id),
        )
        conn.commit()
        conn.close()
        self.cancel_edit()
        self.load_words()

    def cancel_edit(self):
        self.editing_id = None
        self.save_button.configure(text="Save", command=self.save_word)
        self.cancel_button.configure(state="disabled")
        self.clear_form()

    def clear_form(self):
        self.ent_eng.delete(0, "end")
        self.ent_mm.delete(0, "end")
        self.ent_cn.delete(0, "end")

    def delete_word(self):
        sel = self.tree.selection()
        if not sel:
            return
        if messagebox.askyesno("Confirm", "Delete selected word?"):
            conn = sqlite3.connect(DB_FILE)
            for i in sel:
                conn.execute("DELETE FROM words WHERE id=?", (self.tree.item(i)["values"][0],))
            conn.commit(); conn.close()
            self.load_words()

    def load_words(self):
        for i in self.tree.get_children():
            self.tree.delete(i)
        q = f"%{normalize_myanmar_text(self.ent_search.get())}%"
        conn = sqlite3.connect(DB_FILE)
        rows = conn.execute(
            "SELECT * FROM words WHERE english LIKE ? OR myanmar LIKE ? OR chinese LIKE ? ORDER BY id DESC",
            (q, q, q)).fetchall()
        conn.close()
        for r in rows:
            self.tree.insert("", "end", values=r)

    def open_quiz(self):
        quiz = tk.Toplevel(self.root)
        quiz.title("VocApp | Quick Quiz")
        quiz.geometry("820x500")
        quiz.minsize(700, 400)
        quiz.configure(bg="#eef2f6")

        quiz_header = ttk.Frame(quiz, style="Header.TFrame", padding=(22, 16))
        quiz_header.pack(fill="x")
        ttk.Label(quiz_header, text="Quick Quiz", style="Title.TLabel").pack(anchor="w")
        ttk.Label(quiz_header, text="A fresh set of 10 words from your library", style="Subtitle.TLabel").pack(anchor="w", pady=(3, 0))

        table_frame = ttk.Frame(quiz, style="App.TFrame", padding=16)
        table_frame.pack(fill="both", expand=True)
        quiz_tree = ttk.Treeview(table_frame, columns=("number", "english", "myanmar", "chinese"), show="headings")
        for column, width in (("number", 60), ("english", 220), ("myanmar", 260), ("chinese", 220)):
            quiz_tree.heading(column, text=column.capitalize())
            quiz_tree.column(column, width=width, minwidth=60, anchor="w")
        quiz_tree.pack(fill="both", expand=True)

        def refresh_quiz():
            for item in quiz_tree.get_children():
                quiz_tree.delete(item)
            conn = sqlite3.connect(DB_FILE)
            rows = conn.execute(
                "SELECT english, myanmar, chinese FROM words ORDER BY RANDOM() LIMIT 10"
            ).fetchall()
            conn.close()
            for number, row in enumerate(rows, start=1):
                quiz_tree.insert("", "end", values=(number,) + row)

        ttk.Button(quiz, text="Refresh Items", command=refresh_quiz, style="Accent.TButton").pack(pady=(0, 16))
        refresh_quiz()

if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = VocabApp(root)
    root.mainloop()