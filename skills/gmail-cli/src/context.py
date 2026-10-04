"""The ctx handed to every command. No logic."""
from .core import profile


class Context:
    def __init__(self, args, writer, cfg):
        self.args = args
        self.cfg = cfg
        self.writer = writer
        self.write = writer.write
        self.text = writer.text
        self.note = writer.note

    @property
    def profile(self):
        return profile.active()

    @property
    def profiles(self):
        return profile.selected()
