from imapbackup import mailutils
from .fixtures import dummy_eml_bytes


def test_decode_email_header(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    assert msg is not None
    assert msg["Subject"] == "Test Email"


def test_decode_email_full(dummy_eml_bytes):
    msg = mailutils.decode_email(dummy_eml_bytes)
    assert msg is not None
    assert msg["Subject"] == "Test Email"
    assert msg.get_body() is not None


def test_addresses(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    from_addrs, to_addrs = mailutils.addresses(msg)
    assert from_addrs == {"test@example.com"}
    assert "recipient@example.com" in to_addrs


def test_addresses_with_cc():
    eml = b"""From: alice@example.com
To: bob@example.com
CC: carol@example.com, dave@example.com
Subject: CC Test

Body.
"""
    msg = mailutils.decode_email_header(eml)
    from_addrs, to_addrs = mailutils.addresses(msg)
    assert from_addrs == {"alice@example.com"}
    assert to_addrs == {"bob@example.com", "carol@example.com", "dave@example.com"}


def test_addresses_with_received_for():
    eml = b"""From: sender@example.com
To: list@example.com
Received: from mx.example.com by server.example.com for <hidden@example.com>; Wed, 20 Feb 2026 12:00:00 +0100
Subject: Received For Test

Body.
"""
    msg = mailutils.decode_email_header(eml)
    _, to_addrs = mailutils.addresses(msg)
    assert "hidden@example.com" in to_addrs
    assert "list@example.com" in to_addrs


def test_addresses_lowercase():
    eml = b"""From: Alice@Example.COM
To: BOB@Example.Org
Subject: Case Test

Body.
"""
    msg = mailutils.decode_email_header(eml)
    from_addrs, to_addrs = mailutils.addresses(msg)
    assert "alice@example.com" in from_addrs
    assert "bob@example.org" in to_addrs


def test_subject(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    assert mailutils.subject(msg) == "Test Email"


def test_subject_missing():
    eml = b"""From: a@b.com
To: c@d.com

No subject here.
"""
    msg = mailutils.decode_email_header(eml)
    assert mailutils.subject(msg) == ""


def test_message_id():
    eml = b"""From: a@b.com
To: c@d.com
Message-Id: <unique-id-123@example.com>
Subject: ID Test

Body.
"""
    msg = mailutils.decode_email_header(eml)
    assert mailutils.message_id(msg) == "<unique-id-123@example.com>"


def test_message_id_missing():
    eml = b"""From: a@b.com
To: c@d.com
Subject: No ID

Body.
"""
    msg = mailutils.decode_email_header(eml)
    assert mailutils.message_id(msg) == ""


def test_date(dummy_eml_bytes):
    msg = mailutils.decode_email_header(dummy_eml_bytes)
    dt = mailutils.date(msg)
    assert dt is not None
    assert dt.year == 2026


def test_date_missing():
    eml = b"""From: a@b.com
To: c@d.com
Subject: No Date

Body.
"""
    msg = mailutils.decode_email_header(eml)
    assert mailutils.date(msg) is None


def test_unwrap_exchange_journal_item():
    journal = (
        b"From: journal@example.com\r\n"
        b"To: archive@example.com\r\n"
        b"Subject: Journal\r\n"
        b"Content-Type: multipart/mixed; boundary=\"BOUNDARY\"\r\n"
        b"\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: text/plain\r\n"
        b"\r\n"
        b"Journal envelope\r\n"
        b"--BOUNDARY\r\n"
        b"Content-Type: message/rfc822\r\n"
        b"\r\n"
        b"From: real-sender@example.com\r\n"
        b"To: real-recipient@example.com\r\n"
        b"Subject: Real Message\r\n"
        b"\r\n"
        b"Real body content.\r\n"
        b"--BOUNDARY--\r\n"
    )
    result = mailutils.unwrap_exchange_journal_item(journal)
    assert result is not None
    assert b"Real Message" in result


def test_unwrap_exchange_journal_not_a_journal():
    plain = b"""From: a@b.com
To: c@d.com
Subject: Plain email

Just a plain email, no RFC822 attachments.
"""
    result = mailutils.unwrap_exchange_journal_item(plain)
    assert result is None
