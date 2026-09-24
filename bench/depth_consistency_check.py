"""Option A's estimator on real chunks, before it goes anywhere near the pipeline.

The depth scales `levanta.recon.depth_consistency` finds, per view, on chunks the network has
already produced and that are on disk (solved independently, raw, in their own frames):

- the Replica laps, where every view's true depth scale is known from the exact rendered
  depth, so the estimate can be checked view by view;
- ARKitScenes 41069021 at 1 and 4 fps, where it cannot, and whatever comes out is the result.

No GPU.  Printed per scene as median and range, which is part of option A's result
(bench/results/pose_drift_options_2026-09-24.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))


def views_of(chunk: dict) -> list[dict]:
    return [{"depth": chunk["depth"][j].astype(np.float32), "mask": chunk["mask"][j], "K": chunk["K"][j], "T": chunk["T"][j]} for j in range(len(chunk["idx"]))]


def main() -> None:
    from chain_policies import load_chunks
    from known_poses import compare_depth, depth_truth

    from levanta.recon.depth_consistency import consistent_depth_scales

    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    out = {}
    replica_src = ROOT / "out" / "replica_apt0" / "render"
    seqs = json.loads((ROOT / "out" / "replica_laps" / "sequences.json").read_text(encoding="utf-8"))
    scenes = [
        ("replica one lap", ROOT / "out/replica_laps/one_lap_independent", seqs["one_lap"]),
        ("replica three laps", ROOT / "out/replica_laps/three_laps_independent", seqs["three_laps"]),
        ("arkitscenes 41069021, 1 fps", ROOT / "out/chain_exp/fps_1/41069021/noK", None),
        ("arkitscenes 41069021, 4 fps", ROOT / "out/chain_exp/fps_4/41069021/noK", None),
    ]
    for name, run, seq in scenes:
        chunks = load_chunks(run / "chunks")
        index = json.loads((run / "frames" / "index.json").read_text(encoding="utf-8"))
        est, truth, per_chunk = [], [], []
        for c in chunks:
            views = views_of(c)
            s, rep = consistent_depth_scales(views)
            per_chunk.append({"estimable": rep["estimable"], "common": rep.get("common"), "median_view": float(np.median(s))})
            if not rep["estimable"]:
                continue
            for j, v in enumerate(views):
                est.append(float(s[j]))
                if seq is not None:
                    step = min(round(index[int(c["idx"][j])]["time_s"]), len(seq) - 1)
                    t = depth_truth(replica_src, seq[step])
                    got = compare_depth(v["depth"], v["mask"], t) if t is not None else None
                    truth.append(1.0 / got["scale"] if got else np.nan)
        row = {"chunks": len(chunks), "estimable": sum(p["estimable"] for p in per_chunk), "views": len(est),
               "median": float(np.median(est)) if est else None, "range": [float(min(est)), float(max(est))] if est else None}
        line = f"{name}: {row['estimable']} of {row['chunks']} chunks estimable, {row['views']} views, scale median {row['median']:.2f}, range {row['range'][0]:.2f} to {row['range'][1]:.2f}" if est else f"{name}: nothing estimable"
        if truth:
            t = np.array(truth)
            e = np.array(est)
            ok = np.isfinite(t)
            ratio = e[ok] / t[ok]
            row.update({"truth_median": float(np.median(t[ok])), "estimate_over_truth_median": float(np.median(ratio)),
                        "estimate_over_truth_range": [float(ratio.min()), float(ratio.max())],
                        "correlation": float(np.corrcoef(e[ok], t[ok])[0, 1]) if ok.sum() > 2 else None})
            line += (f"; truth by rendered depth median {row['truth_median']:.2f}; estimate/truth median {row['estimate_over_truth_median']:.2f}"
                     f" ({ratio.min():.2f} to {ratio.max():.2f}), correlation {row['correlation']:.2f}")
        print(line)
        out[name] = {**row, "per_chunk": per_chunk}
    (ROOT / "out" / "depth_consistency_check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
