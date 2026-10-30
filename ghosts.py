"""Ghosts of bugs past: find bugs that were "fixed", then came back.

Git finds the suspects: a fix commit that rewrites lines an earlier fix wrote.
A local open model (Gemma, through Ollama) reads both commits and says whether
it is the same bug coming back. A plain checker then makes the model quote both
commit messages word for word, and drops any answer that invents a number.

Usage: python ghosts.py [path/to/repo] [--model gemma3:4b] [--max 30]
"""
import argparse
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone

FIX_WORDS = re.compile(
    r"\b(fix|fixes|fixed|fixing|bugfix|hotfix|bug|regression|crash|crashes)\b", re.I)
BORING = re.compile(
    r"\b(typo|typos|lint|linting|format|formatting|whitespace|style|docs?|readme|"
    r"changelog|comment|comments|spelling|ci|deps|dependencies|bump)\b", re.I)
SKIP_START = re.compile(r"^(revert|merge)\b", re.I)
NOT_CODE = re.compile(
    r"(^|/)(docs?|tests?|testing|examples?)/|(^|/)test_[^/]*$|_test\.\w+$|\.(rst|md|txt|cfg|toml|ini|ya?ml|json|lock)$"
    r"|(^|/)(CHANGES|CHANGELOG|HISTORY|NEWS|README)[^/]*$", re.I)
OLLAMA_URL = os.environ.get("GHOSTS_OLLAMA_URL", "http://localhost:11434")


def git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args], capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(out.stderr.decode("utf-8", "replace").strip())
    return out.stdout.decode("utf-8", "replace")


def is_fix(subject):
    return (bool(FIX_WORDS.search(subject)) and not BORING.search(subject)
            and not SKIP_START.match(subject.strip()))


def fix_commits(repo):
    """All non-merge commits whose subject claims a fix, oldest first."""
    log = git(repo, "log", "--no-merges", "--reverse",
              "--format=%H%x1f%P%x1f%an%x1f%at%x1f%s%x1f%b%x1e")
    commits = {}
    for rec in log.split("\x1e"):
        rec = rec.strip("\n")
        if not rec:
            continue
        sha, parents, author, ts, subject, body = (rec.split("\x1f") + [""] * 6)[:6]
        if not parents or not is_fix(subject):
            continue
        commits[sha] = dict(sha=sha, parent=parents.split()[0], author=author,
                            when=int(ts), subject=subject.strip(), body=body.strip())
    return commits


HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def changed_old_lines(repo, c):
    """(path, start, count) of every block of old lines this commit replaced."""
    diff = git(repo, "diff", "-U0", "--no-color", "-M", c["parent"], c["sha"])
    path, blocks = None, []
    for line in diff.splitlines():
        if line.startswith("--- "):
            path = None if line[4:] == "/dev/null" else line[6:]
        elif line.startswith("@@") and path:
            m = HUNK.match(line)
            start, count = int(m.group(1)), int(m.group(2) or 1)
            if count > 0:
                blocks.append((path, start, count))
    return blocks


def blame_owners(repo, c, path, start, count):
    """Which commits wrote these old lines, as seen just before this commit."""
    try:
        out = git(repo, "blame", "-w", "--line-porcelain",
                  "-L", f"{start},+{count}", c["parent"], "--", path)
    except RuntimeError:
        return Counter()
    owners = Counter()
    for line in out.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ \d+", line)
        if m:
            owners[m.group(1)] += 1
    return owners


def find_suspects(repo, fixes, last=None):
    """Pairs (earlier fix, later fix) where the later fix rewrote the earlier fix's lines."""
    pairs = {}
    order = list(fixes.values())
    if last:
        order = order[-last:]
    for later in order:
        for path, start, count in changed_old_lines(repo, later):
            for sha, n in blame_owners(repo, later, path, start, count).items():
                if sha == later["sha"] or sha not in fixes:
                    continue
                key = (sha, later["sha"])
                p = pairs.setdefault(key, dict(earlier=fixes[sha], later=later,
                                               lines=0, files=set()))
                p["lines"] += n
                p["files"].add(path)
    # Same-day follow-ups are usually "oops, finish the fix", not a bug coming back.
    # Only code counts: docs and tests get rewritten all the time without a bug coming back.
    out, seen = [], set()
    for p in sorted(pairs.values(), key=lambda p: -p["lines"]):
        if p["later"]["when"] - p["earlier"]["when"] <= 24 * 3600:
            continue
        if not any(not NOT_CODE.search(f) for f in p["files"]):
            continue
        # The same change landed twice (e.g. on two branches): keep one.
        key = (p["earlier"]["sha"], p["later"]["subject"], p["lines"])
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    out.sort(key=lambda p: -p["lines"])
    return out


def commit_diff(repo, c, files, limit=60):
    text = git(repo, "diff", "-U1", "--no-color", c["parent"], c["sha"], "--", *sorted(files))
    lines = text.splitlines()
    return "\n".join(lines[:limit]) + ("\n[... cut ...]" if len(lines) > limit else "")


def message(c):
    return (c["subject"] + ("\n\n" + c["body"] if c["body"] else ""))[:1500]


# Small models lean towards "true" on yes/no questions, so the verdict is a choice of
# phrases, and the second ask lists them in the opposite order. "The fix caused a new bug"
# gets its own choice: without it, the model files those under "same bug".
SAME, CAUSED, DIFFERENT = "same bug came back", "the fix caused a new bug", "different problem"
VERDICTS = [DIFFERENT, CAUSED, SAME]
SCHEMA = {
    "type": "object",
    "properties": {
        "bug_earlier": {"type": "string"},
        "bug_later": {"type": "string"},
        "quote_earlier": {"type": "string"},
        "quote_later": {"type": "string"},
        "verdict": {"type": "string", "enum": VERDICTS},
        "why": {"type": "string"},
        "epitaph": {"type": "string"},
    },
    "required": ["bug_earlier", "bug_later", "quote_earlier", "quote_later",
                 "verdict", "why", "epitaph"],
}
FLIP_SCHEMA = {
    "type": "object",
    "properties": {"verdict": {"type": "string", "enum": VERDICTS[::-1]},
                   "why": {"type": "string"}},
    "required": ["verdict", "why"],
}
CONFESSION = re.compile(r"\b(regression|regressed|again|properly|re-?fix|broke|broken|still|reintroduced|"
                        r"did not|didn't|incomplete)\b", re.I)


def receipt(p):
    """What git itself says: does the later message point back at the earlier fix?"""
    e, l = p["earlier"], p["later"]
    later = message(l)
    refs = set(re.findall(r"#\d+", message(e))) & set(re.findall(r"#\d+", later))
    if e["sha"][:7] in later:
        return f'the later message names commit {e["sha"][:7]}'
    if refs:
        return "both messages mention " + ", ".join(sorted(refs))
    m = CONFESSION.search(later)
    if m:
        return f'the later message says "{m.group(0)}"'
    return ""


SHOW_DIFFS = True  # off: the model judges from the two commit messages alone


def evidence(repo, p):
    e, l = p["earlier"], p["later"]
    parts = ["Two commits from one git project, in time order. Both touch the same code.",
             "EARLIER COMMIT MESSAGE:\n" + message(e)]
    if SHOW_DIFFS:
        parts.append("EARLIER COMMIT CHANGES:\n" + commit_diff(repo, e, p["files"]))
    parts.append("LATER COMMIT MESSAGE:\n" + message(l))
    if SHOW_DIFFS:
        parts.append("LATER COMMIT CHANGES:\n" + commit_diff(repo, l, p["files"]))
    return "\n\n".join(parts) + "\n"


def build_prompt(repo, p, feedback=""):
    return evidence(repo, p) + f"""
Most pairs like this are NOT the same bug: code gets touched again for new features,
cleanups, tests, or a different bug nearby. Be strict.

Reply in JSON:
- bug_earlier: in a few words, the broken behavior the EARLIER commit fixed
- bug_later: in a few words, the broken behavior the LATER commit fixed
- quote_earlier: a short phrase copied word for word from the EARLIER COMMIT MESSAGE
- quote_later: a short phrase copied word for word from the LATER COMMIT MESSAGE
- verdict, one of:
  "{DIFFERENT}": they fix different broken behaviors, or one is not really a bug fix
  "{CAUSED}": the earlier fix worked, but it broke something else, which the later commit fixes
  "{SAME}": bug_earlier and bug_later are the same broken behavior, so the earlier
  fix did not hold (it was incomplete or wrong)
- why: one plain sentence explaining your answer
- epitaph: one short spooky gravestone line for the bug (no numbers, no names)
{feedback}"""


def build_flip_prompt(repo, p):
    return evidence(repo, p) + f"""
Pick one:
- "{SAME}": the later commit fixes the very same broken behavior again, because the
  earlier fix did not hold.
- "{CAUSED}": the earlier fix worked, but it broke something else, which the later
  commit fixes.
- "{DIFFERENT}": they fix different broken behaviors, or one is not really a bug fix.

Reply in JSON: verdict (one of the three phrases above), why (one plain sentence).
"""


def ask_model(model, prompt, schema=SCHEMA):
    """The model's JSON answer, plus same_bug worked out from its verdict."""
    req = urllib.request.Request(
        OLLAMA_URL + "/api/generate",
        data=json.dumps({"model": model, "prompt": prompt, "format": schema, "stream": False,
                         "options": {"temperature": 0, "seed": 42}}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        answer = json.loads(json.loads(r.read())["response"])
    answer["same_bug"] = answer.get("verdict") == SAME
    return answer


def norm(s):
    return re.sub(r"\s+", " ", s.strip().strip("\"'").lower())


def check(answer, p):
    """Problems with the model's answer, judged only against git. Empty list = it holds."""
    problems = []
    for key, c in (("quote_earlier", p["earlier"]), ("quote_later", p["later"])):
        q = norm(str(answer.get(key, "")))
        if len(q) < 4 or q not in norm(message(c)):
            problems.append(f"{key} must be copied word for word from that commit message")
    facts = message(p["earlier"]) + message(p["later"])
    for key in ("why", "epitaph"):
        for num in re.findall(r"\d+", str(answer.get(key, ""))):
            if num not in facts:
                problems.append(f'{key} uses the number {num}, which is not in either message')
    if answer.get("verdict") not in VERDICTS:
        problems.append("verdict must be one of: " + ", ".join(f'"{v}"' for v in VERDICTS))
    return problems


def judge(repo, model, p, trace=None):
    """Ask once; on a failed check, ask again with the reason. Returns (answer, path).
    Every raw model answer is appended to trace, so a run can be read back later."""
    trace = [] if trace is None else trace
    answer = ask_model(model, build_prompt(repo, p))
    trace.append(answer)
    problems = check(answer, p)
    how = "first try"
    if problems:
        feedback = "\nYour last answer was rejected: " + "; ".join(problems) + ". Fix that."
        answer = ask_model(model, build_prompt(repo, p, feedback))
        trace.append(answer)
        if check(answer, p):
            return None, "dropped: failed the checker twice"
        how = "after one retry"
    if answer["same_bug"]:
        # Ask the opposite question. A ghost only counts if the model says the same thing both ways.
        flip = ask_model(model, build_flip_prompt(repo, p), FLIP_SCHEMA)
        trace.append(flip)
        if not flip["same_bug"]:
            return None, f"dropped: said 'same bug', then '{flip.get('verdict')}' when asked again"
        how += ", same answer when asked the other way"
    return answer, how


def day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def tombstone(p, answer, model):
    e, l = p["earlier"], p["later"]
    days = (l["when"] - e["when"]) // 86400
    return "\n".join([
        f'  BURIED    {day(e["when"])}  {e["sha"][:7]}  "{e["subject"]}"  ({e["author"]})',
        f'  RETURNED  {day(l["when"])}  {l["sha"][:7]}  "{l["subject"]}"  ({l["author"]})',
        f'  {days} days in the grave. The second fix rewrote {p["lines"]} line(s) the first one wrote,',
        f'  in {", ".join(sorted(p["files"]))}.',
        f'  {model}: {answer["why"]}',
        f'  Git receipt: {receipt(p) or "none, the later message does not point back"}',
        f'  "{answer["epitaph"]}"',
    ])


def write_html(path, repo_name, ghosts):
    stones = []
    for p, answer, how in ghosts:
        e, l = p["earlier"], p["later"]
        stones.append(f"""<div class="stone"><div class="rip">R.I.P.</div>
<div class="sub">{html.escape(e["subject"])}</div>
<div class="dates">{day(e["when"])} &ndash; {day(l["when"])}</div>
<div class="epi">&ldquo;{html.escape(answer["epitaph"])}&rdquo;</div>
<div class="why">Came back as: {html.escape(l["subject"])}<br>{html.escape(answer["why"])}</div>
<div class="sha">{e["sha"][:7]} &rarr; {l["sha"][:7]} &middot; {how}</div>
<div class="sha">{html.escape(receipt(p) or "no git receipt")}</div></div>""")
    body = "\n".join(stones) or "<p>No ghosts. Every fix stayed buried.</p>"
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"""<!doctype html><meta charset="utf-8"><title>Ghosts of bugs past</title>
<style>body{{background:#0d0f14;color:#ddd;font-family:Georgia,serif;margin:0;padding:24px}}
h1{{text-align:center;color:#e8a33d;font-weight:normal}}.g{{display:flex;flex-wrap:wrap;gap:24px;justify-content:center}}
.stone{{width:280px;background:linear-gradient(#5b5f68,#3a3d44);border-radius:120px 120px 8px 8px;padding:40px 22px 18px;
text-align:center;box-shadow:0 10px 0 #23251f}}.rip{{font-size:28px;letter-spacing:4px;color:#f3f3f3}}
.sub{{margin:10px 0;font-size:15px}}.dates{{color:#c9c9c9;font-size:13px}}.epi{{margin:14px 0;font-style:italic;color:#ffe2a8}}
.why{{font-size:12px;color:#d4d4d4;font-family:system-ui,sans-serif}}.sha{{margin-top:10px;font-size:11px;color:#a8acb3;font-family:monospace}}</style>
<h1>Ghosts of bugs past &middot; {html.escape(repo_name)}</h1><div class="g">{body}</div>""")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Find bugs that were fixed, then came back.")
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--model", default="gemma3:4b")
    ap.add_argument("--max", type=int, default=30, help="most suspects to ask the model about")
    ap.add_argument("--last", type=int, default=None, help="only look at the last N fix commits")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    repo = os.path.abspath(args.repo)
    name = os.path.basename(repo.rstrip("/\\"))
    fixes = fix_commits(repo)
    print(f"{name}: {len(fixes)} commits say they fix something. Digging...")
    suspects = find_suspects(repo, fixes, args.last)
    print(f"{len(suspects)} later fixes rewrote an earlier fix's lines. "
          f"Asking {args.model} about the top {min(args.max, len(suspects))}.\n")

    ghosts, dropped, log = [], 0, []
    for i, p in enumerate(suspects[:args.max], 1):
        print(f"[{i}] {p['earlier']['sha'][:7]} -> {p['later']['sha'][:7]} ...", end=" ", flush=True)
        trace = []
        try:
            answer, how = judge(repo, args.model, p, trace)
        except (urllib.error.URLError, ConnectionError) as err:
            sys.exit(f"\nCan't reach Ollama at {OLLAMA_URL} ({err}). Is it running? "
                     f"Try: ollama pull {args.model}")
        verdict = how if answer is None else ("GHOST" if answer["same_bug"] else answer["verdict"])
        log.append(dict(earlier=p["earlier"]["sha"][:7], earlier_subject=p["earlier"]["subject"],
                        later=p["later"]["sha"][:7], later_subject=p["later"]["subject"],
                        lines=p["lines"], files=sorted(p["files"]), receipt=receipt(p),
                        verdict=verdict, model_said=trace))
        if answer is None:
            dropped += 1
            print(how)
        elif answer["same_bug"]:
            ghosts.append((p, answer, how))
            print("GHOST")
        else:
            print(answer["verdict"])

    print()
    for p, answer, how in ghosts:
        print("GHOST " + "-" * 60 + "\n" + tombstone(p, answer, args.model) + "\n")
    print(f"{len(ghosts)} ghost(s) found. {dropped} answer(s) dropped by the checker.")
    out = os.path.join(os.getcwd(), f"ghosts_{name}.html")
    write_html(out, name, ghosts)
    print(f"Graveyard: {out}")
    log_path = os.path.join(os.getcwd(), f"ghosts_{name}_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(dict(repo=name, model=args.model, suspects=log), f, indent=1, ensure_ascii=False)
    print(f"Everything the model said: {log_path}")


if __name__ == "__main__":
    main()
