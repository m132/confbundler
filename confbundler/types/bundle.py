from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, fields
from itertools import chain
from pathlib import PurePosixPath
from typing import Any, TypeVar

from confbundler.types import AbsentResource
from confbundler.types.filesystem import BundledEntry, Entry
from confbundler.types.package import Package
from confbundler.types.user import User

T = TypeVar('T')


def uniq(iterable: Iterable[T], key: Callable[[T], Any]):
    '''Group objects by key and yield the first object from each group'''
    iterator = iter(iterable)
    last: T = next(iterator)
    yield last

    for i in iterator:
        if key(i) != key(last):
            last = i
            yield i


def _resolve_globs(globs: dict[str, BundledEntry]):
    for glob, entry in globs.items():
        metadata = {k: v for k, v in entry.__dict__.items()
                    if k in [f.name for f in fields(Entry)]}

        for path in entry.source.glob(glob.lstrip('/')):
            yield PurePosixPath('/') / PurePosixPath(path.relative_to(entry.source)), \
                BundledEntry(path, **metadata)


@dataclass
class Bundle:
    '''Declarative specification of changes made to system configuration'''
    files: dict[PurePosixPath, Entry | AbsentResource] = field(default_factory=dict)
    bundled_globs: dict[str, BundledEntry] = field(default_factory=dict)
    remote_globs: dict[str, Entry] = field(default_factory=dict)
    packages: dict[str, Package | AbsentResource] = field(default_factory=dict)
    users: dict[str, User | AbsentResource] = field(default_factory=dict)

    def iter_files(self):
        '''Iterate over flattened and resolved files'''
        iterator = chain(self.files.items(), _resolve_globs(self.bundled_globs))
        iterator = sorted(iterator, key=lambda x: x[0])
        iterator = uniq(iterator, key=lambda x: x[0])

        for path, file in iterator:
            if isinstance(file, BundledEntry):
                with file as resolved:
                    yield path, resolved
            else:
                yield path, file

    def __add__(self, other: 'Bundle') -> 'Bundle':
        self.files.update(other.files)
        self.bundled_globs.update(other.bundled_globs)
        self.remote_globs.update(other.remote_globs)
        self.packages.update(other.packages)
        self.users.update(other.users)
        return self
