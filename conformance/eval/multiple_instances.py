"""Several instances are open: the change lands in the one the user meant."""

SCENARIO = "multiple_instances"
COMMANDS = ["part move", "session list"]
TURNS = ["Move part R1 on panel.fake to x 5 mm."]
FAKE_HOST = {"files": [], "instances": [
    {"id": "fake-1", "documents": [{"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]},
    {"id": "fake-2", "documents": [{"id": "doc-2", "name": "panel.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def grade(run):
    run.check(run.document("doc-2")["objects"]["R1"] == {"x_mm": 5.0}, "R1 on panel.fake is not at x 5 mm")
    run.check(run.document("doc-1")["objects"]["R1"] == {"x_mm": 1.0}, "R1 on board.fake changed")


def right(agent, turn):
    sessions = agent.run("session", "list").data["items"]
    session = next(s["id"] for s in sessions if any(d["path"].endswith("panel.fake") for d in s["documents"]))
    agent.run("part", "move", "--session", session, "--doc", "doc-2", "--id", "R1", "--x", "5mm")
    agent.say(f"Changed: R1 on panel.fake (instance {session}) moved to x 5 mm.\nSaved: no.\nVerified: yes.")


def wrong(agent, turn):
    agent.run("part", "move", "--session", "fake-1", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
    agent.say("Changed: R1 moved to x 5 mm.")
