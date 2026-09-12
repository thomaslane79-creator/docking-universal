"""Viewer-neutral contracts shared by the desktop and PyMOL adapter."""

from .identities import AtomIdentity, IdentityMapping, StructureIdentity
from .messages import Command, Event, Response
from .selections import AtomPoint, Selection, SelectionOperation

__all__ = [
    "AtomIdentity",
    "AtomPoint",
    "Command",
    "Event",
    "IdentityMapping",
    "Response",
    "Selection",
    "SelectionOperation",
    "StructureIdentity",
]
