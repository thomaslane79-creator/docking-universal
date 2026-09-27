import unittest

from docking_universal.gui.application_host_controller import ApplicationHostController


class Client:
    def __init__(self):
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"result": {"plan": {"ready": True}}}

    connected = True


class ApplicationHostControllerTests(unittest.TestCase):
    def test_routes_revisioned_mutations_through_one_boundary(self):
        client = Client()
        controller = ApplicationHostController("study-1", lambda: client)
        controller.resolve_pockets("decision-1", ["P2"], "reviewed", 7)
        self.assertEqual(client.calls[0], (("study-1", "resolve_decision", {
            "decision_id": "decision-1", "selections": ["P2"],
            "actor": "desktop-user", "rationale": "reviewed",
        }), {"expected_revision": 7}))

    def test_plan_unwraps_result_and_disconnected_controller_fails(self):
        client = Client()
        controller = ApplicationHostController("study-1", lambda: client)
        self.assertEqual(controller.screening_plan("ligands.sdf"), {"ready": True})
        disconnected = ApplicationHostController("study-1", lambda: None)
        self.assertFalse(disconnected.available)
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            disconnected.cancel_active_job(1)

    def test_dead_client_is_not_reported_as_available(self):
        client = Client()
        client.connected = False
        controller = ApplicationHostController("study-1", lambda: client)
        self.assertFalse(controller.available)


if __name__ == "__main__":
    unittest.main()
