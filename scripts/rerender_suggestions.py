"""Re-render alert suggestions with the code check + template (presentation only).

Rewrites each alert's `suggestion` in an alerts JSONL copy: a text that passes
`agent.explain.check_suggestion` is kept, anything else becomes `suggestion_template` from the
alert's own title ("White: 4-4-2 -> 3-4-3 (16:30)"). Decisions, verdicts, explanations, ids and
statuses are not touched; the agent trace keeps the model's original call as it was.

    py scripts/rerender_suggestions.py samples/w900_1260/alerts_llm.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys

from gaffer.agent.explain import check_suggestion, checked_suggestion
from gaffer.config import repo_path

TITLE_RE = re.compile(r"^(?P<team>.+?): (?P<old>\S+) -> (?P<new>\S+) \(")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("alerts", nargs="+", help="alerts JSONL file(s) to rewrite in place")
    args = ap.parse_args(argv)
    for name in args.alerts:
        path = repo_path(name)
        rows, changed = [], 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            a = json.loads(line)
            m = TITLE_RE.match(a.get("title", ""))
            if m is None:
                print(f"{name}: {a.get('alert_id')}: title not parseable, left as is",
                      file=sys.stderr)
            else:
                problems = check_suggestion(a.get("suggestion", ""), m["old"], m["new"])
                text, source = checked_suggestion(a.get("suggestion", ""), m["team"],
                                                  m["old"], m["new"])
                if text != a.get("suggestion"):
                    changed += 1
                    print(f"{a['alert_id']}: {source} ({'; '.join(problems)})\n"
                          f"  was: {a.get('suggestion')}\n  now: {text}")
                    a["suggestion"] = text
            rows.append(json.dumps(a, ensure_ascii=False))
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        print(f"{name}: {changed} of {len(rows)} suggestion(s) re-rendered")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
