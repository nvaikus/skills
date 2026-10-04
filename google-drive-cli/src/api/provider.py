"""The storage backend as the indexer sees it. api/indexer.py knows only this interface, so a
second backend (e.g. Dropbox: list_folder/continue cursor, /files/download) is one new module.

An item is a dict:
  id, parent (one parent id or None), name, mime, folder (0/1),
  key       content fingerprint: unchanged key = the index text is still current (md5, or a
            revision/modified stamp for files without a checksum),
  md5, modified (RFC 3339), size (bytes or None),
  ext       suffix the mount shows after the name ('.docx' for a Google Doc, '' for a plain
            file or folder); None = the mount does not show the item (it is not indexed),
  native    1 when the content is only reachable through export_text (no bytes to download).
"""


class Transient(Exception):
    """A per-file failure worth retrying on the next run (network, 429, 5xx)."""


class Provider:
    name = "?"

    def scope_key(self):
        """Stable id of what this profile indexes; a change wipes and rebuilds the index."""
        raise NotImplementedError

    def compatible(self, old_scope):
        """True when a change from old_scope only re-arranges paths (same corpus): the index then
        relists metadata and moves texts instead of wiping and re-downloading everything."""
        return False

    def root_id(self):
        """Id of the scope's top folder: items whose parent chain reaches it are in scope."""
        raise NotImplementedError

    def address(self, rel):
        """Mount-relative path -> the address the CLI's other commands accept."""
        raise NotImplementedError

    def resolve(self, address):
        """A user-facing address (as address() returns) -> item id; not found -> UsageError."""
        raise NotImplementedError

    def start_cursor(self):
        """Change-feed position 'now', taken BEFORE a full listing so nothing is missed."""
        raise NotImplementedError

    def list_all(self):
        """Full listing of the corpus -> iterator of item batches."""
        raise NotImplementedError

    def changes(self, cursor):
        """-> iterator of (upserted items, removed ids, cursor after this page)."""
        raise NotImplementedError

    def get(self, item_id):
        """One item by id, or None when it is gone or trashed."""
        raise NotImplementedError

    def list_children(self, folder_id):
        raise NotImplementedError

    def fetch(self, item, dest):
        """Download the item's bytes into the file dest (never through a mount)."""
        raise NotImplementedError

    def export_text(self, item, tmp):
        """Native (export-only) item -> (text, extractor) or None when it has no text form."""
        raise NotImplementedError

    def ocr_text(self, item, tmp):
        """Server-side text recognition of a PDF/image -> text, or None when unsupported."""
        return None

    def sweep(self):
        """Remove temporary server-side artifacts a crashed run may have left. -> count."""
        return 0
