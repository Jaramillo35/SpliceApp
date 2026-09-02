"""Test plugins for the NiceGUI pages.

``nicegui.testing.user_plugin`` provides the ``user`` fixture: a simulated
client that opens a page, finds elements and clicks, with no browser. It
is what makes a page refactor provable.
"""

pytest_plugins = ["nicegui.testing.user_plugin"]
