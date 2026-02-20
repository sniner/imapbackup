from datetime import datetime, timezone

from imapbackup import storedb


def test_store_db_setup(tmp_path):
    db_path = tmp_path / "test.db"
    with storedb.StoreDatabase(db_path) as db:
        # Tables should be created
        res = db.dbconn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        tables = [r[0] for r in res]
        assert "mailbox" in tables
        assert "message" in tables
        assert "label" in tables


def test_store_db_add_mailbox(tmp_path):
    db_path = tmp_path / "test.db"
    with storedb.StoreDatabase(db_path) as db:
        mb_id = db.add_mailbox("INBOX")
        assert mb_id > 0
        # Adding same mailbox should return same id
        mb_id_2 = db.add_mailbox("INBOX")
        assert mb_id == mb_id_2


def test_store_db_add_message_and_labels(tmp_path):
    db_path = tmp_path / "test.db"
    with storedb.StoreDatabase(db_path) as db:
        msg_id = db.add_message(
            store_id="hash123",
            email_id="<message-id@example.com>",
            date=datetime.now(timezone.utc),
            subject="Test Subject"
        )
        assert msg_id > 0
        
        # Test adding labels
        db.add_message_labels(msg_id, "Label1", "Label2")
        
        # Verify labels
        labels = db.get_message_labels(msg_id)
        assert set(labels) == {"Label1", "Label2"}
