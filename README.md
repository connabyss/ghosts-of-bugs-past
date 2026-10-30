# Ghosts of bugs past

Some bugs don't stay dead. A commit says "fixed", the bug gets buried, and months later another commit
says "fix it again". This tool digs those up.

- **Git finds the suspects.** For every commit that says it fixes something, `git blame` checks whose
  lines it rewrote. If those lines came from an *earlier* fix, the earlier fix may not have held.
- **A local open model judges.** Gemma (through [Ollama](https://ollama.com), on your own machine) reads
  both commit messages and both diffs, and says whether it's the same bug coming back.
- **A plain checker keeps the model honest.** It must quote both commit messages word for word, and it may
  not invent numbers. If it fails, it gets one retry with the reason, then the answer is dropped.
- **It has to say it both ways.** A "same bug" answer only counts if the model also says "not different
  bugs" when asked the opposite question. The first version skipped this, and Gemma called all 15 suspects
  in click a ghost.

Your code never leaves your machine.

## Run it

You need Python 3.9+, git, and Ollama.

```
ollama pull gemma3:4b
git clone https://github.com/pallets/click
python ghosts.py click
```

It prints each ghost and writes a graveyard page, `ghosts_click.html`.

Options: `--model gemma3:12b` (a bigger model), `--max 30` (how many suspects to ask about),
`--last 200` (only the last 200 fix commits).

## What a ghost means, and what it doesn't

A ghost means two commits that both claim a fix, where the later one rewrote the earlier one's lines and
the model, checked against git, says it's the same bug. It's a lead worth reading, not a verdict. Same-day
follow-ups are skipped, and so are commits about typos, docs, formatting, and reverts, and pairs where the
shared lines are only docs, tests or changelogs.

## Self-test (no model needed)

```
python tests/test_ghosts.py
```

It builds a tiny repo where a bug comes back, and plays the model with a fake Ollama server.

MIT licensed. Built for the DEV Hacktoberfest "Ghost in the Machine" challenge, with help from Claude Code.
