"""Tests for root-confined, symlink-resistant atomic audio storage."""

from __future__ import annotations

import os
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from custom_components.openrouter_tts import storage as storage_module
from custom_components.openrouter_tts.exceptions import (
    FileAlreadyExistsError,
    StorageError,
    UnsafePathError,
)
from custom_components.openrouter_tts.storage import (
    SecureFileStore,
    normalize_filename,
    validate_storage_root,
    validate_subdirectory,
)


def _store(tmp_path: Path) -> tuple[SecureFileStore, Path, Path]:
    config_dir = tmp_path / "config"
    config_dir.mkdir(mode=0o755)
    root = config_dir / "www" / "audio" / "tts"
    return SecureFileStore(str(root), str(config_dir)), config_dir, root


@pytest.mark.parametrize(
    "root_factory",
    [
        lambda config: config,
        lambda config: config.parent / "outside",
        lambda config: Path("relative/root"),
        lambda config: config / "www" / ".." / "escape",
    ],
)
def test_storage_root_must_be_absolute_descendant_but_not_config_itself(
    tmp_path: Path,
    root_factory: Callable[[Path], Path],
) -> None:
    config = tmp_path / "config"
    root = root_factory(config)
    with pytest.raises(UnsafePathError):
        validate_storage_root(str(root), str(config))


def test_storage_errors_do_not_chain_private_paths_or_filenames(tmp_path: Path) -> None:
    root_marker = "private-root-" + "sentinel"
    filename_marker = "private-file-" + "sentinel.wav"
    config = tmp_path / "config"

    with pytest.raises(UnsafePathError) as invalid_root:
        validate_storage_root(str(tmp_path / root_marker), str(config))
    root_traceback = "".join(traceback.format_exception(invalid_root.value))
    assert root_marker not in root_traceback
    assert str(config) not in root_traceback

    config.mkdir(mode=0o755)
    store = SecureFileStore(str(config / "audio"), str(config))
    store.save(
        filename=filename_marker,
        subdirectory=None,
        data=b"audio",
        actual_extension="wav",
    )
    with pytest.raises(FileAlreadyExistsError) as existing:
        store.save(
            filename=filename_marker,
            subdirectory=None,
            data=b"replacement",
            actual_extension="wav",
        )
    existing_traceback = "".join(traceback.format_exception(existing.value))
    assert filename_marker not in existing_traceback


@pytest.mark.parametrize(
    "filename",
    [
        "/tmp/announcement.wav",
        "../announcement.wav",
        "folder/announcement.wav",
        "folder\\announcement.wav",
        "announcement.txt",
        ".hidden.wav",
        "announcement.wav\x00suffix",
    ],
)
def test_absolute_traversing_or_abnormal_filename_is_rejected(filename: str) -> None:
    with pytest.raises(UnsafePathError):
        normalize_filename(filename)


@pytest.mark.parametrize(
    "subdirectory",
    [
        "/absolute",
        "../escape",
        "safe/../../escape",
        "safe/../escape",
        "safe\\escape",
        "safe/\x00escape",
        ".hidden",
    ],
)
def test_absolute_traversing_or_abnormal_subdirectory_is_rejected(
    subdirectory: str,
) -> None:
    with pytest.raises(UnsafePathError):
        validate_subdirectory(subdirectory)


def test_save_is_root_confined_and_url_encodes_every_segment(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)

    saved = store.save(
        filename="안내 음원.wav",
        subdirectory="공용 방송",
        data=b"audio bytes",
        actual_extension="wav",
    )

    target = root / "공용 방송" / "안내 음원.wav"
    assert target.read_bytes() == b"audio bytes"
    assert Path(saved.absolute_path) == target
    assert saved.relative_path == "공용 방송/안내 음원.wav"
    assert saved.url == (
        "/local/audio/tts/"
        "%EA%B3%B5%EC%9A%A9%20%EB%B0%A9%EC%86%A1/"
        "%EC%95%88%EB%82%B4%20%EC%9D%8C%EC%9B%90.wav"
    )
    assert saved.size == len(b"audio bytes")


def test_actual_audio_extension_replaces_requested_suffix(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)

    saved = store.save(
        filename="announcement.mp3",
        subdirectory=None,
        data=b"wav bytes",
        actual_extension="wav",
    )

    assert saved.relative_path == "announcement.wav"
    assert (root / "announcement.wav").read_bytes() == b"wav bytes"
    assert not (root / "announcement.mp3").exists()


def test_existing_file_is_not_overwritten_by_default(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    first = b"original audio"
    store.save(
        filename="announcement.wav",
        subdirectory=None,
        data=first,
        actual_extension="wav",
    )

    with pytest.raises(FileAlreadyExistsError):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"replacement audio",
            actual_extension="wav",
        )

    assert (root / "announcement.wav").read_bytes() == first
    assert list(root.glob(".openrouter-tts-*.tmp")) == []


def test_explicit_overwrite_atomically_replaces_regular_file(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    store.save(
        filename="announcement.wav",
        subdirectory=None,
        data=b"original",
        actual_extension="wav",
    )

    store.save(
        filename="announcement.wav",
        subdirectory=None,
        data=b"replacement",
        actual_extension="wav",
        overwrite=True,
    )

    assert (root / "announcement.wav").read_bytes() == b"replacement"
    assert list(root.glob(".openrouter-tts-*.tmp")) == []


def test_private_staging_is_owner_only_and_empty_after_publish(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)

    store.save(
        filename="announcement.wav",
        subdirectory=None,
        data=b"audio",
        actual_extension="wav",
    )

    staging = root / ".openrouter-tts-staging"
    assert staging.stat().st_mode & 0o777 == 0o700
    assert list(staging.iterdir()) == []
    assert (root / "announcement.wav").stat().st_mode & 0o777 == 0o600


def test_concurrent_no_overwrite_saves_publish_one_complete_file(
    tmp_path: Path,
) -> None:
    store, _config, root = _store(tmp_path)

    def save(data: bytes) -> object:
        try:
            return store.save(
                filename="announcement.wav",
                subdirectory=None,
                data=data,
                actual_extension="wav",
            )
        except FileAlreadyExistsError as err:
            return err

    candidates = (b"first complete audio", b"second complete audio")
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(save, candidates))

    assert sum(isinstance(item, FileAlreadyExistsError) for item in outcomes) == 1
    assert (root / "announcement.wav").read_bytes() in candidates
    assert list((root / ".openrouter-tts-staging").iterdir()) == []


def test_partial_write_failure_leaves_no_final_or_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _config, root = _store(tmp_path)

    def fail_after_partial_write(fd: int, data: bytes) -> None:
        os.write(fd, data[:3])
        raise OSError("simulated short storage failure")

    monkeypatch.setattr(storage_module, "_write_all", fail_after_partial_write)

    with pytest.raises(StorageError):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"complete audio",
            actual_extension="wav",
        )

    assert not (root / "announcement.wav").exists()
    assert list(root.glob(".openrouter-tts-*.tmp")) == []


def test_failed_overwrite_preserves_existing_file_and_cleans_partial_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, _config, root = _store(tmp_path)
    store.save(
        filename="announcement.wav",
        subdirectory=None,
        data=b"original",
        actual_extension="wav",
    )

    def fail_after_partial_write(fd: int, data: bytes) -> None:
        os.write(fd, data[:2])
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(storage_module, "_write_all", fail_after_partial_write)

    with pytest.raises(StorageError):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"replacement",
            actual_extension="wav",
            overwrite=True,
        )

    assert (root / "announcement.wav").read_bytes() == b"original"
    assert list(root.glob(".openrouter-tts-*.tmp")) == []


def test_symlinked_storage_root_cannot_escape_config_directory(tmp_path: Path) -> None:
    store, config, root = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.parent.mkdir(parents=True)
    root.symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        store.save(
            filename="escape.wav",
            subdirectory=None,
            data=b"audio",
            actual_extension="wav",
        )

    assert not (outside / "escape.wav").exists()
    assert config.exists()


def test_world_writable_storage_ancestor_is_rejected_without_fd_leak(
    tmp_path: Path,
) -> None:
    store, config, root = _store(tmp_path)
    root.mkdir(parents=True)
    config.chmod(0o777)
    fd_directory = Path("/proc/self/fd")
    before = len(tuple(fd_directory.iterdir()))

    for _ in range(25):
        with pytest.raises(UnsafePathError):
            store.save(
                filename="announcement.wav",
                subdirectory=None,
                data=b"audio",
                actual_extension="wav",
            )

    after = len(tuple(fd_directory.iterdir()))
    assert after == before
    assert not (root / "announcement.wav").exists()


def test_storage_root_move_during_write_is_detected_before_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store, config, root = _store(tmp_path)
    root.mkdir(parents=True)
    for directory in (config, config / "www", config / "www" / "audio", root):
        directory.chmod(0o755)
    outside = tmp_path / "outside"
    outside.mkdir()
    moved_root = outside / "moved-root"
    original_write_all = storage_module._write_all

    def move_then_write(fd: int, data: bytes) -> None:
        root.rename(moved_root)
        original_write_all(fd, data)

    monkeypatch.setattr(storage_module, "_write_all", move_then_write)

    with pytest.raises(UnsafePathError):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"private audio",
            actual_extension="wav",
        )

    assert not (moved_root / "announcement.wav").exists()
    assert list((moved_root / ".openrouter-tts-staging").iterdir()) == []


def test_symlinked_child_directory_cannot_escape_storage_root(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True)
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        store.save(
            filename="escape.wav",
            subdirectory="escape",
            data=b"audio",
            actual_extension="wav",
        )

    assert not (outside / "escape.wav").exists()


def test_symlinked_private_staging_directory_is_rejected(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    root.mkdir(parents=True)
    (root / ".openrouter-tts-staging").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"audio",
            actual_extension="wav",
        )

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("overwrite", [False, True])
def test_symlinked_destination_is_never_followed(
    tmp_path: Path,
    overwrite: bool,
) -> None:
    store, config, root = _store(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside audio")
    root.mkdir(parents=True)
    for directory in (config, config / "www", config / "www" / "audio", root):
        directory.chmod(0o755)
    (root / "announcement.wav").symlink_to(outside)

    expected_error = UnsafePathError if overwrite else FileAlreadyExistsError
    with pytest.raises(expected_error):
        store.save(
            filename="announcement.wav",
            subdirectory=None,
            data=b"replacement",
            actual_extension="wav",
            overwrite=overwrite,
        )

    assert outside.read_bytes() == b"outside audio"
    assert (root / "announcement.wav").is_symlink()
    assert list(root.glob(".openrouter-tts-*.tmp")) == []


def test_delete_removes_only_requested_regular_audio_file(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    store.save(
        filename="announcement.wav",
        subdirectory="shared",
        data=b"audio",
        actual_extension="wav",
    )

    deleted = store.delete(filename="announcement.wav", subdirectory="shared")

    assert deleted.relative_path == "shared/announcement.wav"
    assert deleted.size == len(b"audio")
    assert deleted.url == "/local/audio/tts/shared/announcement.wav"
    assert not (root / "shared" / "announcement.wav").exists()


def test_delete_rejects_symlinked_file_and_preserves_target(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"outside audio")
    root.mkdir(parents=True)
    (root / "announcement.wav").symlink_to(outside)

    with pytest.raises(UnsafePathError):
        store.delete(filename="announcement.wav", subdirectory=None)

    assert outside.read_bytes() == b"outside audio"
    assert (root / "announcement.wav").is_symlink()


def test_delete_cannot_traverse_symlinked_child_directory(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "announcement.wav").write_bytes(b"outside audio")
    root.mkdir(parents=True)
    (root / "escape").symlink_to(outside, target_is_directory=True)

    with pytest.raises(UnsafePathError):
        store.delete(filename="announcement.wav", subdirectory="escape")

    assert (outside / "announcement.wav").read_bytes() == b"outside audio"


def test_delete_does_not_create_or_traverse_missing_child_directory(
    tmp_path: Path,
) -> None:
    store, _config, root = _store(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.delete(filename="announcement.wav", subdirectory="missing")

    assert not (root / "missing").exists()


def test_delete_does_not_create_missing_storage_root(tmp_path: Path) -> None:
    store, _config, root = _store(tmp_path)

    with pytest.raises(FileNotFoundError):
        store.delete(filename="announcement.wav", subdirectory=None)

    assert not root.exists()
