#!/usr/bin/env python3
"""Run headless MicroRTS bot benchmarks and log results to Weights & Biases."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Dict, List

try:
    import wandb
except ImportError as exc:
    raise SystemExit("Missing dependency: wandb. Install with: pip install wandb") from exc


BENCHMARKS: Dict[str, str] = {
    "random": "ai.RandomAI",
    "worker_rush": "ai.abstraction.WorkerRush",
    "light_rush": "ai.abstraction.LightRush",
    "naive_mcts": "ai.mcts.naivemcts.NaiveMCTS",
    "mayari": "mayariBot.mayari",
    "coac": "ai.coac.CoacAI",
}


def run_cmd(cmd: List[str], cwd: Path | None = None) -> str:
    proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True)
    if proc.returncode != 0:
        print("Command failed:", " ".join(cmd), file=sys.stderr)
        if proc.stdout:
            print(proc.stdout, file=sys.stderr)
        if proc.stderr:
            print(proc.stderr, file=sys.stderr)
        raise RuntimeError("Command failed")
    return proc.stdout


def ensure_microrts_compiled(microrts_dir: Path) -> None:
    required = microrts_dir / "bin" / "rts" / "MicroRTS.class"
    if required.exists():
        return
    print("Compiling MicroRTS (bin classes not found)...")
    cp = f"lib/*{os.pathsep}src"
    run_cmd(["javac", "-cp", cp, "-d", "bin", "src/rts/MicroRTS.java"], cwd=microrts_dir)


def class_to_jar_entry(class_name: str) -> str:
    return class_name.replace(".", "/") + ".class"


def jar_has_class(jar_path: Path, class_name: str) -> bool:
    if not jar_path.exists():
        return False
    entry = class_to_jar_entry(class_name)
    with zipfile.ZipFile(jar_path, "r") as zf:
        return entry in zf.namelist()


def build_bot_jar_from_source(
    repo_dir: Path,
    microrts_dir: Path,
    source_name: str,
    jar_name: str,
    bot_class: str,
) -> Path:
    source_path = repo_dir / source_name
    if not source_path.exists():
        raise FileNotFoundError(f"Bot source not found: {source_path}")

    build_dir = repo_dir / "build_bot"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)

    cp = os.pathsep.join([
        str(microrts_dir / "lib" / "*"),
        str(microrts_dir / "bin"),
    ])
    run_cmd(["javac", "-cp", cp, "-d", str(build_dir), str(source_path)])

    jar_path = repo_dir / jar_name
    if jar_path.exists():
        jar_path.unlink()

    with zipfile.ZipFile(jar_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\nCreated-By: wandb_eval.py\n\n")
        for class_file in build_dir.rglob("*.class"):
            arcname = class_file.relative_to(build_dir).as_posix()
            zf.write(class_file, arcname)

    if not jar_has_class(jar_path, bot_class):
        raise RuntimeError(f"Built jar {jar_path} does not contain {class_to_jar_entry(bot_class)}")

    return jar_path


def compile_match_runner(repo_dir: Path, microrts_dir: Path, extra_jars: List[Path]) -> Path:
    src = repo_dir / "eval" / "MatchRunner.java"
    out_dir = repo_dir / "eval" / "bin"
    out_dir.mkdir(parents=True, exist_ok=True)

    cp_parts = [
        str(microrts_dir / "lib" / "*"),
        str(microrts_dir / "lib" / "bots" / "*"),
        str(microrts_dir / "bin"),
    ] + [str(j) for j in extra_jars if j.exists()]

    run_cmd(["javac", "-cp", os.pathsep.join(cp_parts), "-d", str(out_dir), str(src)])
    return out_dir


def resolve_maps(microrts_dir: Path, map_arg: str) -> List[Path]:
    out: List[Path] = []
    for raw in [x.strip() for x in map_arg.split(",") if x.strip()]:
        p = Path(raw)
        if not p.is_absolute():
            p = microrts_dir / p
        if not p.exists():
            raise FileNotFoundError(f"Map not found: {p}")
        out.append(p)
    return out


def parse_result(stdout: str) -> Dict[str, int | bool]:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if line.startswith("{") and "\"winner\"" in line:
            data = json.loads(line)
            return {
                "winner": int(data["winner"]),
                "cycles": int(data["cycles"]),
                "game_over": bool(data["game_over"]),
            }
    raise ValueError(f"No JSON result found in output:\n{stdout}")


def run_match(
    microrts_dir: Path,
    runner_bin_dir: Path,
    extra_jars: List[Path],
    map_path: Path,
    max_cycles: int,
    utt_version: int,
    conflict_policy: int,
    ai1: str,
    ai2: str,
) -> Dict[str, int | bool]:
    cp_parts = [
        str(microrts_dir / "lib" / "*"),
        str(microrts_dir / "lib" / "bots" / "*"),
        str(microrts_dir / "bin"),
        str(runner_bin_dir),
    ] + [str(j) for j in extra_jars if j.exists()]

    out = run_cmd(
        [
            "java",
            "-cp",
            os.pathsep.join(cp_parts),
            "eval.MatchRunner",
            str(map_path),
            str(max_cycles),
            str(utt_version),
            str(conflict_policy),
            ai1,
            ai2,
        ]
    )
    return parse_result(out)


def summarize(rows: List[Dict[str, object]]) -> List[Dict[str, object]]:
    by_opp: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        by_opp.setdefault(str(row["opponent"]), []).append(row)

    summary: List[Dict[str, object]] = []
    for opp, items in by_opp.items():
        wins = sum(1 for r in items if r["result"] == "win")
        losses = sum(1 for r in items if r["result"] == "loss")
        ties = sum(1 for r in items if r["result"] == "tie")
        games = len(items)
        avg_cycles = sum(int(r["cycles"]) for r in items) / max(games, 1)
        win_rate = wins / max(games, 1)
        score = (wins + 0.5 * ties) / max(games, 1)
        summary.append(
            {
                "opponent": opp,
                "games": games,
                "wins": wins,
                "losses": losses,
                "ties": ties,
                "win_rate": round(win_rate, 4),
                "score": round(score, 4),
                "avg_cycles": round(avg_cycles, 2),
            }
        )
    summary.sort(key=lambda x: str(x["opponent"]))
    return summary


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def maybe_make_plot(summary_rows: List[Dict[str, object]], out_png: Path) -> bool:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return False

    labels = [str(r["opponent"]) for r in summary_rows]
    values = [float(r["win_rate"]) for r in summary_rows]

    plt.figure(figsize=(10, 4))
    plt.bar(labels, values)
    plt.ylim(0.0, 1.0)
    plt.ylabel("Win rate")
    plt.title("AlliBot win rate by opponent")
    plt.xticks(rotation=25, ha="right")
    plt.tight_layout()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(out_png, dpi=160)
    plt.close()
    return True


def maybe_make_per_opponent_plots(
    all_rows: List[Dict[str, object]],
    out_dir: Path,
) -> Dict[str, Path]:
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return {}

    by_opp: Dict[str, List[Dict[str, object]]] = {}
    for row in all_rows:
        by_opp.setdefault(str(row["opponent"]), []).append(row)

    out_dir.mkdir(parents=True, exist_ok=True)
    generated: Dict[str, Path] = {}

    for opp in sorted(by_opp.keys()):
        rows = sorted(by_opp[opp], key=lambda r: int(r["match_index"]))
        scores = [1 if r["result"] == "win" else 0 if r["result"] == "tie" else -1 for r in rows]
        cycles = [int(r["cycles"]) for r in rows]
        x_vals = list(range(len(rows)))

        wins = sum(1 for r in rows if r["result"] == "win")
        losses = sum(1 for r in rows if r["result"] == "loss")
        ties = sum(1 for r in rows if r["result"] == "tie")

        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        axes[0].plot(x_vals, scores, marker="o", linewidth=1.5)
        axes[0].set_yticks([-1, 0, 1])
        axes[0].set_yticklabels(["loss", "tie", "win"])
        axes[0].set_ylabel("Outcome")
        axes[0].grid(alpha=0.3)
        axes[0].set_title(
            f"AlliBot vs {opp} | W:{wins} L:{losses} T:{ties} | WinRate={wins / max(len(rows), 1):.2f}"
        )

        axes[1].plot(x_vals, cycles, marker="o", linewidth=1.5)
        axes[1].set_ylabel("Cycles")
        axes[1].set_xlabel("Game index (within this opponent)")
        axes[1].grid(alpha=0.3)

        fig.tight_layout()

        out_path = out_dir / f"head_to_head_{opp}.png"
        fig.savefig(out_path, dpi=170)
        plt.close(fig)
        generated[opp] = out_path

    return generated


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MicroRTS bot and log results to W&B")
    parser.add_argument("--microrts-dir", default="../microrts", help="Path to microrts repo")
    parser.add_argument("--bot-class", default="alliBot.alli", help="Fully-qualified class name for your bot")
    parser.add_argument("--bot-source", default="alli.java", help="Bot source file in this repo")
    parser.add_argument("--bot-jar", default="alliBot.jar", help="Bot jar file in this repo")
    parser.add_argument("--no-rebuild-bot-jar", action="store_true", help="Skip rebuilding bot jar from bot source")
    parser.add_argument("--skip-copy-bot-jar", action="store_true", help="Do not copy local bot jar into microrts/lib/bots")
    parser.add_argument("--project", default="microrts-bot-eval")
    parser.add_argument("--entity", default=None)
    parser.add_argument("--run-name", default=None)
    parser.add_argument("--offline", action="store_true", help="Use WANDB_MODE=offline")
    parser.add_argument("--maps", default="maps/16x16/basesWorkers16x16.xml")
    parser.add_argument("--opponents", default="random,worker_rush,light_rush,naive_mcts,mayari,coac")
    parser.add_argument("--rounds", type=int, default=3, help="Rounds per map/opponent. Each round runs both sides")
    parser.add_argument("--max-cycles", type=int, default=5000)
    parser.add_argument("--utt-version", type=int, default=2)
    parser.add_argument("--conflict-policy", type=int, default=1)
    args = parser.parse_args()

    if args.offline:
        os.environ["WANDB_MODE"] = "offline"

    repo_dir = Path(__file__).resolve().parent
    microrts_dir = Path(args.microrts_dir).resolve()
    if not microrts_dir.exists():
        raise FileNotFoundError(f"microrts dir not found: {microrts_dir}")

    ensure_microrts_compiled(microrts_dir)

    local_bot_jar = repo_dir / args.bot_jar
    if not args.no_rebuild_bot_jar:
        local_bot_jar = build_bot_jar_from_source(
            repo_dir=repo_dir,
            microrts_dir=microrts_dir,
            source_name=args.bot_source,
            jar_name=args.bot_jar,
            bot_class=args.bot_class,
        )

    if not local_bot_jar.exists():
        raise FileNotFoundError(f"Bot jar not found: {local_bot_jar}")

    if not jar_has_class(local_bot_jar, args.bot_class):
        raise RuntimeError(
            f"{local_bot_jar} does not contain {class_to_jar_entry(args.bot_class)}. "
            "Set --bot-class correctly or rebuild the jar from source."
        )

    if not args.skip_copy_bot_jar:
        dst = microrts_dir / "lib" / "bots" / args.bot_jar
        shutil.copy2(local_bot_jar, dst)

    extra_jars = [local_bot_jar]

    runner_bin_dir = compile_match_runner(repo_dir, microrts_dir, extra_jars)
    map_paths = resolve_maps(microrts_dir, args.maps)

    selected_keys = [x.strip() for x in args.opponents.split(",") if x.strip()]
    unknown = [k for k in selected_keys if k not in BENCHMARKS]
    if unknown:
        raise ValueError(f"Unknown opponents: {unknown}. Valid keys: {sorted(BENCHMARKS.keys())}")

    run = wandb.init(
        project=args.project,
        entity=args.entity,
        name=args.run_name,
        config={
            "bot_class": args.bot_class,
            "maps": [str(p) for p in map_paths],
            "opponents": selected_keys,
            "rounds": args.rounds,
            "max_cycles": args.max_cycles,
            "utt_version": args.utt_version,
            "conflict_policy": args.conflict_policy,
        },
    )

    all_rows: List[Dict[str, object]] = []
    match_index = 0

    for opp_key in selected_keys:
        opp_class = BENCHMARKS[opp_key]
        for map_path in map_paths:
            for round_idx in range(args.rounds):
                result_a = run_match(
                    microrts_dir,
                    runner_bin_dir,
                    extra_jars,
                    map_path,
                    args.max_cycles,
                    args.utt_version,
                    args.conflict_policy,
                    args.bot_class,
                    opp_class,
                )
                winner_a = int(result_a["winner"])
                outcome_a = "win" if winner_a == 0 else "loss" if winner_a == 1 else "tie"
                row_a = {
                    "match_index": match_index,
                    "opponent": opp_key,
                    "map": map_path.name,
                    "round": round_idx,
                    "alli_side": 0,
                    "winner": winner_a,
                    "cycles": int(result_a["cycles"]),
                    "result": outcome_a,
                }
                all_rows.append(row_a)
                wandb.log(
                    {
                        "match/index": match_index,
                        "match/opponent": opp_key,
                        "match/map": map_path.name,
                        "match/alli_side": 0,
                        "match/cycles": int(result_a["cycles"]),
                        "match/result_score": 1 if outcome_a == "win" else 0 if outcome_a == "tie" else -1,
                    }
                )
                match_index += 1

                result_b = run_match(
                    microrts_dir,
                    runner_bin_dir,
                    extra_jars,
                    map_path,
                    args.max_cycles,
                    args.utt_version,
                    args.conflict_policy,
                    opp_class,
                    args.bot_class,
                )
                winner_b = int(result_b["winner"])
                outcome_b = "win" if winner_b == 1 else "loss" if winner_b == 0 else "tie"
                row_b = {
                    "match_index": match_index,
                    "opponent": opp_key,
                    "map": map_path.name,
                    "round": round_idx,
                    "alli_side": 1,
                    "winner": winner_b,
                    "cycles": int(result_b["cycles"]),
                    "result": outcome_b,
                }
                all_rows.append(row_b)
                wandb.log(
                    {
                        "match/index": match_index,
                        "match/opponent": opp_key,
                        "match/map": map_path.name,
                        "match/alli_side": 1,
                        "match/cycles": int(result_b["cycles"]),
                        "match/result_score": 1 if outcome_b == "win" else 0 if outcome_b == "tie" else -1,
                    }
                )
                match_index += 1

    summary_rows = summarize(all_rows)

    reports_dir = repo_dir / "reports"
    write_csv(reports_dir / "match_results.csv", all_rows)
    write_csv(reports_dir / "summary.csv", summary_rows)

    matches_table = wandb.Table(columns=list(all_rows[0].keys()))
    for row in all_rows:
        matches_table.add_data(*[row[k] for k in all_rows[0].keys()])

    summary_table = wandb.Table(columns=list(summary_rows[0].keys()))
    for row in summary_rows:
        summary_table.add_data(*[row[k] for k in summary_rows[0].keys()])

    wandb.log(
        {
            "tables/matches": matches_table,
            "tables/summary": summary_table,
            "charts/win_rate": wandb.plot.bar(summary_table, "opponent", "win_rate", title="Win rate by opponent"),
            "charts/score": wandb.plot.bar(summary_table, "opponent", "score", title="Score by opponent"),
        }
    )

    plot_path = reports_dir / "win_rate_by_opponent.png"
    if maybe_make_plot(summary_rows, plot_path):
        wandb.log({"figures/win_rate_png": wandb.Image(str(plot_path))})

    per_opponent_plots = maybe_make_per_opponent_plots(all_rows, reports_dir / "head_to_head")
    if per_opponent_plots:
        wandb.log({f"figures/head_to_head_{opp}": wandb.Image(str(path)) for opp, path in per_opponent_plots.items()})

    run.finish()

    print("Done.")
    print(f"Match CSV:   {reports_dir / 'match_results.csv'}")
    print(f"Summary CSV: {reports_dir / 'summary.csv'}")
    if plot_path.exists():
        print(f"Plot PNG:    {plot_path}")
    if per_opponent_plots:
        print(f"Head2Head:   {reports_dir / 'head_to_head'}")


if __name__ == "__main__":
    main()
