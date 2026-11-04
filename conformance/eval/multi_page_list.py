"""A list longer than one page: the answer covers every page."""
import re

SCENARIO = "multi_page_list"
COMMANDS = ["part list"]
TURNS = ["Which parts on board.fake have the value DNP? List them all."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [{"id": "doc-1", "name": "board.fake"}]}]}
DNP = ["R4", "R23", "R38", "R44"]


def before(run, turn):
    items = [{"id": f"R{n}", "value": "DNP" if f"R{n}" in DNP else f"{n}k"} for n in range(1, 46)]
    run.host("fault", rule={"method": "read", "command": "part list", "action": "result", "times": 0,
                            "result": {"result": {"items": items}}})


def grade(run):
    named = set(re.findall(r"\bR\d+\b", run.messages[-1]))
    run.check(set(DNP) <= named, f"the answer misses {sorted(set(DNP) - named)}")
    run.check(not run.write_calls(), f"a write command ran: {run.write_calls()}")


def right(agent, turn):
    found, offset = [], 0
    while offset is not None:
        page = agent.run("part", "list", "--doc", "doc-1", "--offset", str(offset)).data
        found += [p["id"] for p in page["items"] if p["value"] == "DNP"]
        offset = page.get("next_offset") if page["has_more"] else None
    agent.say(f"The parts with the value DNP are {', '.join(found)}.")


def wrong(agent, turn):
    page = agent.run("part", "list", "--doc", "doc-1").data
    found = [p["id"] for p in page["items"] if p["value"] == "DNP"]
    agent.say(f"The parts with the value DNP are {', '.join(found)}.")
