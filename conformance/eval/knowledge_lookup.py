"""A question only the knowledge base answers: the answer agrees with the entry the Agent read."""

SCENARIO = "knowledge_lookup"
COMMANDS = ["knowledge search", "knowledge get"]
TURNS = ["In FakeApp, what is the pitch of the placement grid that part positions snap to?"]
FAKE_HOST = {"files": []}


def grade(run):
    run.check(run.said("0.7366"), "the answer does not give the grid pitch of the knowledge entry, 0.7366 mm")
    run.check(any(c.ok and c.value("--id") == "demo-basics" for c in run.ran("knowledge get")),
              "the Agent never read the knowledge entry demo-basics")
    run.check(not run.write_calls(), f"a write command ran: {run.write_calls()}")


def right(agent, turn):
    entry = agent.run("knowledge", "search", "--query", "placement grid").data["items"][0]["id"]
    body = agent.run("knowledge", "get", "--id", entry).stdout
    pitch = "0.7366" if "0.7366 mm" in body else "unknown"
    agent.say(f"The placement grid pitch is {pitch} mm (knowledge entry {entry}).")


def wrong(agent, turn):
    agent.say("FakeApp snaps parts to a 0.635 mm (25 mil) grid.")
