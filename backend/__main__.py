"""Allow running with `python -m backend`.

This preserves the original __main__ behavior of the moved module.
"""

import runpy

runpy.run_module("backend.app.main", run_name="__main__")
