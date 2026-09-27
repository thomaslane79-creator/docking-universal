#!/usr/bin/env python3
import argparse
from docking_universal.p2rank_adapter import materialize_p2rank_candidates

parser = argparse.ArgumentParser()
parser.add_argument("--predictions", required=True)
parser.add_argument("--receptor", required=True)
parser.add_argument("--cavity", required=True)
parser.add_argument("--target", required=True)
parser.add_argument("--maximum-pockets", type=int, default=3)
parser.add_argument("--p2rank-version")
args = parser.parse_args()
materialize_p2rank_candidates(args.predictions, args.receptor, args.cavity, args.target,
                              maximum_pockets=args.maximum_pockets,
                              p2rank_version=args.p2rank_version)
