from __future__ import annotations

import functools
import logging
import pathlib
import sqlite3
import threading

from datetime import datetime
from contextlib import contextmanager
from typing import Any, Optional, List, Union

log = logging.getLogger(__name__)


class RollbackException(Exception):
    pass


class StoreDatabase:
    def __init__(self, path:Union[pathlib.Path,str]):
        self.dbconn = None
        self.client = None
        self.path = path or "metadata.db"

    def __enter__(self) -> StoreDatabaseConnection:
        self.dbconn = sqlite3.connect(self.path, check_same_thread=False)
        self.dbconn.row_factory = sqlite3.Row
        self.client = StoreDatabaseConnection(self.dbconn)
        self.client.setup()
        return self.client

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.dbconn:
            self.dbconn.close()
            self.dbconn = None
            self.client = None

class DatabaseConnection():
    def __init__(self, dbconn:sqlite3.Connection):
        self.dbconn = dbconn
        self.lock = threading.RLock()
        self._transaction = 0

    @contextmanager
    def transaction(self):
        with self.lock:
            outer = self._transaction==0
            self._transaction += 1
            try:
                yield self
                if outer:
                    self.dbconn.commit()
            except:
                if outer:
                    self.dbconn.rollback()
                raise
            finally:
                self._transaction -= 1

    def execute(self, statement:str, *args:Any) -> sqlite3.Cursor:
        with self.lock:
            return self.dbconn.execute(statement, *args)

    def commit(self):
        with self.lock:
            if self._transaction==0:
                self.dbconn.commit()

    def rollback(self):
        raise RollbackException()

    def setup(self):
        pass


class StoreDatabaseConnection(DatabaseConnection):

    def setup(self):
        with self.transaction():
            self.execute("""
                CREATE TABLE IF NOT EXISTS mailbox (
                mailbox_id INTEGER PRIMARY KEY, 
                name TEXT NOT NULL,
                UNIQUE(name) ON CONFLICT IGNORE)
            """)

            self.execute("""
                CREATE TABLE IF NOT EXISTS address (
                address_id INTEGER PRIMARY KEY,
                address TEXT NOT NULL,
                UNIQUE(address) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_address_1 ON address(address)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS label (
                label_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                UNIQUE(name) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_label_1 ON label(name)")
            self.execute("""
                INSERT OR IGNORE INTO label(name) VALUES ("INBOX")
            """)

            self.execute("""
                CREATE TABLE IF NOT EXISTS subject (
                subject_id INTEGER PRIMARY KEY,
                text TEXT NOT NULL,
                UNIQUE(text) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_subject_1 ON subject(text)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS message (
                message_id INTEGER PRIMARY KEY,
                store_id TEXT NOT NULL,
                email_id TEXT,
                date TEXT,
                subject_id INTEGER,
                FOREIGN KEY(subject_id) REFERENCES subject(subject_id),
                UNIQUE(store_id) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_1 ON message(store_id)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS message_mailbox (
                message_id INTEGER,
                mailbox_id INTEGER,
                FOREIGN KEY(message_id) REFERENCES message(message_id),
                FOREIGN KEY(mailbox_id) REFERENCES mailbox(mailbox_id),
                UNIQUE(message_id, mailbox_id) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_mailbox_1 ON message_mailbox(message_id)")
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_mailbox_2 ON message_mailbox(mailbox_id)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS message_label (
                message_id INTEGER NOT NULL,
                label_id INTEGER NOT NULL,
                FOREIGN KEY(message_id) REFERENCES message(message_id),
                FOREIGN KEY(label_id) REFERENCES label(label_id),
                UNIQUE(message_id, label_id) ON CONFLICT IGNORE);
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_label_1 ON message_label(message_id)")
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_label_2 ON message_label(label_id)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS message_sender (
                message_id INTEGER NOT NULL,
                address_id INTEGER NOT NULL,
                FOREIGN KEY(message_id) REFERENCES message(message_id),
                FOREIGN KEY(address_id) REFERENCES address(address_id),
                UNIQUE(message_id, address_id) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_sender_1 ON message_sender(message_id)")
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_sender_2 ON message_sender(address_id)")

            self.execute("""
                CREATE TABLE IF NOT EXISTS message_recipient (
                message_id INTEGER NOT NULL,
                address_id INTEGER NOT NULL,
                FOREIGN KEY(message_id) REFERENCES message(message_id),
                FOREIGN KEY(address_id) REFERENCES address(address_id),
                UNIQUE(message_id, address_id) ON CONFLICT IGNORE)
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_recipient_1 ON message_sender(message_id)")
            self.execute("CREATE INDEX IF NOT EXISTS idx_message_recipient_2 ON message_sender(address_id)")
            
            self.execute("""
                CREATE TABLE IF NOT EXISTS snapshot (
                snapshot_id INTEGER PRIMARY KEY,
                mailbox_id INTEGER NOT NULL,
                label_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                FOREIGN KEY(mailbox_id) REFERENCES mailbox(mailbox_id),
                FOREIGN KEY(label_id) REFERENCES label(label_id),
                UNIQUE(mailbox_id, label_id) ON CONFLICT REPLACE)
            """)
            self.execute("CREATE INDEX IF NOT EXISTS idx_snapshot_1 ON snapshot(mailbox_id)")

            self.execute("""
                CREATE VIEW IF NOT EXISTS v_messages AS
                SELECT
                msg.message_id,
                msg.email_id,
                msg.store_id,
                msg.date,
                mb.name "mailbox",
                addr_send.address "sender",
                addr_rcpt.address "recipient",
                subject.text "subject"
                FROM message msg
                JOIN message_sender send USING (message_id)
                JOIN message_recipient rcpt USING (message_id)
                JOIN subject USING (subject_id)
                JOIN address addr_send ON addr_send.address_id=send.address_id
                JOIN address addr_rcpt ON addr_rcpt.address_id=rcpt.address_id
                LEFT OUTER JOIN message_mailbox mm USING (message_id)
                LEFT OUTER JOIN mailbox mb ON mb.mailbox_id=mm.mailbox_id
            """)

            self.execute("""
                CREATE VIEW IF NOT EXISTS v_exchange_duplicates AS
                SELECT DISTINCT
                msg.message_id,
                msg.email_id,
                msg.store_id,
                msg.date
                FROM message msg
                INNER JOIN message dup
                ON msg.email_id=dup.email_id
                  AND msg.date=dup.date
                  AND msg.store_id<>dup.store_id
                ORDER BY msg.date, msg.email_id, msg.message_id
            """)

    @functools.lru_cache
    def add_mailbox(self, mailbox_name:str) -> int:
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO mailbox(name) VALUES (?)", (mailbox_name,))
            return self.execute("SELECT mailbox_id FROM mailbox WHERE name=?", (mailbox_name,)).fetchone()[0]

    @functools.lru_cache
    def add_label(self, label_name:str) -> int:
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO label(name) VALUES (?)", (label_name,))
            return self.execute("SELECT label_id FROM label WHERE name=?", (label_name,)).fetchone()[0]

    @functools.lru_cache
    def add_address(self, address:str) -> int:
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO address(address) VALUES (?)", (address,))
            return self.execute("SELECT address_id FROM address WHERE address=?", (address,)).fetchone()[0]

    @functools.lru_cache
    def add_subject(self, subject:str) -> int:
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO subject(text) VALUES (?)", (subject,))
            return self.execute("SELECT subject_id FROM subject WHERE text=?", (subject,)).fetchone()[0]

    def add_message(self, store_id:str, email_id:str, date:datetime, subject:str, mailbox_id:int=None) -> int:
        with self.transaction():
            subject_id = self.add_subject(subject)
            self.execute(
                "INSERT OR IGNORE INTO message(store_id, email_id, date, subject_id) VALUES (?, ?, ?, ?)",
                (store_id, email_id, date.isoformat() if date else None, subject_id))
            msg_id = self.execute("SELECT message_id FROM message WHERE store_id=?", (store_id,)).fetchone()[0]
            if mailbox_id is not None:
                self.assign_message_to_mailbox(msg_id, mailbox_id)
            return msg_id

    def assign_message_to_mailbox(self, message_id:int, mailbox_id:int):
        with self.transaction():
            self.execute("INSERT OR IGNORE INTO message_mailbox(message_id, mailbox_id) VALUES (?, ?)", (message_id, mailbox_id))

    def get_message(self, mailbox_id:int, store_id:str) -> int:
        return self.execute("SELECT message_id FROM message WHERE mailbox_id=? AND store_id=?", (mailbox_id, store_id,)).fetchone()[0]

    def get_message_labels(self, message_id:int) -> List[str]:
        return [row[0] for row in self.execute("""
            SELECT label.name from message_label JOIN label USING (label_id) WHERE message_id=?
            """, (message_id,)).fetchall()]

    def get_message_label_ids(self, message_id:int) -> List[int]:
        return [row[0] for row in self.execute("SELECT label_id from message_label WHERE message_id=?", (message_id,)).fetchall()]

    def add_message_labels(self, message_id:int, *label_names:List[str]):
        for label in label_names:
            label_id = self.add_label(label)
            self.execute("INSERT OR IGNORE INTO message_label(message_id, label_id) VALUES (?, ?)", (message_id, label_id))

    def update_message_labels(self, message_id:int, *label_names:List[str]):
        with self.transaction():
            current = set()
            for label in label_names:
                label_id = self.add_label(label)
                current.add(label_id)
                self.execute("INSERT OR IGNORE INTO message_label(message_id, label_id) VALUES (?, ?)", (message_id, label_id))
            for label_id in self.get_message_label_ids(message_id):
                if label_id not in current:
                    self.execute("DELETE FROM message_label WHERE message_id=? AND label_id=?", (message_id, label_id))

    def add_message_sender(self, message_id:int, *sender:List[str]):
        with self.transaction():
            for addr in sender:
                addr_id = self.add_address(addr)
                self.execute("INSERT OR IGNORE INTO message_sender(message_id, address_id) VALUES (?, ?)", (message_id, addr_id))

    def add_message_recipients(self, message_id:int, *recipients:List[str]):
        with self.transaction():
            for addr in recipients:
                addr_id = self.add_address(addr)
                self.execute("INSERT OR IGNORE INTO message_recipient(message_id, address_id) VALUES (?, ?)", (message_id, addr_id))

    def get_snapshot(self, mailbox_id:int, label_id:int) -> Optional[dict]:
        row = self.execute("SELECT * FROM snapshot WHERE mailbox_id=? AND label_id=?", (mailbox_id, label_id)).fetchone()
        return dict(row) if row else None

    def set_snapshot(self, mailbox_id:int, label_id:int, date:datetime=None):
        if date is None:
            date = datetime.now()
        isodate = date.isoformat()
        # NB: does work because of ON CONFLICT REPLACE
        with self.transaction():
            self.execute("INSERT INTO snapshot(mailbox_id, label_id, date) VALUES (?, ?, ?)", (mailbox_id, label_id, isodate))

    def delete_snapshot(self, mailbox_id:int, label_id:Optional[int]=None):
        with self.transaction():
            if label_id:
                self.execute("DELETE FROM snapshot WHERE mailbox_id=? AND label_id=?", (mailbox_id, label_id))
            else:
                self.execute("DELETE FROM snapshot WHERE mailbox_id=?", (mailbox_id,))

    def get_snapshot_date(self, mailbox_id:int, label_id:int, default:Optional[datetime]=None) -> datetime:
        s = self.get_snapshot(mailbox_id, label_id)
        if s:
            return datetime.fromisoformat(s["date"])
        else:
            return default


if __name__=="__main__":
    with StoreDatabase("./test.db") as db:
        mb = db.add_mailbox("Schlumpf")
        msg = db.add_message("12345678901234567890", "<hulla@example.org>", datetime.now(), mailbox_id=mb, subject="Test")
        db.add_message_labels(msg, "Private", "Must read")
        db.add_message_sender(msg, "me@example.com")
        db.add_message_recipients(msg, "friend@example.com", "foo.bar@gmail.com")
        print(msg, db.get_message_labels(msg))
        db.update_message_labels(msg, "Private", "INBOX")
        print(msg, db.get_message_labels(msg))

# vim: set et sw=4 ts=4:
