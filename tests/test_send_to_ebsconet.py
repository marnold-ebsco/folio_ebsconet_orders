from openpyxl import load_workbook

from pipeline import send_to_ebsconet as send

ORDER, TITLE, ISSN = "Order Number", "Title Name", "ISSN"


def sop(order, title, issn="", **more):
    return dict({ORDER: order, TITLE: title, ISSN: issn}, **more)


def line(po, pol, title, issn=""):
    return {"po_number": po, "pol_number": pol, "title": title, "issn": issn}


def test_headers_are_the_53_requested_with_ils_last():
    assert len(send.SEND_HEADERS) == 53 and len(set(send.SEND_HEADERS)) == 53
    assert send.SEND_HEADERS[0] == "Title Name" and send.SEND_HEADERS[-1] == "ILS Number"
    assert send.SEND_HEADERS[16:18] == ["Fund Code", "Publisher Identification"]


def test_match_by_order_number_and_keep_sop_order():
    rows = [sop("A1", "T1"), sop("B2", "T2"), sop("C3", "T3")]
    matched, missing = send.match_rows(
        rows, [line("C3", "C3-1", "T3"), line("A1", "A1-1", "T1")], ORDER, TITLE, ISSN)
    assert [(r[TITLE], pol) for r, pol in matched] == [("T1", "A1-1"), ("T3", "C3-1")]
    assert missing == []                       # B2 was not loaded, so it is not sent


def test_two_lines_on_one_po_match_by_title():
    rows = [sop("A1", "Second", "2"), sop("A1", "First", "1")]
    matched, _ = send.match_rows(
        rows, [line("A1", "A1-1", "First", "1"), line("A1", "A1-2", "Second", "2")],
        ORDER, TITLE, ISSN)
    assert {r[TITLE]: pol for r, pol in matched} == {"First": "A1-1", "Second": "A1-2"}


def test_title_differs_matches_only_a_lone_candidate():
    one, missing = send.match_rows([sop("A1", "Old")], [line("A1", "A1-1", "New")],
                                   ORDER, TITLE, ISSN)
    assert len(one) == 1 and missing == []
    two, missing = send.match_rows([sop("A1", "x"), sop("A1", "y")],
                                   [line("A1", "A1-1", "New")], ORDER, TITLE, ISSN)
    assert two == [] and [m["pol_number"] for m in missing] == ["A1-1"]


def test_case_and_spacing_are_ignored_and_a_row_is_used_once():
    rows = [sop("a1", "A  Title")]
    matched, missing = send.match_rows(
        rows, [line("A1", "A1-1", "a title"), line("A1", "A1-2", "a title")],
        ORDER, TITLE, ISSN)
    assert len(matched) == 1 and len(missing) == 1


def test_write_send_file_copies_values_and_sets_ils(tmp_path):
    row = sop("A1", "T1", "1234-5678", **{"Fund Code": "F", "Subscriber Postal Code": 66605})
    n = send.write_send_file(tmp_path / "send.xlsx", [(row, "A1-1")])
    ws = load_workbook(tmp_path / "send.xlsx").active
    head = [c.value for c in ws[1]]
    body = dict(zip(head, [c.value for c in ws[2]]))
    assert n == 1 and head == send.SEND_HEADERS
    assert body["ILS Number"] == "A1-1" and body["Fund Code"] == "F"
    assert body["Subscriber Postal Code"] == 66605 and body["Invoice Date"] is None
