import json
import os
import queue
import re
import sys
import threading
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd
import Levenshtein
if sys.platform.startswith("win"):
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI aware
    except Exception:
        try:
            windll.user32.SetProcessDPIAware()      # fallback for older Windows
        except Exception:
            pass

try:
    from scalable_processing import read_records_chunked, generate_candidate_pairs_scalable
except ImportError:  # pragma: no cover
    read_records_chunked = None


# Theme

BG        = "#FAFAF8"   # window background (warm off-white)
BG_CARD   = "#FFFFFF"   # panels / cards
BG_FIELD  = "#ECEAE7"   # inputs, bar tracks
BORDER    = "#E7E5E4"   # card / panel borders
FG        = "#1C1917"   # primary text (near-black charcoal)
FG_DIM    = "#57534E"   # secondary text (stone)
FG_FAINT  = "#A8A29E"   # tertiary text
ACCENT    = "#292524"   # primary buttons (dark charcoal)
ACCENT_HOVER = "#1C1917"
GOOD      = "#292524"   # duplicate verdict text (neutral, per original theme)
GOOD_BD   = "#D6D3D1"
WARN      = "#8F6B1E"   # uncertain verdict text (muted amber)
WARN_BD   = "#E5DCC8"
NEUT_BD   = "#E7E5E4"
FONT      = "Segoe UI" if sys.platform.startswith("win") else "Helvetica"

APP_NAME  = "Twin Finder"
TAGLINE   = "Finds the records that say the same thing twice."


# Scoring (identical logic to the web version)

_name_token_re = re.compile(r"[a-zA-Z]{2,}")
_paren_re = re.compile(r"\([^)]*\)")
_GENERIC_NAME_TOKENS = frozenset("""
and et al the for on behalf of university univ institute inst college
department dept laboratory lab collaboration collaborations team group
center centre national school academy division faculty
""".split())

def _author_tokens(s):
    s = _paren_re.sub(" ", str(s))
    return {t.lower() for t in _name_token_re.findall(s)
            if t.lower() not in _GENERIC_NAME_TOKENS}

def _is_missing(v):
    if v is None:
        return True
    if isinstance(v, float) and np.isnan(v):
        return True
    return str(v).strip().lower() in {"", "nan", "none", "null", "unknown", "-", "\u2014"}

def compute_field_similarities(a, b):
    sims = {}
    if not _is_missing(a.get("title")) and not _is_missing(b.get("title")):
        ta, tb = str(a["title"]).lower().strip(), str(b["title"]).lower().strip()
        sims["title"] = 1 - Levenshtein.distance(ta, tb) / max(len(ta), len(tb))
    else:
        sims["title"] = None
    if not _is_missing(a.get("authors")) and not _is_missing(b.get("authors")):
        sa, sb = _author_tokens(a["authors"]), _author_tokens(b["authors"])
        u = len(sa | sb)
        sims["authors"] = len(sa & sb) / u if u else None
    else:
        sims["authors"] = None
    if not _is_missing(a.get("venue")) and not _is_missing(b.get("venue")):
        sims["venue"] = 1.0 if str(a["venue"]).lower().strip() == str(b["venue"]).lower().strip() else 0.0
    else:
        sims["venue"] = None
    if not _is_missing(a.get("year")) and not _is_missing(b.get("year")):
        try:
            sims["year"] = 1.0 if int(float(a["year"])) == int(float(b["year"])) else 0.0
        except (TypeError, ValueError):
            sims["year"] = None
    else:
        sims["year"] = None
    return sims

_W = {"title": 0.55, "authors": 0.25, "venue": 0.10, "year": 0.10}

def _author_conflict(fs):
    return (fs.get("title") is not None and fs.get("authors") is not None
            and fs["title"] > 0.85 and fs["authors"] < 0.2)

def _republication(fs):
    return (fs.get("title") is not None and fs["title"] > 0.85
            and fs.get("authors") is not None and fs["authors"] > 0.7
            and fs.get("venue") == 0.0 and fs.get("year") == 0.0)

def predict(a, b):
    fs = compute_field_similarities(a, b)
    avail = {k: v for k, v in fs.items() if v is not None}
    if not avail:
        return False, 0.0, fs
    tw = sum(_W[k] for k in avail)
    conf = sum(_W[k] * v for k, v in avail.items()) / tw
    if _author_conflict(fs):
        conf *= 0.45
    return conf > 0.7, conf, fs

def explain(is_dup, conf, fs):
    missing = [k for k, v in fs.items() if v is None]
    if _republication(fs):
        head = ("Same title and same authors, but different venue and year — this looks "
                "like the same work published twice (e.g. journal + proceedings version). "
                "Whether that counts as a duplicate is your policy call. ")
    else:
        head = ""
    if is_dup:
        rs = []
        if fs["title"] is not None and fs["title"] > 0.9:
            rs.append(f"nearly identical titles ({fs['title']:.0%})")
        if fs["authors"] is not None and fs["authors"] > 0.7:
            rs.append(f"overlapping authors ({fs['authors']:.0%})")
        if fs["venue"] == 1.0:
            rs.append("same venue")
        if fs["year"] == 1.0:
            rs.append("same year")
        body = "Likely duplicates: " + (", ".join(rs) if rs else "high overall similarity") + "."
    else:
        ds = []
        if _author_conflict(fs):
            ds.append("same title but clearly different authors — likely two distinct works on one topic")
        if fs["title"] is not None and fs["title"] < 0.5:
            ds.append(f"different titles ({fs['title']:.0%})")
        if fs["authors"] is not None and fs["authors"] < 0.3 and not _author_conflict(fs):
            ds.append(f"different authors ({fs['authors']:.0%} overlap)")
        if fs["venue"] is not None and fs["venue"] < 0.5:
            ds.append("different venues")
        if fs["year"] == 0.0:
            ds.append("different years")
        body = "Likely not duplicates: " + (", ".join(ds) if ds else "low overall similarity") + "."
    tail = f" ({', '.join(missing).capitalize()} missing on one side — excluded from the score.)" if missing else ""
    return head + body + tail


# Column auto-mapping

ALIASES = {
    "title":   ["title", "titles", "paper title", "article title", "publication title", "name"],
    "authors": ["authors", "author", "author(s)", "creator", "creators", "author names", "by"],
    "venue":   ["venue", "journal", "conference", "publication", "source", "booktitle",
                "proceedings", "publication venue", "container-title"],
    "year":    ["year", "pub_year", "pub year", "publication year", "date", "published",
                "pubdate", "issued"],
}

def auto_guess(columns):
    lower = {str(c).lower().strip(): c for c in columns}
    out = {}
    for canon, al in ALIASES.items():
        hit = None
        for a in al:
            if a in lower:
                hit = lower[a]; break
        if hit is None:
            for cl, orig in lower.items():
                if any(a in cl for a in al):
                    hit = orig; break
        out[canon] = hit
    return out

def app_dir():
    if getattr(sys, "frozen", False):          # PyInstaller bundle
        return Path(sys.executable).parent
    return Path(__file__).parent


# The application

class TwinFinder(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1060x760")
        self.minsize(880, 620)
        self.configure(bg=BG)
        self._style()

        self.q = queue.Queue()
        self.df = None
        self.pairs = []
        self.idx = 0
        self.log = []
        self.file_path = None
        self.preview = None

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True)
        self.show_home()
        self.after(100, self._poll)

    #style 
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TCombobox", fieldbackground=BG_FIELD, background=BG_FIELD,
                    foreground=FG, arrowcolor=FG_DIM, bordercolor=BG_FIELD,
                    lightcolor=BG_FIELD, darkcolor=BG_FIELD)
        self.option_add("*TCombobox*Listbox.background", BG_FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        s.configure("H.Horizontal.TProgressbar", troughcolor=BG_FIELD,
                    background=ACCENT, bordercolor=BG_FIELD,
                    lightcolor=ACCENT, darkcolor=ACCENT)

    #  widget helpers 
    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def _btn(self, parent, text, cmd, primary=False, width=None):
        b = tk.Button(parent, text=text, command=cmd,
                      font=(FONT, 10, "bold" if primary else "normal"),
                      bg=ACCENT if primary else BG_CARD,
                      fg="#FFFFFF" if primary else FG,
                      activebackground=ACCENT_HOVER if primary else "#F2F1EE",
                      activeforeground="#FFFFFF" if primary else FG,
                      relief="flat", bd=0, padx=18, pady=9, cursor="hand2",
                      highlightbackground=ACCENT if primary else "#D6D3D1",
                      highlightthickness=1)
        if width:
            b.configure(width=width)
        return b

    def _card(self, parent):
        return tk.Frame(parent, bg=BG_CARD, highlightbackground=BORDER,
                        highlightthickness=1)

    #  home screen 
    def show_home(self):
        self._clear()
        f = tk.Frame(self.container, bg=BG)
        f.place(relx=0.5, rely=0.42, anchor="center")

        tk.Label(f, text="BIBLIOGRAPHIC DATA CLEANING", font=(FONT, 8, "bold"),
                 bg=BG, fg=FG_FAINT).pack(pady=(0, 10))
        tk.Label(f, text=APP_NAME, font=(FONT, 44, "bold"), bg=BG, fg=FG).pack()
        tk.Label(f, text=TAGLINE, font=(FONT, 13), bg=BG, fg=FG_DIM).pack(pady=(8, 2))
        tk.Label(f, text=("Open a catalogue of records and Twin Finder ranks the pairs most\n"
                          "likely to be duplicates, with the evidence behind every match.\n"
                          "You make the final call on each one."),
                 font=(FONT, 10), bg=BG, fg=FG_DIM, justify="center").pack(pady=(4, 22))

        row = tk.Frame(f, bg=BG); row.pack()
        self._btn(row, "Open a file\u2026", self.open_file, primary=True, width=18).pack(side="left", padx=6)
        sample = app_dir() / "data" / "processed" / "dblp_10k_clean.csv"
        sb = self._btn(row, "Try sample data", lambda: self.start_load(str(sample)), width=18)
        sb.pack(side="left", padx=6)
        if not sample.exists():
            sb.configure(state="disabled")
        tk.Label(f, text="CSV \u2022 JSON \u2022 JSON-lines  \u2014  no size limit; large files stream from disk",
                 font=(FONT, 9), bg=BG, fg=FG_FAINT).pack(pady=(16, 0))

        self.status = tk.Label(self.container, text="", font=(FONT, 10), bg=BG, fg=FG_DIM)
        self.status.place(relx=0.5, rely=0.80, anchor="center")

    def open_file(self):
        p = filedialog.askopenfilename(
            title="Open a bibliographic dataset",
            filetypes=[("Data files", "*.csv *.json *.jsonl *.ndjson"),
                       ("CSV", "*.csv"), ("JSON", "*.json *.jsonl *.ndjson"),
                       ("All files", "*.*")])
        if p:
            self.show_mapping(p)

    #  mapping screen 
    def show_mapping(self, path):
        try:
            is_jl = False
            if path.lower().endswith((".json", ".jsonl", ".ndjson")):
                with open(path, encoding="utf-8") as fh:
                    head = fh.readline().strip()
                try:
                    json.loads(head); is_jl = head.startswith("{")
                except Exception:
                    is_jl = path.lower().endswith((".jsonl", ".ndjson"))
            if path.lower().endswith(".csv"):
                prev = pd.read_csv(path, nrows=200, dtype=str)
            elif is_jl:
                rows = []
                with open(path, encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            rows.append(json.loads(line))
                        if len(rows) >= 200:
                            break
                prev = pd.DataFrame(rows)
            else:
                prev = pd.read_json(path).head(200)
        except Exception as e:
            messagebox.showerror(APP_NAME, f"Could not read file:\n{e}")
            return
        if len(prev.columns) == 0:
            messagebox.showerror(APP_NAME, "No columns found in this file.")
            return

        self.file_path, self._is_jl = path, is_jl
        self._clear()
        f = tk.Frame(self.container, bg=BG); f.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(f, text="Map your columns", font=(FONT, 20, "bold"), bg=BG, fg=FG).pack()
        tk.Label(f, text=Path(path).name + f"   \u2022   columns: {', '.join(map(str, prev.columns[:8]))}"
                 + (" \u2026" if len(prev.columns) > 8 else ""),
                 font=(FONT, 9), bg=BG, fg=FG_DIM, wraplength=680).pack(pady=(6, 18))

        guess = auto_guess(list(prev.columns))
        cols = ["\u2014 none \u2014"] + [str(c) for c in prev.columns]
        self.map_vars = {}
        grid = tk.Frame(f, bg=BG); grid.pack()
        for i, (canon, label) in enumerate([("title", "Title (required)"), ("authors", "Authors"),
                                            ("venue", "Venue / Journal"), ("year", "Year")]):
            tk.Label(grid, text=label, font=(FONT, 10), bg=BG, fg=FG_DIM,
                     anchor="e", width=16).grid(row=i, column=0, padx=8, pady=6, sticky="e")
            var = tk.StringVar(value=str(guess[canon]) if guess.get(canon) else cols[0])
            cb = ttk.Combobox(grid, textvariable=var, values=cols, state="readonly", width=34)
            cb.grid(row=i, column=1, pady=6)
            self.map_vars[canon] = var

        row = tk.Frame(f, bg=BG); row.pack(pady=(22, 0))
        self._btn(row, "\u2190 Back", self.show_home).pack(side="left", padx=6)
        self._btn(row, "Start validation", self._start_from_mapping, primary=True).pack(side="left", padx=6)

    def _start_from_mapping(self):
        none = "\u2014 none \u2014"
        m = {k: (None if v.get() == none else v.get()) for k, v in self.map_vars.items()}
        if not m["title"]:
            messagebox.showwarning(APP_NAME, "Title is required.")
            return
        self.start_load(self.file_path, m, self._is_jl)

    # loading (background thread) 
    def start_load(self, path, mapping=None, is_jl=False):
        if read_records_chunked is None:
            messagebox.showerror(APP_NAME, "scalable_processing.py must sit next to this program.")
            return
        if not os.path.exists(path):
            messagebox.showerror(APP_NAME, f"File not found:\n{path}")
            return
        if mapping is None:                      # sample data: known columns
            mapping = {"title": "title", "authors": "authors", "venue": "venue", "year": "year"}
        self._show_progress(f"Reading {Path(path).name} \u2026")
        threading.Thread(target=self._worker, args=(path, mapping, is_jl), daemon=True).start()

    def _show_progress(self, text):
        self._clear()
        f = tk.Frame(self.container, bg=BG); f.place(relx=0.5, rely=0.45, anchor="center")
        tk.Label(f, text=APP_NAME, font=(FONT, 22, "bold"), bg=BG, fg=FG).pack(pady=(0, 18))
        self.prog_label = tk.Label(f, text=text, font=(FONT, 11), bg=BG, fg=FG_DIM)
        self.prog_label.pack(pady=(0, 10))
        self.prog = ttk.Progressbar(f, style="H.Horizontal.TProgressbar",
                                    length=420, mode="determinate", maximum=1.0)
        self.prog.pack()

    def _worker(self, path, mapping, is_jl):
        try:
            df = read_records_chunked(
                path, mapping, is_json_lines=is_jl, chunksize=50_000,
                progress=lambda k: self.q.put(("label", f"Loaded {k:,} records\u2026")))
            self.q.put(("label", f"Loaded {len(df):,} records. Scanning for duplicates\u2026"))
            raw = generate_candidate_pairs_scalable(
                df, threshold=0.5, max_pairs=500,
                progress=lambda fr: self.q.put(("bar", float(fr))))
            pairs = [{"idx_a": i, "idx_b": j, "sim": s} for (i, j, s) in raw]
            self.q.put(("done", (df, pairs)))
        except Exception as e:
            self.q.put(("error", str(e)))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "label" and hasattr(self, "prog_label"):
                    self.prog_label.configure(text=payload)
                elif kind == "bar" and hasattr(self, "prog"):
                    self.prog["value"] = min(1.0, payload)
                elif kind == "error":
                    messagebox.showerror(APP_NAME, f"Error while loading:\n{payload}")
                    self.show_home()
                elif kind == "done":
                    self.df, self.pairs = payload
                    self.idx, self.log = 0, []
                    if not self.pairs:
                        messagebox.showinfo(APP_NAME, "No candidate duplicate pairs found.")
                        self.show_home()
                    else:
                        self.show_review()
        except queue.Empty:
            pass
        self.after(100, self._poll)

    # review screen 
    def show_review(self):
        self._clear()
        if self.idx >= len(self.pairs):
            return self.show_summary()

        pair = self.pairs[self.idx]
        a = self.df.iloc[pair["idx_a"]].to_dict()
        b = self.df.iloc[pair["idx_b"]].to_dict()
        is_dup, conf, fs = predict(a, b)
        uncertain = _republication(fs) or (0.55 < conf <= 0.82)

        top = tk.Frame(self.container, bg=BG); top.pack(fill="x", padx=26, pady=(16, 4))
        home = tk.Label(top, text="\u25C8 " + APP_NAME, font=(FONT, 11, "bold"),
                        bg=BG, fg=FG, cursor="hand2")
        home.pack(side="left")
        home.bind("<Button-1>", lambda e: self._confirm_home())
        acc = sum(1 for r in self.log if r["user_decision"] == "accept")
        tk.Label(top, text=f"Pair {self.idx+1} of {len(self.pairs)}   \u2022   "
                           f"accepted {acc} / rejected {len(self.log)-acc}",
                 font=(FONT, 10), bg=BG, fg=FG_DIM).pack(side="right")

        # verdict banner
        if uncertain:
            vtext, vcol, vbd = (f"Uncertain \u2014 needs your judgment \u00b7 score {conf:.0%}",
                                WARN, WARN_BD)
        elif is_dup:
            vtext, vcol, vbd = f"Likely duplicate \u00b7 confidence {conf:.0%}", GOOD, GOOD_BD
        else:
            vtext, vcol, vbd = (f"Likely not a duplicate \u00b7 confidence {1-conf:.0%}",
                                FG_DIM, NEUT_BD)
        vb = tk.Frame(self.container, bg=BG_CARD, highlightbackground=vbd, highlightthickness=1)
        vb.pack(fill="x", padx=26, pady=(8, 10))
        tk.Label(vb, text=vtext, font=(FONT, 11, "bold"), bg=BG_CARD, fg=vcol,
                 anchor="w", padx=14, pady=8).pack(fill="x")

        # paper cards
        cards = tk.Frame(self.container, bg=BG); cards.pack(fill="x", padx=26)
        cards.columnconfigure(0, weight=1, uniform="c"); cards.columnconfigure(1, weight=1, uniform="c")
        for col, (label, rec) in enumerate([("PAPER A", a), ("PAPER B", b)]):
            c = self._card(cards); c.grid(row=0, column=col, sticky="nsew", padx=(0, 8) if col == 0 else (8, 0))
            tk.Label(c, text=label, font=(FONT, 8, "bold"), bg=BG_CARD, fg=FG_FAINT,
                     anchor="w").pack(fill="x", padx=14, pady=(10, 2))
            tk.Label(c, text=str(rec.get("title", "\u2014")), font=(FONT, 11, "bold"),
                     bg=BG_CARD, fg=FG, anchor="w", justify="left",
                     wraplength=430).pack(fill="x", padx=14)
            meta = (f"Authors   {str(rec.get('authors', '\u2014')).replace('|', ', ')}\n"
                    f"Venue      {rec.get('venue', '\u2014')}\n"
                    f"Year        {rec.get('year', '\u2014')}")
            tk.Label(c, text=meta, font=(FONT, 9), bg=BG_CARD, fg=FG_DIM,
                     anchor="w", justify="left", wraplength=430).pack(fill="x", padx=14, pady=(6, 12))

        # similarity bars
        bars = self._card(self.container); bars.pack(fill="x", padx=26, pady=(12, 0))
        tk.Label(bars, text="FIELD SIMILARITY", font=(FONT, 8, "bold"), bg=BG_CARD,
                 fg=FG_FAINT, anchor="w").pack(fill="x", padx=14, pady=(10, 4))
        for name in ("title", "authors", "venue", "year"):
            row = tk.Frame(bars, bg=BG_CARD); row.pack(fill="x", padx=14, pady=3)
            tk.Label(row, text=name.capitalize(), font=(FONT, 9), bg=BG_CARD,
                     fg=FG_DIM, width=9, anchor="w").pack(side="left")
            v = fs[name]
            track = tk.Frame(row, bg=BG_FIELD, height=8); track.pack(side="left", fill="x", expand=True, padx=8)
            track.pack_propagate(False)
            if v is not None and v > 0:
                fill = tk.Frame(track, bg=FG_DIM if v >= 0.5 else FG_FAINT, height=8)
                fill.place(relx=0, rely=0, relwidth=max(0.02, v), relheight=1)
            tk.Label(row, text=("n/a" if v is None else f"{v:.0%}"), font=(FONT, 9),
                     bg=BG_CARD, fg=FG_FAINT if v is None else FG, width=5, anchor="e").pack(side="right")
        tk.Frame(bars, bg=BG_CARD, height=8).pack()

        # explanation
        ex = self._card(self.container); ex.pack(fill="x", padx=26, pady=(12, 0))
        tk.Label(ex, text=explain(is_dup, conf, fs), font=(FONT, 9), bg=BG_CARD, fg="#44403C",
                 anchor="w", justify="left", wraplength=940, padx=14, pady=10).pack(fill="x")

        # actions
        act = tk.Frame(self.container, bg=BG); act.pack(pady=16)
        self._btn(act, "Accept \u2014 duplicates", lambda: self._decide("accept", is_dup, conf, fs),
                  primary=True, width=22).pack(side="left", padx=5)
        self._btn(act, "Reject \u2014 not duplicates", lambda: self._decide("reject", is_dup, conf, fs),
                  width=22).pack(side="left", padx=5)
        self._btn(act, "Skip", self._skip, width=10).pack(side="left", padx=5)

    def _decide(self, decision, is_dup, conf, fs):
        pair = self.pairs[self.idx]
        self.log.append({
            "pair_index": self.idx, "idx_a": int(pair["idx_a"]), "idx_b": int(pair["idx_b"]),
            "ai_prediction": "duplicate" if is_dup else "not_duplicate",
            "ai_confidence": float(conf), "user_decision": decision,
            "field_similarities": {k: (None if v is None else float(v)) for k, v in fs.items()},
            "timestamp": datetime.now().isoformat(),
        })
        self.idx += 1
        self.show_review()

    def _skip(self):
        self.idx += 1
        self.show_review()

    def _confirm_home(self):
        if not self.log or messagebox.askyesno(
                APP_NAME, "Return to home? Unexported decisions will be lost."):
            self.show_home()

    # summary screen 
    def show_summary(self):
        self._clear()
        f = tk.Frame(self.container, bg=BG); f.place(relx=0.5, rely=0.42, anchor="center")
        tk.Label(f, text="All pairs reviewed", font=(FONT, 22, "bold"), bg=BG, fg=FG).pack()
        acc = sum(1 for r in self.log if r["user_decision"] == "accept")
        tk.Label(f, text=f"{len(self.log)} decisions \u2022 {acc} accepted as duplicates \u2022 "
                         f"{len(self.log)-acc} rejected",
                 font=(FONT, 11), bg=BG, fg=FG_DIM).pack(pady=(8, 22))
        row = tk.Frame(f, bg=BG); row.pack()
        self._btn(row, "Export decisions (JSON)\u2026", self._export, primary=True).pack(side="left", padx=6)
        self._btn(row, "Back to home", self.show_home).pack(side="left", padx=6)

    def _export(self):
        p = filedialog.asksaveasfilename(
            defaultextension=".json", initialfile="twin_finder_feedback.json",
            filetypes=[("JSON", "*.json")])
        if p:
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(self.log, fh, indent=2)
            messagebox.showinfo(APP_NAME, f"Saved {len(self.log)} decisions to:\n{p}")


if __name__ == "__main__":
    TwinFinder().mainloop()
