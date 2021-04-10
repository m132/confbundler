#!/usr/bin/env python3
from argparse import ArgumentParser
from pathlib import Path

from override import OverrideBundle, compile_bundles


def main() -> None:
    parser = ArgumentParser('override-generator')
    parser.add_argument('-f', '--force', action='store_true',
        help='overwrite the output file if it already exists')
    parser.add_argument('bundles', nargs='+',
        help='paths to bundles to compile', metavar='BUNDLE')
    parser.add_argument('output', type=Path,
        help='output file', metavar='OUTPUT')

    args = parser.parse_args()
    try:
        output = args.output.open('wb' if args.force else 'xb')
    except OSError as exception:
        parser.error(str(exception))

    try:
        compile_bundles(map(OverrideBundle.from_dir, args.bundles), output)
    finally:
        output.close()

if __name__ == '__main__':
    main()
