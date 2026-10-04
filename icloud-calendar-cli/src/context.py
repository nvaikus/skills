"""The ctx handed to every command. No logic beyond lazy session creation."""
from .api import calendars, tz
from .core import profile


class Context:
    def __init__(self, args, writer, cfg):
        self.args = args
        self.cfg = cfg
        self.writer = writer
        self.write = writer.write
        self.text = writer.text
        self.note = writer.note
        self._session = None

    @property
    def profile(self):
        return profile.active()

    @property
    def zone(self):
        return tz.local()

    @property
    def zone_name(self):
        return tz.local_name() or "UTC"

    def session(self):
        """(Session, cfg): credentials from the environment, calendar home discovered once and cached."""
        if self._session is None:
            self._session, self.cfg = calendars.session_for(self.cfg, profile.active())
        return self._session

    def calendars(self):
        return calendars.list_all(self.session(), self.cfg)
