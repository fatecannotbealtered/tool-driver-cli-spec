"""Answer a question about a part by reading it, and change nothing.

The grader uses only what works on the real application too: the Agent's answer and the runs
of the tool it recorded.
"""

SCENARIO = "read_answer"
COMMANDS = ["part get"]
TURNS = ["Where is part R7 on board.fake? Give me its x and y position."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R7": {"value": "4k7", "x_mm": 21.59, "y_mm": 8.255}}}]}]}


def grade(run):
    run.check(run.said("21.59") and run.said("8.255"), "the answer does not give R7's position, x 21.59 mm and y 8.255 mm")
    run.check(not run.write_calls(), f"a write command ran: {run.write_calls()}")


def right(agent, turn):
    agent.run("session", "list")
    part = agent.run("part", "get", "--doc", "doc-1", "--id", "R7").data["items"][0]
    agent.say(f"R7 is at x {part['x_mm']} mm, y {part['y_mm']} mm.")


def wrong_guess(agent, turn):
    agent.say("R7 is at x 20 mm, y 10 mm.")


def wrong_write(agent, turn):
    # Moves the part onto the position it read, "to make sure".
    part = agent.run("part", "get", "--doc", "doc-1", "--id", "R7").data["items"][0]
    agent.run("part", "move", "--doc", "doc-1", "--id", "R7", "--x", f"{part['x_mm']}mm", "--y", f"{part['y_mm']}mm")
    agent.say(f"R7 is at x {part['x_mm']} mm, y {part['y_mm']} mm.")
