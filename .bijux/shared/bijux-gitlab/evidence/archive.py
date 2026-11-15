"""Admit bounded native artifact archives before writing any owned output."""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_MEMBERS = 100000


def require(condition, message):
    if not condition:
        raise ValueError(message)


def archive_members(data: bytes, *, reserve=None) -> dict:
    require(isinstance(data, bytes) and 0 < len(data) <= MAX_ARCHIVE_BYTES, 'Native archive byte count is unbounded')
    files, modes, names, directories, total = {}, {}, set(), set(), 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            require(0 < len(entries) <= MAX_MEMBERS, 'Native archive member count is unbounded')
            for info in entries:
                require('\x00' not in info.orig_filename, 'Native artifact member contains an embedded null')
                name = info.filename[:-1] if info.is_dir() else info.filename
                require(name and len(name) <= 4096 and '\\' not in name and ':' not in name
                        and not any(ord(character) < 32 or ord(character) == 127 for character in name)
                        and not PurePosixPath(name).is_absolute()
                        and all(part not in ('', '.', '..') and len(part) <= 255 for part in name.split('/'))
                        and len(name.split('/')) <= 128, 'Unsafe native artifact member path')
                require(name not in names, 'Duplicate native artifact member')
                names.add(name)
                mode = info.external_attr >> 16
                kind = stat.S_IFMT(mode)
                require(kind in ((0, stat.S_IFDIR) if info.is_dir() else (0, stat.S_IFREG)), 'Native artifact links and special members are refused')
                require(not info.flag_bits & 1 and info.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED), 'Unsupported native artifact compression or encryption')
                require(0 <= info.file_size <= MAX_MEMBER_BYTES, 'Native artifact member is oversized')
                if info.is_dir():
                    require(info.file_size == 0, 'Native archive directory has a body')
                    directories.add(name)
                    continue
                total += info.file_size
                require(total <= MAX_EXPANDED_BYTES, 'Native artifact expansion exceeds byte limit')
                if reserve is not None:
                    reserve(info.file_size)
                body = archive.read(info)
                require(len(body) == info.file_size, 'Native archive member size changed')
                files[name] = body
                modes[name] = 0o755 if mode & 0o111 else 0o644
                directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != '.')
            require(bool(files), 'Native artifact has no physical files')
            for name in names:
                require(not any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent) != '.'),
                        'Native artifact file/directory ownership collides')
            require(not set(files) & directories, 'Native artifact file/directory ownership collides')
    except (zipfile.BadZipFile, EOFError, RuntimeError, NotImplementedError, OSError):
        raise ValueError('Native artifact archive body is corrupt or unsupported') from None
    hashes = {name: hashlib.sha256(body).hexdigest() for name, body in sorted(files.items())}
    return {'files': files, 'modes': modes, 'directories': sorted(directories), 'files_sha256': hashes, 'archive_sha256': hashlib.sha256(data).hexdigest(),
            'archive_bytes': len(data), 'expanded_bytes': total,
            'members_sha256': hashlib.sha256(json.dumps(hashes, sort_keys=True, separators=(',', ':')).encode()).hexdigest()}


def extract(data: bytes, destination: Path) -> dict:
    members = archive_members(data)
    destination = Path(destination).absolute()
    require(not any(path.is_symlink() for path in (destination, *destination.parents)), 'Native artifact destination traverses links')
    require(not destination.exists(), 'Preserve existing native artifact destination')
    parent = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for component in destination.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent); parent = child
        os.mkdir(destination.name, mode=0o700, dir_fd=parent)
        root = os.open(destination.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    finally:
        os.close(parent)
    try:
        for name in sorted(members['directories'], key=lambda value: (len(value.split('/')), value)):
            directory = os.dup(root)
            try:
                for component in name.split('/'):
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory); directory = child
            finally:
                os.close(directory)
        for name, body in sorted(members['files'].items()):
            directory = os.dup(root)
            try:
                for component in name.split('/')[:-1]:
                    try:
                        os.mkdir(component, mode=0o700, dir_fd=directory)
                    except FileExistsError:
                        pass
                    child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                    os.close(directory); directory = child
                descriptor = os.open(name.split('/')[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                     members['modes'][name], dir_fd=directory)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(body)
            finally:
                os.close(directory)
    finally:
        os.close(root)
    return {key: value for key, value in members.items() if key not in ('files', 'modes')}
