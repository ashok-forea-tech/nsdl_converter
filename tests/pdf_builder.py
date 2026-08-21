"""Minimal synthetic-PDF builder for CAS parser regression fixtures.

Renders text in a fixed-width font so each line's word x-positions are
predictable from character offsets alone -- close enough to how NSDL's real
PDFs tokenise for pdfplumber's word extraction, without needing to replicate
their exact typesetting. All fixture content is fabricated (fake PAN, names,
account numbers, ISINs, amounts); nothing here is derived from a real
statement.
"""

import io
from reportlab.pdfgen import canvas

PAGE_WIDTH, PAGE_HEIGHT = 595, 842
FONT_NAME = 'Courier'
FONT_SIZE = 9
CHAR_WIDTH = FONT_SIZE * 0.6  # exact for Courier in reportlab's AFM metrics

# cas_parser.CASDocument drops every word outside this vertical band (it
# strips the repeated page banner/footer) -- fixture content must stay inside it.
TOP_MARGIN = 65
BOTTOM_MARGIN = PAGE_HEIGHT - 30


class PageWriter:
    """Writes lines at a given pdfplumber-style 'top' (distance from page
    top), left-anchored at a given column of a fixed-width grid."""

    def __init__(self, c):
        self.c = c
        self.c.setFont(FONT_NAME, FONT_SIZE)

    def line(self, top, text, col=0):
        if top < TOP_MARGIN or top > BOTTOM_MARGIN:
            raise ValueError(f"line at top={top} falls outside the parser's visible band "
                              f"({TOP_MARGIN}-{BOTTOM_MARGIN})")
        x = col * CHAR_WIDTH
        y = PAGE_HEIGHT - top - FONT_SIZE
        self.c.drawString(x, y, text)


class CASFixtureBuilder:
    """Accumulates pages of (top, text, col) lines and renders them to PDF bytes."""

    def __init__(self):
        self._pages = [[]]

    def add(self, top, text, col=0):
        self._pages[-1].append((top, text, col))
        return self

    def new_page(self):
        self._pages.append([])
        return self

    def render(self):
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(PAGE_WIDTH, PAGE_HEIGHT))
        for page_lines in self._pages:
            w = PageWriter(c)
            for top, text, col in page_lines:
                w.line(top, text, col)
            c.showPage()
        c.save()
        return buf.getvalue()

    def save(self, path):
        with open(path, 'wb') as f:
            f.write(self.render())


def cols(widths, gap=4):
    """Given the max character width expected in each column (label or any
    row value, whichever is wider), returns a list of safe left-edge char
    offsets with `gap` chars of breathing room between columns -- avoids
    hand-picked offsets that let adjacent columns' text visually overlap
    and get tokenised as one run by pdfplumber."""
    starts = []
    x = 0
    for w in widths:
        starts.append(x)
        x += w + gap
    return starts


def account_header(b, top, kind='NSDL', dp_name='FAKE BROKING LIMITED', dp_id='IN900000',
                    client_id='00000000', holder='TEST HOLDER', pan='ABCDE1234F'):
    """Writes the 4-line account header block parse_document/parse_demat_transactions
    both key off (ACCOUNT_HDR_RE, DPID_RE, HOLDER_PAN_RE), starting at `top`.
    Returns the `top` of the next free line."""
    b.add(top, f'{kind} Demat Account')
    b.add(top + 14, 'ACCOUNT HOLDER')
    b.add(top + 28, dp_name)
    b.add(top + 42, f'{holder} (PAN:{pan})')
    b.add(top + 56, f'DP ID: {dp_id} Client ID: {client_id}')
    return top + 70


def demat_txn_account_header(b, top, dp_name='FAKE BROKING LIMITED', dp_id='IN900000',
                              client_id='00000000', holder='TEST HOLDER', kind='NSDL'):
    """The demat-transactions ledger's own account header variant, keyed off
    ACCOUNT_HDR_RE followed by a line literally 'Summary of Transactions of'."""
    b.add(top, f'{kind} Demat Account')
    b.add(top + 14, 'Summary of Transactions of')
    b.add(top + 28, dp_name)
    b.add(top + 42, holder)
    b.add(top + 56, f'DP ID: {dp_id} Client ID: {client_id}')
    return top + 70
