"""The change itself opens a dialog: pass it to the person, then resolve the operation, and never send the write again."""

SCENARIO = "dialog_after_dispatch"
COMMANDS = ["part move", "operation resolve"]
TURNS = ["Move part R1 on board.fake to x 5 mm.", "I clicked OK in the dialog. Please go on."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def before(run, turn):
    if turn == 0:
        run.host("fault", rule={"method": "apply", "command": "part move", "action": "error", "apply_first": True,
                                "error": {"code": "E_HUMAN_REQUIRED", "action": "dismiss_dialog",
                                          "message": "Overlap warning: R1 now overlaps C4"}})


def grade(run):
    run.check(run.said("dialog", turn=0) or run.said("overlap", turn=0) or run.said("弹窗", turn=0),
              "the first answer does not pass the dialog on to the person")
    dialog = [c for c in run.calls if c.turn == 0 and c.code == "E_HUMAN_REQUIRED"]
    run.check(dialog, "the Agent never met the dialog")
    if dialog:
        operation = dialog[-1].details.get("receipt", {}).get("operation_id")
        run.check(any(c.value("--id") == operation for c in run.ran("operation resolve", turn=1)),
                  f"after the person closed the dialog, the Agent did not resolve the operation {operation}")
    run.check(not run.ran("part move", turn=1), "the Agent sent the move again after the dialog")
    run.check(len(run.applied("part move")) == 1, f"the move reached the application {len(run.applied('part move'))} times")


def right(agent, turn):
    if turn == 0:
        out = agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        agent.say(f"The move was sent, then FakeApp opened a dialog: {out.envelope['error']['message']} "
                  "Please close it and tell me; I will not send the move again.")
    else:
        resume = [c for c in agent.calls if c.code == "E_HUMAN_REQUIRED"][-1].details["resume"]
        out = agent.line(resume)
        outcome = out.data["receipt"]["outcome"] if out.ok else {}
        agent.say(f"Changed: R1 moved to x 5 mm ({outcome.get('change')}).\nSaved: no.\nVerified: {outcome.get('verification')}.")


def wrong(agent, turn):
    if turn == 0:
        agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        agent.say("FakeApp opened a dialog. Please close it and tell me.")
    else:
        agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        resume = [c for c in agent.calls if c.code == "E_HUMAN_REQUIRED"][-1].details["resume"]
        agent.line(resume)
        agent.say("Changed: R1 moved to x 5 mm.")
