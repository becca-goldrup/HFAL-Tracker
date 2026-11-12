"""Builds a small practice spreadsheet with the same layout as the CSS tracker.

The values are made up -- this is only for testing the tool without the real file.
    python tests/make_sample_sheet.py
"""
import sys
from pathlib import Path

import openpyxl
from openpyxl.worksheet.table import Table

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config

HEADERS = ["Hospital Name", "HYPERLINKED hospital names", "Address", "City", "NYC?", "State", "Zip",
    "Operating certificate number", "CMS Certification number (CCN)/Medical provider number (MPN)",
    "Permanent Facility Identifier (PFI)", "OCN_num", "OCN_PFI", "System", "HFA Link", "COMPLIANCE GRADE",
    "Automatic Fail?", "Noncompliant Categories Count", "Application Posted",
    "Policy Summary Posted (as PDF, or on landing page)", "Policy Statement Posted",
    "Consistent across posted documents (Y/N)", "Primary Service Area boundaries compliant with 2007 guidelines?",
    "No time limit to submit?", "Notes on timeframe", "No evidence of asset checks",
    "No mention of immigration status as a barrier", "Inconsistency notes", "Languages Available",
    'Notes (e.g. use of "charity care")', "ENTIRE Uniform Application", "Contact information included in application",
    "Contact phone #", "Income & Discount Tables Incuded in Application", "2025 FPL Guidelines",
    "Max FPL (compliant is =/>400%)", "Installments capped at 5% of monthly income",
    "Application notes (any prohibited information?)", "Primary Service Area described in summary? ",
    "Means of applying for assistance explained", "Income levels used to determine assistance", "Notes",
    "SEPTEMBER - PDF in Folder", "Other Notes"]
SAMPLE = [
    ("Sample Hospital A", "1 Main St", "Oneonta", "13820", "Bassett Health",
     "https://www.bassett.org/patients-visitors/billing-insurance/financial-assistance", None),
    ("Sample Hospital B", "2 Main St", "Saranac Lake", "12983", "Adirondack Health",
     "https://www.adirondackhealth.org/financial-assistance-policies", None),
    ("Sample Hospital C", "3 Main St", "Buffalo", "14203", "Kaleida Health",
     "Financial Assistance | Kaleida (title only, real link embedded)",
     "https://www.buffalogeneral.org/care/Financial-Assistance-Program/Financial-Assistance"),
]
wb = openpyxl.Workbook(); ws = wb.active; ws.title = config.SHEET_NAME
ws["R1"], ws["AD1"], ws["AL1"] = "MATERIALS ON WEBSITE", "APPLICATION", "PLAIN LANGUAGE SUMMARY"
ws.append([]) if False else None
for i, h in enumerate(HEADERS, 1):
    ws.cell(2, i, h)
for r, (name, addr, city, z, system, link, embedded) in enumerate(SAMPLE, 3):
    for col, v in {"A": name, "C": addr, "D": city, "F": "NY", "G": z, "M": system, "N": link}.items():
        ws[f"{col}{r}"] = v
    if embedded:
        ws[f"N{r}"].hyperlink = embedded
    ws[f"O{r}"] = f'=IF(P{r}=TRUE,"F",IF(Q{r}=0,"A",IF(Q{r}<=3,"B",IF(Q{r}<=6,"C",IF(Q{r}<=9,"D","F")))))'
    ws[f"P{r}"] = f'=IF(OR(R{r}="no",AD{r}="no"),TRUE,FALSE)'
    ws[f"Q{r}"] = f'=COUNTIF(R{r}:AN{r},"no")'
    for col in ["R","S","T","U","V","W","Y","Z","AD","AE","AG","AH","AJ","AL","AM","AN"]:
        ws[f"{col}{r}"] = "yes"
    ws[f"AI{r}"] = 4
ws.add_table(Table(displayName="Table1", ref=f"A2:AQ{2 + len(SAMPLE)}"))

out = Path(__file__).parent / "sample-tracker.xlsx"
wb.save(out)
print("wrote", out)
