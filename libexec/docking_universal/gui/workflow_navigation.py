"""Visibility policy for stage-local workflow docks."""

class WorkflowNavigationController:
    def __init__(self, docks):
        self.docks = dict(docks)

    def activate(self, target):
        if target == "central":
            for dock in self.docks.values(): dock.hide()
            return
        if target in self.docks:
            for name, dock in self.docks.items(): dock.setVisible(name == target)
