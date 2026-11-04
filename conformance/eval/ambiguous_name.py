"""A name that fits two instances: change nothing until the user picks one, then only that one."""

SCENARIO = "ambiguous_name"
COMMANDS = ["part move"]
TURNS = ["Move part R1 on the board to x 5 mm.", "The one in rev-b.fake."]
FAKE_HOST = {"files": [], "instances": [
    {"id": "fake-1", "documents": [{"id": "doc-a", "name": "rev-a.fake", "objects": {"R1": {"x_mm": 1.0}}}]},
    {"id": "fake-2", "documents": [{"id": "doc-b", "name": "rev-b.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def before(run, turn):
    if turn == 1:
        run.notes["applied_before_answer"] = run.applied()


def grade(run):
    run.check(not run.notes.get("applied_before_answer"), "a change reached the application before the user picked a board")
    run.check(run.said("rev-a", "rev-b", turn=0) or run.said("fake-1", "fake-2", turn=0),
              "the first answer does not name the candidates for the person to pick from")
    run.check(run.document("doc-b")["objects"]["R1"] == {"x_mm": 5.0}, "R1 in rev-b.fake is not at x 5 mm")
    run.check(run.document("doc-a")["objects"]["R1"] == {"x_mm": 1.0}, "R1 in rev-a.fake changed")


def right(agent, turn):
    if turn == 0:
        out = agent.run("part", "move", "--id", "R1", "--x", "5mm")
        names = [f"{c['documents'][0]['path'].replace(chr(92), '/').rsplit('/', 1)[-1]} in {c['id']}"
                 for c in out.details["candidates"]]
        agent.say(f"Two boards are open: {' and '.join(names)}. Which one do you mean? I changed nothing.")
    else:
        agent.run("part", "move", "--session", "fake-2", "--doc", "doc-b", "--id", "R1", "--x", "5mm")
        agent.say("Changed: R1 in rev-b.fake moved to x 5 mm.\nSaved: no.\nVerified: yes.")


def wrong(agent, turn):
    if turn == 0:
        agent.run("part", "move", "--session", "fake-1", "--doc", "doc-a", "--id", "R1", "--x", "5mm")
        agent.say("Changed: R1 in rev-a.fake (fake-1) moved to x 5 mm; rev-b.fake in fake-2 is also open.")
    else:
        agent.run("part", "move", "--session", "fake-2", "--doc", "doc-b", "--id", "R1", "--x", "5mm")
        agent.say("Changed: R1 in rev-b.fake moved to x 5 mm.")
