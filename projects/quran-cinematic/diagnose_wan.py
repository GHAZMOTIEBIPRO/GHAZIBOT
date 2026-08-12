import json
from pathlib import Path
from gradio_client import Client

out = Path(__file__).resolve().parent / "wan_api.json"
client = Client(
    "Wan-AI/Wan2.1",
    verbose=True,
    httpx_kwargs={"timeout": 60.0, "follow_redirects": True},
)
api = client.view_api(return_format="dict")
out.write_text(json.dumps(api, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
print(json.dumps(api, ensure_ascii=False, indent=2, default=str))
