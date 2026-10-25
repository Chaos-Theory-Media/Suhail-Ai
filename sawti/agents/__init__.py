"""Sawti agents. Each agent inspects one part of the studio and offers fix actions.

A finding is a dict:
    id, agent, severity ('fail' | 'warn' | 'manual' | 'info' | 'ok'), title, detail,
    action (registered action name or None), action_label
"""


def finding(fid, agent, severity, title, detail="", action=None, action_label=None):
    return dict(id=fid, agent=agent, severity=severity, title=title, detail=detail,
                action=action, action_label=action_label)


class Action:
    """A fix the operator (or an approved auto-prep) can run.

    safe      — allowed to run automatically once learned/approved (never records, never deletes media)
    live_safe — allowed while a show is live (device/routing changes are NOT)
    """

    def __init__(self, name, label, fn, safe=False, live_safe=False, agent="", impact=None):
        self.name, self.label, self.fn = name, label, fn
        self.safe, self.live_safe, self.agent = safe, live_safe, agent
        self.impact = impact
