"""The rclone binary gdrive owns: install, locate, run, remote control (rc)."""
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from ..core import http, paths, profile
from ..core.errors import CliError, UsageError

BASE = "https://downloads.rclone.org"
OS_NAMES = {"darwin": "osx", "linux": "linux", "win32": "windows"}
ARCH_NAMES = {"x86_64": "amd64", "amd64": "amd64", "arm64": "arm64", "aarch64": "arm64",
              "i386": "386", "i686": "386", "x86": "386", "armv7l": "arm-v7", "armv6l": "arm-v6"}


def exe_name():
    return "rclone.exe" if os.name == "nt" else "rclone"


def binary():
    return paths.sub(paths.data(), "bin") / exe_name()


def conf():
    """The active profile's rclone.conf (holds the OAuth token)."""
    return profile.dir() / "rclone.conf"


def require():
    b = binary()
    if not b.exists():
        raise UsageError(f"rclone is not installed at {b}: run `gdrive setup` first")
    return str(b)


def os_arch():
    osn = OS_NAMES.get(sys.platform)
    arch = ARCH_NAMES.get(platform.machine().lower())
    if not osn or not arch:
        raise UsageError(f"no rclone build known for {sys.platform}/{platform.machine()}")
    return osn, arch


def installed_version():
    b = binary()
    if not b.exists():
        return None
    try:
        out = subprocess.run([str(b), "version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    first = out.splitlines()[0] if out else ""
    return first.split()[-1] if first.startswith("rclone ") else None


def latest_version():
    text = http.get_text(f"{BASE}/version.txt").strip()  # "rclone v1.75.1"
    ver = text.split()[-1]
    if not ver.startswith("v"):
        raise CliError(f"unexpected {BASE}/version.txt content: {text[:80]!r}")
    return ver


def install(version):
    """Download the official build for this OS/arch, verify SHA256, unpack into bin/. -> path."""
    osn, arch = os_arch()
    name = f"rclone-{version}-{osn}-{arch}.zip"
    sums = http.get_text(f"{BASE}/{version}/SHA256SUMS")
    want = next((ln.split()[0] for ln in sums.splitlines() if ln.strip().endswith("  " + name)), None)
    if not want:
        raise CliError(f"{name} is not listed in {BASE}/{version}/SHA256SUMS")
    with tempfile.TemporaryDirectory(prefix="gdrive-setup-") as tmp:
        z = Path(tmp) / name
        http.download(f"{BASE}/{version}/{name}", z)
        got = hashlib.sha256(z.read_bytes()).hexdigest()
        if got != want:
            raise CliError(f"checksum mismatch for {name}: got {got}, want {want} - nothing installed")
        with zipfile.ZipFile(z) as zf:
            member = next((m for m in zf.namelist() if m.rsplit("/", 1)[-1] == exe_name()), None)
            if not member:
                raise CliError(f"{name} holds no {exe_name()}")
            dest = binary()
            tmp_bin = dest.with_name(dest.name + ".new")
            with zf.open(member) as src, open(tmp_bin, "wb") as out:
                shutil.copyfileobj(src, out)
    os.chmod(tmp_bin, 0o755)
    os.replace(tmp_bin, dest)  # atomic: a running mount keeps its old inode
    return dest


def run(args, timeout=120, check=True):
    """rclone <args> --config <ours> -> CompletedProcess (text). Failure -> CliError with stderr tail."""
    argv = [require(), *args, "--config", str(conf())]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise CliError(f"rclone {args[0]} did not finish within {timeout} s") from None
    if check and p.returncode != 0:
        tail = [ln for ln in p.stderr.splitlines() if ln.strip()][-6:]
        raise CliError(f"rclone {args[0]} failed (exit {p.returncode})",
                       payload=[{"rclone": ln} for ln in tail])
    return p


def rc(state, method, params=None):
    """Call a running mount's remote control. -> dict, or None when it does not answer."""
    if not state.get("rc_addr"):
        return None
    try:
        return http.request("POST", f"http://{state['rc_addr']}/{method}", body=params or {},
                            basic=(state["rc_user"], state["rc_pass"]), allow_mutate=True,
                            timeout=5, retries=0)
    except CliError:
        return None
