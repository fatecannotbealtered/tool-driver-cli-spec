"""The reply to a write is lost after dispatch: run the lookup before anything else; the change lands once."""

SCENARIO = "lost_reply"
COMMANDS = ["part move", "operation resolve"]
TURNS = ["Move part R1 on board.fake to x 5 mm."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def before(run, turn):
    run.host("fault", rule={"method": "apply", "command": "part move", "action": "close", "apply_first": True})


def grade(run):
    calls = run.calls
    lost = [i for i, c in enumerate(calls) if c.code == "E_OUTCOME_UNKNOWN"]
    run.check(lost, "the write never reported an unknown outcome")
    if lost:
        operation = calls[lost[0]].details.get("receipt", {}).get("operation_id")
        after = calls[lost[0] + 1:lost[0] + 2]
        run.check(after and after[0].command == "operation resolve" and after[0].value("--id") == operation,
                  f"the next call after the unknown outcome was {after[0] if after else 'none'}, not the lookup of {operation}")
    run.check(len(run.applied("part move")) == 1, f"the move reached the application {len(run.applied('part move'))} times")
    run.check(run.document("doc-1")["objects"]["R1"] == {"x_mm": 5.0}, "R1 is not at x 5 mm")


def right(agent, turn):
    out = agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
    resolved = agent.line(out.details["lookup"])
    outcome = resolved.data["receipt"]["outcome"] if resolved.ok else {}
    agent.say(f"The reply was lost, so I looked the operation up instead of sending the move again. "
              f"Changed: R1 moved to x 5 mm ({outcome.get('change')}).\nSaved: no.\nVerified: {outcome.get('verification')}.")


def wrong(agent, turn):
    out = agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
    agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
    agent.line(out.details["lookup"])
    agent.say("Changed: R1 moved to x 5 mm.")
