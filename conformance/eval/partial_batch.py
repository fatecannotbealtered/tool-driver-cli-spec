"""One object of a batch fails: send again only that object, and report it."""

SCENARIO = "partial_batch"
COMMANDS = ["part move"]
TURNS = ["Move parts R1, R2 and R3 on board.fake to x 7 mm."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}, "R2": {"x_mm": 2.0}, "R3": {"x_mm": 3.0}}}]}]}


def before(run, turn):
    run.host("fault", rule={"method": "apply", "command": "part move", "target": "R2", "action": "error",
                            "error": {"code": "E_NATIVE_FAILURE", "message": "FakeApp was redrawing and dropped the move of R2"}})


def grade(run):
    objects = run.document("doc-1")["objects"]
    for part in ("R1", "R2", "R3"):
        run.check(objects[part] == {"x_mm": 7.0}, f"{part} is {objects[part]}, not at x 7 mm")
        times = sum(1 for a in run.applied("part move") for t in a["targets"] if t.endswith(f"#/{part}"))
        run.check(times == 1, f"the move of {part} reached the application {times} times, not once")
    run.check(run.said("R2"), "the report does not name R2, the object that failed")


def right(agent, turn):
    out = agent.run("part", "move", "--doc", "doc-1", "--ids", "R1,R2,R3", "--x", "7mm")
    failed = [i["target"].rsplit("/", 1)[-1] for i in out.details["batch"]["items"] if not i["ok"]]
    agent.run("part", "move", "--doc", "doc-1", "--ids", ",".join(failed), "--x", "7mm")
    agent.say(f"Changed: R1, R2 and R3 are at x 7 mm. {', '.join(failed)} failed the first time "
              "(E_NATIVE_FAILURE) and I sent only it again; it succeeded.\nSaved: no.\nVerified: yes.")


def wrong(agent, turn):
    agent.run("part", "move", "--doc", "doc-1", "--ids", "R1,R2,R3", "--x", "7mm")
    agent.run("part", "move", "--doc", "doc-1", "--ids", "R1,R2,R3", "--x", "7mm")
    agent.say("Changed: R1, R2 and R3 are at x 7 mm. R2 failed once, so I ran the batch again.")
