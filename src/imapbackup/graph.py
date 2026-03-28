"""MS Graph backend for accessing Microsoft 365 mailboxes."""

from __future__ import annotations

import collections.abc
import logging
import re
import urllib.parse
from datetime import datetime
from typing import TYPE_CHECKING, Any

from imapbackup import cas, conf, mailutils

if TYPE_CHECKING:
    import httpx
    import msal

log = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]


class MSGraphClient:
    """MailboxClient implementation using Microsoft Graph API.

    Authenticates via MSAL client credentials flow (service principal),
    suitable for unattended backup of Microsoft 365 mailboxes.
    """

    def __init__(self, job: conf.JobConfig):
        import httpx as _httpx
        import msal as _msal

        self.job = job
        self.job_name = job.name
        self.delete_after_export = job.delete_after_export
        self.exchange_journal = job.exchange_journal

        authority = f"https://login.microsoftonline.com/{job.tenant_id}"
        self._msal_app: msal.ConfidentialClientApplication = (
            _msal.ConfidentialClientApplication(
                client_id=job.client_id,
                authority=authority,
                client_credential=job.client_secret,
            )
        )
        token = self._acquire_token()

        self._http: httpx.Client = _httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=60.0,
        )
        self._user = job.username

        self._folder_map: dict[str, str] = {}
        self._build_folder_map()

    def _acquire_token(self) -> str:
        result = self._msal_app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if not result or "access_token" not in result:
            error = result.get("error_description", "unknown error") if result else "no result"
            raise RuntimeError(f"MSAL authentication failed: {error}")
        return result["access_token"]

    def _refresh_auth(self) -> None:
        """Refresh the access token (MSAL handles caching internally)."""
        token = self._acquire_token()
        self._http.headers["Authorization"] = f"Bearer {token}"

    def close(self) -> None:
        """Close the HTTP client."""
        self._http.close()

    def _request(self, method: str, url: str, **kwargs) -> "httpx.Response":
        """Send an HTTP request, refreshing the token on 401."""
        resp = self._http.request(method, url, **kwargs)
        if resp.status_code == 401:
            log.debug("Token expired, refreshing")
            self._refresh_auth()
            resp = self._http.request(method, url, **kwargs)
        return resp

    def _paginate(
        self,
        url: str,
        params: dict[str, str] | None = None,
    ) -> collections.abc.Generator[dict[str, Any], None, None]:
        """Yield items from a paginated Graph API response."""
        current_params = params.copy() if params else {}
        base_url = url

        while True:
            resp = self._request("GET", base_url, params=current_params)
            resp.raise_for_status()
            data = resp.json()

            yield from data.get("value", [])

            next_link = data.get("@odata.nextLink")
            if not next_link:
                break

            parsed = urllib.parse.urlparse(next_link)
            query = urllib.parse.parse_qs(parsed.query)
            skip_token = query.get("$skiptoken") or query.get("$skip")
            if skip_token:
                if "$skiptoken" in query:
                    current_params["$skiptoken"] = skip_token[0]
                elif "$skip" in query:
                    current_params["$skip"] = skip_token[0]
            else:
                base_url = next_link
                current_params = {}

    def _build_folder_map(self) -> None:
        """Recursively build a mapping of folder display paths to Graph IDs."""
        self._folder_map.clear()
        self._enumerate_folders(
            f"{GRAPH_BASE_URL}/users/{self._user}/mailFolders",
            prefix="",
        )

    def _enumerate_folders(self, url: str, prefix: str) -> None:
        params = {"$select": "id,displayName,childFolderCount", "$top": "100"}
        for folder in self._paginate(url, params):
            name = folder.get("displayName", "")
            path = f"{prefix}/{name}" if prefix else name
            folder_id = folder["id"]
            self._folder_map[path] = folder_id

            if folder.get("childFolderCount", 0) > 0:
                child_url = (
                    f"{GRAPH_BASE_URL}/users/{self._user}/mailFolders/{folder_id}/childFolders"
                )
                self._enumerate_folders(child_url, prefix=path)

    def _resolve_folder(self, folder_name: str) -> str:
        """Resolve a folder display name or path to its Graph ID."""
        if folder_name in self._folder_map:
            return self._folder_map[folder_name]
        lower = folder_name.casefold()
        for path, fid in self._folder_map.items():
            if path.casefold() == lower:
                return fid
        raise RuntimeError(f"Folder not found: {folder_name}")

    def _download_mime(self, msg_id: str) -> bytes:
        """Download a message as RFC 822 MIME content."""
        url = f"{GRAPH_BASE_URL}/users/{self._user}/messages/{msg_id}/$value"
        resp = self._request("GET", url)
        resp.raise_for_status()
        return resp.content

    def _graph_delete(self, msg_id: str) -> None:
        url = f"{GRAPH_BASE_URL}/users/{self._user}/messages/{msg_id}"
        resp = self._request("DELETE", url)
        resp.raise_for_status()

    def _iter_messages(
        self,
        folder_name: str,
        folder_id: str,
        since: datetime | None = None,
    ) -> collections.abc.Generator[dict[str, Any], None, None]:
        """List messages in a folder, optionally filtered by date."""
        url = f"{GRAPH_BASE_URL}/users/{self._user}/mailFolders/{folder_id}/messages"
        params: dict[str, str] = {
            "$top": "50",
            "$select": "id,receivedDateTime",
            "$orderby": "receivedDateTime asc",
        }
        if since:
            since_str = since.strftime("%Y-%m-%dT%H:%M:%SZ")
            params["$filter"] = f"receivedDateTime ge {since_str}"

        yield from self._paginate(url, params)

    def folders(self) -> collections.abc.Generator[str, None, None]:
        ignore_names = self.job.ignore_folder_names
        for path in self._folder_map:
            if any(re.match(pattern, path) for pattern in ignore_names):
                continue
            yield path

    def folder_backup(
        self,
        folder_name: str,
        store: cas.ContentAddressedStorage,
        since: datetime | None = None,
        callback: collections.abc.Callable[[dict], None] | None = None,
    ) -> int:
        folder_id = self._resolve_folder(folder_name)
        messages = list(self._iter_messages(folder_name, folder_id, since))
        log.info("%s::%s: found %s messages", self.job_name, folder_name, len(messages))

        counter = 0
        for idx, msg_info in enumerate(messages, 1):
            msg_id = msg_info["id"]
            try:
                msg = self._download_mime(msg_id)
            except Exception as exc:
                log.error(
                    "%s::%s[%s]: download failed: %s",
                    self.job_name,
                    folder_name,
                    idx,
                    exc,
                )
                continue

            if self.exchange_journal:
                unwrapped = mailutils.unwrap_exchange_journal_item(msg)
                if unwrapped is None:
                    log.warning(
                        "%s::%s[%s]: not a journal item, skipping",
                        self.job_name,
                        folder_name,
                        idx,
                    )
                    continue
                msg = unwrapped

            result, store_id, _path = store.add(msg)
            log.info(
                "%s::%s[%s]: %s: id=%s",
                self.job_name,
                folder_name,
                idx,
                result,
                store_id,
            )

            if callback:
                try:
                    header = mailutils.decode_email_header(msg)
                    from_addrs, to_addrs = mailutils.addresses(header)
                    callback(
                        {
                            "mailbox": self.job_name,
                            "folder": folder_name,
                            "email_id": mailutils.message_id(header),
                            "store_id": store_id,
                            "labels": [folder_name],
                            "sender": from_addrs,
                            "recipients": to_addrs,
                            "date": mailutils.date(header),
                            "subject": mailutils.subject(header),
                        }
                    )
                except Exception as exc:
                    log.exception(
                        "%s::%s[%s]: Error in callback: %s",
                        self.job_name,
                        folder_name,
                        idx,
                        exc,
                    )
                    continue

            counter += 1
            if counter % 100 == 0:
                log.info(
                    "%s::%s: %s/%s messages processed",
                    self.job_name,
                    folder_name,
                    counter,
                    len(messages),
                )

            if self.delete_after_export:
                try:
                    self._graph_delete(msg_id)
                except Exception as exc:
                    log.error(
                        "%s::%s[%s]: delete failed: %s",
                        self.job_name,
                        folder_name,
                        idx,
                        exc,
                    )

        return counter

    def full_backup(
        self,
        store: cas.ContentAddressedStorage,
        since: datetime | None = None,
        callback: collections.abc.Callable[[dict], None] | None = None,
    ) -> None:
        for folder in self.folders():
            try:
                self.folder_backup(folder, store, since=since, callback=callback)
            except Exception as exc:
                log.error("%s::%s: backup failed: %s", self.job_name, folder, exc)

    def get_messages(
        self,
        folder_name: str,
        since: datetime | None = None,
    ) -> collections.abc.Generator[tuple[Any, datetime | None, bytes], None, None]:
        folder_id = self._resolve_folder(folder_name)
        for msg_info in self._iter_messages(folder_name, folder_id, since):
            msg_id = msg_info["id"]
            received = msg_info.get("receivedDateTime")
            msg_date = datetime.fromisoformat(received) if received else None
            try:
                msg = self._download_mime(msg_id)
            except Exception as exc:
                log.error(
                    "%s::%s: download failed for %s: %s",
                    self.job_name,
                    folder_name,
                    msg_id[:20],
                    exc,
                )
                continue
            log.info("%s::%s: fetched %s", self.job_name, folder_name, msg_id[:20])
            yield msg_id, msg_date, msg

    def save_message(
        self,
        msg: bytes,
        folder_name: str,
        date: datetime | None = None,
    ) -> None:
        folder_id = self._resolve_folder(folder_name)
        url = f"{GRAPH_BASE_URL}/users/{self._user}/mailFolders/{folder_id}/messages"
        resp = self._request("POST", url, content=msg, headers={"Content-Type": "text/plain"})
        resp.raise_for_status()

    def move_message(self, msg_id: Any, folder_name: str) -> None:
        folder_id = self._resolve_folder(folder_name)
        url = f"{GRAPH_BASE_URL}/users/{self._user}/messages/{msg_id}/move"
        resp = self._request("POST", url, json={"destinationId": folder_id})
        resp.raise_for_status()

    def delete_message(self, msg_id: Any, expunge: bool = False) -> None:
        self._graph_delete(msg_id)
