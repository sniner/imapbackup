# imapbackup - A toolkit for email backup and archiving

`imapbackup` contains two command line tools:

* `ib-mailbox` for exporting emails from IMAP mailboxes
* `ib-archive` contributes a few functions for the archive data structure

## `ib-mailbox`

With `ib-mailbox` you can archive emails from IMAP mailboxes. The export can
be repeated at regular intervals, no duplicates will be saved as long as you
always export from the same mailbox.

`ib-mailbox` needs a configuration file for the backup job, you find the
description below.

First of all, you may want to get an overview of all folders in the mailbox to
be able to exclude certain folders from the backup:

```console
$ ib-mailbox list --job example.job
example.org::Trash
example.org::Archive
example.org::Archive/2022
example.org::Archive/2021
example.org::Archive/2020
example.org::INBOX
```

Now you are ready for the first backup run:

```console
$ ib-mailbox backup --job example.job ./backup
2022-04-12 10:05:52,275 INFO -- START
2022-04-12 10:05:52,276 INFO -- Processing mailbox: example.org
2022-04-12 10:05:52,527 INFO -- example.org::INBOX: found 3 messages
2022-04-12 10:05:52,799 INFO -- example.org::INBOX[1]: NEW: id=25652e390168...a234
2022-04-12 10:05:52,799 INFO -- example.org::INBOX[2]: NEW: id=fa1f63a13f91...c9ee
2022-04-12 10:05:52,799 INFO -- example.org::INBOX[3]: NEW: id=800be881dc38...7fa8
```

If you run it again, the messages will be downloaded again, but no duplicates
will be saved:

```console
$ ib-mailbox --job example.job backup ./backup
2022-04-12 10:09:28,248 INFO -- START
2022-04-12 10:09:28,250 INFO -- Processing mailbox: mailbox.org
2022-04-12 10:09:28,531 INFO -- example.org::INBOX: found 9 messages
2022-04-12 10:09:28,820 INFO -- example.org::INBOX[1]: EXISTS: id=25652e390168...a234
2022-04-12 10:09:28,820 INFO -- example.org::INBOX[2]: EXISTS: id=fa1f63a13f91...c9ee
2022-04-12 10:09:28,820 INFO -- example.org::INBOX[3]: EXISTS: id=800be881dc38...7fa8
```

## `ib-archive`

With `ib-archive` you can move/copy existing `eml` files into the archive
directory structure. Let's say you have some mails stored in `./my_mails` and
want to consolidate them into the archive under `./backup`:

```console
$ ib-archive --verbose import ./my_mails ./backup
```

The import function also has a few options:

```console
$ ib-archive import --help
usage: ib-archive import [-h] [--docuware] [--move] source destination

Import emails from source archive to destination

positional arguments:
  source       Directory from which you want to copy/move the mails
  destination  Archive directory

options:
  -h, --help   show this help message and exit
  --docuware   Source archive is a Docuware email archive
  --move       Move emails, i.e. remove emails from source after backup
```


## `ib-copy`

This tool is work in progress and not yet usable. Its purpose will be to
transfer mails between two IMAP mailboxes.


## Mail archive structure

Mails are exported as RFC822 `eml` files in a content-addressed directory
structure:

```
./archive
├── 00
│   ├── 00
│   │   └── 00003c6ec5464cca9...7af8.eml
│   ├── 0f
│   │   └── 000ffe5b49390d9b2...26eb.eml
│   ├── 11
│   │   └── 001124d77ce778289...4fd8.eml
│   ├── 30
│   │   └── 0030f33161416b03e...97aa.eml
```

The filename is the hash of the eml file itself and at the same time the key
to the data structure. It is therefore very easy to determine that the files
have not been tampered with by determining their hash value and comparing it
with the filename. Finding an email by its sender/recipient or subject is not
possible without the help of external tools.

Mails with the same message ID are considered identical by the user, but if
their RFC822 representation is different, they are stored multiple times
because the hash values differ. Especially MS Exchange is very creative in
generating different versions from the same mail, in particular the mails from
the journal differ from those in the mailbox by an additional `Received` entry
and replaced MIME multiplart delimiters.


## Job file

For `ib-mailbox` you have to create a configuration file for the backup job.

A simple example for Google Mail:

```yaml
gmail.com:
    server: "imap.gmail.com"
    username: "john.doe@gmail.com"
    password: "123456"
    folders:
        - All Mail
```

This is a YAML file, so you need to pay attention to the correct indentation.

### Parameters

`server` (Required): IP address or hostname of the IMAP server.

`username`, `password` (Required): Login credentials for the IMAP server. Only
login with username and password is currently supported.

`port`: If not specified, 993 is used.

`tls`: Set to `false` if an encrypted connection is not to be established.
Default is true.

`folders`: List of names of folder to be exported.

`ignore_folder_flags`: With IMAP, flags can be assigned to folders (and
messages). Here you can define a list of flags for folders that you want to
ignore if one of these flags is set.

`ignore_folder_names`: List of names of folders you want to ignore. The name
can also be a regular expression like `.*/foldername`


### Options

`tls_check_hostname`, `tls_verify_cert`: Default true, use these options to
disable the associated checks.

`exchange_journal`: This option enables the handling of MS Exchange Journal
messages. In this case, the original mail is found as an attachment in the
journal mail. The handling of these journal mails is not very elaborate, but
in my experience it works reliably - as long as they really are journal mails.
If you don't know exactly if you need this option, then you don't need it.
Default false.

`delete_after_export`: Default false. With this option enabled each exported
mail will be removed from the IMAP server. Use with caution.

`with_db`: Creates a metadata SQLite database.

`incremental`: Downloads only messages since the last backup job. Needs
`with_db` option.


### More examples

Example 1: Here you can see how to exclude folders from the backup.

```yaml
example.org:
    username: "john.doe@example.org"
    password: "123456"
    server: "imap.example.org"
    port: 993
    tls: true
    ignore_folder_flags:
        - Junk
        - Drafts
        - Trash
    ignore_folder_names:
        - .*/Calendar/?.*
    folders:
        - "INBOX"
        - "Archive"
```

Example 2: Exporting MS Exchange journal mails.

```yaml
exchange.example.org:
  server: "exchange.example.org"
  username: "john.doe@example.org"
  password: "123456"
  tls_check_hostname: false
  exchange_journal: true
  delete_after_export: true
  folders:
    - INBOX
```


## Metadata database

If requested in the job file with the `with_db` option, an SQLite database is
created inside the archive and some fields from the header like date, message
ID, sender, recipient and subject are written to this database.

For an archive without DB, a database can also be created afterwards with
`ib-archive db-from-archive --mailbox IDENTIFIER FOLDER`. The mailbox
identifier should match the name of the mailbox in your job file.


## MS Windows

A short tutorial on how to create an EXE file for Windows.

First, enter the Python environment by starting `CMD.EXE` or PowerShell CLI in
the project folder.

```console
C:\> pipenv install --dev
```

Now install `auto-py-to-exe`:

```console
C:\> pipenv run pip install auto-py-to-exe
C:\> auto-py-to-exe
```

Select the appropriate `py` file from `imapbackup/cli` in "Script Location"
field. Activate "One File" option and "Console Based". Now press the button
"CONVERT .PY TO .EXE". You will find the executable in folder `./output`.

