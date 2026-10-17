"""Single GUI boundary for versioned application-host commands."""

from __future__ import annotations

from typing import Callable


class ApplicationHostController:
    """Route typed GUI intentions to the sole scientific-state writer."""

    def __init__(self, study_id: str, client_getter: Callable[[], object | None]):
        self.study_id = study_id
        self._client_getter = client_getter

    @property
    def available(self) -> bool:
        client = self._client_getter()
        return bool(client is not None and getattr(client, "connected", True))

    def _request(self, operation, payload, revision=None):
        client = self._client_getter()
        if client is None:
            raise RuntimeError("The application host is not connected")
        if revision is None:
            return client.request(self.study_id, operation, payload)
        return client.request(
            self.study_id, operation, payload, expected_revision=revision,
        )

    def resolve_decision(self, decision_id, selections, rationale, revision):
        return self._request("resolve_decision", {
            "decision_id": decision_id, "selections": list(selections),
            "actor": "desktop-user", "rationale": rationale or None,
        }, revision)

    def resolve_pockets(self, decision_id, selections, rationale, revision):
        return self.resolve_decision(decision_id, selections, rationale, revision)

    def start_preparation(self, payload, revision):
        return self._request("start_receptor_preparation", payload, revision)

    def inspect_protocol_bundle(self, source):
        return self._request("inspect_protocol_bundle", {"protocol_bundle": str(source)})["result"]["protocol"]

    def import_protocol_bundle(self, source, reviewed_sha256, revision):
        return self._request("import_protocol_bundle", {
            "protocol_bundle": str(source), "reviewed_sha256": reviewed_sha256,
        }, revision)

    def start_control_validation(self, payload, revision):
        return self._request("start_control_validation", payload, revision)

    def cancel_active_job(self, revision, job_id=None):
        return self._request("cancel_active_job", {"job_id": job_id} if job_id else {}, revision)

    def start_finalization(self, payload, revision):
        return self._request("start_protocol_finalization", payload, revision)

    def inspect_ligand_library(self, ligand_source, column_mapping=None, sheet=None):
        payload = {"ligand_source": ligand_source}
        if column_mapping is not None:
            payload['column_mapping'] = column_mapping
        if sheet is not None:
            payload['sheet'] = sheet
        return self._request("inspect_ligand_library", payload)["result"]["library"]

    def ligand_record_preview(self, ligand_source, fingerprint, record_id, column_mapping=None):
        payload = {
            "ligand_source": ligand_source, "fingerprint": fingerprint, "record_id": record_id,
        }
        if column_mapping is not None:
            payload['column_mapping'] = column_mapping
        return self._request("ligand_record_preview", payload)["result"]["preview"]

    def screening_plan(self, ligand_source, ligand_selection=None):
        payload = {"ligand_source": ligand_source}
        if ligand_selection is not None:
            payload["ligand_selection"] = ligand_selection
        response = self._request("screening_plan", payload)
        return response["result"]["plan"]

    def start_screening(self, payload, revision):
        return self._request("start_screening", payload, revision)

    def start_pose_interaction(self, analysis_root, pose_id, revision):
        return self._request("start_pose_interaction", {
            "analysis_root": str(analysis_root), "pose_id": int(pose_id),
        }, revision)
