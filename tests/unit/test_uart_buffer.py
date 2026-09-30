import re

from dryflash.uart import UartBuffer


def test_cursor_reads_are_incremental():
    b = UartBuffer(capacity=1024)
    b.append(b"hello ")
    r = b.read(0, 100)
    assert r.data == b"hello " and r.next_cursor == 6 and r.dropped == 0
    b.append(b"world")
    r = b.read(r.next_cursor, 100)
    assert r.data == b"world" and r.next_cursor == 11


def test_max_bytes_limits_read():
    b = UartBuffer(capacity=1024)
    b.append(b"abcdef")
    r = b.read(0, 4)
    assert r.data == b"abcd" and r.next_cursor == 4


def test_overflow_reports_dropped_bytes():
    b = UartBuffer(capacity=8)
    b.append(b"0123456789AB")  # 12 bytes into an 8-byte ring
    assert b.total == 12 and b.start == 4
    r = b.read(0, 100)
    assert r.dropped == 4 and r.data == b"456789AB" and r.next_cursor == 12


def test_cursor_beyond_end_returns_empty():
    b = UartBuffer(capacity=16)
    b.append(b"abc")
    r = b.read(10, 5)
    assert r.data == b"" and r.next_cursor == 3


def test_search_from_cursor():
    b = UartBuffer(capacity=1024)
    b.append(b"boot...\nvalue=1\nvalue=42\n")
    m = b.search(re.compile(rb"value=(\d+)"), 0)
    assert m.group(1) == b"1"
    m2 = b.search(re.compile(rb"value=(\d+)"), m.end_offset)
    assert m2.group(1) == b"42"
    assert m2.start_offset == b.total - len(b"value=42\n")
    assert b.search(re.compile(rb"nope"), 0) is None


def test_tail_and_context():
    b = UartBuffer(capacity=1024)
    b.append(b"line1\nline2\nline3\n")
    assert b.tail(6) == b"line3\n"
    assert b.slice(6, 12) == b"line2\n"


def test_search_can_stop_at_the_last_complete_line():
    b = UartBuffer(capacity=1024)
    b.append(b"value=1\nvalue=2")          # second line still arriving
    rx = re.compile(rb"value=(\d+)")
    first = b.search(rx, 0, b.last_line_end())
    assert first.group(1) == b"1"
    assert b.search(rx, first.end_offset, b.last_line_end()) is None
    b.append(b"3\n")
    assert b.search(rx, first.end_offset, b.last_line_end()).group(1) == b"23"
