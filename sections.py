import re
from cas_parser import ISIN_RE, DATE_RE, to_number, build_columns, group_rows_by_anchor, assign_column

# ---------------------------------------------------------------------------
# Line clustering: group words on a page into visual lines (by 'top')
# ---------------------------------------------------------------------------

def cluster_lines(words, tol=3):
    lines = []
    for w in sorted(words, key=lambda w: (w['top'], w['x0'])):
        if lines and abs(lines[-1]['top'] - w['top']) <= tol:
            lines[-1]['words'].append(w)
            lines[-1]['top'] = (lines[-1]['top'] + w['top']) / 2
        else:
            lines.append({'top': w['top'], 'words': [w]})
    for ln in lines:
        ln['words'].sort(key=lambda w: w['x0'])
        ln['text'] = ' '.join(w['text'] for w in ln['words'])
    return lines


ACCOUNT_HDR_RE = re.compile(r'^(NSDL|CDSL) Demat Account$')
DPID_RE = re.compile(r'DP ID:\s*(\S+)\s+Client ID:\s*(\S+)')
HOLDER_PAN_RE = re.compile(r'\(PAN:([A-Z0-9]+)\)')

SECTION_TRIGGERS = {
    'Equities (E)': 'equities',
    'Preference Shares (P)': 'preference',
    'Mutual Funds (M)': 'mf_holdings',
    'Sovereign Gold Bonds (SGB)': 'sgb',
    'Alternate Investment Fund (A)': 'aif',
    'Mutual Fund Folios (F)': 'mf_folios',
}

TABLE_DEFS = {
    'equities': {
        'header_labels': [('ISIN', 'ISIN'), ('Company', 'Company Name'), ('Face', 'Face Value'),
                           ('No.', 'No. of Shares'), ('Market', 'Market Price'), ('Value', 'Value')],
        'kinds': {'Face Value': 'num_dec', 'No. of Shares': 'num_int', 'Market Price': 'num_dec', 'Value': 'num_dec'},
        'anchor_col': 'ISIN',
    },
    'preference': {
        'header_labels': [('ISIN', 'ISIN'), ('Company', 'Company Name'), ('Face', 'Face Value'),
                           ('No.', 'No. of Shares'), ('Market', 'Market Price/Unit'), ('Value', 'Value')],
        'kinds': {'Face Value': 'num_dec', 'No. of Shares': 'num_int', 'Market Price/Unit': 'num_dec',
                  'Value': 'num_dec'},
        'anchor_col': 'ISIN',
    },
    'mf_holdings': {
        'header_labels': [('ISIN', 'ISIN'), ('ISIN', 'ISIN Description'), ('No.', 'No. of Units'),
                           ('NAV', 'NAV'), ('Value', 'Value')],
        'kinds': {'No. of Units': 'num_dec', 'NAV': 'num_dec', 'Value': 'num_dec'},
        'anchor_col': 'ISIN',
    },
    'aif': {
        'header_labels': [('ISIN', 'ISIN'), ('ISIN', 'ISIN Description'), ('No.', 'No. of Units'),
                           ('NAV', 'NAV'), ('Value', 'Value')],
        'kinds': {'No. of Units': 'num_dec', 'NAV': 'num_dec', 'Value': 'num_dec'},
        'anchor_col': 'ISIN',
    },
    'sgb': {
        'header_labels': [('ISIN', 'ISIN'), ('Issuer', 'Issuer Name'), ('Coupon', 'Coupon Rate/Frequency'),
                           ('Maturity', 'Maturity Date'), ('No.', 'No. of Units'), ('Face', 'Face Value/Unit'),
                           ('Market', 'Market Price/unit'), ('Value', 'Value')],
        'kinds': {'No. of Units': 'num_int', 'Face Value/Unit': 'num_dec', 'Market Price/unit': 'num_dec',
                  'Value': 'num_dec'},
        'anchor_col': 'ISIN',
    },
    'mf_folios': {
        'header_labels': [('ISIN', 'ISIN/UCC'), ('ISIN', 'ISIN Description'), ('Folio', 'Folio No.'),
                           ('No.', 'No. of Units'), ('Average', 'Avg Cost/Unit'), ('Total', 'Total Cost'),
                           ('Current', 'Current NAV/unit'), ('Current', 'Current Value'),
                           ('Unrealised', 'Unrealised P/L'), ('Annualised', 'Annualised Return %')],
        'kinds': {'Folio No.': 'num_int', 'No. of Units': 'num_dec', 'Avg Cost/Unit': 'num_dec',
                  'Total Cost': 'num_dec', 'Current NAV/unit': 'num_dec', 'Current Value': 'num_dec',
                  'Unrealised P/L': 'num_dec', 'Annualised Return %': 'num_dec'},
        'anchor_col': 'ISIN/UCC',
    },
}


def find_header_columns(lines, start_idx, table_key):
    """Look at lines[start_idx: start_idx+3] for the header words of this table type
    and build ColumnSpec list. Returns (columns, line_idx_after_header) or (None, start_idx)."""
    defn = TABLE_DEFS[table_key]
    header_words = []
    scanned = 0
    idx = start_idx
    # Header for these tables is always exactly 2 physical lines
    while idx < len(lines) and scanned < 3:
        header_words.extend(lines[idx]['words'])
        scanned += 1
        # Stop once we've collected words for all target labels at least once
        found_names = set()
        for label, out_name in defn['header_labels']:
            if any(w['text'] == label for w in header_words):
                found_names.add(out_name)
        if len(found_names) >= len(set(n for _, n in defn['header_labels'])):
            idx += 1
            break
        idx += 1
    cols = build_columns(header_words, defn['header_labels'], defn['kinds'])
    if len(cols) < 3:
        return None, start_idx
    return cols, idx


def is_stop_line(text):
    t = text.strip()
    return t.startswith('Sub Total') or t.startswith('Total') or t.startswith('Notes:') or \
        t.startswith('Total Expense Ratio')


def extract_table_rows(lines, header_end_idx, columns, anchor_col_name):
    """Collect rows from lines[header_end_idx:] until a stop line.
    Returns (rows, subtotal, next_idx, terminated) -- `terminated` is True only when an
    actual stop line (Sub Total / Total / Notes: / Total Expense Ratio) was found, as
    opposed to simply running out of lines on this page because the table continues onto
    the next one. The caller uses this to decide whether the current section is truly
    finished (safe to stop treating a bare 'ISIN' word as this table's header again) or
    still open (must keep recognising the repeated header on the following page).
    """
    row_words = []
    idx = header_end_idx
    subtotal = None
    terminated = False
    while idx < len(lines):
        text = lines[idx]['text']
        if is_stop_line(text):
            m = re.search(r'([\d,]+\.\d{2})\s*$', text)
            if m:
                subtotal = to_number(m.group(1))
            idx += 1
            terminated = True
            break
        row_words.extend(lines[idx]['words'])
        idx += 1
    rows = group_rows_by_anchor(row_words, columns, anchor_col_name,
                                 lambda t: bool(ISIN_RE.match(t)))
    return rows, subtotal, idx, terminated


def parse_document(doc):
    """
    doc: CASDocument
    Returns dict with keys: summary, holdings (list of dict), mf_folios (list of dict)
    """
    holdings = []      # each: {account, holder, pan, asset_class, **row}
    mf_folios = []      # each: {**row}
    summary = {}

    current_account = None
    current_holder = None
    current_pan = None
    mode = None

    for pidx in range(doc.n_pages):
        words = doc.pages_words[pidx]
        lines = cluster_lines(words)
        i = 0
        while i < len(lines):
            text = lines[i]['text']

            if ACCOUNT_HDR_RE.match(text.strip()):
                # DP name is typically the next line; DP ID/Client ID line follows
                dp_name = lines[i + 1]['text'].strip() if i + 1 < len(lines) else ''
                j = i + 1
                dp_id = client_id = None
                while j < len(lines) and j < i + 5:
                    m = DPID_RE.search(lines[j]['text'])
                    if m:
                        dp_id, client_id = m.group(1), m.group(2)
                        break
                    j += 1
                # holder/PAN appears on a nearby line containing "(PAN:"
                k = i
                holder = pan = None
                while k < len(lines) and k < i + 8:
                    m = HOLDER_PAN_RE.search(lines[k]['text'])
                    if m:
                        pan = m.group(1)
                        holder = re.sub(r'\s*\(PAN:.*\)', '', lines[k]['text']).strip()
                        break
                    k += 1
                current_account = f"{dp_name} (DP ID:{dp_id} Client ID:{client_id})"
                current_holder = holder
                current_pan = pan
                i += 1
                continue

            # Portfolio composition (summary) capture
            if text.strip() == 'PORTFOLIO COMPOSITION':
                j = i + 2  # skip header row 'ASSET CLASS Value in ` %'
                comp = {}
                while j < len(lines) and not lines[j]['text'].strip().startswith('TOTAL'):
                    m = re.match(r'^(.*?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d.]+)%$', lines[j]['text'].strip())
                    if m:
                        comp[m.group(1).strip()] = to_number(m.group(2))
                    j += 1
                summary['portfolio_composition'] = comp
                i = j
                continue

            if text.strip().startswith('YOUR CONSOLIDATED PORTFOLIO VALUE'):
                m = re.search(r'([\d,]+\.\d{2})', text)
                if m:
                    summary['consolidated_portfolio_value'] = to_number(m.group(1))
                i += 1
                continue

            matched_trigger = None
            for label, key in SECTION_TRIGGERS.items():
                if text.strip() == label:
                    matched_trigger = key
                    break
            if matched_trigger:
                mode = matched_trigger
                i += 1
                continue

            # If current mode's header appears here, parse the table
            if mode in TABLE_DEFS:
                defn = TABLE_DEFS[mode]
                probe_words = lines[i]['words'] + (lines[i + 1]['words'] if i + 1 < len(lines) else [])
                first_label = defn['header_labels'][0][0]
                if any(w['text'] == first_label for w in lines[i]['words']):
                    cols, after_idx = find_header_columns(lines, i, mode)
                    if cols:
                        rows, subtotal, next_idx, terminated = extract_table_rows(
                            lines, after_idx, cols, defn['anchor_col'])
                        for r in rows:
                            r = {k: v.strip() for k, v in r.items()}
                            if not r.get(defn['anchor_col']):
                                continue
                            if mode == 'mf_folios':
                                r['_subtotal_of_page'] = subtotal
                                mf_folios.append(r)
                            else:
                                r['account'] = current_account
                                r['holder'] = current_holder
                                r['pan'] = current_pan
                                r['asset_class'] = mode
                                r['_subtotal_of_page'] = subtotal
                                holdings.append(r)
                        if terminated:
                            mode = None
                        i = next_idx
                        continue
            i += 1

    return {'summary': summary, 'holdings': holdings, 'mf_folios': mf_folios}


# ---------------------------------------------------------------------------
# Transactions (demat corporate-action/transfer ledger, and MF transaction statement)
# ---------------------------------------------------------------------------

# Demat's own ISIN header uses "ISIN : <code> - <name>" (a space before the colon). The
# Mutual Fund transaction table uses "ISIN: <code> - <name> ... Folio No - <folio>" (no
# space before the colon). These must NOT be conflated -- an earlier version's regex
# matched both, which let demat-transaction row collection silently run on past the end
# of the demat section into the MF transaction table (different columns entirely) and,
# in the worst case, into the closing KYC/address section, producing rows with numbers
# that don't mean what the column header claims. The space requirement here is the fix.
ISIN_HEADER_RE = re.compile(r'^ISIN\s+:\s*([A-Z0-9]+)\s*-\s*(.+)$')
MF_ISIN_HEADER_RE = re.compile(r'^ISIN:\s*([A-Z0-9]+)\s*-\s*(.+?)\s+Folio\s+No\s*-\s*(\S+)\s*$')
OPENING_BAL_RE = re.compile(r'^Opening\s+Balance\s+([\d,]+\.?\d*)\s*$')
CLOSING_BAL_RE = re.compile(r'^Closing\s+Balance\s+([\d,]+\.?\d*)\s*$')
MF_DATE_RE = re.compile(r'^\d{2}-[A-Za-z]{3}-\d{4}$')
# Hard stops: once any of these appear, demat-transaction row collection must not continue
# under stale column definitions, no matter what a later line's shape happens to look like.
DEMAT_TXN_HARD_STOPS = ('MUTUAL FUND FOLIOS (F)', 'Mutual Funds Transaction Statement',
                         'Know more about your accounts', '***End of Statement***', 'About NSDL')


def parse_demat_transactions(doc):
    """Per-ISIN ledger of demat corporate-action / transfer entries (Date, Order No,
    Description, Instruction Details, Opening/Debit/Credit/Closing Balance)."""
    out = []
    current_account = None
    current_holder = None
    current_isin = None
    current_company = None
    columns = None
    for pidx in range(doc.n_pages):
        lines = cluster_lines(doc.pages_words[pidx])
        i = 0
        while i < len(lines):
            text = lines[i]['text'].strip()

            if any(text.startswith(stop) for stop in DEMAT_TXN_HARD_STOPS):
                # Demat transactions are conclusively over -- never let stale columns or a
                # stale current_isin cause anything after this point to be collected.
                current_isin = None
                columns = None
                i += 1
                continue

            if ACCOUNT_HDR_RE.match(text) and i + 1 < len(lines) and \
                    lines[i + 1]['text'].strip() == 'Summary of Transactions of':
                j = i
                dp_id = client_id = None
                while j < len(lines) and j < i + 6:
                    m = DPID_RE.search(lines[j]['text'])
                    if m:
                        dp_id, client_id = m.group(1), m.group(2)
                        break
                    j += 1
                dp_line = lines[i + 2]['text'].strip() if i + 2 < len(lines) else ''
                holder_line = lines[i + 3]['text'].strip() if i + 3 < len(lines) else ''
                current_account = f"{dp_line} (DP ID:{dp_id} Client ID:{client_id})"
                current_holder = holder_line
                i += 1
                continue

            m = ISIN_HEADER_RE.match(text)
            if m:
                current_isin, current_company = m.group(1), m.group(2)
                i += 1
                continue

            if lines[i]['words'] and lines[i]['words'][0]['text'] == 'Date' \
                    and any(w['text'] == 'Order' for w in lines[i]['words']):
                header_words = list(lines[i]['words'])
                if i + 1 < len(lines):
                    header_words += lines[i + 1]['words']
                if i - 1 >= 0:
                    header_words += lines[i - 1]['words']  # 'Opening'/'Closing' sit one line above 'Date'
                labels = [('Date', 'Date'), ('Order', 'Order No'), ('Description', 'Description'),
                          ('Instruction', 'Instruction Details'), ('Opening', 'Opening Balance'),
                          ('Debit', 'Debit'), ('Credit', 'Credit'), ('Closing', 'Closing Balance')]
                kinds = {'Order No': 'num_int', 'Opening Balance': 'num_dec', 'Debit': 'num_dec',
                         'Credit': 'num_dec', 'Closing Balance': 'num_dec'}
                columns = build_columns(header_words, labels, kinds)
                i += 2
                continue

            if text.startswith('Beneficiary'):
                i += 1
                continue

            if columns and current_isin and lines[i]['words'] and DATE_RE.match(lines[i]['words'][0]['text']):
                row_words = []
                j = i
                while j < len(lines):
                    t2 = lines[j]['text'].strip()
                    if ISIN_HEADER_RE.match(t2) or ACCOUNT_HDR_RE.match(t2) or \
                            (lines[j]['words'] and lines[j]['words'][0]['text'] == 'Date') or \
                            t2.startswith('Transactions') or t2 == 'Beneficiary' or \
                            any(t2.startswith(stop) for stop in DEMAT_TXN_HARD_STOPS):
                        break
                    row_words.extend(lines[j]['words'])
                    j += 1
                rows = group_rows_by_anchor(row_words, columns, 'Date',
                                             lambda t: bool(DATE_RE.match(t)))
                for r in rows:
                    r = {k: v.strip() for k, v in r.items()}
                    r['account'] = current_account
                    r['holder'] = current_holder
                    r['ISIN'] = current_isin
                    r['Company/Scheme'] = current_company
                    out.append(r)
                i = j
                continue

            i += 1
    return out


def parse_mf_transactions(doc):
    """Per-folio ledger of mutual fund transactions (Date, Transaction Details, Amount,
    Stamp Duty, NAV, Price, Units), bounded by Opening Balance / Closing Balance lines."""
    out = []
    columns = None
    current_isin = current_scheme = current_folio = None
    for pidx in range(doc.n_pages):
        lines = cluster_lines(doc.pages_words[pidx])
        i = 0
        while i < len(lines):
            text = lines[i]['text'].strip()

            if lines[i]['words'] and lines[i]['words'][0]['text'] == 'Date' and \
                    any(w['text'] == 'Transaction' for w in lines[i]['words']):
                header_words = list(lines[i]['words'])
                if i + 1 < len(lines):
                    header_words += lines[i + 1]['words']
                labels = [('Date', 'Date'), ('Transaction', 'Transaction Details'),
                          ('Amount', 'Amount'), ('Stamp', 'Stamp Duty'), ('NAV', 'NAV'),
                          ('Price', 'Price'), ('Units', 'Units')]
                kinds = {'Amount': 'num_dec', 'Stamp Duty': 'num_dec', 'NAV': 'num_dec',
                         'Price': 'num_dec', 'Units': 'num_dec'}
                columns = build_columns(header_words, labels, kinds)
                i += 2
                continue

            m = MF_ISIN_HEADER_RE.match(text)
            if m:
                current_isin, current_scheme, current_folio = m.group(1), m.group(2), m.group(3)
                i += 1
                continue

            if OPENING_BAL_RE.match(text):
                i += 1
                continue

            if columns and current_isin and lines[i]['words'] and MF_DATE_RE.match(lines[i]['words'][0]['text']):
                row_words = []
                j = i
                while j < len(lines):
                    t2 = lines[j]['text'].strip()
                    if MF_ISIN_HEADER_RE.match(t2) or CLOSING_BAL_RE.match(t2) or \
                            (lines[j]['words'] and lines[j]['words'][0]['text'] == 'Date') or \
                            t2.startswith('***End'):
                        break
                    row_words.extend(lines[j]['words'])
                    j += 1
                rows = group_rows_by_anchor(row_words, columns, 'Date',
                                             lambda t: bool(MF_DATE_RE.match(t)))
                for r in rows:
                    r = {k: v.strip() for k, v in r.items()}
                    r['ISIN'] = current_isin
                    r['Scheme'] = current_scheme
                    r['Folio No.'] = current_folio
                    out.append(r)
                i = j
                continue

            i += 1
    return out
