"""Local browser workspace for the persisted SE02 workflow."""
from .manager import JobManager
from .server import make_server

__all__ = ['JobManager','make_server']
