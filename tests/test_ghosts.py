"""Self-test, no model needed: builds a tiny repo with a bug that comes back,
and answers for the model with a fake Ollama server."""
import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import ghosts  # noqa: E402


def run(repo, *args, date=None):
    env = dict(os.environ, GIT_AUTHOR_NAME="Ann", GIT_AUTHOR_EMAIL="a@x",
               GIT_COMMITTER_NAME="Ann", GIT_COMMITTER_EMAIL="a@x")
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def commit(repo, text, msg, date):
    with open(os.path.join(repo, "app.py"), "w") as f:
        f.write(text)
    run(repo, "add", "app.py")
    run(repo, "commit", "-m", msg, date=date)


def make_repo():
    repo = tempfile.mkdtemp()
    run(repo, "init", "-q")
    commit(repo, "def size(x):\n    return len(x)\n", "Add size helper", "2024-01-01T00:00:00")
    commit(repo, "def size(x):\n    if x is None:\n        return 0\n    return len(x)\n",
           "Fix crash when x is None", "2024-02-01T00:00:00")
    commit(repo, "def size(x):\n    if not x:\n        return 0\n    return len(x)\n",
           "Fix crash on empty input again", "2024-06-01T00:00:00")
    commit(repo, "def size(x):\n    if not x:\n        return 0\n    return len(x)\n# fix typo\n",
           "Fix typo", "2024-07-01T00:00:00")
    return repo


class Fake(BaseHTTPRequestHandler):
    answers = []

    def do_POST(self):
        self.rfile.read(int(self.headers["Content-Length"]))
        body = json.dumps({"response": json.dumps(Fake.answers.pop(0))}).encode()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def test_finds_the_suspect():
    repo = make_repo()
    fixes = ghosts.fix_commits(repo)
    assert [c["subject"] for c in fixes.values()] == [
        "Fix crash when x is None", "Fix crash on empty input again"]  # "Fix typo" is boring
    sus = ghosts.find_suspects(repo, fixes)
    assert len(sus) == 1
    assert sus[0]["earlier"]["subject"] == "Fix crash when x is None"
    assert sus[0]["later"]["subject"] == "Fix crash on empty input again"
    assert sus[0]["files"] == {"app.py"}


def test_checker():
    repo = make_repo()
    p = ghosts.find_suspects(repo, ghosts.fix_commits(repo))[0]
    good = dict(same_bug=True, verdict=ghosts.SAME, bug_earlier="crash", bug_later="crash",
                quote_earlier="crash when x is None", quote_later="empty input again",
                why="Both fix the same crash.", epitaph="It never stayed dead.")
    assert ghosts.check(good, p) == []
    bad = dict(good, quote_earlier="crash when x is missing", why="It came back after 3,527 years.")
    problems = ghosts.check(bad, p)
    assert any("quote_earlier" in x for x in problems)
    assert any("3" in x for x in problems)


GOOD = dict(verdict=ghosts.SAME, bug_earlier="crash on None", bug_later="crash on empty input",
            quote_earlier="Fix crash when x is None", quote_later="crash on empty input",
            why="Both fix a crash on missing input.", epitaph="Buried twice, still restless.")


def run_main(repo, answers):
    Fake.answers = list(answers)
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    ghosts.OLLAMA_URL = f"http://127.0.0.1:{srv.server_port}"
    out = tempfile.mkdtemp()
    cwd = os.getcwd()
    os.chdir(out)
    try:
        ghosts.main([repo])
    finally:
        os.chdir(cwd)
        srv.shutdown()
    assert Fake.answers == []
    return open(os.path.join(out, f"ghosts_{os.path.basename(repo)}.html"), encoding="utf-8").read()


def test_end_to_end_with_retry():
    # First answer fails the checker, the retry passes, the flipped question agrees.
    page = run_main(make_repo(), [dict(GOOD, quote_later="made up words"), GOOD,
                                  dict(verdict=ghosts.SAME, why="Same crash.")])
    assert "Buried twice, still restless." in page and "after one retry" in page
    assert 'the later message says &quot;again&quot;' in page  # "Fix crash on empty input again"


def test_flip_disagrees_drops_the_ghost():
    page = run_main(make_repo(), [GOOD, dict(verdict=ghosts.DIFFERENT, why="Two different bugs.")])
    assert "No ghosts" in page


def test_docs_and_tests_only_are_not_suspects():
    assert ghosts.NOT_CODE.search("docs/index.rst") and ghosts.NOT_CODE.search("tests/test_x.py")
    assert ghosts.NOT_CODE.search("CHANGES.rst") and ghosts.NOT_CODE.search("src/pkg/test_util.py")
    assert not ghosts.NOT_CODE.search("src/click/core.py")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
