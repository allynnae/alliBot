## alliBot

This is a modified version of Mayari.

Quick Play:
```
cd microrts
java -cp "lib/*;lib/bots/*;bin" rts.MicroRTS -l STANDALONE --headless false -m maps/16x16/basesWorkers16x16.xml -c 5000 --ai1 alliBot.alli --ai2 ai.RandomBiasedAI
```

## W&B Evaluation Report

This repo includes `wandb_eval.py` for automated benchmark evaluation of `alliBot.alli` against:
- `random`
- `worker_rush`
- `light_rush`
- `naive_mcts`
- `mayari`
- `coac`

### 1) Install Python dependencies
```powershell
pip install wandb matplotlib
```

### 2) Make sure MicroRTS is present and compiled
```powershell
cd C:\Users\allis\microrts
javac -cp "lib/*;src" -d bin src/rts/MicroRTS.java
```

### 3) Run an evaluation (offline example)
```powershell
cd C:\Users\allis\alliBot
python wandb_eval.py --microrts-dir ..\microrts --offline --rounds 2 --max-cycles 2000
```

### 4) Run an online W&B evaluation
```powershell
wandb login
python wandb_eval.py --microrts-dir ../microrts --project microrts-bot-eval --rounds 5
```

Outputs are saved locally to:
- `reports/match_results.csv`
- `reports/summary.csv`
- `reports/win_rate_by_opponent.png` (if matplotlib is installed)

Notes:
- Each round runs two games per opponent/map (swap sides for fairness).
- The script rebuilds `alliBot.jar` from `alli.java` by default and then copies it to `microrts/lib/bots/` (use `--no-rebuild-bot-jar` to skip).
- Select opponents via `--opponents random,worker_rush,...` and maps via `--maps maps/16x16/basesWorkers16x16.xml,maps/24x24/basesWorkers24x24A.xml`.

LLM Usage:
- Codex was used in certain aspects. Prompts include the following:
    - "This is originally the Mayari bot for the MicroRTS competition. Do you notice any bugs/flaws?"
    - "If I wanted to improve performance against the Worker Rush bot specifically, what method would you suggest?"