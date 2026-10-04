"""The ctx handed to every command. No logic beyond wiring connect -> drain -> store."""
from .core import config, wa
from .core.store import Store


class Context:
    def __init__(self, args, writer, cfg):
        self.args = args
        self.cfg = cfg
        self.account = args.account or cfg["default_account"]
        self.writer = writer
        self.write = writer.write
        self.note = writer.note
        self._session = None
        self._store = None

    def store(self):
        if self._store is None:
            self._store = Store(config.store_path(self.account))
        return self._store

    def session(self, need_auth=True, drain=True):
        """Connected session; by default the offline queue is drained into the store first."""
        if self._session is None:
            self._session = wa.connect(self.cfg, self.account, need_auth=need_auth)
            if drain and need_auth:
                from .api import sync
                sync.drain(self._session, self.store(), maximum=self.cfg["sync_wait"])
        return self._session

    def synced_store(self):
        """Store for reads: synced first unless --offline."""
        if not getattr(self.args, "offline", False):
            self.session()
        return self.store()

    def close(self):
        try:
            if self._session is not None:
                self._session.stop()
                left = self._session.leftovers()
                if left:
                    from .api import sync
                    sync.absorb(left, self.store(), self._session)
                self._session = None
        finally:
            if self._store is not None:
                self._store.close()
                self._store = None
