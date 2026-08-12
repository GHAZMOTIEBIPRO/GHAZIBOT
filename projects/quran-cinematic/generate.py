from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from gradio_client import Client

ROOT = Path(__file__).resolve().parent
SCENES_FILE = ROOT / "surah_al_insan_scenes.json"
OUT = ROOT / "output"
SPACE = os.getenv("HF_SPACE", "Lightricks/ltx-video-distilled")
HF_TOKEN = os.getenv("HF_TOKEN") or None

NEGATIVE = (
    "worst quality, low quality, blurry, jittery, inconsistent motion, warped anatomy, "
    "extra fingers, plastic skin, wax face, oversaturated colors, fantasy game aesthetic, "
    "religious iconography, angels, divine humanoid figure, glowing portals, text, subtitles, logos"
)


def extract_path(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            p = extract_path(item)
            if p:
                return p
        return None
    if isinstance(value, dict):
        for key in ("video", "path", "name", "file", "url"):
            if key in value:
                p = extract_path(value[key])
                if p:
                    return p
    return None


def copy_result(src: str, dst: Path) -> None:
    p = Path(src)
    if p.exists():
        shutil.copy2(p, dst)
        return
    raise FileNotFoundError(f"Gradio returned a video reference that is not a local downloaded file: {src}")


def generate_scene(client: Client, scene: dict[str, Any], dst: Path) -> None:
    prompt = scene["prompt"]
    duration = float(scene.get("duration", 4.0))
    seed = int(scene.get("seed", 42))

    # LTX Space input order as published by its Gradio app:
    # prompt, negative, image, video, height, width, mode, duration,
    # frames_to_use, seed, randomize_seed, guidance_scale, improve_texture
    result = client.predict(
        prompt,
        NEGATIVE,
        None,
        None,
        512,
        288,
        "text-to-video",
        duration,
        9,
        seed,
        False,
        1.0,
        False,
        api_name="/text_to_video",
    )
    src = extract_path(result)
    if not src:
        raise RuntimeError(f"Could not identify returned video path: {result!r}")
    copy_result(src, dst)


def normalize_clip(src: Path, dst: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(src),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
                   "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black,fps=24",
            "-an",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", str(dst),
        ],
        check=True,
    )


def stitch(clips: list[Path], final_path: Path) -> None:
    concat = OUT / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in clips), encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat.name,
            "-c", "copy", final_path.name,
        ],
        cwd=OUT,
        check=True,
    )


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    scenes = json.loads(SCENES_FILE.read_text(encoding="utf-8"))
    client = Client(SPACE, token=HF_TOKEN)

    successful: list[Path] = []
    failures: list[dict[str, str]] = []

    for index, scene in enumerate(scenes, start=1):
        raw = OUT / f"raw_{index:02d}_{scene['id']}.mp4"
        normalized = OUT / f"clip_{index:02d}_{scene['id']}.mp4"
        print(f"\n=== Generating {scene['id']} ===", flush=True)
        error: Exception | None = None
        for attempt in (1, 2):
            try:
                generate_scene(client, scene, raw)
                normalize_clip(raw, normalized)
                successful.append(normalized)
                error = None
                break
            except Exception as exc:  # noqa: BLE001 - workflow should record provider failures
                error = exc
                print(f"Attempt {attempt} failed: {exc}", file=sys.stderr, flush=True)
                if attempt == 1:
                    time.sleep(15)
        if error is not None:
            failures.append({"scene": scene["id"], "error": str(error)})

    (OUT / "generation_report.json").write_text(
        json.dumps(
            {
                "space": SPACE,
                "successful_clips": [p.name for p in successful],
                "failures": failures,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    if not successful:
        print("No clips were generated successfully.", file=sys.stderr)
        return 2

    final = OUT / "surah_al_insan_cinematic_9x16.mp4"
    if len(successful) == 1:
        shutil.copy2(successful[0], final)
    else:
        stitch(successful, final)

    print(f"FINAL_VIDEO={final}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
