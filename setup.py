import sys
from setuptools import setup, find_packages

setup(
    # Requirements
    python_requires=">=3.9",

    # Metadata
    name = "imapbackup",
    version = "0.1.1",
    author = "Stefan Schönberger",
    author_email = "mail@sniner.dev",
    description = "Export and backup tool for IMAP mailboxes",

    # Packages
    packages = find_packages(),

    # Dependencies
    install_requires = [
        "imapclient",
        "pyyaml",
    ],
    extras_require = {
        "dev": [
        ],
    },

    # Executables
    entry_points = {
        "console_scripts": [
            "ib-mailbox = imapbackup.cli.mailbox:main",
            "ib-archive = imapbackup.cli.archive:main",
            "ib-copy = imapbackup.cli.copy:main",
        ]
    },

    # Packaging information
    platforms = "any",
)

# vim: set et sw=4 ts=4: