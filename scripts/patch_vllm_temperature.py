#!/usr/bin/env python3
"""Apply/re-apply the per-request temperature patch for vLLM-Omni Qwen3-TTS.

Makes the frontend temperature slider actually take effect:
  1. serving_speech.py: copy extra_params.temperature into the stage-0
     SamplingParams.temperature (main sampler).
  2. gpu_model_runner.py: _talker_mtp_forward reads per-request
     extra_args["temperature"] and overrides the subtalker (residual
     codebook) temperature.

Idempotent: safe to run multiple times. After upgrading/reinstalling
vllm_omni, re-run this script (from the ppt2video env) and restart
vLLM-Omni.

IMPORTANT: the app layer (app/services/vllm_omni_tts.py) clamps temperature
to [0.3, 1.5] to avoid the Qwen3-TTS low-temperature EOS-loop bug.
"""

import sys
from pathlib import Path

SITE_PACKAGES = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
VLLM_OMNI_DIR = SITE_PACKAGES / "vllm_omni"
SERVING_SPEECH = VLLM_OMNI_DIR / "entrypoints" / "openai" / "serving_speech.py"
GPU_MODEL_RUNNER = VLLM_OMNI_DIR / "worker" / "gpu_model_runner.py"


def patch_file(path: Path, anchor: str, insertion: str) -> bool:
    if not path.exists():
        print(f"[skip] 不存在: {path}")
        return False
    content = path.read_text(encoding="utf-8")
    marker = insertion.splitlines()[0]
    if marker in content:
        print(f"[skip] 已打过补丁: {path}")
        return False
    if anchor not in content:
        print(f"[warn] 锚点未找到: {path}")
        return False
    content = content.replace(anchor, anchor + insertion, 1)
    path.write_text(content, encoding="utf-8")
    print(f"[ok]   已打补丁: {path}")
    return True


def main() -> None:
    print(f"vllm_omni 目录: {VLLM_OMNI_DIR}")
    if not VLLM_OMNI_DIR.exists():
        print("[error] vllm_omni 未找到，请确认在 ppt2video 环境运行")
        sys.exit(1)

    # Patch 1: serving_speech.py — apply temperature to stage-0 main sampler
    p1_anchor = "            sampling_params_list[0].extra_args.update(request.extra_params)\n"
    p1_insert = (
        "            # PATCH: also apply temperature to the stage-0 main sampler so\n"
        "            # per-request temperature actually takes effect for Qwen3-TTS.\n"
        "            _extra_temp = request.extra_params.get(\"temperature\")\n"
        "            if _extra_temp is not None:\n"
        "                try:\n"
        "                    sampling_params_list[0].temperature = float(_extra_temp)\n"
        "                    logger.info(\"PATCH: stage0 sampling temperature -> %s\", _extra_temp)\n"
        "                except (TypeError, ValueError):\n"
        "                    logger.warning(\"PATCH: invalid temperature %r ignored\", _extra_temp)\n"
    )
    patch_file(SERVING_SPEECH, p1_anchor, p1_insert)

    # Patch 2: gpu_model_runner.py — per-request subtalker temperature
    p2_anchor = (
        '            "top_p": subtalker_params.get("top_p"),\n'
        "        }\n"
    )
    p2_insert = (
        "        # PATCH: per-request temperature override from extra_args.\n"
        "        # For a single-row batch the request temperature maps 1:1; for a\n"
        "        # multi-row batch, use it only when every row agrees on a value.\n"
        "        _talker_temps = [_explicit_talker_temperature(rid) for rid in decode_req_ids]\n"
        "        _valid_temps = {t for t in _talker_temps if t is not None}\n"
        "        if _valid_temps:\n"
        "            if len(_valid_temps) == 1:\n"
        "                talker_kwargs[\"temperature\"] = _valid_temps.pop()\n"
        "                logger.info(\"PATCH: subtalker temperature -> %s (req=%s)\", talker_kwargs[\"temperature\"], decode_req_ids[0])\n"
        "            else:\n"
        "                logger.warning(\n"
        "                    \"PATCH: mixed per-request temperatures %s; falling back to YAML default\",\n"
        "                    sorted(_valid_temps),\n"
        "                )\n"
    )
    patch_file(GPU_MODEL_RUNNER, p2_anchor, p2_insert)

    # Patch 3: gpu_model_runner.py — _explicit_talker_temperature helper
    p3_anchor = (
        "            return int(seed) if seed is not None else None\n"
        "\n"
        "        def _row_generator(req_id: str) -> torch.Generator | None:\n"
    )
    p3_insert = (
        "        def _explicit_talker_temperature(req_id: str) -> float | None:\n"
        "            sampling_params = getattr(self.requests[req_id], \"sampling_params\", None)\n"
        "            extra_args = getattr(sampling_params, \"extra_args\", None) if sampling_params is not None else None\n"
        "            temp = None\n"
        "            if isinstance(extra_args, dict):\n"
        "                temp = extra_args.get(\"temperature\")\n"
        "            return float(temp) if temp is not None else None\n"
        "\n"
    )
    patch_file(GPU_MODEL_RUNNER, p3_anchor, p3_insert)

    import ast
    for p in (SERVING_SPEECH, GPU_MODEL_RUNNER):
        try:
            ast.parse(p.read_text(encoding="utf-8"))
            print(f"[ok]   语法检查通过: {p.name}")
        except SyntaxError as e:
            print(f"[error] 语法错误 {p.name}: {e}")
            sys.exit(1)

    print("\n完成。请重启应用 (scripts/start_all.sh)。升级 vllm_omni 后重新运行本脚本即可。")


if __name__ == "__main__":
    main()
