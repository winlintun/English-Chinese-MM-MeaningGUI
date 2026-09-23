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
        self.root.title("English Vocabulary Manager")
        self.root.geometry("750x500")

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
        style.configure("Treeview", font=self.myanmar_font, rowheight=28)
        style.configure("Treeview.Heading", font=self.heading_font)

        # ---- Input frame ----
        frame = ttk.LabelFrame(root, text="Add New Word", padding=10)
        frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(frame, text="English:").grid(row=1, column=0, sticky="w", pady=2)
        self.ent_eng = tk.Entry(frame, width=30, font=self.myanmar_font)
        self.ent_eng.grid(row=1, column=1, padx=5, pady=2, sticky="w")

        ttk.Label(frame, text="Myanmar:").grid(row=2, column=0, sticky="w", pady=2)
        self.ent_mm = tk.Entry(frame, width=30, font=self.myanmar_font)
        self.ent_mm.grid(row=2, column=1, padx=5, pady=2, sticky="w")

        ttk.Label(frame, text="Chinese:").grid(row=3, column=0, sticky="w", pady=2)
        self.ent_cn = tk.Entry(frame, width=30, font=self.myanmar_font)
        self.ent_cn.grid(row=3, column=1, padx=5, pady=2, sticky="w")

        self.save_button = ttk.Button(frame, text="Save", command=self.save_word)
        self.save_button.grid(row=1, column=2, rowspan=3, padx=10)
        self.cancel_button = ttk.Button(frame, text="Cancel", command=self.cancel_edit, state="disabled")
        self.cancel_button.grid(row=1, column=3, rowspan=3, padx=(0, 10))

        # ---- Search ----
        ttk.Label(frame, text="Search:").grid(row=4, column=0, sticky="w", pady=(10, 2))
        self.ent_search = tk.Entry(frame, width=30, font=self.myanmar_font)
        self.ent_search.grid(row=4, column=1, padx=5, pady=(10, 2), sticky="w")
        self.ent_search.bind("<KeyRelease>", lambda e: self.load_words())
        ttk.Button(frame, text="Add Chinese to Selected", command=self.add_chinese).grid(row=4, column=2, padx=10, pady=(10, 2))

        # ---- Table ----
        cols = ("id", "english", "chinese", "myanmar")
        self.tree = ttk.Treeview(root, columns=cols, show="headings", height=15)
        for c, w in zip(cols, (40, 180, 240, 240)):
            self.tree.heading(c, text=c.capitalize())
            self.tree.column(c, width=w)
        self.tree.pack(fill="both", expand=True, padx=10, pady=5)

        actions = ttk.Frame(root)
        actions.pack(fill="x", padx=10, pady=5)
        ttk.Button(actions, text="Edit Selected", command=self.edit_word).pack(side="left")
        ttk.Button(actions, text="Delete Selected", command=self.delete_word).pack(side="left", padx=5)
        ttk.Button(actions, text="Quiz", command=self.open_quiz).pack(side="right")

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
        quiz.title("Vocabulary Quiz")
        quiz.geometry("700x400")

        ttk.Label(quiz, text="Random vocabulary items").pack(pady=(10, 2))
        quiz_tree = ttk.Treeview(quiz, columns=("number", "english", "myanmar", "chinese"), show="headings")
        for column, width in (("number", 60), ("english", 180), ("myanmar", 220), ("chinese", 180)):
            quiz_tree.heading(column, text=column.capitalize())
            quiz_tree.column(column, width=width)
        quiz_tree.pack(fill="both", expand=True, padx=10, pady=5)

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

        ttk.Button(quiz, text="Refresh Items", command=refresh_quiz).pack(pady=(0, 10))
        refresh_quiz()

if __name__ == "__main__":
    init_db()
    root = tk.Tk()
    app = VocabApp(root)
    root.mainloop()