"""Explicit automation policies that cannot cross scientific boundaries."""

from __future__ import annotations

from dataclasses import dataclass, field

from .decisions import DecisionRequired


@dataclass(frozen=True)
class AutomationRule:
    decision_kind: str
    selections: tuple[str, ...]


@dataclass(frozen=True)
class AutomationPolicy:
    id: str
    name: str
    rules: tuple[AutomationRule, ...] = ()
    enabled: bool = False
    scope: str = "study"
    warning: str = "AUTOMATED SCIENTIFIC DECISIONS"

    def selection_for(self, decision: DecisionRequired) -> tuple[str, ...] | None:
        if not self.enabled or not decision.automation_eligible or decision.requires_explicit_user:
            return None
        for rule in self.rules:
            if rule.decision_kind == decision.kind:
                decision.validate_response(rule.selections)
                options = {option.value: option for option in decision.options}
                if any(not options[value].automation_eligible for value in rule.selections):
                    return None
                return rule.selections
        return None
