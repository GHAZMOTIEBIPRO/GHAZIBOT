# EdgarTools optional integration smoke

This optional research adapter does **not** replace the existing SEC EDGAR collector and is not an execution-grade market feed.

Install a compatible `edgartools` release in a controlled environment, then set `SEC_EDGAR_IDENTITY` to a real SEC-compliant contact identity. Do not commit the identity to the repository.

Run:

```bash
python -m options_radar.edgartools_research_adapter --symbol MU --limit 5
```

Exit status 2 means missing dependency, missing identity, invalid symbol, or provider error. Form 4 is **not** interpreted as a verified purchase; 8-K does **not** automatically imply a positive catalyst. Results are research-only. A successful live SEC smoke and comparison against the existing SEC collector are required before wiring this into Telegram or production workflows.
