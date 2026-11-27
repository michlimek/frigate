"""Tests for the required NFS storage guard."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from frigate.util.network_storage import (
    Mount,
    check_storage,
    mount_from_info,
    read_requirement,
    wait_for_storage,
    watch_storage,
)

MODULE = "frigate.util.network_storage"
SOURCE = "192.0.2.1:/mnt/pool/frigate"


class TestNetworkStorage(unittest.TestCase):
    def test_stacked_mounts_resolve_actual_id(self):
        info = (
            "10 1 0:1 / /media/frigate rw - autofs systemd-1 rw\n"
            f"11 10 0:2 / /media/frigate rw - nfs4 {SOURCE} rw\n"
        )
        self.assertEqual(mount_from_info("10", info).fs_type, "autofs")
        self.assertEqual(mount_from_info("11", info), Mount("nfs4", SOURCE, True))
        with self.assertRaises(OSError):
            mount_from_info("12", info)

    def test_read_only_superblock(self):
        info = f"11 10 0:2 / /media/frigate rw - nfs4 {SOURCE} ro\n"
        self.assertFalse(mount_from_info("11", info).writable)

    def test_missing_requirement_disables_guard_but_empty_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "required_storage_source"
            self.assertIsNone(read_requirement(marker))
            marker.write_text("\n")
            with self.assertRaises(ValueError):
                read_requirement(marker)
            marker.write_text(SOURCE + "\n")
            self.assertEqual(read_requirement(marker), SOURCE)

    def test_actual_local_filesystem_rejected_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            self.assertFalse(check_storage(SOURCE, path, test_write=True)[0])
            self.assertEqual(list(path.iterdir()), [])

    def test_wrong_source_and_read_only_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for mount in [
                Mount("nfs4", "other:/pool", True),
                Mount("nfs4", SOURCE, False),
            ]:
                with self.subTest(mount=mount), patch(
                    f"{MODULE}.mount_for_fd", return_value=mount
                ):
                    self.assertFalse(check_storage(SOURCE, path, test_write=True)[0])
                    self.assertEqual(list(path.iterdir()), [])

    def test_writable_verified_descriptor_is_probed_and_cleaned(self):
        with tempfile.TemporaryDirectory() as tmp, patch(
            f"{MODULE}.mount_for_fd", return_value=Mount("nfs4", SOURCE, True)
        ):
            path = Path(tmp)
            self.assertEqual(
                check_storage(SOURCE, path, test_write=True), (True, "ready")
            )
            self.assertEqual(list(path.iterdir()), [])
            with patch(f"{MODULE}.os.fsync", side_effect=PermissionError("denied")):
                self.assertFalse(check_storage(SOURCE, path, test_write=True)[0])
                self.assertEqual(list(path.iterdir()), [])

    def test_startup_waits_until_storage_returns(self):
        stop = Mock()
        stop.wait.return_value = False
        with patch(
            f"{MODULE}.check_storage",
            side_effect=[(False, "local"), (True, "ready")],
        ) as check:
            self.assertTrue(wait_for_storage(SOURCE, stop))
            self.assertEqual(check.call_count, 2)
        stop.wait.assert_called_once()

    def test_startup_can_be_stopped_while_waiting(self):
        stop = Mock()
        stop.wait.return_value = True
        with patch(f"{MODULE}.check_storage", return_value=(False, "local")):
            self.assertFalse(wait_for_storage(SOURCE, stop))

    def test_runtime_requests_shutdown_once_on_loss(self):
        stop = Mock()
        stop.wait.return_value = False
        shutdown = Mock()
        with patch(
            f"{MODULE}.check_storage",
            side_effect=[(True, "ready"), (False, "local")],
        ):
            watch_storage(SOURCE, stop, shutdown)
        shutdown.assert_called_once_with()

    def test_normal_shutdown_does_not_request_restart(self):
        stop = Mock()
        stop.wait.return_value = True
        shutdown = Mock()
        with patch(f"{MODULE}.check_storage", return_value=(True, "ready")):
            watch_storage(SOURCE, stop, shutdown)
        shutdown.assert_not_called()
