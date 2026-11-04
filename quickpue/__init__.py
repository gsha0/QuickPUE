"""QuickPUE: rapid, transparent data centre infrastructure energy and PUE estimator.

Public API (REQ-UI-1): ``load_project``, ``run``, ``export``, ``explain``.
"""

__version__ = "0.1.0"

from .inputs import list_presets, load_project  # noqa: E402
from .runner import run  # noqa: E402


def export(results, out_dir, formats=("csv", "md", "json"), output_set=None, hourly=True, charts=True):
    from .outputs import export as _export

    return _export(results, out_dir, formats=formats, output_set=output_set, hourly=hourly, charts=charts)


def explain(results, item, hour=0, scenario=None):
    from .report import explain as _explain

    return _explain(results, item, hour, scenario)


__all__ = ["load_project", "run", "export", "explain", "list_presets", "__version__"]
