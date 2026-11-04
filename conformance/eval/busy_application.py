"""The application is busy: wait, run the command again, and the change lands once."""
import time

SCENARIO = "busy_application"
COMMANDS = ["part move"]
TURNS = ["Move part R1 on board.fake to x 5 mm."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def before(run, turn):
    run.host("fault", rule={"method": "apply", "command": "part move", "action": "error", "times": 2,
                            "error": {"code": "E_BUSY", "message": "FakeApp is recalculating"}})


def grade(run):
    run.check(len(run.applied("part move")) == 1, f"the move reached the application {len(run.applied('part move'))} times")
    run.check(run.document("doc-1")["objects"]["R1"] == {"x_mm": 5.0}, "R1 is not at x 5 mm")


def right(agent, turn):
    for _ in range(4):
        out = agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        if out.code != "E_BUSY":
            break
        time.sleep(out.details.get("retry_after_ms", 500) / 1000)
    agent.say("Changed: R1 moved to x 5 mm after FakeApp stopped being busy.\nSaved: no.\nVerified: yes.")


def wrong(agent, turn):
    agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
    agent.say("FakeApp is busy, so nothing changed. Try again later.")
