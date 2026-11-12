"""
Step 4: write results into a NEW copy of the CSS spreadsheet.

The original file is never modified. Each run writes
data/output/hfal-tracker-YYYY-MM-DD.xlsx containing:
  * Hospital Tracker -- same layout as before; AI-filled cells, with
      orange  = REVIEW (needs a human; hover the cell to see why)
      blue    = value changed since the previous spreadsheet
    plus 4 new columns at the end (last checked, review count, grade status, documents)
  * AI Review Queue  -- one row per REVIEW cell, with the AI's reasoning and evidence
  * AI Change Log    -- every value the AI changed, run after run
  * AI Run Log       -- what happened to each website on each run
It also writes data/output/hospitals.csv (clean data for the Part 2 dashboard).
"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Optional

import openpyxl
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.table import TableColumn

import config
from hfal.criteria import BY_KEY, GRADED, NO, REVIEW, TEXT_COLUMNS, YES, grade, is_auto_fail

ORANGE = PatternFill("solid", fgColor="FFF4B183")
BLUE = PatternFill("solid", fgColor="FFBDD7EE")
NOFILL = PatternFill(fill_type=None)
AUTHOR = "HFAL AI"

NEW_COLUMNS = ["AI Last Checked", "AI Items Needing Review", "AI Grade Status", "AI Documents Reviewed"]


def _col(letter: str) -> int:
    return column_index_from_string(letter)


class Tracker:
    def __init__(self, path: Path):
        self.path = path
        self.wb = openpyxl.load_workbook(path)
        self.ws = self.wb[config.SHEET_NAME]
        self.run_date = date.today().isoformat()
        self._ensure_new_columns()
        self.changes: list[list] = []
        self.review_rows: list[list] = []
        self.run_rows: list[list] = []

    # ------------------------------------------------------------ reading
    def hospitals(self) -> list[dict]:
        ws, out = self.ws, []
        for r in range(config.FIRST_DATA_ROW, ws.max_row + 1):
            name = ws.cell(r, 1).value
            if not name:
                continue
            link_cell = ws.cell(r, _col("N"))
            url = link_cell.value if str(link_cell.value or "").startswith("http") else None
            if not url and link_cell.hyperlink is not None:
                url = link_cell.hyperlink.target  # some cells show the page title, link is embedded
            url = (url or "").strip()
            fixed_from = url if url in config.HFA_LINK_FIXES else None
            url = config.HFA_LINK_FIXES.get(url, url)
            out.append({
                "row": r, "name": str(name).strip(), "link_fixed_from": fixed_from,
                "address": ws.cell(r, _col("C")).value or "", "city": ws.cell(r, _col("D")).value or "",
                "zip": ws.cell(r, _col("G")).value or "", "system": ws.cell(r, _col("M")).value or "",
                "hfa_url": url,
            })
        return out

    def last_values(self, row: int) -> dict[str, str]:
        return {c.key: self.ws.cell(row, _col(c.column)).value for c in GRADED}

    # ------------------------------------------------------------ layout
    def _ensure_new_columns(self):
        ws = self.ws
        headers = {ws.cell(2, c).value: c for c in range(1, ws.max_column + 1)}
        table = next(iter(ws.tables.values()), None)
        for name in NEW_COLUMNS:
            if name in headers:
                continue
            col = ws.max_column + 1
            ws.cell(2, col, name).font = Font(bold=True)
            headers[name] = col
            if table is not None:
                first, last = table.ref.split(":")
                last_row = "".join(ch for ch in last if ch.isdigit())
                table.ref = f"{first}:{get_column_letter(col)}{last_row}"
                table.tableColumns.append(TableColumn(id=len(table.tableColumns) + 1, name=name))
                if table.autoFilter is not None:
                    table.autoFilter.ref = table.ref
        self.new_col = {n: headers[n] for n in NEW_COLUMNS}
        # The FPL column is titled with the year being checked (e.g. "2026 FPL Guidelines").
        fpl_cell = ws.cell(2, _col(BY_KEY["fpl_current_year"].column))
        want = f"{config.FPL_YEAR} FPL Guidelines"
        if fpl_cell.value != want:
            old = fpl_cell.value
            fpl_cell.value = want
            if table is not None:
                for tc in table.tableColumns:
                    if tc.name == old:
                        tc.name = want

    # ------------------------------------------------------------ writing
    def _set(self, row: int, col: int, value, label: str, hospital: str, review_reason: Optional[str],
             evidence: list[str]):
        cell = self.ws.cell(row, col)
        old = cell.value
        changed = str(old).strip().lower() != str(value).strip().lower() if old is not None else value not in (None, "")
        cell.value = value
        if review_reason:
            cell.fill = ORANGE
            cell.comment = Comment(f"NEEDS REVIEW ({self.run_date}): {review_reason}"[:2000]
                                   + (f"\nPrevious value: {old}" if old is not None else ""), AUTHOR, width=400, height=200)
        elif changed and old is not None:
            cell.fill = BLUE
            cell.comment = Comment((f"AI changed this from '{old}' to '{value}' on {self.run_date}.\n"
                                    + "\n".join(evidence[:3]))[:2000], AUTHOR, width=400, height=200)
        else:
            cell.fill = NOFILL
            if cell.comment is not None and cell.comment.author == AUTHOR:
                cell.comment = None
        if changed:
            self.changes.append([self.run_date, hospital, get_column_letter(col), label, old, value,
                                 "\n".join(evidence[:3])])

    def apply(self, hospital: dict, decisions: dict, text: dict, warnings: list[str], site,
              max_fpl_value) -> None:
        row, name = hospital["row"], hospital["name"]
        if hospital.get("link_fixed_from"):
            link = self.ws.cell(row, _col("N"))
            self._set(row, _col("N"), hospital["hfa_url"], "HFA Link", name, None,
                      [f"Old link no longer works: {hospital['link_fixed_from']}"])
            link.hyperlink = hospital["hfa_url"]
        for c in GRADED:
            d = decisions[c.key]
            value = max_fpl_value if c.key == "max_fpl_400" else d.value
            self._set(row, _col(c.column), value, c.header.strip(), name,
                      d.reason if d.value == REVIEW else None, d.evidence)
            if d.value == REVIEW:
                self.review_rows.append([self.run_date, name, hospital["system"], c.column, c.header.strip(),
                                         d.ai_answer, d.confidence, d.reason, "\n".join(d.evidence),
                                         hospital["hfa_url"], ""])
        for key, letter in TEXT_COLUMNS.items():
            self._set(row, _col(letter), text[key], key, name, None, [])
        for w in warnings:
            self.review_rows.append([self.run_date, name, hospital["system"], "-", "Whole hospital", "", "",
                                     w, "", hospital["hfa_url"], ""])
        docs = "\n".join(f"{d.doc_id}: {d.url}" for d in site.documents if not d.error)
        self._write_status(row, docs)

    def mark_checked(self, hospital: dict, note: str):
        """Website unchanged since last run, or could not be checked: keep values."""
        self.ws.cell(hospital["row"], self.new_col["AI Last Checked"], f"{self.run_date} ({note})")
        if not note.startswith("website unchanged"):
            self.review_rows.append([self.run_date, hospital["name"], hospital["system"], "-", "Whole hospital",
                                     "", "", f"Not re-checked this run, previous values kept: {note}", "",
                                     hospital["hfa_url"], ""])
        else:
            self._write_status(hospital["row"], None)

    def _write_status(self, row: int, docs: Optional[str]):
        vals = self.last_values(row)
        n_review = sum(1 for v in vals.values() if v == REVIEW)
        self.ws.cell(row, self.new_col["AI Last Checked"], self.run_date)
        self.ws.cell(row, self.new_col["AI Items Needing Review"], n_review)
        g = grade_row(vals)
        self.ws.cell(row, self.new_col["AI Grade Status"],
                     f"{g['grade']} (final)" if n_review == 0 else
                     f"{g['grade']} (provisional: {n_review} item(s) need review)")
        if docs is not None:
            self.ws.cell(row, self.new_col["AI Documents Reviewed"], docs[:32000])

    def log_run(self, hfa_url: str, status: str, n_hospitals: int, n_docs: int, usage: Optional[dict]):
        u = usage or {}
        self.run_rows.append([self.run_date, hfa_url, status, n_hospitals, n_docs,
                              u.get("input", ""), u.get("output", "")])

    # ------------------------------------------------------------ saving
    def _sheet(self, title: str, headers: list[str], widths: list[int], reset: bool):
        if title in self.wb.sheetnames and reset:
            del self.wb[title]
        if title not in self.wb.sheetnames:
            s = self.wb.create_sheet(title)
            s.append(headers)
            for i, w in enumerate(widths, 1):
                s.column_dimensions[get_column_letter(i)].width = w
                s.cell(1, i).font = Font(bold=True)
            s.freeze_panes = "A2"
        return self.wb[title]

    def save(self) -> Path:
        q = self._sheet("AI Review Queue",
                        ["Run date", "Hospital", "System", "Column", "Criterion", "AI answer", "AI confidence",
                         "Why it needs review", "Evidence (doc: quote)", "HFA link", "Reviewer decision / notes"],
                        [11, 38, 22, 7, 36, 9, 9, 70, 70, 40, 30], reset=True)
        # Keep the queue in sync with the sheet: any REVIEW cell from an earlier run
        # that wasn't re-checked this time still belongs in the queue.
        fresh = {(r[1], r[3]) for r in self.review_rows}
        for h in self.hospitals():
            for c in GRADED:
                if self.ws.cell(h["row"], _col(c.column)).value == REVIEW and (h["name"], c.column) not in fresh:
                    cm = self.ws.cell(h["row"], _col(c.column)).comment
                    self.review_rows.append(["earlier run", h["name"], h["system"], c.column, c.header.strip(),
                                             "", "", cm.text if cm else "", "", h["hfa_url"], ""])
        for r in self.review_rows:
            q.append(r)
        log = self._sheet("AI Change Log", ["Date", "Hospital", "Column", "Field", "Old value", "New value",
                                            "Evidence"], [11, 38, 7, 36, 25, 25, 80], reset=False)
        for r in self.changes:
            log.append(r)
        runs = self._sheet("AI Run Log", ["Date", "HFA link", "Status", "Hospitals", "Documents",
                                          "Input tokens", "Output tokens"], [11, 60, 40, 9, 9, 12, 12], reset=False)
        for r in self.run_rows:
            runs.append(r)
        for s in (q, log):
            for row in s.iter_rows(min_row=2):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        # Make Excel recompute the grade formulas when the file is opened.
        self.wb.calculation.fullCalcOnLoad = True
        config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out = config.OUTPUT_DIR / f"hfal-tracker-{self.run_date}.xlsx"
        self.wb.save(out)
        self.export_csv()
        return out

    def export_csv(self) -> Path:
        """Clean, formula-free data for the Part 2 dashboard."""
        rows = []
        for h in self.hospitals():
            r = h["row"]
            vals = self.last_values(r)
            g = grade_row(vals)
            rec = {k: h[k] for k in ("name", "address", "city", "zip", "system", "hfa_url")}
            rec["nyc"] = bool(self.ws.cell(r, _col("E")).value)
            rec.update({"grade": g["grade"], "grade_best_case": g["grade_best"], "grade_worst_case": g["grade_worst"],
                        "grade_is_final": g["n_review"] == 0, "auto_fail": g["auto_fail"],
                        "noncompliant_count": g["n_no"], "needs_review_count": g["n_review"]})
            for c in GRADED:
                rec[c.key] = self.ws.cell(r, _col(c.column)).value
            for key, letter in TEXT_COLUMNS.items():
                rec[key] = self.ws.cell(r, _col(letter)).value
            rec["last_checked"] = self.ws.cell(r, self.new_col["AI Last Checked"]).value
            rows.append(rec)
        out = config.OUTPUT_DIR / "hospitals.csv"
        with out.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        # The plain-language law text for each criterion, for the dashboard.
        (config.OUTPUT_DIR / "criteria.json").write_text(json.dumps(
            [{"key": c.key, "column": c.column, "header": c.header.strip(), "section": c.section,
              "plain_language": c.plain_language} for c in GRADED], indent=1))
        return out


def _normalize(v) -> str:
    """Sheet values -> yes / no / REVIEW. Max FPL is stored as a number (4 = 400%)."""
    if isinstance(v, (int, float)):
        return YES if v >= 4 else NO
    s = str(v or "").strip()
    if s.lower() in ("yes", "no"):
        return s.lower()
    if s.upper() == REVIEW:
        return REVIEW
    if s[:1].isdigit():  # e.g. "400% (500% for pharmacy only)"
        try:
            n = float(s.split("%")[0].split()[0])
            return YES if (n >= 400 or 4 <= n < 100) else NO
        except ValueError:
            pass
    return REVIEW  # blank or unexpected


def grade_row(raw: dict) -> dict:
    """Grade a hospital. Unresolved REVIEW items make the grade a range:
    best case (every REVIEW turns out compliant) to worst case (every REVIEW is not)."""
    vals = {k: _normalize(v) for k, v in raw.items()}
    best = {k: (YES if v == REVIEW else v) for k, v in vals.items()}
    worst = {k: (NO if v == REVIEW else v) for k, v in vals.items()}
    g_best, g_worst = grade(best, is_auto_fail(best)), grade(worst, is_auto_fail(worst))
    return {"grade": g_best if g_best == g_worst else f"{g_best} to {g_worst}",
            "grade_best": g_best, "grade_worst": g_worst, "auto_fail": is_auto_fail(vals),
            "n_no": sum(v == NO for v in vals.values()), "n_review": sum(v == REVIEW for v in vals.values())}
