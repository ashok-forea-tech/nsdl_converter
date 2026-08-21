# NSDL CAS to Excel Converter

Convert an NSDL Consolidated Account Statement (CAS) PDF into a clean,
accurate, multi-sheet Excel workbook — entirely offline.

Not affiliated with NSDL. Unofficial, community tool.

## Why this exists

NSDL CAS PDFs are notoriously hard to convert accurately. They pack
numeric columns tightly with no visible grid lines and right-aligned
figures — exactly the conditions that make naive "extract the text" or
generic "extract the table" tools silently glue two adjacent numbers
together (a folio number fused to a unit count, a NAV fused to a
value, and so on). Several commercial and open-source converters get
this wrong in ways that are hard to spot just by looking at the
output.

This tool reads the exact pixel position of every word in the PDF,
derives each table's real column boundaries from its own header row,
and distinguishes bare integers (folio numbers, share counts) from
decimal amounts (costs, NAVs, values in `,`-grouped Indian format) to
resolve exactly the boundary cases that trip up simpler converters.

It was built and iteratively corrected against two real CAS
statements (different months, different holdings, different
transaction types — bonus issues, NFO purchases, redemptions, SIPs,
switches, zero-balance folios, unlisted securities) until every
figure matched the source PDF exactly.

## What you get

One Excel workbook with these sheets (only sheets with data are
created):

- **Summary** — consolidated portfolio value and asset-class breakdown
- **Equities**, **Preference Shares**, **Mutual Funds (Demat)**,
  **Sovereign Gold Bonds**, **Alternate Investment Fund** — holdings
  by asset class, across every demat account in the statement
- **Mutual Fund Folios** — units, average cost, current NAV, current
  value, unrealised P/L, and annualised return per folio
- **Demat Transactions** — every corporate-action/transfer entry per
  ISIN, with opening/debit/credit/closing balances
- **MF Transactions** — every switch/purchase/redemption/SIP per
  folio, with amount, stamp duty, NAV, price, and units

## Built-in verification

Every run prints independent reconciliation checks — this is the
actual point of the tool, not a decorative log:

- **Asset-class totals**: every extracted line item is summed and
  compared against NSDL's own printed portfolio-composition total for
  that asset class.
- **Demat transaction arithmetic**: `Opening Balance − Debit + Credit`
  must equal `Closing Balance` for every row — checked independently
  of any statement total.
- **MF transaction sanity**: NAV and Price are checked to agree on
  every row, as NSDL always prints them.

If any check comes back `MISMATCH`, the tool is telling you exactly
which sheet needs a manual look. It is not a silent failure.

## Getting the double-click app

**Option A — download a pre-built release.** Check the
[Releases](../../releases) page for a ready-made
`NSDL_CAS_Converter.exe` (built automatically by this repo's GitHub
Actions workflow on Windows).

**Option B — build it yourself (also just one step).** On Windows,
with Python installed:
1. Double-click `build_windows_exe.bat`.
2. Your app is at `dist\NSDL_CAS_Converter.exe` — copy it anywhere;
   nobody needs Python installed to run it from then on.

**Option C — run from source** (any OS):
```
pip install -r requirements.txt
python nsdl_cas_converter.py statement.pdf -o output.xlsx
```

## Using the app

1. Launch it (double-click the exe, or run the script).
2. Choose the CAS PDF.
3. Enter its password if it has one.
4. Choose where to save the Excel file, or accept the default.
5. Click "Convert to Excel" — the log panel shows the reconciliation
   checks as they run.

Runs **entirely offline**. The PDF and its password never leave your
machine — there is no network code in this tool at all.

## How it works

- `cas_parser.py` — the core word-position engine: decrypts the PDF,
  locates table column boundaries from header rows, and assigns each
  word to the correct column using both position and value type
  (integer vs. decimal vs. text).
- `sections.py` — table-specific extractors (Summary, Holdings by
  asset class, Mutual Fund Folios, Demat Transactions, MF
  Transactions).
- `excel_writer.py` — writes the parsed data into a formatted
  workbook.
- `nsdl_cas_converter.py` — CLI + Tkinter GUI entry point, plus the
  reconciliation checks.

## Utilities

`utils/decrypt-pdf.py` — standalone helper to remove password
protection from a CAS PDF, producing a plain, unlocked copy:
```
python utils/decrypt-pdf.py statement.pdf mypassword
```
Writes `statement_decrypt.pdf` alongside the input file.

## Known limitations

- Tested against NSDL's standard CAS layout (the one shown in this
  README). Other RTAs' consolidated statement formats (e.g. CDSL's)
  use a different layout and are not currently supported.
- The password-unlock step assumes a standard PDF user-password
  encryption; unusual protection schemes may not open.
- If NSDL changes their statement's column layout, extraction may
  need updating — please open an issue with a masked/dummy sample if
  you hit this.

## Contributing

Issues and pull requests welcome. If you hit a parsing bug, the most
useful thing you can attach is a **masked or dummy CAS PDF** that
reproduces it (never a real statement) — real column-position bugs
are much easier to fix with a concrete example than a description.

## Disclaimer

This is an independent, community-built tool and is not affiliated
with, endorsed by, or supported by NSDL. It is provided as-is (see
[LICENSE](LICENSE)) with no warranty. Always spot-check the
reconciliation output against your actual statement before relying on
the converted figures for tax, audit, or compliance purposes.
