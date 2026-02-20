from imapbackup import archive, cas
from .fixtures import dummy_eml_bytes


def test_mail_archive_walk(tmp_path, dummy_eml_bytes):
    # Setup test repository
    eml_file = tmp_path / "test.eml"
    eml_file.write_bytes(dummy_eml_bytes)
    
    # Also create a non-eml file
    dummy_file = tmp_path / "test.txt"
    dummy_file.write_text("Hello")

    arch = archive.MailArchive(root_dir=tmp_path)
    files = list(arch.walk())
    
    assert len(files) == 1
    assert files[0] == eml_file


def test_mail_archive_stats(tmp_path, dummy_eml_bytes):
    eml_file = tmp_path / "test.eml"
    eml_file.write_bytes(dummy_eml_bytes)
    
    arch = archive.MailArchive(root_dir=tmp_path)
    count, size = arch.stats()
    
    assert count == 1
    assert size == len(dummy_eml_bytes)


def test_mail_archive_to_cas(tmp_path, dummy_eml_bytes):
    eml_file = tmp_path / "test.eml"
    eml_file.write_bytes(dummy_eml_bytes)
    
    cas_dir = tmp_path / "cas"
    store = cas.ContentAdressedStorage(root_dir=cas_dir)
    
    arch = archive.MailArchive(root_dir=tmp_path)
    arch.archive_to_cas(store, move=False)
    
    assert list(store.walk())  # Should have one file
    assert eml_file.exists()  # move=False
    
    # Test move
    arch.archive_to_cas(store, move=True)
    assert not eml_file.exists()


def test_docuware_archive_walk(tmp_path, dummy_eml_bytes):
    arch_dir = tmp_path / "dw"
    arch_dir.mkdir()
    
    eml1 = arch_dir / "small.eml"
    eml1.write_bytes(b"small")
    
    eml2 = arch_dir / "large.eml"
    eml2.write_bytes(dummy_eml_bytes)
    
    arch = archive.DocuwareMailArchive(root_dir=arch_dir)
    files = list(arch.walk())
    
    # DocuwareArchive returns the largest .eml file in the directory
    assert len(files) == 1
    assert files[0] == eml2
