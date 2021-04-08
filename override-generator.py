#!/usr/bin/env python3
from argparse import ArgumentParser, FileType

from override import OverrideBundle, compile_bundles


def main() -> None:
    parser = ArgumentParser('override-generator')
    parser.add_argument('bundles', nargs='+',
        help='paths to bundles to compile', metavar='BUNDLE')
    parser.add_argument('output', type=FileType(mode='wb'),
        help='output file', metavar='OUTPUT')

    args = parser.parse_args()
    compile_bundles(map(OverrideBundle.from_dir, args.bundles), args.output)

if __name__ == '__main__':
    main()
