from __future__ import annotations

import imaplib
import logging
import pathlib
import socket
import time
from datetime import datetime, timezone
from typing import cast

from imapbackup import cas, conf, mailbox, mailutils, storedb

log = logging.getLogger(__name__)


class JobError(Exception):
    pass


def backup(job: conf.JobConfig, store_path: pathlib.Path, compress: bool = False) -> None:
    def _store_metadata(email: dict):
        msg = db.add_message(
            email["store_id"], email["email_id"], email["date"], email["subject"]
        )
        db.assign_message_to_mailbox(msg, mb_id)
        db.add_message_labels(msg, *email["labels"])
        db.add_message_sender(msg, *email["sender"])
        db.add_message_recipients(msg, *email["recipients"])

    with mailbox.Mailbox(job=job) as mb:
        store = cas.ContentAddressedStorage(store_path, suffix=".eml", compress=compress)
        if job.with_db:
            with storedb.StoreDatabase(path=store_path / "store.db") as db:
                mb_id = db.add_mailbox(job.name)
                folders = job.folders if job.folders else mb.folders()
                for folder in folders:
                    folder_id = db.add_label(folder)
                    start_date = db.get_snapshot_date(mb_id, folder_id) if job.incremental else None
                    snapshot_date = datetime.now(timezone.utc)
                    mb.folder_backup(
                        folder, store, since=start_date, callback=_store_metadata
                    )
                    db.set_snapshot(mb_id, folder_id, date=snapshot_date)
        else:
            if job.folders:
                for folder in job.folders:
                    mb.folder_backup(folder, store)
            else:
                mb.full_backup(store)


def folder_list(job: conf.JobConfig) -> None:
    with mailbox.Mailbox(job=job) as mb:
        for folder in mb.folders():
            print(f"{job.name}::{folder}")


def update_db_from_archive(store_path: pathlib.Path, mailbox: str | None = None) -> None:
    store = cas.ContentAddressedStorage(store_path, suffix=".eml")
    with storedb.StoreDatabase(path=store_path / "store.db") as db:
        mb_id = db.add_mailbox(mailbox) if mailbox else None
        for path in store.walk():
            msg = store.read(path)
            header = mailutils.decode_email_header(msg)
            from_addrs, to_addrs = mailutils.addresses(header)
            store_id = path.name.split(".")[0]
            email_id = mailutils.message_id(header)
            date = mailutils.date(header)
            subject = mailutils.subject(header)
            log.debug("%s: message_id=%s, date=%s", store_id, email_id, date)

            msg_id = db.add_message(store_id, email_id, date, subject)
            if mb_id:
                db.assign_message_to_mailbox(msg_id, mb_id)
            db.add_message_sender(msg_id, *from_addrs)
            db.add_message_recipients(msg_id, *to_addrs)


def _format_archive_folder(template: str) -> str:
    now = datetime.now()
    return now.strftime(template)


def _copy_folder(
    mb_from: mailbox.MailboxClient,
    mb_to: mailbox.MailboxClient,
    folder: str,
    archive_folder: str | None = None,
) -> None:
    for msg_id, msg_date, msg in mb_from.get_messages(folder):
        mb_to.save_message(msg, folder, date=msg_date)
        if archive_folder:
            dest_folder = _format_archive_folder(archive_folder)
            log.info(
                "%s::%s: Moving message '%s' to folder '%s'",
                mb_from.job_name,
                folder,
                msg_id,
                dest_folder,
            )
            try:
                mb_from.move_message(msg_id, dest_folder)
            except mailbox.MailboxError:
                mb_from.save_message(msg, dest_folder, date=msg_date)
                mb_from.delete_message(msg_id, expunge=True)


def _copy(source: conf.JobConfig, destination: conf.JobConfig, archive_folder: str | None = None) -> None:
    with mailbox.Mailbox(job=source) as mb_from:
        with mailbox.Mailbox(job=destination) as mb_to:
            folders = source.folders if source.folders else ["INBOX"]
            for folder in folders:
                _copy_folder(mb_from, mb_to, folder, archive_folder=archive_folder)


def _idle_copy(
    source: conf.JobConfig,
    folder_name: str,
    destination: conf.JobConfig,
    archive_folder: str | None = None,
) -> None:
    def _copy_to_dest(mb_from: mailbox.MailboxClient):
        with mailbox.Mailbox(job=destination) as mb_to:
            _copy_folder(mb_from, mb_to, folder_name, archive_folder=archive_folder)

    backoff = 1
    while True:
        try:
            with mailbox.Mailbox(job=source) as mb_from:
                imap_client = cast(mailbox.ImapClient, mb_from)
                backoff = 1
                _copy_to_dest(imap_client)
                while True:
                    for _, _ in imap_client.watch_folder("INBOX"):
                        _copy_to_dest(imap_client)
        except (imaplib.IMAP4.abort, socket.error):
            log.warning(
                "%s::%s: Connection lost, reconnecting in %ds",
                source.name, folder_name, backoff,
            )
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)


def copy(source: conf.JobConfig, destination: conf.JobConfig, idle: bool = False) -> None:
    if source.move_to_archive:
        if source.archive_folder:
            archive_folder = source.archive_folder
        else:
            raise JobError("Option 'move_to_archive' given, but 'archive_folder' missing")
    else:
        archive_folder = None

    if idle:
        # FIXME: currently only INBOX
        _idle_copy(source, "INBOX", destination, archive_folder=archive_folder)
    else:
        _copy(source, destination, archive_folder=archive_folder)
