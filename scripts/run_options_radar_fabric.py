from __future__ import annotations

from options_radar.data_fabric_runtime import install_data_fabric
from options_radar.durable_state import restore_missing_durable_options_state
from options_radar.free_autonomy import enforce_free_autonomy_environment


def main() -> None:
    # Enforce zero-cost feeds before Settings or any data client is imported.
    # This prevents stale SIP/OPRA environment values from silently turning the
    # autonomous path into a paid dependency.
    free_status = enforce_free_autonomy_environment()
    print(
        "Free autonomy: "
        f"enabled={free_status.enabled} "
        f"stock_feed={free_status.stock_stream_feed} "
        f"option_feed={free_status.option_stream_feed} "
        f"paid_allowed={free_status.paid_market_data_allowed}"
    )

    # Artifacts remain the hot state restored by the workflow. The durable
    # bot-state branch fills only files that are missing, so it cannot roll a
    # newer artifact backward if the state-vault workflow is briefly delayed.
    durable = restore_missing_durable_options_state()
    print(
        "Durable options state: "
        f"attempted={durable.attempted} "
        f"branch_available={durable.branch_available} "
        f"restored={len(durable.restored)} "
        f"preserved_local={len(durable.preserved_local)}"
    )
    if durable.error:
        print(f"Durable options state fallback unavailable: {durable.error}")

    # Install acquisition-only hardening before importing the hardened runner so
    # every DataFetcher created by the options path uses the same fabric.
    install_data_fabric()
    from scripts.run_options_radar_hardened import main as hardened_main

    hardened_main()


if __name__ == "__main__":
    main()
