from __future__ import annotations

import collections.abc
import gzip
import hashlib
import io
import logging
import os
import pathlib

log = logging.getLogger(__name__)


class ContentAdressedStorage:
    def __init__(
        self,
        root_dir: str | pathlib.Path = ".",
        suffix: str | None = None,
        depth: int = 2,
        compression: bool = False,
        hashfactory: collections.abc.Callable | None = None,
    ):
        self.root_dir = pathlib.Path(root_dir)
        pathlib.Path.mkdir(self.root_dir, parents=True, exist_ok=True)
        self.collisions_dir = pathlib.Path(self.root_dir, "collisions")
        self.compression = compression or False
        self.hashfactory = hashfactory if hashfactory else hashlib.sha384
        self.depth = depth if depth >= 0 else 2
        self.suffix = suffix
        self.blocksize = 16384
        # TODO: Compression is not fully implemented yet
        if self.compression:
            raise NotImplementedError

    @property
    def suffix(self) -> str:
        return self._suffix

    @suffix.setter
    def suffix(self, value: str | None):
        if value:
            self._suffix = value.strip()
            if not self._suffix.startswith("."):
                self._suffix = "." + self._suffix
        else:
            self._suffix = ".dat"

    def _subdirs(self, hashval: str) -> list[str]:
        if len(hashval) < self.depth * 2:
            raise ValueError(f"hash string to short, {self.depth * 2} characters required")
        return [hashval[i : i + 2] for i in range(0, self.depth * 2, 2)]

    def _path(self, hashval: str) -> pathlib.Path:
        return pathlib.Path(self.root_dir, *self._subdirs(hashval))

    def _reader(self, data: io.IOBase | bytes) -> io.IOBase:
        if isinstance(data, bytes):
            reader = io.BytesIO(data)
        elif isinstance(data, io.IOBase):
            if data.seekable():
                reader = data
                reader.seek(0)
            else:
                blob = data.read()
                if not isinstance(blob, bytes):
                    raise TypeError("read() has to return bytes")
                reader = io.BytesIO(blob)
        else:
            raise TypeError("instance of bytes or io.IOBase expected")
        return reader

    def _hashval(self, reader: io.IOBase) -> str:
        m = self.hashfactory()
        while True:
            block = reader.read(self.blocksize or 4096)
            if block is None or len(block) == 0:
                break
            m.update(block)
        reader.seek(0)
        return m.hexdigest()

    def _filesize(self, reader: io.IOBase) -> int:
        pos = reader.tell()
        size = reader.seek(0, io.SEEK_END)
        reader.seek(pos)
        return size

    def _destination(self, hashval: str) -> tuple[pathlib.Path, str]:
        filename = hashval + self.suffix + (".gz" if self.compression else "")
        path = self._path(hashval)
        return path, filename

    def add(self, data: io.IOBase | bytes) -> tuple[str, str, pathlib.Path]:
        reader = self._reader(data)
        hashval = self._hashval(reader)
        path, filename = self._destination(hashval)
        file = path / filename
        if file.exists():
            size = self._filesize(reader)
            if file.stat().st_size == size:
                # TODO: not working for compressed files
                log.debug(f"{file}: already exists")
                return "EXISTS", hashval, file
            else:
                log.error(f"{file}: collision detected!")
                path = self.collisions_dir
                file = path / filename
                if file.exists():
                    # no second collision check
                    log.debug(f"{file}: collision file already exists")
                    return "EXISTS", hashval, file
        pathlib.Path.mkdir(path, parents=True, exist_ok=True)
        iomod = gzip if self.compression else io
        tmp_file = file.with_suffix("._tmp_")
        try:
            with iomod.open(tmp_file, "wb") as f:
                while True:
                    block = reader.read(self.blocksize or 4096)
                    if block is None or len(block) == 0:
                        break
                    f.write(block)
        except Exception as exc:
            log.error(f"{file}: error while writing file: {exc}")
            if tmp_file.exists():
                tmp_file.unlink()
            raise
        else:
            tmp_file.rename(file)
        log.debug(f"{file}: new entry")
        return "NEW", hashval, file

    def locate(
        self, data: io.IOBase | bytes | str, exists: bool = False
    ) -> pathlib.Path | None:
        if isinstance(data, str):
            hashval = data
        else:
            hashval = self._hashval(self._reader(data))
        path, filename = self._destination(hashval)
        result = path / filename
        if exists:
            return result if result.exists() else None
        else:
            return result

    def walk(self):
        for path, _, files in os.walk(self.root_dir):
            for file in [pathlib.Path(path, f) for f in files if f.endswith(self.suffix)]:
                yield file
