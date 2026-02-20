from imapbackup import mailutils
from .fixtures import dummy_eml_bytes


def test_decode_email_header(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    assert msg is not None
    assert msg["Subject"] == "Test Email"


def test_addresses(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    from_addrs, to_addrs = mailutils.addresses(msg)
    assert from_addrs == {"test@example.com"}
    assert "recipient@example.com" in to_addrs


def test_subject(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    assert mailutils.subject(msg) == "Test Email"


def test_date(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    dt = mailutils.date(msg)
    assert dt is not None
    assert dt.year == 2026
