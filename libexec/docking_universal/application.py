"""Window-independent controller for resumable scientific workflows."""

from __future__ import annotations

from uuid import uuid4

from .automation import AutomationPolicy
from .decisions import ApprovalRecord, DecisionOption, DecisionRequired, DecisionStatus
from .events import EventType, ScientificDetail, WorkflowEvent
from .models import ArtifactRecord, CompletionStatus, Job, JobStatus, PocketCandidate, ScientificAuthority, record_to_dict, utc_now
from .state import JsonStudyStore, StudyState
from .workflow import record_stage_completion


class ActiveStageError(RuntimeError):
    pass


class ExplicitApprovalRequired(RuntimeError):
    pass


class StudyController:
    """Own state transitions; CLI and GUI clients only present them."""

    def __init__(self, store: JsonStudyStore):
        self.store = store

    def create_study(
        self,
        study_id: str,
        name: str,
        workflow: str = "site_guided_protocol",
        *,
        request_id: str | None = None,
    ) -> StudyState:
        workflow_data = {"creation_request_id": request_id} if request_id else {}
        return self.store.create(StudyState(
            study_id=study_id, name=name, workflow=workflow, workflow_data=workflow_data,
        ))

    def get_study(self, study_id: str) -> StudyState:
        return self.store.load(study_id)

    def event_view(self, study_id: str, detail: ScientificDetail) -> list[dict]:
        return [event.presented(detail) for event in self.get_study(study_id).events]

    def start_simulated_pocket_review(
        self,
        study_id: str,
        candidates: list[PocketCandidate],
        automation: AutomationPolicy | None = None,
    ) -> DecisionRequired:
        return self.start_pocket_review(study_id, candidates, automation=automation)

    def start_pocket_review(
        self,
        study_id: str,
        candidates: list[PocketCandidate],
        *,
        artifacts: tuple[ArtifactRecord, ...] = (),
        review_artifact_ids: tuple[str, ...] = (),
        source: dict | None = None,
        automation: AutomationPolicy | None = None,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> DecisionRequired:
        """Start a review from real or simulated candidate artifact records."""
        state = self.get_study(study_id)
        if request_id:
            prior = state.workflow_data.get("pocket_review_requests", {}).get(request_id)
            if prior:
                return self.get_decision(study_id, prior)
        if expected_revision is not None and state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        if state.active_job:
            raise ActiveStageError(f"Study {study_id} already has an active stage: {state.active_job.stage}")
        if not candidates:
            raise ValueError("Pocket review requires at least one candidate")

        job = Job(
            id=self._id("job"),
            stage="pocket_review",
            status=JobStatus.RUNNING,
            started_at=utc_now(),
            progress=0.0,
            request_id=request_id,
        )
        state.jobs.append(job)
        state.current_stage = job.stage
        state.completion_status = CompletionStatus.RUNNING
        state.workflow_data["pocket_candidates"] = [record_to_dict(candidate) for candidate in candidates]
        if source:
            state.workflow_data["pocket_review_source"] = source
        known_artifacts = {artifact.id for artifact in state.artifacts}
        for artifact in artifacts:
            if artifact.id not in known_artifacts:
                state.artifacts.append(artifact)
                known_artifacts.add(artifact.id)
        if automation and automation.enabled:
            state.workflow_data["active_automation_policy"] = record_to_dict(automation)
            self._event(
                state,
                EventType.WARNING_RAISED,
                automation.warning,
                explanation=(
                    f"The enabled {automation.scope} policy '{automation.name}' may resolve only "
                    "decisions explicitly marked as automation-eligible; every application is audited."
                ),
                technical={"policy_id": automation.id, "rules": len(automation.rules)},
                data={"policy": record_to_dict(automation)},
                mandatory=True,
            )
        self._event(
            state,
            EventType.STAGE_STARTED,
            "Pocket evidence review started",
            explanation="Candidate cavities are hypotheses that must be reviewed before they define a docking region.",
            teaching="An fpocket rank describes cavity geometry; it does not establish biological relevance.",
            technical={"job_id": job.id, "candidate_count": len(candidates)},
        )
        job.progress = 1.0
        decision = DecisionRequired(
            id=self._id("decision"),
            kind="select_pockets",
            prompt="Choose one or more docking regions",
            detected=f"{len(candidates)} candidate docking regions are available",
            why_stopped="Selecting a search region changes what molecular space the docking engine will examine.",
            consequences=(
                "Selected regions will be locked into the exploratory protocol.",
                "Pocket evidence does not by itself validate biological relevance.",
            ),
            options=tuple(
                DecisionOption(
                    value=candidate.id,
                    label=candidate.label,
                    consequence=candidate.summary,
                    recommended=candidate.rank == 1,
                    automation_eligible=candidate.evidence.get("automation_eligible", True),
                )
                for candidate in candidates
            ),
            artifact_ids=tuple(dict.fromkeys(
                [candidate.box_artifact_id for candidate in candidates] + list(review_artifact_ids)
            )),
            maximum_selections=len(candidates),
            automation_eligible=True,
        )
        state.decisions.append(decision)
        if request_id:
            state.workflow_data.setdefault("pocket_review_requests", {})[request_id] = decision.id
        job.status = JobStatus.WAITING_FOR_DECISION
        state.completion_status = CompletionStatus.WAITING_FOR_DECISION
        self._event(
            state,
            EventType.DECISION_REQUIRED,
            decision.prompt,
            explanation=" ".join((decision.why_stopped, *decision.consequences)),
            teaching="Compare geometry, structural context, and retained evidence rather than treating rank as an answer.",
            technical={"decision_id": decision.id, "options": [option.value for option in decision.options]},
            data={"decision": record_to_dict(decision)},
            mandatory=True,
        )
        self.store.save(state)

        if automation:
            selections = automation.selection_for(decision)
            if selections is not None:
                self.resolve_decision(
                    study_id,
                    decision.id,
                    selections,
                    actor=automation.name,
                    rationale=f"Applied enabled {automation.scope} automation policy",
                    policy_id=automation.id,
                )
        return self.get_decision(study_id, decision.id)

    def get_decision(self, study_id: str, decision_id: str) -> DecisionRequired:
        state = self.get_study(study_id)
        decision = next((item for item in state.decisions if item.id == decision_id), None)
        if decision is None:
            raise KeyError(f"Unknown decision: {decision_id}")
        return decision

    def resolve_decision(
        self,
        study_id: str,
        decision_id: str,
        selections: tuple[str, ...],
        *,
        actor: str,
        rationale: str | None = None,
        policy_id: str | None = None,
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ApprovalRecord:
        state = self.get_study(study_id)
        if request_id:
            replay = next((item for item in state.approvals if item.request_id == request_id), None)
            if replay is not None:
                return replay
        if expected_revision is not None and state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        decision = next((item for item in state.decisions if item.id == decision_id), None)
        if decision is None:
            raise KeyError(f"Unknown decision: {decision_id}")
        decision.validate_response(selections)
        method = "automated_policy" if policy_id else "explicit_user"
        if policy_id and decision.requires_explicit_user:
            raise ExplicitApprovalRequired(f"Decision {decision.id} cannot be resolved by automation")
        if policy_id:
            persisted = state.workflow_data.get("active_automation_policy")
            if not isinstance(persisted, dict) or not persisted.get("enabled") or persisted.get("id") != policy_id:
                raise ExplicitApprovalRequired("Automation policy is not the enabled persisted study policy")
            rules = {
                rule.get("decision_kind"): tuple(rule.get("selections", ()))
                for rule in persisted.get("rules", ()) if isinstance(rule, dict)
            }
            options = {option.value: option for option in decision.options}
            if rules.get(decision.kind) != selections or any(not options[value].automation_eligible for value in selections):
                raise ExplicitApprovalRequired("Automation policy does not authorize this exact decision response")

        approval = ApprovalRecord(
            id=self._id("approval"),
            decision_id=decision.id,
            selections=selections,
            actor=actor,
            method=method,
            rationale=rationale,
            policy_id=policy_id,
            evidence={"artifact_ids": list(decision.artifact_ids), "decision_created_at": decision.created_at},
            request_id=request_id,
        )
        state.approvals.append(approval)
        decision.status = DecisionStatus.RESOLVED
        decision.resolved_at = utc_now()
        if decision.kind == "select_pockets":
            state.selected_pocket_ids = list(selections)
            state.scientific_authority = ScientificAuthority.EXPLORATORY_NO_CONTROL
        job = state.active_job
        if job is None or job.status is not JobStatus.WAITING_FOR_DECISION:
            raise RuntimeError("No waiting workflow stage is available to resume")
        job.status = JobStatus.COMPLETED
        job.finished_at = utc_now()
        state.current_stage = None
        record_stage_completion(state, job.stage)
        self._event(
            state,
            EventType.DECISION_RESOLVED,
            f"Decision resolved: {', '.join(selections)}",
            explanation="The selected regions and decision provenance are retained with the study.",
            technical={"approval_id": approval.id, "method": method, "policy_id": policy_id},
            data={"approval": record_to_dict(approval)},
            mandatory=method == "automated_policy",
        )
        self._event(
            state,
            EventType.STAGE_COMPLETED,
            "Pocket evidence review completed",
            explanation="The study remains exploratory until target-specific control evidence establishes greater authority.",
            technical={"job_id": job.id},
        )
        self.store.save(state)
        return approval

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}-{uuid4().hex}"

    @staticmethod
    def _event(
        state: StudyState,
        event_type: EventType,
        message: str,
        *,
        explanation: str = "",
        teaching: str = "",
        technical: dict | None = None,
        data: dict | None = None,
        mandatory: bool = False,
    ) -> None:
        state.events.append(
            WorkflowEvent(
                id=StudyController._id("event"),
                sequence=len(state.events) + 1,
                type=event_type,
                message=message,
                explanation=explanation,
                teaching=teaching,
                technical=technical or {},
                data=data or {},
                mandatory=mandatory,
            )
        )
