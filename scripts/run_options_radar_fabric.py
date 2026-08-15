from __future__ import annotations

from options_radar.data_fabric_runtime import install_data_fabric


def main() -> None:
    # Install acquisition-only hardening before importing the hardened runner so
    # every DataFetcher created by the options path uses the same fabric.
    install_data_fabric()
    from scripts.run_options_radar_hardened import main as hardened_main

    hardened_main()


if __name__ == "__main__":
    main()
