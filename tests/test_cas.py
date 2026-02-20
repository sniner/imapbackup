from imapbackup import cas


def test_cas_init_directory(tmp_path):
    _ = cas.ContentAdressedStorage(root_dir=tmp_path / "cas")
    assert (tmp_path / "cas").exists()


def test_cas_add_bytes(tmp_path):
    store = cas.ContentAdressedStorage(root_dir=tmp_path / "cas")
    status, hashval, path = store.add(b"hello world")
    assert status == "NEW"
    assert path.exists()
    assert path.read_bytes() == b"hello world"
    
    # Adding the same should return EXISTS
    status2, hashval2, path2 = store.add(b"hello world")
    assert status2 == "EXISTS"
    assert hashval == hashval2
    assert path == path2


def test_cas_locate(tmp_path):
    store = cas.ContentAdressedStorage(root_dir=tmp_path / "cas")
    data = b"find me"
    store.add(data)
    
    path = store.locate(data)
    assert path is not None
    assert path.exists()
    
    # locate without existing file but exists=True
    path_missing = store.locate(b"missing", exists=True)
    assert path_missing is None
    
    path_uncheck = store.locate(b"missing", exists=False)
    assert path_uncheck is not None
    assert not path_uncheck.exists()


def test_cas_walk(tmp_path):
    store = cas.ContentAdressedStorage(root_dir=tmp_path / "cas")
    store.add(b"file1")
    store.add(b"file2")
    
    files = list(store.walk())
    assert len(files) == 2
