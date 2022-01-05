#!/usr/bin/env python3
from argparse import ArgumentParser
from pathlib import Path

from override_generator.adapters.tar import write_out
from override_generator.adapters.yaml import load
from override_generator.types.bundle import Bundle

parser = ArgumentParser('override-generator')
parser.add_argument('-f', '--force', action='store_true',
                    help='overwrite the output file if it already exists')
parser.add_argument('bundles', nargs='+', type=Path,
                    help='paths to bundles to compile', metavar='BUNDLE')
parser.add_argument('output', type=Path,
                    help='output file', metavar='OUTPUT')

args = parser.parse_args()
try:
    output = args.output.open('wb' if args.force else 'xb')
except OSError as exception:
    parser.error(str(exception))

try:
    bundle = Bundle()
    for path in args.bundles:
        bundle += load(path / 'manifest.yaml')
    write_out(bundle.iter_files(), output)
finally:
    output.close()
