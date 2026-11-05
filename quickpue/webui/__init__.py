"""Web input editor for QuickPUE projects (inputs and input visualisation only).

The editor builds and edits the same YAML project files the CLI reads. It never runs the hourly
simulation and never changes the schema, presets, engine or sizing code: it only calls the public
loader (``load_project``), the preparation step used by ``quickpue validate`` (``prepare``) and the
read-only libraries (presets, part-load curves, schedules, EPW reader).

Start it with ``quickpue-ui [project.yaml]`` or ``python -m quickpue.webui``.
"""

from .server import main, make_server

__all__ = ["main", "make_server"]
