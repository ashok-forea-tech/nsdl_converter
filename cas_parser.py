"""
NSDL CAS (Consolidated Account Statement) PDF -> structured data parser.

Design notes (why this exists):
NSDL CAS PDFs are NOT simple flowing text documents. They are built from
positioned table cells with colored background bands (no vector grid
lines), and long text (fund/company names) wraps onto continuation lines
INSIDE a cell, and even individual numbers (e.g. a unit count like
"19,003.736") can visually wrap across two lines. A naive "extract text
and split on whitespace" or generic "extract_table" approach silently
mis-assigns those wrapped fragments to the wrong row/column, which is
exactly how numbers come out wrong.

This parser instead works at the word-position level:
  1. For every table, it locates the column header row and computes each
     column's x-range from the header words' positions.
  2. It then walks the words below the header, groups them into column
     buckets, and detects the START of a new logical row using an anchor
     pattern for that table (an ISIN, a date, etc).
  3. Any words that appear before the next anchor are treated as
     CONTINUATION of the current row (wrapped text/number), and are
     merged into the correct column — text columns get a joining space,
     numeric columns get concatenated directly (so "19,003.73" + "6"
     correctly becomes "19,003.736" instead of two different values).

This is slower than a generic table-extraction call, but it is what
makes the numbers trustworthy.
"""

import re
import pdfplumber
import pikepdf
import io
from dataclasses import dataclass, field


# Standard ISIN format: 'IN' (India's country code) + 10 more alphanumeric characters
# (issuer + security identifier + check digit) = 12 chars total. The third character
# varies by instrument/registration type (E=equity, F=mutual fund, 0=govt securities,
# 8=rights/renunciation entitlements, and others) -- an earlier version only recognised
# INE/INF/IN0, which silently dropped whole holding rows for any other prefix (their
# anchor test failed, so the row's words were swept in as a "continuation" of the
# previous row and its numeric Value was discarded).
ISIN_RE = re.compile(r'^IN[A-Z0-9]{10}$')
NUMERIC_RE = re.compile(r'^-?[\d,]+\.?\d*$')
DATE_RE = re.compile(r'^\d{2}-[A-Za-z]{3}-\d{4}$')


def to_number(s):
    """Convert an Indian-formatted number string ('1,23,456.78', '-1.5%') to float. Returns None if not numeric."""
    if s is None:
        return None
    s = s.strip().replace(',', '').replace('%', '')
    if s in ('', '-', 'NA', 'See Note'):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def decrypt_pdf_bytes(path, password=None):
    """Return decrypted PDF bytes (in-memory) for a possibly password-protected NSDL CAS PDF."""
    with open(path, 'rb') as f:
        raw = f.read()
    try:
        pdf = pikepdf.open(io.BytesIO(raw), password=password or "")
    except pikepdf.PasswordError:
        raise ValueError("Incorrect password for this PDF.")
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


@dataclass
class ColumnSpec:
    name: str
    x0: float
    x1: float  # midpoint boundary to the next column (set after all columns known)
    kind: str = 'text'  # 'text' or 'num'


def build_columns(header_words, column_names_in_order, kind_map):
    """
    header_words: list of pdfplumber word dicts on the header line(s) we've already
                  identified as belonging to given column labels (by matching text).
    column_names_in_order: list of (label_text_to_find, output_name) in left-to-right order.
    Returns list[ColumnSpec] with x-ranges computed as midpoints between consecutive columns.
    """
    # Header label text is sometimes repeated across columns (e.g. "Value" appears both
    # inside "Face Value Per Unit" and as the final "Value" column; "Current" appears in
    # both "Current NAV" and "Current Value"). We resolve this by walking the requested
    # columns strictly left-to-right and, for each label, taking the next occurrence whose
    # x0 is greater than the previous column's x0 -- never the same occurrence twice.
    specs = []
    cursor_x = -1.0
    for label, out_name in column_names_in_order:
        candidates = sorted((w for w in header_words if w['text'] == label and w['x0'] > cursor_x),
                             key=lambda w: w['x0'])
        if not candidates:
            continue
        x0 = candidates[0]['x0']
        specs.append(ColumnSpec(out_name, x0, None, kind_map.get(out_name, 'text')))
        cursor_x = candidates[0]['x1'] + 15  # skip past this whole header word before next search
    # Boundaries are the midpoint between each pair of neighbouring header anchors (on both
    # sides), not the raw header x0 -- data cells routinely start a little left of where the
    # header label itself begins (e.g. right-leaning number columns), so using the header's
    # own x0 as a hard left edge clips real data into the wrong bucket.
    # Right-hand bias between two numeric columns: NSDL right-aligns numbers within each
    # column, so a value routinely sits closer to (or even past) the raw header-anchor
    # midpoint toward its own column's right edge than the header text position alone
    # would suggest. A small rightward nudge on numeric-numeric boundaries compensates
    # for that consistent drift without disturbing text-column boundaries (which don't
    # exhibit it, since text is left-aligned).
    NUMERIC_BOUNDARY_BIAS = 17
    anchors = [c.x0 for c in specs]
    for i, c in enumerate(specs):
        if i > 0:
            left = (anchors[i - 1] + anchors[i]) / 2
            if specs[i - 1].kind in ('num_int', 'num_dec', 'num') and c.kind in ('num_int', 'num_dec', 'num'):
                left += NUMERIC_BOUNDARY_BIAS
        else:
            left = anchors[i] - 40
        if i + 1 < len(specs):
            right = (anchors[i] + anchors[i + 1]) / 2
            if c.kind in ('num_int', 'num_dec', 'num') and specs[i + 1].kind in ('num_int', 'num_dec', 'num'):
                right += NUMERIC_BOUNDARY_BIAS
        else:
            right = anchors[i] + 400
        c.x0, c.x1 = left, right
    return specs


def word_kind_of(text):
    """Classify a token as 'num_int' (bare integer -- e.g. a folio number or share count),
    'num_dec' (a decimal amount/rate), or 'text'."""
    if not NUMERIC_RE.match(text):
        return 'text'
    return 'num_dec' if '.' in text else 'num_int'


def assign_column(word, columns):
    """
    Assign a word to a column. Position is checked first against ALL columns, and a clean
    position match into a TEXT column is always trusted -- free-text fields (fund/company
    names, descriptions) routinely contain digits as part of the name itself (e.g. "150"
    in "NIFTY MIDCAP 150 INDEX FUND"), and those must stay put rather than being yanked
    into a numeric column purely because the token looks numeric.

    The kind-based reasoning only kicks in for the genuinely ambiguous cases:
      - An alphabetic word's position lands inside a NUMERIC column (a wrapped text word
        bleeding slightly past its own column's edge) -- reroute to the nearest text column.
      - A numeric word's position lands inside a numeric column of the WRONG numeric
        subkind (int vs decimal) -- e.g. a right-aligned bare folio number sitting closer
        to the neighbouring decimal "Units" column than to its own column. Only then do we
        look for a same-subkind column nearby, and only override if the word sits within a
        small tolerance of that column's edge (a fragment genuinely wrapped mid-column,
        such as a decimal number's trailing digit, is deliberately left where position says).
    """
    word_kind = word_kind_of(word['text'])
    cx = (word['x0'] + word['x1']) / 2

    pos_matched = None
    for c in columns:
        if c.x0 <= cx < c.x1:
            pos_matched = c
            break
    if pos_matched is None:
        pos_matched = min(columns, key=lambda c: min(abs(cx - c.x0), abs(cx - c.x1)))

    if pos_matched.kind == 'text':
        return pos_matched

    if word_kind == 'text':
        text_cols = [c for c in columns if c.kind == 'text']
        if text_cols:
            return min(text_cols, key=lambda c: min(abs(cx - c.x0), abs(cx - c.x1)))
        return pos_matched

    if word_kind == pos_matched.kind or pos_matched.kind == 'num':
        return pos_matched

    # word is numeric but of the "wrong" numeric subkind for the column position matched --
    # only override to a same-subkind neighbour if the word sits right at that boundary.
    same_kind_cols = [c for c in columns if c.kind == word_kind]
    if same_kind_cols:
        nearest = min(same_kind_cols, key=lambda c: min(abs(cx - c.x0), abs(cx - c.x1)))
        if min(abs(cx - nearest.x0), abs(cx - nearest.x1)) < 6:
            return nearest
    return pos_matched


def group_rows_by_anchor(words, columns, anchor_col_name, anchor_test, stop_words=('Sub', 'Total')):
    """
    Walk words (already sorted by top, then x0) and build logical rows.
    A new row starts whenever a word assigned to `anchor_col_name` satisfies anchor_test(text).
    All other words (any column, any line) accumulate into the current row until the next anchor.
    Stops entirely once a word's text matches something in stop_words while no row is open,
    or more practically: caller should slice the word list to the section's page range beforehand.
    Returns list of dict(column_name -> merged string).
    """
    rows = []
    current = None
    i = 0
    n = len(words)
    while i < n:
        w = words[i]
        # NSDL prints the literal footnote "See Note" in place of a market price for
        # unlisted securities that have no traded price. It sits roughly where a numeric
        # value would go, so by position it can land in a numeric column -- but it isn't
        # data at all, and it must not be allowed to drift into a neighbouring text column
        # either (that would corrupt an otherwise-correct company/fund name). It's dropped
        # outright here, before column assignment, rather than handled through position or
        # kind heuristics that would have to fight the legitimate case of ordinary wrapped
        # text landing nearby.
        if w['text'] == 'See' and i + 1 < n and words[i + 1]['text'] == 'Note':
            i += 2
            continue
        col = assign_column(w, columns)
        txt = w['text']
        if col.name == anchor_col_name and anchor_test(txt):
            if current is not None:
                rows.append(current)
            current = {c.name: '' for c in columns}
            current[col.name] = txt
            i += 1
            continue
        if current is None:
            i += 1
            continue
        sep = '' if col.kind in ('num', 'num_int', 'num_dec') else ' '
        if current[col.name]:
            current[col.name] = current[col.name] + sep + txt
        else:
            current[col.name] = txt
        i += 1
    if current is not None:
        rows.append(current)
    return rows


def words_between(all_page_words_by_page, start_page, start_top, end_page, end_top):
    """Collect words strictly between two (page_index, top) cursor positions, in reading order."""
    out = []
    for pidx in range(start_page, end_page + 1):
        words = all_page_words_by_page[pidx]
        for w in words:
            if pidx == start_page and w['top'] <= start_top:
                continue
            if pidx == end_page and w['top'] >= end_top:
                continue
            out.append(w)
    return out


class CASDocument:
    """Loads a (decrypted) NSDL CAS PDF and exposes per-page word lists plus line-joined text."""

    def __init__(self, pdf_bytes):
        self._pdf = pdfplumber.open(io.BytesIO(pdf_bytes))
        self.pages_words = []
        self.pages_text = []
        for page in self._pdf.pages:
            words = page.extract_words(x_tolerance=1, y_tolerance=3, keep_blank_chars=False)
            # Every page repeats a bold banner ("Consolidated Account Statement" / the tab
            # strip) at the very top and a bold footer ("National Securities Depository
            # Limited <page#>") at the very bottom. These render with doubled glyphs (a
            # faux-bold PDF trick) and occasionally the footer's y-position lands close
            # enough to a table's last row near a page break to be swept into it. Neither
            # band carries any statement data, so they're dropped outright before any
            # section parsing happens.
            words = [w for w in words if 62 < w['top'] < page.height - 25]
            self.pages_words.append(words)
            self.pages_text.append(page.extract_text() or '')

    @property
    def n_pages(self):
        return len(self.pages_words)

    def close(self):
        self._pdf.close()
