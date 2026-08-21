"""Generates the synthetic CAS regression fixtures into test_fixtures/.

Every fixture is a small, fabricated PDF (fake PAN/names/account numbers,
fake ISINs, fake amounts) built with tests/pdf_builder.py, engineered to
reproduce one specific real-world layout or edge case the parser has to
handle. Run directly to (re)generate all fixtures:

    python tests/generate_fixtures.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from pdf_builder import CASFixtureBuilder, account_header, demat_txn_account_header, cols  # noqa: E402

OUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'test_fixtures')


def fixture_standard_nsdl():
    """Baseline: NSDL account, standard 2-line Equities header, 2 rows."""
    b = CASFixtureBuilder()
    C_ISIN, C_NAME, C_FACE, C_NO, C_MKT, C_VAL = cols([13, 14, 6, 6, 8, 10])
    top = account_header(b, 70, kind='NSDL')
    b.add(top, 'Equities (E)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'Company', C_NAME).add(top, 'Face', C_FACE) \
        .add(top, 'No.', C_NO).add(top, 'Market', C_MKT).add(top, 'Value', C_VAL)
    top += 14
    b.add(top, 'Stock', C_NAME).add(top, 'Shares', C_NO).add(top, 'Price', C_MKT)
    top += 14
    b.add(top, 'INE111111111', C_ISIN).add(top, 'ALPHA TESTCO', C_NAME).add(top, '2.00', C_FACE) \
        .add(top, '100', C_NO).add(top, '250.00', C_MKT).add(top, '25,000.00', C_VAL)
    top += 14
    b.add(top, 'LIMITED', C_NAME)
    top += 14
    b.add(top, 'INE222222222', C_ISIN).add(top, 'BETA TESTCO', C_NAME).add(top, '10.00', C_FACE) \
        .add(top, '50', C_NO).add(top, '100.00', C_MKT).add(top, '5,000.00', C_VAL)
    top += 14
    b.add(top, 'LIMITED', C_NAME)
    top += 14
    b.add(top, 'Sub Total 30,000.00', 0)
    top += 14
    b.add(top, 'Total 30,000.00', 0)
    return b


def fixture_cdsl_holdings_layout():
    """CDSL's Current/Safekeep/Pledged-Bal. holdings layout (Mutual Funds).
    Regression for: values dropped/garbled under the different CDSL column
    set, and balance-breakdown continuation lines corrupting the real
    Quantity/Value figures via blind same-column concatenation."""
    b = CASFixtureBuilder()
    C_ISIN, C_SEC, C_CUR, C_SAFE, C_PLED, C_MKT, C_VAL = cols([13, 12, 8, 8, 8, 6, 10])
    top = account_header(b, 70, kind='CDSL')
    b.add(top, 'Mutual Funds (M)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'SECURITY', C_SEC).add(top, 'Current', C_CUR) \
        .add(top, 'Safekeep', C_SAFE).add(top, 'Pledged', C_PLED).add(top, 'Market', C_MKT).add(top, 'Value', C_VAL)
    top += 14
    b.add(top, 'Free', C_CUR).add(top, 'Locked', C_SAFE).add(top, 'Earmarked', C_PLED)
    top += 14
    b.add(top, 'Lent', C_CUR).add(top, 'Pledge', C_SAFE).add(top, 'Pledgee', C_PLED)
    top += 14
    b.add(top, 'INF999999999', C_ISIN).add(top, 'GAMMA MUTUAL', C_SEC).add(top, '100.000', C_CUR) \
        .add(top, '0.000', C_SAFE).add(top, '0.000', C_PLED).add(top, '50.00', C_MKT).add(top, '5,000.00', C_VAL)
    top += 14
    # continuation lines: same x-position balance breakdown (NOT the same value
    # wrapped -- a different figure) plus more wrapped security name text.
    b.add(top, 'FUND SCHEME', C_SEC).add(top, '100.000', C_CUR).add(top, '0.000', C_SAFE).add(top, '0.000', C_PLED)
    top += 14
    b.add(top, 'GROWTH PLAN', C_SEC).add(top, '0.000', C_CUR).add(top, '0.000', C_SAFE).add(top, '0.000', C_PLED)
    top += 14
    b.add(top, 'Sub Total 5,000.00', 0)
    return b


def fixture_cdsl_demat_transactions():
    """CDSL's running-Current-Balance ledger layout (Date/Transaction
    Particulars/Credit/Debit/Current Balance), including a Particulars string
    long enough to reach into the naive midpoint boundary with Credit --
    regression for the description-overflow-into-Credit corruption bug."""
    b = CASFixtureBuilder()
    C_DATE, C_DESC, C_CR, C_DR, C_BAL = cols([11, 40, 9, 9, 9])
    b = CASFixtureBuilder()
    top = demat_txn_account_header(b, 70, kind='CDSL')
    top += 14  # 'Current' sits one line above the main header row
    b.add(top, 'Current', C_BAL)
    top += 14
    b.add(top, 'Date', C_DATE).add(top, 'Transaction', C_DESC).add(top, 'Particulars', C_DESC + 12) \
        .add(top, 'Credit', C_CR).add(top, 'Debit', C_DR).add(top, 'Current', C_BAL)
    top += 14
    b.add(top, 'Balance', C_BAL)
    top += 14
    b.add(top, 'ISIN : INF666666666 - KAPPA FUND GROWTH', C_DATE)
    top += 14
    b.add(top, '01-Jan-2024', C_DATE).add(top, 'Opening', C_DESC).add(top, 'Balance', C_DESC + 10) \
        .add(top, '125.000', C_BAL)
    top += 14
    # a long, unbroken particulars string reaching a bare numeric reference
    # token positioned right up near (but left of) Credit's real column edge
    # ref token: past the OLD naive midpoint boundary (37 chars here) but still
    # left of the real, pinned Credit boundary (~58 chars) -- with a safe gap
    # on both sides so pdfplumber doesn't visually merge it with neighbours.
    ref_col = 50
    b.add(top, '11-Jan-2024', C_DATE).add(top, 'EPDR', C_DESC).add(top, 'Txn12345', C_DESC + 6) \
        .add(top, 'CtBo110002115', C_DESC + 17).add(top, '123456', ref_col) \
        .add(top, '50.000', C_CR).add(top, '175.000', C_BAL)
    top += 14
    b.add(top, '31-Jan-2024', C_DATE).add(top, 'Closing', C_DESC).add(top, 'Balance', C_DESC + 10) \
        .add(top, '175.000', C_BAL)
    return b


def fixture_legacy_mf_folios_2016():
    """Pre-2017 Mutual Fund Folios layout with no cost-basis/unrealised-P&L
    columns -- just ISIN/UCC, ISIN Description, Folio No., No. of Units, NAV,
    Value. Regression for the whole sheet silently zeroing out under the
    modern 10-column definition."""
    b = CASFixtureBuilder()
    C_ISIN, C_NAME, C_FOLIO, C_UNITS, C_NAV, C_VAL = cols([13, 18, 9, 8, 8, 10])
    top = account_header(b, 70, kind='NSDL')
    b.add(top, 'Mutual Fund Folios (F)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'ISIN', C_NAME).add(top, 'Description', C_NAME + 7) \
        .add(top, 'Folio', C_FOLIO).add(top, 'No.', C_FOLIO + 8).add(top, 'No.', C_UNITS).add(top, 'of', C_UNITS + 6) \
        .add(top, 'NAV', C_NAV).add(top, 'Value', C_VAL)
    top += 14
    b.add(top, 'INF999999998', C_ISIN).add(top, 'DELTA MUTUAL FUND', C_NAME).add(top, '12345678', C_FOLIO) \
        .add(top, '500.000', C_UNITS).add(top, '45.5000', C_NAV).add(top, '22,750.00', C_VAL)
    top += 14
    b.add(top, 'Sub Total 22,750.00', 0)
    return b


def fixture_jan2018_3line_header():
    """A 3-physical-line Equities header where the word 'Value' is
    duplicated -- once inside 'Face Value' (line 1), once as the table's
    real final 'Value' column (line 2). Regression for find_header_columns
    declaring the header complete after line 1 and never reading line 2,
    silently dropping the real Value column."""
    b = CASFixtureBuilder()
    C_ISIN, C_NAME, C_FACE, C_NO, C_MKT, C_FAIR, C_VAL = cols([13, 14, 12, 6, 8, 10, 10])
    top = account_header(b, 70, kind='NSDL')
    b.add(top, 'Equities (E)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'Company', C_NAME).add(top, 'Face', C_FACE).add(top, 'Value', C_FACE + 5) \
        .add(top, 'No.', C_NO).add(top, 'Market', C_MKT).add(top, 'Fair', C_FAIR).add(top, 'Market', C_FAIR + 8)
    top += 14
    b.add(top, 'Stock', C_NAME).add(top, 'Shares', C_NO).add(top, 'Highest', C_MKT).add(top, 'Value', C_VAL)
    top += 14
    b.add(top, '(on', C_ISIN).add(top, 'date)', C_ISIN + 6)
    top += 14
    b.add(top, 'INE333333333', C_ISIN).add(top, 'EPSILON TESTCO', C_NAME).add(top, '5.00', C_FACE) \
        .add(top, '60', C_NO).add(top, '150.00', C_MKT).add(top, '9,000.00', C_VAL)
    top += 14
    b.add(top, 'LIMITED', C_NAME)
    top += 14
    b.add(top, 'Sub Total 9,000.00', 0)
    return b


def fixture_not_available_isin():
    """NSDL's literal 'NOT AVAILABLE' placeholder in the ISIN/UCC column
    (a folio not yet assigned an ISIN). Regression for such a row failing
    the row-start anchor test and silently merging into the PREVIOUS row,
    concatenating two folios' amounts into one garbled number."""
    b = CASFixtureBuilder()
    C_ISIN, C_NAME, C_FOLIO, C_UNITS, C_AVG, C_TOT, C_NAV, C_VAL, C_PL, C_RET = \
        cols([14, 18, 10, 8, 8, 9, 8, 9, 11, 11])
    top = account_header(b, 70, kind='NSDL')
    b.add(top, 'Mutual Fund Folios (F)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'ISIN', C_NAME).add(top, 'Folio', C_FOLIO).add(top, 'No.', C_FOLIO + 8) \
        .add(top, 'Average', C_AVG).add(top, 'Total', C_TOT).add(top, 'Current', C_NAV) \
        .add(top, 'Current', C_VAL).add(top, 'Unrealised', C_PL).add(top, 'Annualised', C_RET)
    top += 14
    b.add(top, 'INF888888888', C_ISIN).add(top, 'ZETA FUND GROWTH', C_NAME).add(top, '11112222', C_FOLIO) \
        .add(top, '100.000', C_UNITS).add(top, '50.0000', C_AVG).add(top, '5,000.00', C_TOT) \
        .add(top, '55.0000', C_NAV).add(top, '5,500.00', C_VAL).add(top, '500.00', C_PL).add(top, '10.00', C_RET)
    top += 14
    b.add(top, 'NOT AVAILABLE', C_ISIN).add(top, 'ZETA FUND GROWTH', C_NAME).add(top, '33334444', C_FOLIO) \
        .add(top, '50.000', C_UNITS).add(top, '52.0000', C_AVG).add(top, '2,600.00', C_TOT) \
        .add(top, '55.0000', C_NAV).add(top, '2,750.00', C_VAL).add(top, '150.00', C_PL).add(top, '6.00', C_RET)
    top += 14
    b.add(top, 'Sub Total 8,250.00', 0)
    return b


def fixture_in8_isin_prefix():
    """A real, non-INE/INF/IN0 ISIN prefix (IN8..., used for rights/
    renunciation entitlements). Regression for the old ISIN_RE allowlist
    failing to anchor such a row, silently swallowing its whole Value into
    the previous row's continuation text."""
    b = CASFixtureBuilder()
    C_ISIN, C_NAME, C_FACE, C_NO, C_MKT, C_VAL = cols([13, 14, 6, 6, 8, 10])
    top = account_header(b, 70, kind='NSDL')
    b.add(top, 'Equities (E)')
    top += 14
    b.add(top, 'ISIN', C_ISIN).add(top, 'Company', C_NAME).add(top, 'Face', C_FACE) \
        .add(top, 'No.', C_NO).add(top, 'Market', C_MKT).add(top, 'Value', C_VAL)
    top += 14
    b.add(top, 'Stock', C_NAME).add(top, 'Shares', C_NO).add(top, 'Price', C_MKT)
    top += 14
    b.add(top, 'INE444444444', C_ISIN).add(top, 'ETA TESTCO', C_NAME).add(top, '2.00', C_FACE) \
        .add(top, '40', C_NO).add(top, '100.00', C_MKT).add(top, '4,000.00', C_VAL)
    top += 14
    b.add(top, 'LIMITED', C_NAME)
    top += 14
    b.add(top, 'IN8012345671', C_ISIN).add(top, 'THETA RIGHTS', C_NAME).add(top, '2.00', C_FACE) \
        .add(top, '20', C_NO).add(top, '10.00', C_MKT).add(top, '200.00', C_VAL)
    top += 14
    b.add(top, 'LIMITED', C_NAME)
    top += 14
    b.add(top, 'Sub Total 4,200.00', 0)
    return b


def fixture_pledge_unpledge():
    """CDSL Pledge Accept / Pledge Setup pair: Debit/Credit move shares
    between Free and Pledged sub-balances without changing the total
    Current Balance. Not a bug -- documents that the parser correctly
    extracts these rows' real fields even though Opening-Debit+Credit=
    Closing legitimately does not hold for them."""
    b = CASFixtureBuilder()
    C_DATE, C_DESC, C_CR, C_DR, C_BAL = cols([11, 40, 9, 9, 9])
    top = demat_txn_account_header(b, 70, kind='CDSL')
    top += 14
    b.add(top, 'Current', C_BAL)
    top += 14
    b.add(top, 'Date', C_DATE).add(top, 'Transaction', C_DESC).add(top, 'Particulars', C_DESC + 12) \
        .add(top, 'Credit', C_CR).add(top, 'Debit', C_DR).add(top, 'Current', C_BAL)
    top += 14
    b.add(top, 'Balance', C_BAL)
    top += 14
    b.add(top, 'ISIN : INF555555555 - LAMBDA FUND GROWTH', C_DATE)
    top += 14
    b.add(top, '01-Feb-2024', C_DATE).add(top, 'Opening', C_DESC).add(top, 'Balance', C_DESC + 10) \
        .add(top, '2500.000', C_BAL)
    top += 14
    b.add(top, '05-Feb-2024', C_DATE).add(top, 'PledgeAccept CtrBo123', C_DESC) \
        .add(top, 'DRPSB', C_DESC + 24).add(top, '2,500.000', C_DR).add(top, '2,500.000', C_BAL)
    top += 14
    b.add(top, '05-Feb-2024', C_DATE).add(top, 'PledgeSetup CtrBo123', C_DESC) \
        .add(top, 'CRPSB', C_DESC + 24).add(top, '2,500.000', C_CR).add(top, '2,500.000', C_BAL)
    top += 14
    b.add(top, '28-Feb-2024', C_DATE).add(top, 'Closing', C_DESC).add(top, 'Balance', C_DESC + 10) \
        .add(top, '2,500.000', C_BAL)
    return b


def fixture_redemption_nav_price():
    """MF Transactions statement, Redemption row where NAV and Price
    legitimately differ (post-STT price vs. redemption NAV). Documents
    correct extraction of two genuinely distinct figures, not a bug."""
    b = CASFixtureBuilder()
    C_DATE, C_DESC, C_AMT, C_STAMP, C_NAV, C_PRICE, C_UNITS = cols([11, 14, 9, 6, 8, 8, 8])
    top = 70
    b.add(top, 'Date', C_DATE).add(top, 'Transaction', C_DESC).add(top, 'Amount', C_AMT) \
        .add(top, 'Stamp', C_STAMP).add(top, 'NAV', C_NAV).add(top, 'Price', C_PRICE).add(top, 'Units', C_UNITS)
    top += 14
    b.add(top, 'Details', C_DESC).add(top, 'Duty', C_STAMP)
    top += 14
    b.add(top, 'ISIN:INF777777777 - IOTA FUND GROWTH Folio No - 99998888', C_DATE)
    top += 14
    b.add(top, 'Opening Balance 500.000', C_DATE)
    top += 14
    b.add(top, '27-Jan-2024', C_DATE).add(top, 'Redemption', C_DESC).add(top, '9,616.00', C_AMT) \
        .add(top, '0.00', C_STAMP).add(top, '61.3100', C_NAV).add(top, '60.7000', C_PRICE).add(top, '158.420', C_UNITS)
    top += 14
    b.add(top, 'Closing Balance 341.580', C_DATE)
    return b


FIXTURES = {
    'standard_nsdl.pdf': fixture_standard_nsdl,
    'cdsl_holdings_layout.pdf': fixture_cdsl_holdings_layout,
    'cdsl_demat_transactions.pdf': fixture_cdsl_demat_transactions,
    'legacy_mf_folios_2016.pdf': fixture_legacy_mf_folios_2016,
    'jan2018_3line_header.pdf': fixture_jan2018_3line_header,
    'not_available_isin.pdf': fixture_not_available_isin,
    'in8_isin_prefix.pdf': fixture_in8_isin_prefix,
    'pledge_unpledge.pdf': fixture_pledge_unpledge,
    'redemption_nav_price.pdf': fixture_redemption_nav_price,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, build in FIXTURES.items():
        b = build()
        path = os.path.join(OUT_DIR, name)
        b.save(path)
        print(f'wrote {path}')


if __name__ == '__main__':
    main()
