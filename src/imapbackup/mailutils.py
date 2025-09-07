import email.message
import email.parser
import email.policy
import email.utils
import io
import logging
import re

from imapbackup import fixedpolicy

from typing import Union, Tuple, List, Generator, Set

from datetime import datetime

def _mail_reader(msg:Union[io.IOBase,bytes]) -> io.IOBase:
    if isinstance(msg, io.IOBase):
        reader = msg
        if reader.seekable():
            reader.seek(0)
    else:
        reader = io.BytesIO(msg)
    return reader

def decode_email(msg:Union[io.IOBase,bytes], headersonly:bool=False) -> email.message.EmailMessage:
    reader = _mail_reader(msg)
    return email.parser.BytesParser(policy=email.policy.default).parse(reader, headersonly=headersonly)

def decode_email_header(msg:Union[io.IOBase,bytes]) -> email.message.EmailMessage:
    return decode_email(msg, headersonly=True)

def addresses(msg:email.message.EmailMessage) -> Tuple[List[str], List[str]]:
    """Extract from/to addresses from message. Returns tuple of lists (from, to)."""

    def received_for() -> Generator[str, None, None]:
        for field in msg.get_all("Received", []):
            m = re.search(r"\bfor\s+\<?([\w\-\.]+@[\w\-\.]+\w)\>?\b", field, flags=re.IGNORECASE)
            if m:
                yield m[1].lower()

    def addr_field(label:str) -> Set[str]:
        try:
            addrs = email.utils.getaddresses(msg.get_all(label, []))
        except:
            addrs = []
        return {a[1].lower() for a in addrs}
        
    to_addrs = addr_field("To").union(received_for())
    from_addrs = addr_field("From")
    cc_addrs = addr_field("CC")
    return from_addrs, to_addrs.union(cc_addrs)

def date(msg:email.message.EmailMessage) -> datetime:
    date = msg.get("Date")
    if date:
        date = email.utils.parsedate_to_datetime(date)
    return date

def message_id(msg:email.message.EmailMessage) -> str:
    return msg.get("Message-Id") or ""

def subject(msg:email.message.EmailMessage) -> str:
    return msg.get("Subject") or ""

def unwrap_exchange_journal_item(msg:Union[io.IOBase,bytes]) -> bytes:
    """Returns None if not a journal item. Binary RFC822 message otherwise."""

    def as_bytes(m):
        try:
            return m.as_bytes(policy=email.policy.SMTP)
        except UnicodeEncodeError:
            logging.debug("as_bytes: email.policy.SMTP failed")
        try:
            return m.as_bytes(policy=email.policy.SMTPUTF8)
        except UnicodeEncodeError:
            logging.debug("as_bytes: email.policy.SMTPUTF8 failed")
        # FIXME: fixedpolicy
        try:
            return m.as_bytes(policy=fixedpolicy.SMTP)
        except UnicodeEncodeError:
            logging.debug("as_bytes: fixedpolicy.SMTP failed")
        try:
            return m.as_bytes(policy=fixedpolicy.SMTPUTF8)
        except UnicodeEncodeError:
            logging.debug("as_bytes: fixedpolicy.SMTPUTF8 failed")
        try:
            return m.as_bytes(policy=fixedpolicy.compat32)
        except UnicodeEncodeError:
            logging.debug("as_bytes: fixedpolicy.compat32 failed")
        return None

    def rfc822_attachment(parts, idx):
        submsgs = [as_bytes(m) for m in parts[idx].get_payload()]
        if len(submsgs)==1:
            return submsgs[0]
        return None

    reader = _mail_reader(msg)
    cover = email.parser.BytesParser(policy=email.policy.default).parse(reader)
    parts = [part for part in cover.walk() if part.get_content_type()=="message/rfc822"]
    
    # WORKAROUND: From my observations, Microsoft sends the journal messages to
    # the journal mailbox with the original sender. If DKIM/SPF is active for
    # the sender domain, this message is rejected by the receiving SMTP server,
    # after which Microsoft sends an "Undeliverable: <SUBJECT>" mail. This now
    # contains two RFC822 attachments instead of one, since the original journal
    # message is appended at the end.
    if len(parts)>0:
        # If more than one RFC822 attachments are found:
        # * if this is an 'Undeliverable' message, then part[1] is the right message
        # * there is a RFC822 message attached to the original mail
        # It is an 'Undeliverable' message if the first RFC822 attachment mistakenly
        # starts with 'Content-Type:'.
        submsg = rfc822_attachment(parts, 0)
        if submsg and submsg.startswith(b"Content-Type:"):
            submsg = rfc822_attachment(parts, 1)
            if submsg:
                logging.warning("Message was rescued from 'Undeliverable' stupidity")
        return submsg
    return None

# vim: set et sw=4 ts=4: