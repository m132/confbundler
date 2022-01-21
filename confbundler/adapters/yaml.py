from collections.abc import Mapping
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import IO, Any, Callable, NamedTuple, Sequence, Type, TypeVar
from warnings import warn

from yaml import MappingNode, SafeLoader, ScalarNode, SequenceNode
from yaml.constructor import ConstructorError
from yaml.error import Mark
from yaml.nodes import Node

from confbundler.types import AbsentResource
from confbundler.types.bundle import Bundle
from confbundler.types.filesystem import (BundledEntry, Device,
                                                 Directory, Entry, File, Pipe,
                                                 RemoteEntry, SymbolicLink)
from confbundler.types.package import Package
from confbundler.types.user import Group, User

T = TypeVar('T')


class ConstructorWarning(ConstructorError, Warning):
    @classmethod
    def from_error(cls, error: ConstructorError):
        self = cls.__new__(cls)
        self.__dict__ = error.__dict__
        return self


class FileOmittedWarning(ConstructorWarning):
    pass


class ExpectedProperty(NamedTuple):
    name: str
    constructor: Callable
    required: bool | Callable[['Loader', Any], Any]


class SerializedTypeSpecification(NamedTuple):
    default: Type
    states: Mapping[str, Type]
    properties: Sequence[tuple[Type, Sequence[ExpectedProperty]]]


def _bundled_source_fallback(self, path):
    if isinstance(path, PurePosixPath):
        return self.root / path.relative_to('/')
    return self.root


def _parse_time(*args, **kwargs):
    raise NotImplementedError()


files_spec = SerializedTypeSpecification(
    default=BundledEntry,
    states={
        'from-host': BundledEntry,
        'from-target': RemoteEntry,
        'file': File,
        'directory': Directory,
        'character-device': Device,
        'block-device': Device,
        'symbolic-link': SymbolicLink,
        'pipe': Pipe,
        'absent': AbsentResource
    },
    properties=(
        (BundledEntry, (
            ExpectedProperty('source', Path, _bundled_source_fallback),
        )),
        (RemoteEntry, (
            ExpectedProperty('source', PurePosixPath, lambda _, index: index),
        )),
        (File, (
            ExpectedProperty('content', BytesIO, True),
        )),
        (Device, (
            ExpectedProperty('kind', Device.Kind, True),
            ExpectedProperty('minor', int, True),
            ExpectedProperty('major', int, True),
        )),
        (Entry, (
            ExpectedProperty('owner', User, False),
            ExpectedProperty('group', Group, False),
            ExpectedProperty('mode', int, False),
            ExpectedProperty('atime', _parse_time, False),
            ExpectedProperty('mtime', _parse_time, False),
            ExpectedProperty('xattrs', dict, False),
        )),
    )
)

packages_spec = SerializedTypeSpecification(
    default=Package,
    states={
        'installed': Package,
        'absent': AbsentResource
    },
    properties=(
        (Package, (
            ExpectedProperty('name', str, lambda _, index: index),
        )),
    )
)


users_spec = SerializedTypeSpecification(
    default=User,
    states={
        'present': User,
        'absent': AbsentResource
    },
    properties=(
        (User, (
            ExpectedProperty('name', str, lambda _, index: index),
        )),
    )
)


def _unpack_node(node: ScalarNode | MappingNode | Any) -> \
        tuple[ScalarNode, MappingNode | None]:
    if isinstance(node, ScalarNode):
        return (node, None)
    elif isinstance(node, MappingNode):
        for key, val in node.value:
            # TODO: possibly redundant
            if not isinstance(key, ScalarNode):
                raise ConstructorError(
                    problem='expected a scalar',
                    problem_mark=key.start_mark
                )
            if not isinstance(val, MappingNode):
                raise ConstructorError(
                    problem='expected a mapping',
                    problem_mark=val.start_mark
                )
            return (key, val)
        raise ConstructorError(
            problem='found an empty node',
            problem_mark=node.start_mark
        )
    else:
        raise ConstructorError(
            problem=f'expected a scalar or a mapping, but found {node.id}',
            problem_mark=node.start_mark
        )


def _parse_path_node(node: ScalarNode):
    '''
    Parse a path node and return a str (in the case of a glob pattern) or
    a PurePosixPath (in the case of a literal path)
    '''
    if not isinstance(node.value, str):
        raise ConstructorError(
            problem='expected a string',
            problem_mark=node.start_mark
        )

    if any(i in node.value for i in '*?[]'):
        if not node.value.startswith('/'):
            warn(ConstructorWarning(
                problem=f'path {node.value} is not absolute',
                problem_mark=node.start_mark
            ))
            return f'/{node.value}'
        return node.value

    path = PurePosixPath(node.value)
    if not path.is_absolute():
        warn(ConstructorWarning(
            problem=f'path {path} is not absolute',
            problem_mark=node.start_mark
        ))
    return PurePosixPath('/') / path


# TODO: slim it down, most of the logic here isn't specific to YAML
class Loader(SafeLoader):
    """
    Extended YAML loader providing safe and automatic deserialization
    of properties specific to override manifests.
    """
    root: Path  # XXX: is this forwards-compatible?

    def __init__(self, stream: IO, *args, root: Path, **kwargs):
        super().__init__(stream, *args, **kwargs)
        self.root = root

    def _construct(self,
                   spec: SerializedTypeSpecification,
                   node: MappingNode | None,
                   index: Any | None = None,
                   fallback_error_mark: Mark | None = None):
        entry_type = spec.default
        prop_nodes: dict[str, Node] = {}
        props: dict[str, Any] = {}

        if node is not None:
            # index the properties
            for prop, prop_val in node.value:
                # TODO: the check below is possibly redundant
                if isinstance(prop, ScalarNode):
                    prop_nodes[prop.value] = prop_val
                else:
                    # FIXME: warn about malformed ones
                    pass

            if 'state' in prop_nodes:
                state = prop_nodes.pop('state')

                if not isinstance(state, ScalarNode) or not isinstance(state.value, str):
                    raise ConstructorError(
                        problem='expected a string',
                        problem_mark=state.start_mark
                    )

                try:
                    entry_type = spec.states[state.value]
                except KeyError as error:
                    raise ConstructorError(
                        problem=f"unsupported state `{state.value}'",
                        problem_mark=state.start_mark
                    ) from error

        for _type, expected_props in spec.properties:
            if issubclass(entry_type, _type):
                for prop in expected_props:
                    try:
                        value = prop_nodes.pop(prop.name)
                        constructed = self.construct_object(value, deep=True)
                    except KeyError as error:
                        if prop.required is True:
                            raise ConstructorError(
                                problem=f"required property `{prop.name}' not found",
                                problem_mark=fallback_error_mark
                            ) from error
                        if prop.required:
                            constructed = prop.required(self, index)
                        else:
                            continue

                    # XXX: typing minefield
                    if isinstance(constructed, Mapping):
                        props[prop.name] = prop.constructor(**constructed)
                    elif isinstance(constructed, list):
                        props[prop.name] = prop.constructor(*constructed)
                    else:
                        props[prop.name] = prop.constructor(constructed)

        for prop, prop_node in prop_nodes.items():
            warn(ConstructorWarning(
                problem=f'unrecognized property {prop}',
                problem_mark=prop_node.start_mark
            ))

        # XXX: typing minefield
        return entry_type(**props)

    def construct_file(self, node: ScalarNode | MappingNode | Any) -> \
            tuple[str | PurePosixPath, Entry | AbsentResource]:
        path_node, entry_node = _unpack_node(node)
        path = _parse_path_node(path_node)

        return (path, self._construct(files_spec, entry_node, path, node.start_mark))

    def construct_package(self, node: ScalarNode | MappingNode | Any) -> \
            tuple[str, Package | AbsentResource]:
        name_node, entry_node = _unpack_node(node)
        name = name_node.value

        if not isinstance(name, str):
            raise ConstructorError(
                problem='expected a string',
                problem_mark=name_node.start_mark
            )

        return (name, self._construct(packages_spec, entry_node, name, node.start_mark))

    def construct_user(self, node: ScalarNode | MappingNode | Any) -> \
            tuple[str, User | AbsentResource]:
        name_node, entry_node = _unpack_node(node)
        name = name_node.value

        if not isinstance(name, str):
            raise ConstructorError(
                problem='expected a string',
                problem_mark=name_node.start_mark
            )

        return (name, self._construct(users_spec, entry_node, name, node.start_mark))

    def construct_bundle(self, node):
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                problem=f'expected a bundle node, but found {node.id}',
                problem_mark=node.start_mark
            )

        bundle = Bundle()

        for key, value in node.value:
            if not isinstance(key, ScalarNode):
                warn(ConstructorWarning(
                    problem=f'expected a scalar, found {key.id}, skipping',
                    problem_mark=key.start_mark
                ))
                continue

            if not isinstance(value, SequenceNode):
                warn(ConstructorWarning(
                    problem=f'expected a sequence, found {value.id}, skipping',
                    problem_mark=value.start_mark
                ))
                continue

            if key.value == 'files':
                for file in value.value:
                    try:
                        path, constructed = self.construct_file(file)
                    except ConstructorError as error:
                        warn(FileOmittedWarning.from_error(error))
                        continue

                    if isinstance(path, PurePosixPath):
                        bundle.files[path] = constructed
                    else:
                        if isinstance(constructed, RemoteEntry):
                            bundle.remote_globs[path] = constructed
                        elif isinstance(constructed, BundledEntry):
                            bundle.bundled_globs[path] = constructed
                        else:
                            warn(FileOmittedWarning(
                                problem='globbing with literal files is not supported yet',
                                problem_mark=file.start_mark
                            ))
            elif key.value == 'packages':
                for package in value.value:
                    try:
                        name, constructed = self.construct_package(package)
                    except ConstructorError as error:
                        warn(ConstructorWarning.from_error(error))
                        continue

                    bundle.packages[name] = constructed
            elif key.value == 'users':
                for user in value.value:
                    try:
                        name, constructed = self.construct_user(user)
                    except ConstructorError as error:
                        warn(ConstructorWarning.from_error(error))
                        continue

                    bundle.users[name] = constructed
            else:
                warn(ConstructorWarning(
                    problem=f"unrecognized key `{key.value}'",
                    problem_mark=key.start_mark
                ))

        return bundle


Loader.add_constructor('tag:yaml.org,2002:bundle', Loader.construct_bundle)
Loader.add_path_resolver('tag:yaml.org,2002:bundle', (), None)


def load(path: Path) -> Bundle:
    with path.open('r') as file:
        loader = Loader(file, root=path.parent)

        # parse all documents contained in the yaml file
        try:
            bundle = loader.get_data()
            while loader.check_data():
                bundle += loader.get_data()
        finally:
            loader.dispose()

    return bundle
