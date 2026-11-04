"""A dialog blocks the application: pass the action to the person, then run the command once they are done."""

SCENARIO = "blocking_dialog"
COMMANDS = ["part move"]
TURNS = ["Move part R1 on board.fake to x 5 mm.", "I closed the dialog. Please go on."]
FAKE_HOST = {"files": [], "instances": [{"id": "fake-1", "documents": [
    {"id": "doc-1", "name": "board.fake", "objects": {"R1": {"x_mm": 1.0}}}]}]}


def before(run, turn):
    if turn == 0:
        run.host("set_session", session="fake-1", state="blocked", title="License expires in 3 days", action="dismiss_dialog")
    else:
        run.notes["applied_while_blocked"] = run.applied()
        run.host("set_session", session="fake-1", state="ready")


def grade(run):
    # The Agent may see the dialog in `session list` or in an error; either way it tells the person.
    run.check(run.said("license", turn=0) or run.said("dialog", turn=0) or run.said("弹窗", turn=0),
              "the first answer does not pass the dialog on to the person")
    run.check(not run.notes.get("applied_while_blocked"), "a change reached the application while the dialog was open")
    run.check(len(run.applied("part move")) == 1, f"the move reached the application {len(run.applied('part move'))} times")
    run.check(run.document("doc-1")["objects"]["R1"] == {"x_mm": 5.0}, "R1 is not at x 5 mm after the person closed the dialog")


def right(agent, turn):
    if turn == 0:
        session = agent.run("session", "list").data["items"][0]
        agent.say(f"Nothing changed yet: FakeApp shows the dialog \"{session['blocker']['title']}\". Please close it "
                  "and tell me when you are done.")
    else:
        agent.run("part", "move", "--session", "fake-1", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        agent.say("Changed: R1 moved to x 5 mm.\nSaved: no.\nVerified: yes.")


def wrong(agent, turn):
    if turn == 0:
        for _ in range(3):
            agent.run("part", "move", "--doc", "doc-1", "--id", "R1", "--x", "5mm")
        agent.say("FakeApp did not take the change; it seems to be stuck.")
    else:
        agent.say("Good. Anything else?")
