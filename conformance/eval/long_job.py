"""Work longer than one call: poll the job until it ends, then report how it ended."""
import re

from _report import plain

SCENARIO = "long_job"
COMMANDS = ["analysis run", "job get"]
TURNS = ["Run the analysis of board.fake with depth 3 and tell me how it ended."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}
WORDS = {"completed": r"\bcomplet|\bfinished\b|\bsucceeded\b|\bsuccess|\bdone\b|完成|成功",
         "failed": r"\bfail|失败", "cancelled": r"\bcancel|取消", "unknown": r"\bunknown\b|未知"}


def before(run, turn):
    run.host("fault", rule={"method": "apply", "command": "analysis run", "action": "job", "steps": 3})


def grade(run):
    jobs = run.state()["jobs"]
    run.check(jobs and all(j["state"] != "running" for j in jobs), f"the job has not ended: {[j['state'] for j in jobs]}")
    started = [c for c in run.ran("analysis run") if c.ok and (c.data.get("result") or {}).get("job")]
    run.check(started, "the analysis never started a job")
    if started and jobs:
        job = started[-1].data["result"]["job"]["id"]
        polls = [c for c in run.ran("job get") if c.value("--job") == job]
        run.check(polls and polls[-1].ok and polls[-1].data.get("state") == jobs[-1]["state"],
                  f"the Agent did not poll job {job} until it saw the final state")
        state = jobs[-1]["state"]
        run.check(re.search(WORDS.get(state, re.escape(state)), plain(run.messages[-1])),
                  f"the report does not say that the job ended {state}")


def right(agent, turn):
    out = agent.run("analysis", "run", "--doc", "doc-1", "--depth", "3")
    poll = out.data["result"]["job"]["poll"]
    state = "running"
    for _ in range(20):
        state = agent.line(poll).data["state"]
        if state not in ("running", "cancel_requested"):
            break
    agent.say(f"The analysis job ended with the state {state}.")


def wrong(agent, turn):
    agent.run("analysis", "run", "--doc", "doc-1", "--depth", "3")
    agent.say("The analysis ran and succeeded.")
