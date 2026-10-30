# Ghosts of bugs past

Some bugs don't stay dead. A commit says "fixed", the bug gets buried, and months later another commit
says "fix it again". This tool digs those up.

- **Git finds the suspects.** For every commit that says it fixes something, `git blame` checks whose
  lines it rewrote. If those lines came from an *earlier* fix, the earlier fix may not have held.
- **A local open model judges.** Gemma (through [Ollama](https://ollama.com), on your own machine) reads
  both commit messages and both diffs, and says whether it's the same bug coming back.
- **A plain checker keeps the model honest.** It must quote both commit messages word for word, and it may
  not invent numbers. If it fails, it gets one retry with the reason, then the answer is dropped.
- **It has to say it twice.** The verdict is a choice between two phrases, "same bug came back" or
  "different problem", and the model is asked a second time with the choices in the opposite order. A ghost
  only counts if both answers agree. Small models lean towards "yes" on yes/no questions: the first version
  called all 15 suspects in click a ghost, and a yes/no double check then called none of them one.
- **Git adds a receipt.** Each ghost shows whether the later commit message points back at the earlier fix
  (its commit id, a shared issue number, or words like "regression" or "properly").

Your code never leaves your machine.

## Run it

You need Python 3.9+, git, and Ollama.

```
ollama pull gemma3:12b
git clone https://github.com/pallets/click
python ghosts.py click
```

It prints each ghost and writes a graveyard page, `ghosts_click.html`, plus `ghosts_click_log.json` with
everything the model said about every suspect.

Options: `--model gemma3:4b` (smaller and faster, but much more of a yes-man), `--max 30` (how many suspects to ask about),
`--last 200` (only the last 200 fix commits).

## What a ghost means, and what it doesn't

A ghost means two commits that both claim a fix, where the later one rewrote the earlier one's lines and
the model, checked against git, says it's the same bug. It's a lead worth reading, not a verdict. Same-day
follow-ups are skipped, and so are commits about typos, docs, formatting, and reverts, and pairs where the
shared lines are only docs, tests or changelogs.

## How good is the judge?

`eval.py` asks the model about 8 pairs from click and requests that a person labelled by reading both
commits: 2 real ghosts, 2 fixes that caused a new bug, 4 different problems. Results on one PC:

| Model | Diffs shown | Real ghosts found | False ghosts |
|---|---|---|---|
| gemma3:4b | yes | 2 of 2 | 5 of 6 |
| gemma3:4b | no | 1 of 2 | 2 of 6 |
| gemma3:12b | no | 2 of 2 | 4 of 6 |
| gemma3:12b | yes | 2 of 2 | 1 of 6 |

Eight pairs is a small set, and the prompts were tuned while looking at it, so treat these as a sanity
check, not a benchmark. In the last row, most false ghosts were stopped by the second ask, not the first.

On real runs (click and requests, top 12 each) Gemma 3 12B called 14 ghosts: by hand, 1 is clearly real,
6 might be, 7 are not. See [HAND_CHECK.md](HAND_CHECK.md). Read ghosts as leads, and trust the git receipt
most.

## Self-test (no model needed)

```
python tests/test_ghosts.py
```

It builds a tiny repo where a bug comes back, and plays the model with a fake Ollama server.

MIT licensed. Built for the DEV Hacktoberfest "Ghost in the Machine" challenge, with help from Claude Code.
