"""Fail-closed guard for an explicitly required Frigate media mount."""

import logging
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

REQUIREMENT_FILE = Path("/config/required_storage_source")
MEDIA_PATH = Path("/media/frigate")
CHECK_INTERVAL = 5


class StopEvent(Protocol):
    def wait(self, timeout: float) -> bool: ...


@dataclass(frozen=True)
class Mount:
    fs_type: str
    source: str
    writable: bool


def mount_from_info(mount_id: str, info: str) -> Mount:
    """Resolve the actual mount ID, not the longest mount-point prefix."""
    for line in info.splitlines():
        left, separator, right = line.partition(" - ")
        fields = left.split()
        if not separator or len(fields) < 6 or fields[0] != mount_id:
            continue
        fs = right.split()
        if len(fs) >= 3:
            return Mount(
                fs[0],
                fs[1],
                "rw" in fields[5].split(",") and "rw" in fs[2].split(","),
            )
    raise OSError("Mount ID not present in mountinfo")


def mount_for_fd(fd: int) -> Mount:
    """Identify the filesystem behind an already opened descriptor."""
    info = Path(f"/proc/self/fdinfo/{fd}").read_text()
    for line in info.splitlines():
        if line.startswith("mnt_id:"):
            return mount_from_info(
                line.split(":", 1)[1].strip(),
                Path("/proc/self/mountinfo").read_text(),
            )
    raise OSError("Missing mount ID in fdinfo")


def read_requirement(path: Path = REQUIREMENT_FILE) -> str | None:
    """Read an opt-in NFS source; an invalid requirement must not disable it."""
    try:
        source = path.read_text().strip()
    except FileNotFoundError:
        return None
    if not source or not source.partition(":/")[0] or ":/" not in source:
        raise ValueError("Required storage source must be an NFS server:/path")
    if any(char.isspace() for char in source):
        raise ValueError("Required storage source must not contain whitespace")
    return source


def check_storage(
    source: str, path: Path = MEDIA_PATH, *, test_write: bool = False
) -> tuple[bool, str]:
    """Check the actual mount and optionally write through the verified descriptor."""
    flags = os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    # The startup check must trigger automount; the runtime check need not.
    flags |= os.O_RDONLY if test_write else os.O_PATH
    try:
        fd = os.open(path, flags)
        try:
            mount = mount_for_fd(fd)
            if mount.fs_type not in {"nfs", "nfs4"}:
                return False, f"unexpected filesystem {mount.fs_type}"
            if mount.source != source:
                return False, "unexpected NFS source"
            if not mount.writable:
                return False, "read-only NFS mount"
            if test_write:
                name = f".frigate-storage-probe-{uuid.uuid4().hex}"
                probe = os.open(
                    name,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                    0o600,
                    dir_fd=fd,
                )
                try:
                    os.write(probe, b"frigate\n")
                    os.fsync(probe)
                finally:
                    os.close(probe)
                    os.unlink(name, dir_fd=fd)
            return True, "ready"
        finally:
            os.close(fd)
    except OSError as exc:
        return False, f"storage check failed: {exc}"


def wait_for_storage(source: str, stop_event: StopEvent) -> bool:
    """Do not start Frigate's media writers before the required NFS is writable."""
    previous = None
    while True:
        ready, reason = check_storage(source, test_write=True)
        if ready:
            logger.info("Required NFS storage is ready")
            return True
        if reason != previous:
            logger.error("Waiting for required NFS storage: %s", reason)
            previous = reason
        if stop_event.wait(CHECK_INTERVAL):
            return False


def watch_storage(
    source: str, stop_event: StopEvent, shutdown: Callable[[], None]
) -> None:
    """Request a container shutdown if the expected media mount is lost."""
    while True:
        ready, reason = check_storage(source)
        if not ready:
            logger.critical("Required NFS storage lost: %s; stopping Frigate", reason)
            shutdown()
            return
        if stop_event.wait(CHECK_INTERVAL):
            return
