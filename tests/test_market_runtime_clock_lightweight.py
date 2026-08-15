from __future__ import annotations

import subprocess
import sys


def test_runtime_clock_import_does_not_initialize_options_engine():
    code = (
        "import sys; "
        "import market_runtime_clock; "
        "assert 'options_radar' not in sys.modules; "
        "state = market_runtime_clock.market_clock_state(); "
        "assert state.reason"
    )
    subprocess.run([sys.executable, "-c", code], check=True)
