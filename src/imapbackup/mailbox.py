from __future__ import annotations

import email.parser
import email.policy
import functools
import logging
import re
import ssl
import threading
import time

from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Tuple, Any, Optional, Callable, Generator

import imapclient
import sys

if sys.version_info >= (3, 14):
    # Monkeypatch for imapclient 3.1.0 on Python 3.14:
    # IMAP4WithTimeout.open explicitly sets self.file which is now a property without a setter.
    # Removing the open method makes it fallback to imaplib.IMAP4.open which works fine.
    try:
        import imapclient.imap4
        if hasattr(imapclient.imap4.IMAP4WithTimeout, 'open'):
            del imapclient.imap4.IMAP4WithTimeout.open
    except Exception:
        pass

from imapbackup import cas, utils, mailutils

log = logging.getLogger(__name__)

class MailboxError(Exception):
    pass

class MailboxClient:

    def __init__(self, mailbox:Mailbox):
        self.mbox = mailbox
        self.conn = mailbox._conn
        self.job_name = mailbox.job_name
        self.lock = threading.RLock()
        self.capabilities = self.conn.capabilities()
        self.delete_after_export = self.mbox.job.get("delete_after_export", False)
        self.exchange_journal = self.mbox.job.get("exchange_journal", False)
        self.gmail = functools.reduce(lambda acc, c: acc or c.startswith(b"X-GM-"), self.capabilities, False)
        self.move_cap = b"MOVE" in self.capabilities
        self.trash_folder = self.mbox.job.get("trash_folder")
        self.error_folder = self.mbox.job.get("error_folder") if self.move_cap else None

    @staticmethod
    def _isfoldertype(folder, *flags:List[str]):
        folderflags = set(folder[0])
        flags = [(b'\\'+f.encode(), f) for f in [f.capitalize().capitalize() for f in flags]]
        for flag in flags:
            if flag[0] in folderflags:
                return flag[1]
        return None

    @staticmethod
    def _isfoldername(folder, *patterns:List[str]):
        foldername = folder[2]
        for pattern in patterns:
            if re.match(pattern, foldername):
                return pattern
        return None

    def folders(self) -> Generator[str, None, None]:
        with self.lock:
            for folder in self.conn.list_folders():
                if self._isfoldertype(folder, *self.mbox.job.get("ignore_folder_flags", [])):
                    continue
                if self._isfoldername(folder, *self.mbox.job.get("ignore_folder_names", [])):
                    continue
                yield folder

    def select_folder(self, folder_name:str, readonly:bool=True):
        if not self.conn.folder_exists(folder_name):
            self.conn.create_folder(folder_name)
        self.conn.select_folder(folder_name, readonly=readonly)

    def watch_folder(self, folder_name:str, timeout:int=20, break_out:int=3600):
        with self.lock:
            start_time = time.monotonic()
            while time.monotonic()-start_time<break_out:
                self.select_folder(folder_name)
                self.conn.idle()
                responses = None
                while not responses:
                    idle_time = time.monotonic()
                    responses = self.conn.idle_check(timeout=max(timeout, 10))
                    log.debug("%s::%s: IDLE response %s", self.job_name, folder_name, responses)
                    if responses:
                        self.conn.idle_done()
                        break
                    now = time.monotonic()
                    if now-idle_time < timeout/2:
                        # Workaround: idle_check() does not raise an exception when
                        # connection breaks, instead it returns immediately.
                        log.warning("%s::%s: IDLE connection broken", self.job_name, folder_name)
                        return
                    if now-start_time >= break_out:
                        self.conn.idle_done()
                        return
                yield folder_name, responses
            # finally:
            #     log.info("%s::%s: Leaving IDLE loop", self.job_name, folder_name)
            #     self.conn.idle_done()

    def _walk_folder(self, folder_name:str, message_ids:List[int], chunk_size:int=10, delete:bool=False) -> Generator[Tuple[int,bytes,datetime], None, None]:
        for msg_ids in utils.chunks(message_ids, chunk_size):
            msg_ids_str = ", ".join([str(i) for i in msg_ids])
            log.debug("%s::%s: fetching %s", self.job_name, folder_name, msg_ids_str)
            try:
                for msg_id, msg_data in self.conn.fetch(msg_ids, ["INTERNALDATE", "RFC822"]).items():
                    yield msg_id, msg_data[b"RFC822"], msg_data[b"INTERNALDATE"]
            except Exception as exc:
                log.error("%s::%s[%s]: %s", self.job_name, folder_name, msg_id, exc)
            else:
                if delete:
                    log.debug("%s::%s: deleting %s", self.job_name, folder_name, msg_ids_str)
                    self.conn.delete_messages(msg_ids)

    def _collect_metadata(self, folder_name:str, msg_id:Any, store_id:str, msg:bytes):
        if self.gmail:
            labels = self.conn.get_gmail_labels(msg_id)
            labels = labels.get(msg_id, [])
            if not folder_name.startswith("[Google Mail]"):
                labels = [folder_name] + labels
        else:
            labels = [folder_name]
        header = mailutils.decode_email_header(msg)
        from_addrs, to_addrs = mailutils.addresses(header)
        return {
            "mailbox": self.mbox.job_name,
            "folder": folder_name,
            "email_id": mailutils.message_id(header),
            "store_id": store_id,
            "labels": labels,
            "sender": from_addrs,
            "recipients": to_addrs,
            "date": mailutils.date(header),
            "subject": mailutils.subject(header),
        }

    def _clear_folder(self, folder_name:str):
        with self.lock:
            try:
                self.conn.select_folder(folder_name, readonly=False)
                try:
                    message_ids = self.conn.search()
                    for msg_ids in utils.chunks(message_ids, 10):
                        self.conn.delete_messages(msg_ids)
                except Exception as exc:
                    log.error("%s::%s: %s", self.job_name, folder_name, exc)
                finally:
                    self.conn.expunge()
                    self.conn.unselect_folder()
            except Exception as exc:
                log.error("%s::%s: %s", self.job_name, folder_name, exc)

    def folder_backup(self, folder_name:str, store:cas, since:Optional[datetime]=None, callback:Optional[Callable[dict]]=None) -> Tuple[int, int]:
        with self.lock:
            counter = 0
            folder_info = self.conn.select_folder(folder_name, readonly=not self.delete_after_export)
            try:
                items_in_folder = folder_info[b'EXISTS']
                if since:
                    start_date = since - timedelta(days=1)
                    query = ["NOT", "DELETED", "SINCE", start_date.date()]
                else:
                    query = ["NOT", "DELETED"]
                message_ids = self.conn.search(query)
                items_found = len(message_ids)
                if items_found!=items_in_folder:
                    log.info("%s::%s: found %s/%s messages", self.job_name, folder_name, items_found, items_in_folder)
                else:
                    log.info("%s::%s: found %s messages", self.job_name, folder_name, items_found)
                for msg_id, msg, _ in self._walk_folder(folder_name, message_ids, delete=False):
                    if self.exchange_journal:
                        msg = mailutils.unwrap_exchange_journal_item(msg)
                        if msg is None:
                            if self.error_folder:
                                log.warning("%s::%s[%s]: not a journal item, moving to error folder", self.job_name, folder_name, msg_id)
                                self.move_message(msg_id, self.error_folder)
                            else:
                                log.warning("%s::%s[%s]: not a journal item, skipping", self.job_name, folder_name, msg_id)
                            continue
                    result, store_id, _path = store.add(msg)
                    log.info("%s::%s[%s]: %s: id=%s", self.job_name, folder_name, msg_id, result, store_id)
                    if callback:
                        try:
                            md = self._collect_metadata(folder_name=folder_name, msg_id=msg_id, store_id=store_id, msg=msg)
                            callback(md)
                        except Exception as exc:
                            log.exception("%s::%s[%s]: Error in callback: %s", self.job_name, folder_name, msg_id, exc)
                            continue
                    if self.delete_after_export:
                        self.conn.delete_messages(msg_id)
                    counter += 1
            except Exception as exc:
                log.error("%s::%s: %s", self.job_name, folder_name, exc)
                raise
            else:
                if self.delete_after_export:
                    self.conn.expunge()
            finally:
                self.conn.unselect_folder()
            if self.gmail and self.trash_folder:
                # Special treatment for Gmail: Empty trash folder. Use job option "trash_folder".
                self._clear_folder(self.trash_folder)
            return counter, len(message_ids)

    def full_backup(self, store:cas, since:Optional[datetime]=None, callback:Optional[callable]=None):
        for folder in self.folders():
            try:
                self.folder_backup(folder_name=folder[2], store=store, since=since, callback=callback)
            except:
                continue

    def get_messages(self, folder_name:str, since:Optional[datetime]=None) -> Generator[Tuple[bytes, datetime], None, None]:
        with self.lock:
            counter = 0
            folder_info = self.conn.select_folder(folder_name, readonly=not self.delete_after_export)
            try:
                items_in_folder = folder_info[b'EXISTS']
                if since:
                    start_date = since - timedelta(days=1)
                    query = ["NOT", "DELETED", "SINCE", start_date.date()]
                else:
                    query = ["NOT", "DELETED"]
                message_ids = self.conn.search(query)
                items_found = len(message_ids)
                if items_found!=items_in_folder:
                    log.info("%s::%s: found %s/%s messages", self.job_name, folder_name, items_found, items_in_folder)
                else:
                    log.info("%s::%s: found %s messages", self.job_name, folder_name, items_found)
                for msg_id, msg, msg_date in self._walk_folder(folder_name, message_ids, delete=False):
                    log.info("%s::%s[%s]: fetched", self.job_name, folder_name, msg_id)
                    yield msg_id, msg_date, msg
                    if self.delete_after_export:
                        self.conn.delete_messages(msg_id)
                    counter += 1
            except Exception as exc:
                log.error("%s::%s: %s", self.job_name, folder_name, exc)
                raise
            else:
                if self.delete_after_export:
                    self.conn.expunge()
            finally:
                self.conn.unselect_folder()

    def save_message(self, msg:bytes, folder_name:str, date:datetime=None):
        with self.lock:
            if not self.conn.folder_exists(folder_name):
                self.conn.create_folder(folder_name)
            self.conn.append(folder_name, msg, msg_time=date)

    def move_message(self, msg_id:int, folder_name:str):
        with self.lock:
            if self.move_cap:
                if not self.conn.folder_exists(folder_name):
                    self.conn.create_folder(folder_name)
                self.conn.move(msg_id, folder_name)
            else:
                raise MailboxError("IMAP server has no MOVE capability, moving messages is not supported")

    def delete_message(self, msg_id:int, expunge:bool=False):
        with self.lock:
            self.conn.delete_messages(msg_id)
            if expunge:
                self.conn.expunge(msg_id)

class Mailbox:

    def __init__(self, job:dict):
        self.job = job or {}
        self.job_name = self.job.get("name", ".")
        self._client = None

    def __enter__(self):
        tls = self.job.get("tls", True)
        if tls:
            tls_context = ssl.create_default_context()
            if self.job.get("tls_check_hostname", True) is False:
                tls_context.check_hostname = False
            if self.job.get("tls_verify_cert", True) is False:
                tls_context.verify_mode = ssl.CERT_NONE
        else:
            tls_context = None

        self._conn = imapclient.IMAPClient(
            host=self.job.get("server", "localhost"),
            port=self.job.get("port", 993),
            ssl=tls,
            ssl_context=tls_context,
        )
        self._conn.login(self.job["username"], self.job["password"])
        self._client = MailboxClient(self)
        return self._client

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._conn:
            self._conn.logout()
            self._conn = None
            self._client = None

    @property
    def client(self) -> MailboxClient:
        return self._client


# vim: set et sw=4 ts=4:
