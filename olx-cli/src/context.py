"""The ctx handed to every command. No logic."""


class Context:
    def __init__(self, args, writer, cfg):
        self.args = args
        self.cfg = cfg
        self.writer = writer
        self.write = writer.write
        self.text = writer.text
        self.note = writer.note
