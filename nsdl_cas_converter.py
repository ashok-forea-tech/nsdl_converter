"""
NSDL CAS to Excel Converter
---------------------------
Converts an NSDL Consolidated Account Statement (CAS) PDF into a clean,
multi-sheet Excel workbook. Runs entirely on your own computer -- the PDF
and the password never leave this machine, no internet connection is used.

Usage (double-click / no arguments): opens a simple window to pick the
PDF, enter its password (if any), and choose where to save the Excel file.

Usage (command line):
    python nsdl_cas_converter.py statement.pdf [-o output.xlsx] [-p PASSWORD]
"""
import sys
import os
import argparse
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cas_parser import CASDocument, decrypt_pdf_bytes, to_number
from sections import parse_document, parse_demat_transactions, parse_mf_transactions
from excel_writer import write_workbook, write_workbook_full


def convert(pdf_path, out_path, password=None, log=print):
    log(f"Reading {os.path.basename(pdf_path)} ...")
    pdf_bytes = decrypt_pdf_bytes(pdf_path, password)
    log("Decrypted. Parsing statement tables (this may take a few seconds)...")
    doc = CASDocument(pdf_bytes)
    result = parse_document(doc)
    n_holdings = len(result['holdings'])
    n_folios = len(result['mf_folios'])
    log(f"Found {n_holdings} demat holdings and {n_folios} mutual fund folio rows.")
    _reconcile(result, log)
    log("Parsing transaction ledgers...")
    demat_txns = parse_demat_transactions(doc)
    mf_txns = parse_mf_transactions(doc)
    doc.close()
    log(f"Found {len(demat_txns)} demat transaction rows and {len(mf_txns)} mutual fund transaction rows.")
    _reconcile_transactions(demat_txns, mf_txns, log)
    log(f"Writing {os.path.basename(out_path)} ...")
    write_workbook_full(result, demat_txns, mf_txns, out_path, source_filename=os.path.basename(pdf_path))
    log("Done.")
    return result


def _reconcile(result, log):
    """Cross-check extracted line-item totals against the statement's own printed
    portfolio-composition summary. This is the actual trustworthiness check: if every
    detail row for an asset class sums to the same figure NSDL printed as that class's
    total, the numbers were read correctly -- not merely 'a number was produced'."""
    comp = result['summary'].get('portfolio_composition', {})
    checks = [
        ('equities', 'Equities (E)', 'Value'),
        ('preference', 'Preference Shares (P)', 'Value'),
        ('mf_holdings', 'Mutual Funds (M)', 'Value'),
        ('aif', 'Alternate Investment Fund (A)', 'Value'),
        ('sgb', 'Sovereign Gold Bonds (SGB)', 'Value'),
    ]
    by_class = {}
    for h in result['holdings']:
        by_class.setdefault(h['asset_class'], []).append(h)
    all_ok = True
    for cls, comp_key, value_field in checks:
        printed = comp.get(comp_key)
        if printed is None:
            continue
        computed = sum((to_number(r.get(value_field)) or 0) for r in by_class.get(cls, []))
        ok = abs(computed - printed) < 0.5
        all_ok = all_ok and ok
        mark = 'OK' if ok else 'MISMATCH'
        log(f"  [{mark}] {comp_key}: sheet total {computed:,.2f} vs statement total {printed:,.2f}")
    printed_folios = comp.get('Mutual Fund Folios (F)')
    if printed_folios is not None:
        computed = sum((to_number(r.get('Current Value')) or 0) for r in result['mf_folios'])
        ok = abs(computed - printed_folios) < 0.5
        all_ok = all_ok and ok
        mark = 'OK' if ok else 'MISMATCH'
        log(f"  [{mark}] Mutual Fund Folios (F): sheet total {computed:,.2f} vs statement total {printed_folios:,.2f}")
    log("All asset-class totals reconcile with the statement's own summary."
        if all_ok else
        "WARNING: one or more asset classes did not reconcile -- please spot-check that sheet.")


def _reconcile_transactions(demat_txns, mf_txns, log):
    """Independent arithmetic checks on the transaction ledgers themselves -- these don't
    rely on any statement-printed total, they check each row's own internal consistency:
    for a demat entry, Opening Balance - Debit + Credit must equal Closing Balance; for an
    MF transaction, the NAV and Price columns should agree (NSDL prints the same figure in
    both for a standard transaction). A row failing either check is a strong, row-level
    signal that something was mis-parsed, not merely a rounding footnote."""
    bad_demat = 0
    for r in demat_txns:
        vals = [to_number(r.get(k)) for k in ('Opening Balance', 'Debit', 'Credit', 'Closing Balance')]
        if any(v is None for v in vals) or abs((vals[0] - vals[1] + vals[2]) - vals[3]) > 0.01:
            bad_demat += 1
    mark = 'OK' if bad_demat == 0 else 'MISMATCH'
    log(f"  [{mark}] Demat Transactions: {len(demat_txns) - bad_demat}/{len(demat_txns)} rows satisfy "
        f"Opening - Debit + Credit = Closing")

    bad_mf = 0
    for r in mf_txns:
        nav, price = to_number(r.get('NAV')), to_number(r.get('Price'))
        if nav is None or price is None or abs(nav - price) > 0.001:
            bad_mf += 1
    mark = 'OK' if bad_mf == 0 else 'MISMATCH'
    log(f"  [{mark}] MF Transactions: {len(mf_txns) - bad_mf}/{len(mf_txns)} rows have NAV = Price as expected")



def run_cli():
    ap = argparse.ArgumentParser(description="Convert an NSDL CAS PDF to Excel.")
    ap.add_argument('pdf', help="Path to the NSDL CAS PDF")
    ap.add_argument('-o', '--output', help="Output .xlsx path (default: same name as PDF)")
    ap.add_argument('-p', '--password', help="PDF password, if protected")
    args = ap.parse_args()

    out_path = args.output or (os.path.splitext(args.pdf)[0] + '.xlsx')
    password = args.password
    if password is None:
        # Try without a password first (already-decrypted files), else prompt.
        try:
            decrypt_pdf_bytes(args.pdf, None)
        except ValueError:
            import getpass
            password = getpass.getpass("PDF password: ")
    try:
        convert(args.pdf, out_path, password)
        print(f"\nSaved: {out_path}")
    except Exception as e:
        print(f"\nError: {e}")
        sys.exit(1)


def run_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("NSDL CAS \u2192 Excel Converter")
    root.geometry("560x420")
    root.resizable(False, False)

    state = {'pdf_path': None, 'out_path': None}

    frm = tk.Frame(root, padx=16, pady=16)
    frm.pack(fill='both', expand=True)

    tk.Label(frm, text="NSDL CAS \u2192 Excel Converter", font=('Segoe UI', 14, 'bold')).pack(anchor='w')
    tk.Label(frm, text="Runs fully offline. Nothing leaves this computer.",
             fg='#555').pack(anchor='w', pady=(0, 12))

    file_row = tk.Frame(frm)
    file_row.pack(fill='x', pady=4)
    file_label = tk.Label(file_row, text="No file selected", anchor='w', fg='#333')
    file_label.pack(side='left', fill='x', expand=True)

    def pick_file():
        path = filedialog.askopenfilename(title="Select NSDL CAS PDF", filetypes=[("PDF files", "*.pdf")])
        if path:
            state['pdf_path'] = path
            file_label.config(text=os.path.basename(path))
            default_out = os.path.splitext(path)[0] + '.xlsx'
            state['out_path'] = default_out
            out_label.config(text=os.path.basename(default_out))

    tk.Button(file_row, text="Choose PDF...", command=pick_file).pack(side='right')

    pw_row = tk.Frame(frm)
    pw_row.pack(fill='x', pady=8)
    tk.Label(pw_row, text="PDF Password (leave blank if none):").pack(anchor='w')
    pw_var = tk.StringVar()
    tk.Entry(pw_row, textvariable=pw_var, show='*').pack(fill='x', pady=(4, 0))

    out_row = tk.Frame(frm)
    out_row.pack(fill='x', pady=8)
    out_label = tk.Label(out_row, text="(same folder as PDF)", anchor='w', fg='#333')
    out_label.pack(side='left', fill='x', expand=True)

    def pick_out():
        if not state['pdf_path']:
            messagebox.showinfo("Choose a PDF first", "Please choose the CAS PDF first.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".xlsx",
                                             initialfile=os.path.basename(state['out_path']),
                                             filetypes=[("Excel files", "*.xlsx")])
        if path:
            state['out_path'] = path
            out_label.config(text=os.path.basename(path))

    tk.Button(out_row, text="Save As...", command=pick_out).pack(side='right')

    log_box = tk.Text(frm, height=10, state='disabled', bg='#f4f4f4', wrap='word')
    log_box.pack(fill='both', expand=True, pady=(12, 8))

    def log(msg):
        log_box.config(state='normal')
        log_box.insert('end', msg + '\n')
        log_box.see('end')
        log_box.config(state='disabled')
        root.update_idletasks()

    def do_convert():
        if not state['pdf_path']:
            messagebox.showinfo("Choose a PDF first", "Please choose the CAS PDF first.")
            return
        log_box.config(state='normal')
        log_box.delete('1.0', 'end')
        log_box.config(state='disabled')
        try:
            convert(state['pdf_path'], state['out_path'], pw_var.get() or None, log=log)
            messagebox.showinfo("Done", f"Saved:\n{state['out_path']}")
        except Exception as e:
            log(f"ERROR: {e}")
            log(traceback.format_exc())
            messagebox.showerror("Conversion failed", str(e))

    tk.Button(frm, text="Convert to Excel", command=do_convert, bg='#8B1E2D', fg='white',
              font=('Segoe UI', 11, 'bold'), pady=6).pack(fill='x')

    root.mainloop()


if __name__ == '__main__':
    if len(sys.argv) > 1:
        run_cli()
    else:
        try:
            run_gui()
        except ImportError:
            print("tkinter not available -- use command-line mode instead:")
            print("  python nsdl_cas_converter.py statement.pdf")
