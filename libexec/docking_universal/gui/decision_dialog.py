"""Reusable progressive-disclosure review for scientific decisions."""

from __future__ import annotations

import json

from .qt import QtCore, QtWidgets


DETAIL_LEVELS = (
    ("Brief", "brief"),
    ("Guided", "guided"),
    ("Background", "background"),
    ("Technical", "technical"),
)


class DecisionDialog(QtWidgets.QDialog):
    """Show one retained decision without conflating explanation and approval."""

    SETTINGS_KEY = "decisions/explanation_level"

    def __init__(
        self, decision, *, settings, evidence=None, selected=(), allow_approval=False,
        parent=None,
    ):
        super().__init__(parent)
        self.decision = decision
        self.settings = settings
        self.evidence = evidence or {}
        self.allow_approval = allow_approval
        self._option_checks = {}
        self.setObjectName("scientific_decision_dialog")
        self.setWindowTitle(decision.prompt)
        self.resize(880, 680)

        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel(f"<h2>{decision.prompt}</h2>")
        title.setWordWrap(True)
        detected = QtWidgets.QLabel(f"<b>What was found</b><br>{decision.detected}")
        detected.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(detected)

        option_group = QtWidgets.QGroupBox("Available choices")
        option_layout = QtWidgets.QVBoxLayout(option_group)
        selected = set(selected)
        for option in decision.options:
            label = option.label + (" — suggested starting point" if option.recommended else "")
            check = QtWidgets.QCheckBox(label)
            check.setObjectName(f"decision_option_{option.value}")
            check.setChecked(option.value in selected)
            check.setEnabled(allow_approval)
            consequence = QtWidgets.QLabel(option.consequence)
            consequence.setWordWrap(True)
            consequence.setStyleSheet("color: palette(mid);")
            consequence.setContentsMargins(24, 0, 8, 6)
            option_layout.addWidget(check)
            option_layout.addWidget(consequence)
            self._option_checks[option.value] = check
        option_scroll = QtWidgets.QScrollArea()
        option_scroll.setObjectName("decision_options_scroll")
        option_scroll.setWidgetResizable(True)
        option_scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        option_scroll.setMaximumHeight(250)
        option_scroll.setWidget(option_group)
        layout.addWidget(option_scroll)

        control_row = QtWidgets.QHBoxLayout()
        control_row.addWidget(QtWidgets.QLabel("Explanation:"))
        self.detail_level = QtWidgets.QComboBox()
        for label, value in DETAIL_LEVELS:
            self.detail_level.addItem(label, value)
        saved = str(settings.value(self.SETTINGS_KEY, "guided"))
        index = self.detail_level.findData(saved)
        self.detail_level.setCurrentIndex(index if index >= 0 else 1)
        self.remember_level = QtWidgets.QCheckBox("Use this explanation level for future decisions")
        self.remember_level.setChecked(True)
        control_row.addWidget(self.detail_level)
        control_row.addWidget(self.remember_level)
        control_row.addStretch(1)
        layout.addLayout(control_row)

        self.detail = QtWidgets.QTextBrowser()
        self.detail.setOpenExternalLinks(False)
        layout.addWidget(self.detail, 1)
        self.detail_level.currentIndexChanged.connect(self._render_detail)
        self._render_detail()

        self.rationale = QtWidgets.QLineEdit()
        self.rationale.setPlaceholderText("Optional scientific rationale for the audit trail")
        self.rationale.setVisible(allow_approval)
        layout.addWidget(self.rationale)

        buttons = QtWidgets.QDialogButtonBox()
        if allow_approval:
            self.approve_button = buttons.addButton(
                "Approve selected choice(s)", QtWidgets.QDialogButtonBox.ButtonRole.AcceptRole,
            )
            self.approve_button.clicked.connect(self._validate_and_accept)
        close = buttons.addButton(QtWidgets.QDialogButtonBox.StandardButton.Close)
        close.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def selected_values(self) -> tuple[str, ...]:
        return tuple(value for value, check in self._option_checks.items() if check.isChecked())

    def _validate_and_accept(self) -> None:
        values = self.selected_values()
        try:
            self.decision.validate_response(values)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self, "Choice required", str(exc))
            return
        self._remember()
        self.accept()

    def reject(self) -> None:
        self._remember()
        super().reject()

    def _remember(self) -> None:
        if self.remember_level.isChecked():
            self.settings.setValue(self.SETTINGS_KEY, self.detail_level.currentData())

    def _render_detail(self) -> None:
        level = self.detail_level.currentData()
        consequences = "".join(f"<li>{value}</li>" for value in self.decision.consequences)
        sections = [
            f"<h3>Why the workflow paused</h3><p>{self.decision.why_stopped}</p>",
            f"<h3>What this choice changes</h3><ul>{consequences}</ul>",
        ]
        if level in {"guided", "background", "technical"}:
            guided = self.decision.presentation.get("guided")
            if guided:
                sections.append(f"<h3>How to review this decision</h3>{guided}")
        if level in {"background", "technical"}:
            background = self.decision.presentation.get("background")
            if background:
                sections.append(f"<h3>Scientific background</h3><p>{background}</p>")
        if level == "technical":
            technical = self.decision.presentation.get("technical")
            if technical:
                sections.append(f"<h3>Technical record</h3><p>{technical}</p>")
            retained = {
                "decision_payload": self.decision.payload,
                "continuation": self.decision.continuation,
                "artifact_ids": list(self.decision.artifact_ids),
                "evidence": self.evidence,
            }
            sections.append(
                "<h3>Retained data</h3><pre>" +
                json.dumps(retained, indent=2, sort_keys=True).replace("&", "&amp;").replace("<", "&lt;") +
                "</pre>"
            )
        if level == "brief":
            sections = sections[:1]
        self.detail.setHtml("".join(sections))
