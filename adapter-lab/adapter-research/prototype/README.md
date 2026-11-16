# Probe #6 prototype — Action-to-Request Alignment

Tests whether a plain model can judge: does a proposed tool action follow from
the user's request? Output per case: aligned / unrelated / ambiguous.
This is step-1 prototyping (no training, no Granite Switch) — it tells you if
the contract is sound and whether a general model already handles it.

## Files
- cases_6.jsonl   the test cases (edit/add your own, one JSON object per line)
- prompt.txt      the judge prompt template (edit to try different wording)
- run_probe6.py   runs every case through Ollama, writes results
- results.csv / results.html   generated output

## Run (Anaconda Prompt or cmd, with Ollama running)
    python run_probe6.py --dry-run           # test the harness, no model
    ollama list                              # see your model names
    python run_probe6.py --model qwen3.5:4b  # run against a model you have
Open results.html to review. Red rows = model disagreed with the expected label.

Only Python's standard library is used — no pip install needed.
