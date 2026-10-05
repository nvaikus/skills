"""`claude-tg profile`: read or change the bot's own name, descriptions and profile photo.

Like notify it runs without the service and reads the token file itself (a bot run's env has no token).
No args = the getters; each setter flag is applied independently and reported as one TSV line."""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config
from .botapi import Bot, TgError

# flag -> (setter, getter, param, max length)
TEXT = {
    "name": ("setMyName", "getMyName", "name", 64),
    "description": ("setMyDescription", "getMyDescription", "description", 512),
    "short": ("setMyShortDescription", "getMyShortDescription", "short_description", 120),
}
JPG = {".jpg", ".jpeg"}
FIELD = "p"  # multipart field the InputProfilePhoto JSON points at
MAX_PHOTO = 10 * 1024 * 1024


class ProfileError(Exception):
    pass


def validate(a) -> list:
    """Usage errors for the setter flags; empty list = ok."""
    errs = []
    for key, (_, _, _, limit) in TEXT.items():
        v = getattr(a, key, None)
        if v is not None and len(v) > limit:
            errs.append(f"--{key} is {len(v)} chars; Telegram allows {limit}")
    if a.photo and a.photo_remove:
        errs.append("--photo and --photo-remove exclude each other")
    if a.photo and not Path(a.photo).expanduser().is_file():
        errs.append(f"no such file: {a.photo}")
    return errs


def wants_change(a) -> bool:
    return any(getattr(a, k, None) is not None for k in TEXT) or bool(a.photo or a.photo_remove)


def show(bot, lang=None) -> list:
    """[(field, value)] from the getters; newlines escaped so each field stays one line."""
    out = []
    for key, (_, getter, param, _) in TEXT.items():
        v = bot.call(getter, language_code=lang).get(param, "")
        out.append((key, v.replace("\\", "\\\\").replace("\n", "\\n")))
    return out


def as_jpg(path: Path, tmp: Path) -> Path:
    """The photo as jpg: as is, else converted with ffmpeg (first frame) into `tmp`."""
    if path.suffix.lower() in JPG:
        return path
    ff = shutil.which("ffmpeg")
    if not ff:
        raise ProfileError(f"{path.name}: the profile photo must be jpg; install ffmpeg to convert it, "
                           "or pass a .jpg")
    out = tmp / "profile.jpg"
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(path), "-frames:v", "1", "-q:v", "2", str(out)],
                       capture_output=True, text=True, timeout=60)
    if r.returncode or not out.is_file():
        raise ProfileError(f"{path.name}: ffmpeg could not convert it to jpg ({r.stderr.strip()[-200:]})")
    return out


def set_photo(bot, path: Path):
    """setMyProfilePhoto: `photo` = InputProfilePhoto JSON naming the multipart field via attach://."""
    with tempfile.TemporaryDirectory() as d:
        jpg = as_jpg(path, Path(d))
        if jpg.stat().st_size > MAX_PHOTO:
            raise ProfileError(f"{path.name} is {jpg.stat().st_size / 2**20:.1f} MB as jpg; keep it under 10 MB")
        return bot.upload("setMyProfilePhoto", FIELD, jpg, photo={"type": "static", "photo": f"attach://{FIELD}"})


def apply(bot, a) -> list:
    """[(field, "ok" | "error: ...")] for each requested change; one failure never blocks the others."""
    out = []
    for key, (setter, _, param, _) in TEXT.items():
        v = getattr(a, key, None)
        if v is None:
            continue
        try:
            bot.call(setter, language_code=a.lang, **{param: v})
            out.append((key, "ok"))
        except TgError as e:
            out.append((key, f"error: {e.description}"))
    if a.photo or a.photo_remove:
        try:
            if a.photo:
                set_photo(bot, Path(a.photo).expanduser())
            else:
                bot.call("removeMyProfilePhoto")
            out.append(("photo", "removed" if a.photo_remove else "ok"))
        except (TgError, ProfileError) as e:
            out.append(("photo", f"error: {getattr(e, 'description', None) or e}"))
    return out


def main(cfg: dict, a) -> int:
    errs = validate(a)
    if errs:
        for e in errs:
            print(f"claude-tg profile: {e}", file=sys.stderr)
        return 2
    try:
        bot = Bot(config.read_token(cfg))
        rows = apply(bot, a) if wants_change(a) else show(bot, a.lang)
    except TgError as e:
        print(f"claude-tg profile: {e}", file=sys.stderr)
        return 1
    for k, v in rows:
        print(f"{k}\t{v}")
    return 1 if any(v.startswith("error:") for _, v in rows) else 0
