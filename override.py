from __future__ import annotations

import os
import tarfile
from collections.abc import Iterable
from inspect import Parameter, signature
from itertools import islice
from pathlib import Path, PurePosixPath
from stat import S_ISBLK, S_ISCHR, S_ISDIR, S_ISFIFO, S_ISLNK, S_ISREG
from typing import BinaryIO, Optional, Type, Union

import yaml


class OverrideLoader(yaml.SafeLoader):
    """
    An extended YAML loader providing safe and automatic deserialization
    of properties specific to override manifests.
    """

class OverrideFile:
    """A class representing file entries of override bundles."""
    __slots__ = {
        'path': 'Destination path of the file',
        'mode': 'UNIX permissions of the file',
        'uid': 'UNIX file owner ID',
        'user': 'UNIX file owner',
        'gid': 'UNIX file owner group ID',
        'group': 'UNIX file owner group name'
    }

    def __init__(self, path: os.PathLike,
                 mode: Optional[int] = None,
                 uid: Optional[int] = None, user: Optional[str] = None,
                 gid: Optional[int] = None, group: Optional[str] = None):
        self.path = PurePosixPath(path)
        self.mode = mode
        self.uid = uid
        self.user = user
        self.gid = gid
        self.group = group

    def __repr__(self) -> str:
        parameters = signature(type(self).__init__).parameters.values()
        parameter_strings = []

        # populate parameter_strings with strings in the format of "[key=]value"
        for i in islice(parameters, 1, None): # skip self
            value = getattr(self, i.name)
            if value is None:
                continue

            # TODO: tbh idk if that's a right thing to do
            if i.kind != Parameter.POSITIONAL_ONLY \
                    and i.default != Parameter.empty:
                parameter_strings.append(f'{i.name}={repr(value)}')
            else:
                parameter_strings.append(repr(value))

        return f'{type(self).__name__}({", ".join(parameter_strings)})'

    # TODO: annotate this
    @classmethod
    def from_yaml(cls: Type[OverrideFile], loader,
                  node: Union[yaml.ScalarNode, yaml.MappingNode]) -> OverrideFile:
        """
        Converts a representation node to a Python object.

        Takes a ScalarNode or a MappingNode and constructs an OverrideFile,
        taking the value of the ScalarNode or the name of the MappingNode as the path,
        and passing the keys of the MappingNode to the constructor.
        """
        if isinstance(node, yaml.ScalarNode):
            return cls(loader.construct_scalar(node))
        if isinstance(node, yaml.MappingNode):
            for key, val in loader.construct_mapping(node, deep=True).items():
                return cls(key, **val)
            raise ValueError('The node contains no data')
        raise TypeError('Unsupported node type')

OverrideLoader.add_constructor('!File', OverrideFile.from_yaml)
OverrideLoader.add_path_resolver('!File', ('files', None), dict)
OverrideLoader.add_path_resolver('!File', ('files', None), str)

class OverrideBundle:
    """A declarative specification of changes to system configuration."""
    __slots__ = {
        'files': 'Files included in the bundle',
        'packages': 'Packages required by the bundle',
        'root': 'Bundle root directory'
    }

    def __init__(self):
        self.files: list[OverrideFile] = []
        self.packages: set[str] = set()
        self.root = Path()

    @classmethod
    def from_dir(cls: Type[OverrideBundle], path: os.PathLike) -> OverrideBundle:
        """
        Creates an OverrideBundle from the manifest.yaml file in the given directory.
        """
        path = Path(path)

        with (path / 'manifest.yaml').open() as file:
            loader = OverrideLoader(file)

            # TODO: use a generator instead
            parsed = loader.get_single_data()
            loader.dispose()

        bundle = cls()
        bundle.files = parsed['files']
        bundle.packages.update(parsed['packages'])
        bundle.root = path
        return bundle

def compile_bundles(bundles: Iterable[OverrideBundle], output: BinaryIO) -> None:
    with tarfile.open(fileobj=output, mode='w', format=tarfile.GNU_FORMAT) as tar:
        # TODO: deduplicate and sort the files
        for bundle in bundles:
            for file in bundle.files:
                fs_path = bundle.root / \
                          (file.path if not file.path.is_absolute() else file.path.relative_to('/'))
                fs_stat = None
                tar_info = tarfile.TarInfo(str(file.path))

                try:
                    fs_stat = fs_path.lstat()
                    tar_info.size = fs_stat.st_size
                    tar_info.mtime = fs_stat.st_mtime

                    if S_ISREG(fs_stat.st_mode):
                        tar_info.type = tarfile.REGTYPE
                    elif S_ISDIR(fs_stat.st_mode):
                        tar_info.type = tarfile.DIRTYPE
                    elif S_ISFIFO(fs_stat.st_mode):
                        tar_info.type = tarfile.FIFOTYPE
                    elif S_ISLNK(fs_stat.st_mode):
                        tar_info.type = tarfile.SYMTYPE
                    elif S_ISCHR(fs_stat.st_mode):
                        tar_info.type = tarfile.CHRTYPE
                    elif S_ISBLK(fs_stat.st_mode):
                        tar_info.type = tarfile.BLKTYPE
                except OSError as exception:
                    # TODO: use logging instead
                    # TODO: support fully inline definitions
                    print(exception)

                tar_info.mode = file.mode or \
                    (0o755 if tar_info.type == tarfile.DIRTYPE else 0o644)
                tar_info.uid = file.uid or 0
                tar_info.gid = file.gid or 0
                tar_info.uname = file.user or 'root'
                tar_info.gname = file.group or 'root'

                if fs_stat and tar_info.type == tarfile.REGTYPE:
                    with fs_path.open('rb') as fobj:
                        tar.addfile(tar_info, fobj)
                else:
                    tar.addfile(tar_info)
