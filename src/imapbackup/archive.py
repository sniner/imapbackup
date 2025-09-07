import email.parser
import email.policy
import email.utils
import gzip
import hashlib
import io
import logging
import os
import pathlib
import sys

from typing import Union, Tuple, List

from imapbackup import cas, mailutils


log = logging.getLogger(__name__)


class MailArchive:
    def __init__(self, root_dir:pathlib.Path):
        self.root_dir = root_dir or "."

    def walk(self):
        """E-Mail-Dateien im Export-Archiv lokalisieren."""
        for path, _, files in os.walk(self.root_dir):
            for eml in [pathlib.Path(path, f) for f in files if f.endswith(".eml")]:
                yield eml

    def archive_to_cas(self, store:cas, compression=False, move=False):
        for eml in self.walk():
            try:
                with open(eml, "rb") as f:
                    result, uid, _ = store.add(f)
            except Exception as exc:
                log.error("Error adding %s to store: %s", eml, exc)
                continue
            else:
                log.info("%s: %s: %s", eml, result, uid)
                if move:
                    eml.unlink()
                    log.debug("%s: file deleted", eml)

    def addresses(self):
        """Alle eindeutigen Adressen aus den E-Mails im Archiv extrahieren."""
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

    def stats(self) -> Tuple[int, int]:
        """Anzahl Mails und die Gesamtgröße im Export-Archiv bestimmen."""
        size = 0
        count = 0
        for eml in self.walk():
            count += 1
            size += eml.stat().st_size
        return count, size


class DocuwareMailArchive(MailArchive):

    def walk(self):
        """E-Mail-Dateien im Docuware-Archiv lokalisieren."""
        for path, _, files in os.walk(self.root_dir):
            eml = [pathlib.Path(path, f) for f in files if f.endswith(".eml")]
            if len(eml)>1:
                eml_file = max([(f.stat().st_size, f) for f in eml], key=lambda x: x[0])[1]
            elif len(eml)==1:
                eml_file = eml[0]
            else:
                continue
            yield eml_file


# vim: set et sw=4 ts=4:
