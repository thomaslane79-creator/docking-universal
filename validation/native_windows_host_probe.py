"""Installed host-only native probe, with no structures or scientific searches."""
import argparse
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scientific", action="store_true")
    args = parser.parse_args()
    sys.path.insert(0, str(args.app))
    from docking_universal.gui.host_client import ApplicationHostClient, ApplicationHostError
    from docking_universal.host import ApplicationHostLease
    from docking_universal.state import JsonStudyStore
    root = args.out / "Studies Ω 日本語"
    client = ApplicationHostClient(root, args.app / "docking-universal-application-host.py")
    try:
        client.start()
        if client.runtime["scientific_stages_supported"] != args.scientific:
            raise ValueError("Native host scientific capabilities do not match the installed scope")
        response = client.request("native-probe", "create_study", {"name": "Protein Ω 日本語"})
        if response["result"]["study"]["name"] != "Protein Ω 日本語":
            raise ValueError("Unicode host response failed to round trip")
        store = JsonStudyStore(root)
        prior = store.path_for("native-probe").read_bytes()
        try:
            client.request("native-probe", "start_control_validation" if args.scientific else "start_receptor_preparation", {}, expected_revision=response["revision"])
        except ApplicationHostError as exc:
            if not any(text in str(exc) for text in ("not configured", "not accepted")):
                raise
        else:
            raise ValueError("Unported native preparation was unexpectedly accepted")
        if store.path_for("native-probe").read_bytes() != prior:
            raise ValueError("Rejected native preparation mutated study state")
        first = client.session_id
        client.restart()
        if client.session_id == first or client.request("native-probe", "snapshot")["status"] != "applied":
            raise ValueError("Installed host restart failed")
        reader = client._reader
        client.close()
        if reader.is_alive():
            raise ValueError("Host reader survived close")
        with ApplicationHostLease(root):
            pass  # Child is gone and no longer owns the state directory.
        print(json.dumps({"unicode_round_trip": True, "rejected_stage_state_unchanged": True,
                          "restart_passed": True, "reader_stopped_and_lease_released": True}))
    finally:
        client.close()


if __name__ == "__main__":
    main()
