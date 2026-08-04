"""
Jira OAuth integration package.

Registers the jira_bp Flask blueprint.
All Jira logic is isolated here — nothing outside this package is modified
except the two additive lines in app.py that import and register the blueprint.
"""
from .routes import jira_bp  # noqa: F401 — re-exported for app.py
