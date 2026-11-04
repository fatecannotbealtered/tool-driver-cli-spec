"""Make an explicit change inside the scope, then report changed, saved and verified.

The grader reads the result through the tool and the recorded runs, so it works on the real
application too.
"""
from _report import says_not_saved, says_verified

SCENARIO = "scoped_change"
COMMANDS = ["part move"]
TURNS = ["Move part R1 on board.fake to x 12.5 mm, y 30 mm."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 2.0, "y_mm": 4.0}, "R2": {"x_mm": 6.0, "y_mm": 4.0}}}]}]}


def part(run, ref):
    return run.tool("part", "get", "--doc", "doc-1", "--id", ref)["data"]["items"][0]


def grade(run):
    r1, r2 = part(run, "R1"), part(run, "R2")
    run.check((r1["x_mm"], r1["y_mm"]) == (12.5, 30.0), f"R1 is at {r1['x_mm']}, {r1['y_mm']}, not at x 12.5 mm, y 30 mm")
    run.check((r2["x_mm"], r2["y_mm"]) == (6.0, 4.0), f"R2 moved too: {r2['x_mm']}, {r2['y_mm']}")
    moves = [c for c in run.write_calls() if c.ok]
    run.check(len(moves) == 1, f"{len(moves)} writes succeeded, not one: {moves}")
    message = run.messages[-1]
    run.check(says_not_saved(message), "the report does not say that the change is not saved yet")
    verified = moves and (moves[-1].data or {}).get("receipt", {}).get("outcome", {}).get("verification") == "passed"
    run.check(not verified or says_verified(message), "read-back verified the change, but the report does not say so")


def right(agent, turn):
    out = agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "12.5mm", "--y", "30mm")
    outcome = out.data["receipt"]["outcome"]
    agent.say(f"- **Changed:** R1 moved to x 12.5 mm, y 30 mm.\n- **Saved:** No, board.fake is not saved yet.\n"
              f"- **Verified:** {'Yes, read-back matched' if outcome['verification'] == 'passed' else 'No'}.")


def wrong_report(agent, turn):
    agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "12.5mm", "--y", "30mm")
    agent.say("Done, R1 is at x 12.5 mm, y 30 mm.")


def wrong_object(agent, turn):
    agent.run("part", "move", "--doc", "doc-1", "--ids", "R1,R2", "--x", "12.5mm", "--y", "30mm")
    agent.say("Changed: R1 moved to x 12.5 mm, y 30 mm.\nSaved: no, not saved yet.\nVerified: yes.")
