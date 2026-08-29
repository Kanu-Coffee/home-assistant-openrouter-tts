"""Symlink-resistant, atomic storage for generated audio."""

from __future__ import annotations

import errno
import os
import secrets
import stat
import threading
import unicodedata
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from .exceptions import FileAlreadyExistsError, StorageError, UnsafePathError

_ALLOWED_EXTENSIONS = frozenset({".mp3", ".wav"})
_OPEN_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_STAGING_DIRECTORY = ".openrouter-tts-staging"


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Non-sensitive metadata about a stored audio file."""

    absolute_path: str
    relative_path: str
    url: str | None
    size: int


def validate_storage_root(root: str, config_dir: str) -> Path:
    """Require an absolute lexical descendant of the HA configuration directory."""
    if "\x00" in root or "\x00" in config_dir:
        raise UnsafePathError("Storage paths may not contain null bytes")
    root_path = Path(root)
    config_path = Path(config_dir)
    if not root_path.is_absolute() or not config_path.is_absolute():
        raise UnsafePathError("The storage root must be an absolute path")
    if ".." in root_path.parts or ".." in config_path.parts:
        raise UnsafePathError("Storage paths may not contain parent traversal")
    normalized_root = Path(os.path.normpath(root_path))
    normalized_config = Path(os.path.normpath(config_path))
    try:
        normalized_root.relative_to(normalized_config)
    except ValueError:
        raise UnsafePathError(
            "The storage root must remain inside the Home Assistant config directory"
        ) from None
    if normalized_root == normalized_config:
        raise UnsafePathError(
            "The Home Assistant config directory cannot be a storage root"
        )
    return normalized_root


def _validate_component(component: str, *, description: str) -> str:
    normalized = unicodedata.normalize("NFC", component)
    if (
        not normalized
        or normalized in {".", ".."}
        or "\x00" in normalized
        or "/" in normalized
        or "\\" in normalized
        or ":" in normalized
        or normalized.startswith(".")
        or normalized.endswith((".", " "))
        or any(ord(character) < 32 or ord(character) == 127 for character in normalized)
        or len(os.fsencode(normalized)) > 240
    ):
        raise UnsafePathError(f"The {description} contains an unsafe path component")
    return normalized


def validate_subdirectory(subdirectory: str | None) -> tuple[str, ...]:
    """Validate a portable POSIX relative subdirectory."""
    if not subdirectory:
        return ()
    if "\x00" in subdirectory or "\\" in subdirectory:
        raise UnsafePathError("The subdirectory contains an unsafe separator")
    path = PurePosixPath(subdirectory)
    if path.is_absolute() or not path.parts:
        raise UnsafePathError("The subdirectory must be relative")
    return tuple(
        _validate_component(part, description="subdirectory") for part in path.parts
    )


def normalize_filename(filename: str, actual_extension: str | None = None) -> str:
    """Validate one filename and align its suffix to validated response audio."""
    name = _validate_component(filename, description="filename")
    path = PurePosixPath(name)
    if path.name != name:
        raise UnsafePathError("The filename must not contain a directory")
    suffix = path.suffix.casefold()
    if suffix and suffix not in _ALLOWED_EXTENSIONS:
        raise UnsafePathError("Only .mp3 and .wav audio extensions are allowed")
    if actual_extension is None:
        if suffix not in _ALLOWED_EXTENSIONS:
            raise UnsafePathError("An .mp3 or .wav extension is required")
        return name

    normalized_extension = f".{actual_extension.casefold().lstrip('.')}"
    if normalized_extension not in _ALLOWED_EXTENSIONS:
        raise UnsafePathError("The generated audio extension is unsupported")
    stem = name[: -len(suffix)] if suffix else name
    if not stem:
        raise UnsafePathError("The filename needs a non-empty stem")
    return f"{stem}{normalized_extension}"


def _assert_trusted_directory(
    fd: int,
    *,
    allow_sticky: bool,
    trusted_owners: frozenset[int] | None,
) -> None:
    """Reject directories that another OS identity can rename or replace."""
    directory_stat = os.fstat(fd)
    mode = directory_stat.st_mode
    writable_by_others = stat.S_IMODE(mode) & 0o022
    sticky_directory = bool(mode & stat.S_ISVTX)
    if (
        not stat.S_ISDIR(mode)
        or (trusted_owners is not None and directory_stat.st_uid not in trusted_owners)
        or (writable_by_others and not (allow_sticky and sticky_directory))
    ):
        raise UnsafePathError(
            "The storage path has unsafe ownership or write permissions"
        )


def _open_trusted_directory(
    path: str,
    *,
    dir_fd: int | None = None,
    allow_sticky: bool,
    trusted_owners: frozenset[int] | None,
) -> int:
    """Open and validate a directory, closing the new fd on validation failure."""
    fd = os.open(path, _OPEN_DIRECTORY_FLAGS, dir_fd=dir_fd)
    try:
        _assert_trusted_directory(
            fd,
            allow_sticky=allow_sticky,
            trusted_owners=trusted_owners,
        )
    except Exception:
        os.close(fd)
        raise
    return fd


def _open_absolute_directory(path: Path) -> int:
    """Open an administrator-selected absolute path without following links."""
    current_fd = _open_trusted_directory("/", allow_sticky=True, trusted_owners=None)
    try:
        for part in path.parts[1:]:
            next_fd = _open_trusted_directory(
                part,
                dir_fd=current_fd,
                allow_sticky=True,
                trusted_owners=None,
            )
            os.close(current_fd)
            current_fd = next_fd
    except Exception:
        os.close(current_fd)
        raise
    else:
        return current_fd


def _open_or_create_child_directories(
    root_fd: int,
    parts: tuple[str, ...],
    trusted_owners: frozenset[int],
) -> int:
    current_fd = os.dup(root_fd)
    try:
        _assert_trusted_directory(
            current_fd,
            allow_sticky=False,
            trusted_owners=trusted_owners,
        )
        for part in parts:
            try:
                next_fd = _open_trusted_directory(
                    part,
                    dir_fd=current_fd,
                    allow_sticky=False,
                    trusted_owners=trusted_owners,
                )
            except FileNotFoundError:
                os.mkdir(part, mode=0o755, dir_fd=current_fd)
                next_fd = _open_trusted_directory(
                    part,
                    dir_fd=current_fd,
                    allow_sticky=False,
                    trusted_owners=trusted_owners,
                )
            os.close(current_fd)
            current_fd = next_fd
    except Exception:
        os.close(current_fd)
        raise
    else:
        return current_fd


def _open_child_directories(
    root_fd: int,
    parts: tuple[str, ...],
    trusted_owners: frozenset[int],
) -> int:
    """Open existing child directories without following links or creating paths."""
    current_fd = os.dup(root_fd)
    try:
        _assert_trusted_directory(
            current_fd,
            allow_sticky=False,
            trusted_owners=trusted_owners,
        )
        for part in parts:
            next_fd = _open_trusted_directory(
                part,
                dir_fd=current_fd,
                allow_sticky=False,
                trusted_owners=trusted_owners,
            )
            os.close(current_fd)
            current_fd = next_fd
    except Exception:
        os.close(current_fd)
        raise
    else:
        return current_fd


def _assert_same_directory(fd: int, expected_fd: int) -> None:
    """Confirm two pinned descriptors identify the same directory."""
    pinned_stat = os.fstat(fd)
    expected_stat = os.fstat(expected_fd)
    if (pinned_stat.st_dev, pinned_stat.st_ino) != (
        expected_stat.st_dev,
        expected_stat.st_ino,
    ):
        raise UnsafePathError(
            "The storage directory moved while the operation was running"
        )


def _assert_absolute_directory_identity(fd: int, expected_path: Path) -> None:
    """Confirm an administrator-selected anchor remains at its absolute path."""
    try:
        expected_fd = _open_absolute_directory(expected_path)
    except OSError:
        raise UnsafePathError(
            "The storage directory moved while the operation was running"
        ) from None
    try:
        _assert_trusted_directory(
            expected_fd,
            allow_sticky=False,
            trusted_owners=None,
        )
        _assert_same_directory(fd, expected_fd)
    finally:
        os.close(expected_fd)


def _assert_relative_directory_identity(
    fd: int,
    config_fd: int,
    parts: tuple[str, ...],
    trusted_owners: frozenset[int],
) -> None:
    """Confirm a pinned storage directory remains below the config anchor."""
    try:
        expected_fd = _open_child_directories(config_fd, parts, trusted_owners)
    except OSError:
        raise UnsafePathError(
            "The storage directory moved while the operation was running"
        ) from None
    try:
        _assert_same_directory(fd, expected_fd)
    finally:
        os.close(expected_fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("Unable to complete the audio file write")
        view = view[written:]


def _open_private_staging_directory(parent_fd: int) -> int:
    """Open a storage-owned directory that other OS users cannot race."""
    with suppress(FileExistsError):
        os.mkdir(_STAGING_DIRECTORY, mode=0o700, dir_fd=parent_fd)
    staging_fd = os.open(_STAGING_DIRECTORY, _OPEN_DIRECTORY_FLAGS, dir_fd=parent_fd)
    staging_stat = os.fstat(staging_fd)
    if (
        not stat.S_ISDIR(staging_stat.st_mode)
        or staging_stat.st_uid != os.geteuid()
        or stat.S_IMODE(staging_stat.st_mode) & 0o077
    ):
        os.close(staging_fd)
        raise UnsafePathError(
            "The private audio staging directory has unsafe ownership or permissions"
        )
    return staging_fd


class SecureFileStore:
    """Store and remove audio below a fixed root using directory file descriptors."""

    def __init__(self, root: str, config_dir: str) -> None:
        self.root = validate_storage_root(root, config_dir)
        self.config_dir = Path(os.path.normpath(config_dir))
        self._root_parts = self.root.relative_to(self.config_dir).parts
        self._lock = threading.Lock()

    def _url_for(self, parts: tuple[str, ...], filename: str) -> str | None:
        www_root = self.config_dir / "www"
        try:
            root_under_www = self.root.relative_to(www_root)
        except ValueError:
            return None
        url_parts = (*root_under_www.parts, *parts, filename)
        return "/local/" + "/".join(quote(part, safe="") for part in url_parts)

    def save(
        self,
        *,
        filename: str,
        subdirectory: str | None,
        data: bytes,
        actual_extension: str,
        overwrite: bool = False,
    ) -> StoredFile:
        """Write all bytes to a temporary inode and atomically publish it."""
        with self._lock:
            return self._save(
                filename=filename,
                subdirectory=subdirectory,
                data=data,
                actual_extension=actual_extension,
                overwrite=overwrite,
            )

    def _save(
        self,
        *,
        filename: str,
        subdirectory: str | None,
        data: bytes,
        actual_extension: str,
        overwrite: bool,
    ) -> StoredFile:
        """Implement save while the per-root operation lock is held."""
        parts = validate_subdirectory(subdirectory)
        final_name = normalize_filename(filename, actual_extension)
        config_fd: int | None = None
        root_fd: int | None = None
        parent_fd: int | None = None
        staging_fd: int | None = None
        temp_name: str | None = None
        temp_fd: int | None = None
        try:
            # The Home Assistant config directory is an administrator-selected trust
            # anchor. Its numeric owner may legitimately differ from the container's
            # EUID on a bind mount, so that owner is trusted only below this pinned fd.
            config_fd = _open_absolute_directory(self.config_dir)
            _assert_trusted_directory(
                config_fd,
                allow_sticky=False,
                trusted_owners=None,
            )
            trusted_owners = frozenset({0, os.geteuid(), os.fstat(config_fd).st_uid})
            root_fd = _open_or_create_child_directories(
                config_fd,
                self._root_parts,
                trusted_owners,
            )
            parent_fd = _open_or_create_child_directories(
                root_fd,
                parts,
                trusted_owners,
            )
            staging_fd = _open_private_staging_directory(parent_fd)
            temp_name = f".openrouter-tts-{secrets.token_hex(12)}.tmp"
            temp_fd = os.open(
                temp_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o600,
                dir_fd=staging_fd,
            )
            _write_all(temp_fd, data)
            os.fsync(temp_fd)
            # Home Assistant itself serves /local files; other local OS users
            # do not need direct read access to generated speech.
            os.fchmod(temp_fd, 0o600)
            _assert_absolute_directory_identity(config_fd, self.config_dir)
            _assert_relative_directory_identity(
                root_fd,
                config_fd,
                self._root_parts,
                trusted_owners,
            )
            _assert_relative_directory_identity(
                parent_fd,
                config_fd,
                (*self._root_parts, *parts),
                trusted_owners,
            )
            if overwrite:
                try:
                    target_stat = os.stat(
                        final_name, dir_fd=parent_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    pass
                else:
                    if not stat.S_ISREG(target_stat.st_mode):
                        raise UnsafePathError(
                            "Overwrite is allowed only for an existing regular file"
                        )
                os.replace(
                    temp_name,
                    final_name,
                    src_dir_fd=staging_fd,
                    dst_dir_fd=parent_fd,
                )
                temp_name = None
            else:
                try:
                    os.link(
                        temp_name,
                        final_name,
                        src_dir_fd=staging_fd,
                        dst_dir_fd=parent_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    raise FileAlreadyExistsError(
                        "The destination exists; enable overwrite to replace it"
                    ) from None
                os.unlink(temp_name, dir_fd=staging_fd)
                temp_name = None
            os.fsync(staging_fd)
            os.fsync(parent_fd)
        except OSError as err:
            if err.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UnsafePathError(
                    "A symbolic link was found in the storage path"
                ) from None
            raise StorageError("The audio file could not be stored safely") from None
        finally:
            if temp_fd is not None:
                os.close(temp_fd)
            if temp_name is not None and staging_fd is not None:
                with suppress(FileNotFoundError):
                    os.unlink(temp_name, dir_fd=staging_fd)
            if staging_fd is not None:
                os.close(staging_fd)
            if parent_fd is not None:
                os.close(parent_fd)
            if root_fd is not None:
                os.close(root_fd)
            if config_fd is not None:
                os.close(config_fd)

        relative = PurePosixPath(*parts, final_name).as_posix()
        return StoredFile(
            absolute_path=str(self.root.joinpath(*parts, final_name)),
            relative_path=relative,
            url=self._url_for(parts, final_name),
            size=len(data),
        )

    def delete(self, *, filename: str, subdirectory: str | None) -> StoredFile:
        """Delete only a regular .mp3/.wav file through safe directory handles."""
        with self._lock:
            return self._delete(filename=filename, subdirectory=subdirectory)

    def _delete(self, *, filename: str, subdirectory: str | None) -> StoredFile:
        """Implement deletion while the per-root operation lock is held."""
        parts = validate_subdirectory(subdirectory)
        final_name = normalize_filename(filename)
        config_fd: int | None = None
        root_fd: int | None = None
        parent_fd: int | None = None
        try:
            config_fd = _open_absolute_directory(self.config_dir)
            _assert_trusted_directory(
                config_fd,
                allow_sticky=False,
                trusted_owners=None,
            )
            trusted_owners = frozenset({0, os.geteuid(), os.fstat(config_fd).st_uid})
            root_fd = _open_child_directories(
                config_fd,
                self._root_parts,
                trusted_owners,
            )
            parent_fd = _open_child_directories(root_fd, parts, trusted_owners)
            _assert_absolute_directory_identity(config_fd, self.config_dir)
            _assert_relative_directory_identity(
                root_fd,
                config_fd,
                self._root_parts,
                trusted_owners,
            )
            _assert_relative_directory_identity(
                parent_fd,
                config_fd,
                (*self._root_parts, *parts),
                trusted_owners,
            )
            target_stat = os.stat(final_name, dir_fd=parent_fd, follow_symlinks=False)
            if not stat.S_ISREG(target_stat.st_mode):
                raise UnsafePathError("Only a regular audio file can be deleted")
            _assert_absolute_directory_identity(config_fd, self.config_dir)
            _assert_relative_directory_identity(
                root_fd,
                config_fd,
                self._root_parts,
                trusted_owners,
            )
            _assert_relative_directory_identity(
                parent_fd,
                config_fd,
                (*self._root_parts, *parts),
                trusted_owners,
            )
            os.unlink(final_name, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except OSError as err:
            if isinstance(err, FileNotFoundError):
                raise
            if err.errno in {errno.ELOOP, errno.ENOTDIR}:
                raise UnsafePathError(
                    "A symbolic link was found in the storage path"
                ) from None
            raise StorageError("The audio file could not be deleted safely") from None
        finally:
            if parent_fd is not None:
                os.close(parent_fd)
            if root_fd is not None:
                os.close(root_fd)
            if config_fd is not None:
                os.close(config_fd)
        relative = PurePosixPath(*parts, final_name).as_posix()
        return StoredFile(
            absolute_path=str(self.root.joinpath(*parts, final_name)),
            relative_path=relative,
            url=self._url_for(parts, final_name),
            size=target_stat.st_size,
        )
