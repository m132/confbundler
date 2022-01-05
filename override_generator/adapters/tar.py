'''Tar format adapter'''
from pathlib import PurePosixPath
from tarfile import (BLKTYPE, CHRTYPE, DIRTYPE, FIFOTYPE, PAX_FORMAT, REGTYPE,
                     SYMTYPE, TarFile, TarInfo)
from typing import IO, Iterable, cast

from override_generator.types import AbsentResource
from override_generator.types.filesystem import (Device, Directory, Entry,
                                                 File, Pipe, SymbolicLink)


def write_out(files: Iterable[tuple[PurePosixPath, Entry | AbsentResource]], output: IO[bytes]):
    with TarFile.open(fileobj=output,
                      mode='w',
                      format=PAX_FORMAT,
                      dereference=False) as tar:
        for path, file in files:
            if isinstance(file, AbsentResource):
                # FIXME#1: use a callback or break this function into smaller ones
                print(f'skipping absent {path}...')
                continue

            content = None
            tar_info = TarInfo()

            if isinstance(file, Device) and file.kind == Device.Kind.BLOCK:
                tar_info.type = BLKTYPE
                tar_info.devmajor = file.devmajor
                tar_info.devminor = file.devminor
            elif isinstance(file, Device) and file.kind == Device.Kind.CHARACTER:
                tar_info.type = CHRTYPE
                tar_info.devmajor = file.devmajor
                tar_info.devminor = file.devminor
            elif isinstance(file, Directory):
                tar_info.type = DIRTYPE
            elif isinstance(file, File):
                tar_info.type = REGTYPE
                tar_info.size = file.length
                content = file.content
            elif isinstance(file, Pipe):
                tar_info.type = FIFOTYPE
            elif isinstance(file, SymbolicLink):
                tar_info.type = SYMTYPE
                tar_info.linkname = str(file.destination)
            else:
                # FIXME: use `warnings` instead
                print(f'{path}: Unsupported type {file.__class__.__name__}')
                continue

            tar_info.name = str(path)
            tar_info.mode = file.mode
            tar_info.uid = file.owner.id
            tar_info.gid = file.group.id
            tar_info.uname = file.owner.name
            tar_info.gname = file.group.name
            tar_info.mtime = file.mtime[0]

            pax_headers = cast(dict[str, str], tar_info.pax_headers)
            if 'atime' in file.__dict__:
                pax_headers['atime'] = f'{file.atime[0]}.{file.atime[1]}'
            if 'mtime' in file.__dict__:
                pax_headers['mtime'] = f'{file.mtime[0]}.{file.mtime[1]}'
            for key, val in file.xattrs.items():
                pax_headers[f'SCHILY.xattr.{key}'] = str(val)

            tar.addfile(tar_info, content)
            print(f'{path}') # FIXME: see #1
