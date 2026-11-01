#!/usr/bin/env python3
"""Execute one explicitly reviewed strict-connectivity preparation stage."""
import argparse
from docking_universal.services.reviewed_connectivity import execute_record

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', required=True)
    parser.add_argument('--record-sha256', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    execute_record(args.record, args.record_sha256, args.out)
