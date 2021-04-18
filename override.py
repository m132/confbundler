from __future__ import annotations

import tarfile
from enum import Enum
from inspect import Parameter, signature
from itertools import islice
from pathlib import Path, PurePath, PurePosixPath
from typing import Any, BinaryIO, Dict, Optional, Tuple, Type, TypeVar, Union

import yaml

T = TypeVar('T')

class OverrideLoader(yaml.SafeLoader):
    """
    An extended YAML loader providing safe and automatic deserialization
    of properties specific to override manifests.
    """
    root: Path # XXX: is this forwards-compatible?

class OverrideEntity:
    """
    The base class providing a foundation and common operations for
    override bundle entities.
    """
    class State(Enum):
        PRESENT = 'present'
        ABSENT = 'absent'

    def __init__(self, state: State = State.PRESENT):
        self.state = state

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

    def __getstate__(self) -> Dict[str, Union[str, int]]:
        # first element of self.State is assumed to be the default value
        if self.state is not next(iter(self.State.__members__.values())):
            return {'state': self.state.value}
        return {}

    def __setstate__(self, state: dict) -> None:
        if 'state' in state:
            self.state = self.State(state['state'])
        else:
            self.state = next(iter(self.State.__members__.values()))

    @classmethod
    def from_yaml(cls: Type[T], loader,
                  node: Union[yaml.ScalarNode, yaml.MappingNode]) -> Tuple[Any, T]:
        instance = cls.__new__(cls)
        state = {}

        if isinstance(node, yaml.ScalarNode):
            name = loader.construct_scalar(node)
        elif isinstance(node, yaml.MappingNode):
            mapping = loader.construct_mapping(node, deep=True).items()
            if not mapping:
                raise ValueError('The node contains no data')

            name, state = next(iter(mapping))
        else:
            raise TypeError('Unsupported node type')

        instance.__setstate__(state)
        return (name, instance)

class OverridePackage(OverrideEntity):
    """A class representing package entries of override bundles."""
    __slots__ = {
        'state': 'State of the package'
    }

OverrideLoader.add_constructor('!Package', OverridePackage.from_yaml)
OverrideLoader.add_path_resolver('!Package', ('packages', None), dict)
OverrideLoader.add_path_resolver('!Package', ('packages', None), str)

class OverrideFile(OverrideEntity):
    """A class representing file entries of override bundles."""
    __slots__ = {
        'state': 'State of the file',
        'source': 'Source object',
        'mode': 'UNIX permissions of the file',
        'uid': 'UNIX file owner ID',
        'user': 'UNIX file owner',
        'gid': 'UNIX file owner group ID',
        'group': 'UNIX file owner group name'
    }

    Device = Tuple[int, int]

    class State(Enum):
        FROM_HOST = 'copy-from-host'
        FROM_TARGET = 'copy-from-target'

        INLINE_FILE = 'file' # TODO: unimplemented
        INLINE_SYMLINK = 'symbolic-link'
        INLINE_DIR = 'directory'
        INLINE_BLOCKDEV = 'block-device'
        INLINE_CHARDEV = 'character-device'

        ABSENT = 'absent'

    def __init__(self, state: State = State.FROM_HOST,
                 source: Optional[Union[PurePath, BinaryIO, Device]] = None):
        if state == self.State.FROM_HOST and not isinstance(source, Path):
            raise TypeError(f'{state.name} requries source to be an instance of Path')

        if state in (self.State.FROM_TARGET, self.State.INLINE_SYMLINK) \
                and not isinstance(source, PurePath):
            raise TypeError(f'{state.name} requries source to be an instance of PurePath')

        super().__init__(state)
        self.source = source
        self.mode: Optional[int] = None
        self.uid: Optional[int] = None
        self.user: Optional[str] = None
        self.gid: Optional[int] = None
        self.group: Optional[str] = None

    def __getstate__(self) -> dict:
        state: Dict[str, Union[str, int]] = super().__getstate__()

        if isinstance(self.source, PurePath):
            state['source'] = str(self.source)
        elif isinstance(self.source, tuple):
            state['source'] = "%i %i" % self.source

        for i in ('mode', 'uid', 'user', 'gid', 'group'):
            if getattr(self, i) is not None:
                state[i] = getattr(self, i)

        return state

    def __setstate__(self, state: dict) -> None:
        # TODO: fix the type annotations here
        if 'state' in state:
            _state = self.State(state['state'])
        else:
            _state = self.State.FROM_HOST
        source: Union[None, PurePath, tuple] = None

        if _state == self.State.FROM_HOST:
            source = Path(state['source'])
        elif _state in (self.State.FROM_TARGET, self.State.INLINE_SYMLINK):
            source = PurePath(state['source'])
        elif _state in (self.State.INLINE_CHARDEV, self.State.INLINE_BLOCKDEV):
            source = tuple(int(x) for x in state['source'].split())

        self.__init__(_state, source)

        for i in ('mode', 'uid', 'user', 'gid', 'group'):
            if i in state:
                setattr(self, i, state[i])

    # TODO: annotate this
    # XXX: minefield ahead!
    @classmethod
    def from_yaml(cls: Type[T], loader,
                  node: Union[yaml.ScalarNode, yaml.MappingNode]) -> Tuple[PurePosixPath, T]:
        instance = cls.__new__(cls)
        state = {}

        if isinstance(node, yaml.ScalarNode):
            path = PurePosixPath(loader.construct_scalar(node))
        elif isinstance(node, yaml.MappingNode):
            mapping = loader.construct_mapping(node, deep=True).items()
            if not mapping:
                raise ValueError('The node contains no data')

            path, state = next(iter(mapping))
            path = PurePosixPath(path)
        else:
            raise TypeError('Unsupported node type')

        path = path if not path.is_absolute() else path.relative_to('/')
        if 'source' not in state:
            state['source'] = str(loader.root / path)
        instance.__setstate__(state)

        return (path, instance)

OverrideLoader.add_constructor('!File', OverrideFile.from_yaml)
OverrideLoader.add_path_resolver('!File', ('files', None), dict)
OverrideLoader.add_path_resolver('!File', ('files', None), str)

class OverrideUser(OverrideEntity):
    """A class representing user entries of override bundles."""
    __slots__ = {
        'state': 'State of the user'
    }

OverrideLoader.add_constructor('!User', OverrideUser.from_yaml)
OverrideLoader.add_path_resolver('!User', ('users', None), dict)
OverrideLoader.add_path_resolver('!User', ('users', None), str)

class OverrideBundle:
    """A declarative specification of changes to system configuration."""
    __slots__ = {
        'files': 'Files included in the bundle',
        'packages': 'Packages required by the bundle',
        'users': 'Users created and removed by the bundle'
    }

    def __init__(self):
        self.files: Dict[PurePosixPath, OverrideFile] = {}
        self.packages: Dict[str, OverridePackage] = {}
        self.users: Dict[str, OverrideUser] = {}

    def update(self, other: Union[OverrideBundle, Path]) -> None:
        if isinstance(other, OverrideBundle):
            for i in self.__slots__:
                getattr(self, i).update(getattr(other, i))
        elif isinstance(other, Path):
            with (other / 'manifest.yaml').open() as file:
                loader = OverrideLoader(file)
                loader.root = other

                # parse all documents contained in the yaml file
                try:
                    while loader.check_data():
                        parsed = loader.get_data()
                        for i in self.__slots__:
                            getattr(self, i).update(parsed[i])
                finally:
                    loader.dispose()
        else:
            raise TypeError('other is neither an OverrideBundle nor a Path')

    def compile(self, output: BinaryIO) -> None:
        with tarfile.open(fileobj=output, mode='w', format=tarfile.GNU_FORMAT, dereference=False) as tar:
            for dest, file in self.files.items():
                if file.state == OverrideFile.State.FROM_HOST:
                    tar_info = tar.gettarinfo(str(file.source), str(dest))
                elif file.state in (OverrideFile.State.FROM_TARGET, OverrideFile.State.ABSENT):
                    raise NotImplementedError(f'OverrideFiles of {file.state.name} type are not supported by compile() yet')
                else:
                    tar_info = tarfile.TarInfo(str(dest))
                    tar_info.type = {
                        OverrideFile.State.INLINE_FILE: tarfile.REGTYPE,
                        OverrideFile.State.INLINE_SYMLINK: tarfile.SYMTYPE,
                        OverrideFile.State.INLINE_DIR: tarfile.DIRTYPE,
                        OverrideFile.State.INLINE_BLOCKDEV: tarfile.BLKTYPE,
                        OverrideFile.State.INLINE_CHARDEV: tarfile.CHRTYPE
                    }[file.state]

                    if tar_info.type == tarfile.SYMTYPE:
                        tar_info.linkname = str(file.source)
                    elif tar_info.type in (tarfile.BLKTYPE, tarfile.CHRTYPE):
                        tar_info.devmajor, tar_info.devminor = file.source

                tar_info.mode = file.mode or \
                    (0o755 if tar_info.type == tarfile.DIRTYPE else 0o644)
                tar_info.uid = file.uid or 0
                tar_info.gid = file.gid or 0
                tar_info.uname = file.user or 'root'
                tar_info.gname = file.group or 'root'

                if tar_info.type == tarfile.REGTYPE:
                    if file.state == OverrideFile.State.FROM_HOST:
                        with file.source.open('rb') as fobj:
                            tar.addfile(tar_info, fobj)
                    else:
                        tar.addfile(tar_info, file.source)
                else:
                    tar.addfile(tar_info)
