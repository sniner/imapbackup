from __future__ import annotations

import collections.abc
import logging
import os
import pathlib

from imapbackup import cas, mailutils

log = logging.getLogger(__name__)


class MailArchive:
    def __init__(self, root_dir: pathlib.Path):
        self.root_dir = root_dir

    def walk(self) -> collections.abc.Generator[pathlib.Path, None, None]:
        """Yield paths to all .eml files in the archive."""
        for path, _, files in os.walk(self.root_dir):
            for eml in [pathlib.Path(path, f) for f in files if f.endswith(".eml")]:
                yield eml

    def archive_to_cas(self, store: cas.ContentAddressedStorage, move: bool = False) -> None:
        """Import all emails into the content-addressed store."""
        for eml in self.walk():
            try:
                with open(eml, "rb") as f:
                    result, uid, _ = store.add(f)
            except OSError as exc:
                log.error("Error adding %s to store: %s", eml, exc)
                continue
            else:
                log.info("%s: %s: %s", eml, result, uid)
                if move:
                    eml.unlink()
                    log.debug("%s: file deleted", eml)

    def addresses(self) -> collections.abc.Generator[tuple[str, str], None, None]:
        """Yield unique sender/recipient addresses from all emails in the archive."""
        addrs = set()
        for eml in self.walk():
            with open(eml, "rb") as f:
                from_addr, to_addr = mailutils.addresses(mailutils.decode_email_header(f))
                for addr in from_addr:
                    if addr not in addrs:
                        addrs.add(addr)
                        yield "<", addr
                for addr in to_addr:
                    if addr not in addrs:
                        addrs.add(addr)
                        yield ">", addr

    def stats(self) -> tuple[int, int]:
        """Return (count, total_size_in_bytes) for all emails in the archive."""
        size = 0
        count = 0
        for eml in self.walk():
            count += 1
            size += eml.stat().st_size
        return count, size


class DocuwareMailArchive(MailArchive):
    def walk(self) -> collections.abc.Generator[pathlib.Path, None, None]:
        """Yield paths to .eml files in a Docuware archive (one per directory, largest wins)."""
        for path, _, files in os.walk(self.root_dir):
            eml = [pathlib.Path(path, f) for f in files if f.endswith(".eml")]
            if len(eml) > 1:
                eml_file = max([(f.stat().st_size, f) for f in eml], key=lambda x: x[0])[1]
            elif len(eml) == 1:
                eml_file = eml[0]
            else:
                continue
            yield eml_file
