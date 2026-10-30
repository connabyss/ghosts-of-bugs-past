"""Score the judge on pairs a person labelled by reading both commits.

Usage: python eval.py path/to/clones [--model gemma3:4b]
The folder must hold clones of pallets/click and psf/requests.
"""
import argparse
import os
import sys

import ghosts

# (repo, earlier, later, label, why the label). Labelled by hand from the commit messages and diffs.
LABELS = [
    ("click", "19fd4d6", "c353590", ghosts.SAME,
     'later message: "Fix regression introduced in 8.4.0 by #3126 and properly fix #3043"'),
    ("requests", "c3e6c41", "5296b8b", ghosts.SAME,
     'later message: "use the current fix versus the old fix, which was broken"'),
    ("click", "0f71fe7", "7d05a59", ghosts.CAUSED,
     "later message: deferring set_parameter_source() in 0f71fe7 made get_parameter_source() return None"),
    ("requests", "edc68a0", "fc8fa1a", ghosts.CAUSED,
     'later message: "Fix regression from #2844 regarding binary bodies"'),
    ("click", "91de59c", "955ca49", ghosts.DIFFERENT, "a cleanup of the same fix: comments, docs, tests"),
    ("click", "812b800", "2468b70", ghosts.DIFFERENT, "empty prompt_suffix vs readline backspace on Linux"),
    ("click", "c4c9eb2", "82f9c62", ghosts.DIFFERENT, "progress bar speed-up vs fixing a test"),
    ("click", "92c8053", "65da5cc", ghosts.DIFFERENT,
     "completion of chained-command arguments vs completion with required options"),
]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("clones")
    ap.add_argument("--model", default="gemma3:12b")
    ap.add_argument("--no-diffs", action="store_true", help="judge from commit messages only")
    args = ap.parse_args(argv)
    ghosts.SHOW_DIFFS = not args.no_diffs
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    pairs = {}
    for name in sorted({r for r, *_ in LABELS}):
        repo = os.path.join(args.clones, name)
        for p in ghosts.find_suspects(repo, ghosts.fix_commits(repo)):
            pairs[(name, p["earlier"]["sha"][:7], p["later"]["sha"][:7])] = (repo, p)
    right = ghost_hits = ghost_false = 0
    for name, e, l, label, why in LABELS:
        repo, p = pairs[(name, e, l)]
        trace = []
        answer, how = ghosts.judge(repo, args.model, p, trace)
        got = answer["verdict"] if answer else "dropped"
        called_ghost = bool(answer and answer["same_bug"])
        right += got == label or (label != ghosts.SAME and not called_ghost and got == "dropped")
        ghost_hits += called_ghost and label == ghosts.SAME
        ghost_false += called_ghost and label != ghosts.SAME
        print(f"{'OK  ' if (called_ghost == (label == ghosts.SAME)) else 'MISS'} {name} {e}->{l}"
              f"  label: {label}  model: {got}  ({how})")
        for t in trace:
            print(f"      said: {t.get('verdict')} | {t.get('why', '')}")
    n_ghosts = sum(1 for *_, label, _ in LABELS if label == ghosts.SAME)
    print(f"\n{args.model}, diffs {'off' if args.no_diffs else 'on'}: ghosts found {ghost_hits} of {n_ghosts}, "
          f"false ghosts {ghost_false} of {len(LABELS) - n_ghosts}.")


if __name__ == "__main__":
    main()
