'''Filesystem related types'''
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum
from io import SEEK_END
from os import major, minor
from pathlib import Path, PurePosixPath
from stat import S_ISBLK, S_ISCHR, S_ISDIR, S_ISFIFO, S_ISLNK, S_ISREG
from typing import IO

from confbundler.types.user import Group, User


@dataclass(init=False, kw_only=True)
class Entry:
    '''Base class representing a present filesystem entry'''
    owner: User = User('root', 0)
    group: Group = Group('root', 0)
    mode: int = 0o644
    atime: tuple[int, int] = (0, 0)
    mtime: tuple[int, int] = (0, 0)
    xattrs: dict[str, str]

    def __init__(self, *,
                 owner: User | None = None,
                 group: Group | None = None,
                 mode: int | None = None,
                 atime: tuple[int, int] | None = None,
                 mtime: tuple[int, int] | None = None,
                 xattrs: dict[str, str] | None = None):
        if owner is not None:
            self.owner = owner
        if group is not None:
            self.group = group
        if mode is not None:
            self.mode = mode
        if atime is not None:
            self.atime = atime
        if mtime is not None:
            self.mtime = mtime
        self.xattrs = xattrs if xattrs is not None else {}


@dataclass(init=False)
class BundledEntry(Entry):
    '''Class encapsulating a file present on the host'''
    source: Path

    def __init__(self, source: Path, **kwargs):
        super().__init__(**kwargs)
        self.source = source
        self._file: IO[bytes] | None = None

    def __enter__(self) -> Entry:
        '''Resolve the bundled entry into a proper filesystem object'''
        stat_info = self.source.lstat()
        metadata = {k: v for k, v in self.__dict__.items()
                    if k in [f.name for f in fields(Entry)]}

        if 'atime' not in metadata:
            metadata['atime'] = (
                stat_info.st_atime_ns // 10**9,
                stat_info.st_atime_ns % 10**9
            )
        if 'mtime' not in metadata:
            metadata['mtime'] = (
                stat_info.st_mtime_ns // 10**9,
                stat_info.st_mtime_ns % 10**9
            )

        if S_ISREG(stat_info.st_mode):
            if not self._file or self._file.closed:
                self._file = self.source.open('rb')
            return File(self._file,
                        stat_info.st_size,
                        **metadata)
        if S_ISBLK(stat_info.st_mode):
            return Device(Device.Kind.BLOCK,
                          major(stat_info.st_rdev),
                          minor(stat_info.st_rdev),
                          **metadata)
        if S_ISCHR(stat_info.st_mode):
            return Device(Device.Kind.CHARACTER,
                          major(stat_info.st_rdev),
                          minor(stat_info.st_rdev),
                          **metadata)
        if S_ISDIR(stat_info.st_mode):
            return Directory(**metadata)
        if S_ISFIFO(stat_info.st_mode):
            return Pipe(**metadata)
        if S_ISLNK(stat_info.st_mode):
            return SymbolicLink(PurePosixPath(self.source.readlink()), **metadata)
        raise TypeError(f'{self.source}: Unsupported file type')

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            self._file.close()


@dataclass(init=False)
class RemoteEntry(Entry):
    '''Class representing an entry stored on the target machine or retrieved from a backup'''
    source: PurePosixPath | None = None

    def __init__(self, source: PurePosixPath | None = None, **kwargs):
        super().__init__(**kwargs)
        if source is not None:
            self.source = source


@dataclass(init=False)
class Device(Entry):
    '''Class representing a device node'''
    class Kind(Enum):
        '''Device entry type enumerator'''
        BLOCK = 'b'
        CHARACTER = 'c'

    kind: Kind
    devmajor: int
    devminor: int

    def __init__(self, kind: Kind, devmajor: int, devminor: int, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.devmajor = devmajor
        self.devminor = devminor


@dataclass(init=False)
class Directory(Entry):
    '''Class representing a directory'''
    mode: int = 0o755


@dataclass(init=False)
class Pipe(Entry):
    '''Class representing a named pipe'''


@dataclass(init=False)
class File(Entry):
    '''Class representing a regular file'''
    content: IO[bytes]
    length: int = 0

    def __init__(self, content: IO[bytes],
                 length: int | None = None,
                 no_auto_length: bool = False,
                 **kwargs):
        super().__init__(**kwargs)
        self.content = content
        if length is not None:
            self.length = length
        elif not no_auto_length and self.content.seekable():
            pos = self.content.tell()
            self.length = self.content.seek(0, SEEK_END)
            self.content.seek(pos)


@dataclass(init=False)
class SymbolicLink(Entry):
    '''Class representing a symbolic link'''
    destination: PurePosixPath

    def __init__(self, destination: PurePosixPath, **kwargs):
        super().__init__(**kwargs)
        self.destination = destination
