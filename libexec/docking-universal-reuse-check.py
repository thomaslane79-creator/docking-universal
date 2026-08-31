#!/usr/bin/env python3
"""Compare two executions of the same reusable protocol."""

import argparse
import json

from docking_universal_reuse import compare_reuse_studies


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first")
    parser.add_argument("second")
    args = parser.parse_args()
    print(json.dumps(compare_reuse_studies(args.first, args.second), indent=2))


if __name__ == "__main__":
    main()
