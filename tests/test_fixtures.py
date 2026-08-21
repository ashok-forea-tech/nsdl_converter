"""Regression tests against the synthetic fixtures in test_fixtures/.

Each fixture isolates one real-world CAS layout or edge case that has
previously caused silent data corruption or loss. Run with:

    pytest tests/
"""

import os

import pytest

from cas_parser import CASDocument, to_number
from sections import parse_document, parse_demat_transactions, parse_mf_transactions

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), '..', 'test_fixtures')


def load(name):
    with open(os.path.join(FIXTURE_DIR, name), 'rb') as f:
        return CASDocument(f.read())


def by_isin(rows, isin, key='ISIN'):
    matches = [r for r in rows if r.get(key) == isin]
    assert matches, f"no row with {key}={isin!r} among {[r.get(key) for r in rows]}"
    return matches[0]


def test_standard_nsdl_equities():
    holdings = parse_document(load('standard_nsdl.pdf'))['holdings']
    assert len(holdings) == 2
    row = by_isin(holdings, 'INE111111111')
    assert row['Company Name'] == 'ALPHA TESTCO LIMITED'
    assert row['Face Value'] == '2.00'
    assert row['No. of Shares'] == '100'
    assert row['Market Price'] == '250.00'
    assert row['Value'] == '25,000.00'


def test_cdsl_holdings_layout_not_corrupted_by_balance_breakdown_lines():
    holdings = parse_document(load('cdsl_holdings_layout.pdf'))['holdings']
    assert len(holdings) == 1
    row = holdings[0]
    assert row['asset_class'] == 'mf_holdings'
    assert row['ISIN Description'] == 'GAMMA MUTUAL FUND SCHEME GROWTH PLAN'
    assert row['No. of Units'] == '100.000'
    assert row['NAV'] == '50.00'
    assert row['Value'] == '5,000.00'


def test_cdsl_demat_transactions_long_particulars_not_swallowed_into_credit():
    rows = parse_demat_transactions(load('cdsl_demat_transactions.pdf'))
    assert len(rows) == 1
    row = rows[0]
    assert row['Description'] == 'EPDR Txn12345 CtBo110002115 123456'
    assert row['Credit'] == '50.000'
    assert row['Debit'] == '0.000'
    assert row['Opening Balance'] == '125.000'
    assert row['Closing Balance'] == '175.000'
    o, d, c, cl = (to_number(row[k]) for k in ('Opening Balance', 'Debit', 'Credit', 'Closing Balance'))
    assert o - d + c == pytest.approx(cl)


def test_legacy_mf_folios_2016_layout():
    folios = parse_document(load('legacy_mf_folios_2016.pdf'))['mf_folios']
    assert len(folios) == 1
    row = folios[0]
    assert row['ISIN Description'] == 'DELTA MUTUAL FUND'
    assert row['Folio No.'] == '12345678'
    assert row['No. of Units'] == '500.000'
    assert row['Current NAV/unit'] == '45.5000'
    assert row['Current Value'] == '22,750.00'


def test_jan2018_3line_header_value_column_not_dropped():
    holdings = parse_document(load('jan2018_3line_header.pdf'))['holdings']
    assert len(holdings) == 1
    row = holdings[0]
    assert row['Face Value'] == '5.00'
    assert row['No. of Shares'] == '60'
    assert row['Market Price'] == '150.00'
    assert row['Value'] == '9,000.00'


def test_not_available_isin_starts_its_own_row():
    folios = parse_document(load('not_available_isin.pdf'))['mf_folios']
    assert len(folios) == 2
    first, second = folios
    assert first['ISIN/UCC'] == 'INF888888888'
    assert first['Current Value'] == '5,500.00'
    assert second['ISIN/UCC'] == 'NOT AVAILABLE'
    assert second['Current Value'] == '2,750.00'
    assert second['Folio No.'] == '33334444'


def test_in8_isin_prefix_recognised_and_not_merged():
    holdings = parse_document(load('in8_isin_prefix.pdf'))['holdings']
    assert len(holdings) == 2
    row = by_isin(holdings, 'IN8012345671')
    assert row['Company Name'] == 'THETA RIGHTS LIMITED'
    assert row['Value'] == '200.00'
    # and the row before it must be untouched, not merged with this one
    first = by_isin(holdings, 'INE444444444')
    assert first['Value'] == '4,000.00'


def test_pledge_unpledge_parsed_without_forcing_balanced_arithmetic():
    rows = parse_demat_transactions(load('pledge_unpledge.pdf'))
    assert len(rows) == 2
    accept, setup = rows
    assert accept['Description'] == 'PledgeAccept CtrBo123 DRPSB'
    assert accept['Debit'] == '2,500.000'
    assert accept['Credit'] == '0.000'
    assert accept['Closing Balance'] == '2,500.000'
    assert setup['Description'] == 'PledgeSetup CtrBo123 CRPSB'
    assert setup['Credit'] == '2,500.000'
    assert setup['Closing Balance'] == '2,500.000'
    # the whole point: total holding is unchanged across the pledge pair,
    # even though Debit/Credit are both nonzero -- not an arithmetic error.


def test_redemption_nav_and_price_both_captured_distinctly():
    rows = parse_mf_transactions(load('redemption_nav_price.pdf'))
    assert len(rows) == 1
    row = rows[0]
    assert row['Transaction Details'] == 'Redemption'
    assert row['NAV'] == '61.3100'
    assert row['Price'] == '60.7000'
    assert row['NAV'] != row['Price']
