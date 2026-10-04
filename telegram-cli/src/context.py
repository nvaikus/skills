"""The ctx handed to every command. No logic."""
from .core import tg


class Context:
    def __init__(self, args, writer, cfg):
        self.args = args
        self.cfg = cfg
        self.account = args.account or cfg["default_account"]
        self.writer = writer
        self.write = writer.write
        self.note = writer.note
        self._client = None

    def client(self, need_auth=True):
        if self._client is None:
            self._client = tg.connect(self.cfg, self.account, need_auth=need_auth)
        return self._client

    def close(self):
        if self._client is not None:
            self._client.disconnect()
            self._client = None
