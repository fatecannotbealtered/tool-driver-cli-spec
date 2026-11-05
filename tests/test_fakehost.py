"""Tests for the fake host in conformance/fakehost."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "conformance"))

from fakehost import Client, ConnectionClosed, FakeHost, HostCallError, ProtocolMismatch  # noqa: E402
from fakehost.framing import Channel, FramingError  # noqa: E402

CONTRACT = json.loads((ROOT / "contract" / "driver-contract.json").read_text(encoding="utf-8"))

COMMANDS = [
    {
        "path": "footprint move", "summary": "Moves footprints.", "effects": ["change"], "modes": ["file", "session"],
        "target_kind": "footprint", "untrusted_fields": [], "adapter_capabilities": ["preview", "apply", "read_back"],
        "survey_ids": [], "irreversible": False, "halt": False, "tolerances": {"x_mm": 0.001, "y_mm": 0.001},
        "default_fields": [], "related_knowledge": [],
        "flags": [
            {"name": "--x", "type": "number", "quantity": "length"},
            {"name": "--y", "type": "number", "quantity": "length"},
        ],
    },
    {
        "path": "plot export", "summary": "Plots a board.", "effects": ["artifact"], "modes": ["session"],
        "target_kind": "file", "untrusted_fields": [], "adapter_capabilities": ["preview", "apply", "read_back"],
        "survey_ids": [], "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": [], "flags": [{"name": "--to", "type": "path", "output": True}],
    },
    {
        "path": "axis move", "summary": "Moves an axis.", "effects": ["physical"], "modes": ["device"],
        "target_kind": "axis", "untrusted_fields": [], "adapter_capabilities": ["preview", "apply", "read_back"],
        "survey_ids": [], "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": [], "flags": [{"name": "--position", "type": "number", "quantity": "length"}],
    },
    {
        "path": "stop", "summary": "Stops the device.", "effects": ["lifecycle"], "modes": ["device"],
        "target_kind": "device", "untrusted_fields": [], "adapter_capabilities": ["apply"],
        "survey_ids": [], "irreversible": False, "halt": True, "tolerances": {}, "default_fields": [],
        "related_knowledge": [], "flags": [],
    },
]

MOVE = {"command": "footprint move", "inputs": {"id": "R1", "x_mm": 12.5, "y_mm": 30.0}, "session": "fake-1", "document": "doc-1"}


def _validator():
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource

    schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "contract" / "schemas").glob("*.json")}
    registry = Registry().with_resources((s["$id"], Resource.from_contents(s)) for s in schemas.values())
    return lambda name: Draft202012Validator(schemas[name], registry=registry)


VALIDATOR = _validator()


class FramingTest(unittest.TestCase):
    @staticmethod
    def channel(data: bytes, chunk: int = 3) -> tuple[Channel, list[bytes]]:
        stream = {"data": data}
        sent: list[bytes] = []

        def recv(n: int) -> bytes:
            piece, stream["data"] = stream["data"][: min(n, chunk)], stream["data"][min(n, chunk):]
            return piece

        return Channel(recv, sent.append, lambda: None, lambda s: None), sent

    def test_round_trip_in_small_pieces(self):
        writer, sent = self.channel(b"")
        writer.write_message({"a": "ü", "b": [1, 2]})
        writer.write_message({"c": None})
        reader, _ = self.channel(b"".join(sent))
        self.assertEqual(reader.read_message(), {"a": "ü", "b": [1, 2]})
        self.assertEqual(reader.read_message(), {"c": None})
        self.assertIsNone(reader.read_message())

    def test_header_uses_crlf_and_byte_length(self):
        writer, sent = self.channel(b"")
        writer.write_message("ü")
        self.assertEqual(sent[0], b'Content-Length: 4\r\n\r\n"\xc3\xbc"')

    def test_broken_input_is_refused(self):
        for data in (b"Content-Length: x\r\n\r\n{}", b"Content-Length: 2\n\n{}", b"Content-Length: 9\r\n\r\n{}", b"Content-Length: 2\r\n\r\n{]"):
            with self.subTest(data=data):
                reader, _ = self.channel(data)
                with self.assertRaises(FramingError):
                    reader.read_message()


class HostTestCase(unittest.TestCase):
    config: dict | None = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state_dir = Path(self.tmp.name) / "state"
        self.host = FakeHost(self.state_dir, self.config, COMMANDS, workdir=self.tmp.name).start()
        self.addCleanup(self.host.stop)
        self.addCleanup(lambda: self.assertEqual(self.host.world.internal_errors, []))

    def client(self, address: str | None = None, **kwargs) -> Client:
        client = Client(address or self.host.address, **kwargs)
        client.connect()
        self.addCleanup(client.close)
        return client

    def valid(self, capability: str, result: dict) -> dict:
        errors = list(VALIDATOR("adapter.schema.json").iter_errors({"result": {capability: result}}))
        self.assertEqual([e.message for e in errors], [], f"{capability}: {result}")
        return result

    def state(self) -> dict:
        return self.client().control("state")


class MainAddressTest(HostTestCase):
    def test_handshake_and_cli_side_capabilities(self):
        c = self.client()
        self.assertEqual(c.hello["session"], {"id": "fakehost", "generation": 0})
        errors = list(VALIDATOR("host-protocol.schema.json").iter_errors({"jsonrpc": "2.0", "id": 1, "result": c.hello}))
        self.assertEqual(errors, [])
        for capability in ("probe", "sessions", "devices", "plugin_status"):
            self.valid(capability, c.call(capability))
        self.assertEqual(self.state()["violations"], [])

    def test_session_mode_write(self):
        c = self.client()
        preview = self.valid("preview", c.call("preview", MOVE))
        key = preview["targets"][0]["key"]
        self.assertTrue(key.startswith("file:///") and key.endswith("doc-1.fake#/R1"))
        self.assertEqual({(ch["field"], ch["after"]) for ch in preview["changes"]}, {("x_mm", 12.5), ("y_mm", 30.0)})
        applied = self.valid("apply", c.call("apply", {**MOVE, "operation_id": "op_1"}))
        self.assertEqual((applied["change"], applied["persistence"]), ("applied", "unchanged"))
        back = self.valid("read_back", c.call("read_back", {**MOVE, "operation_id": "op_1"}))
        self.assertEqual(back["observed"], {key: {"x_mm": 12.5, "y_mm": 30.0}})
        state = self.state()
        doc = next(d for d in state["documents"] if d["id"] == "doc-1")
        self.assertTrue(doc["dirty"])
        self.assertEqual([a["operation_id"] for a in state["applied"]], ["op_1"])
        self.assertEqual(state["violations"], [])

    def test_file_mode_write_saves_the_file(self):
        c = self.client()
        call = {"command": "footprint move", "inputs": {"id": "R1", "x_mm": 1.0}, "document": "file-1"}
        applied = self.valid("apply", c.call("apply", {**call, "operation_id": "op_1"}))
        self.assertEqual(applied["persistence"], "saved")
        on_disk = json.loads((Path(self.tmp.name) / "file-1.fake").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["objects"]["R1"]["x_mm"], 1.0)

    def test_artifact_files_start_absent(self):
        c = self.client()
        out = str(Path(self.tmp.name) / "out" / "board.pdf")
        call = {"command": "plot export", "inputs": {"to": out}, "session": "fake-1", "document": "doc-1"}
        self.assertEqual(c.call("preview", call)["changes"][0]["before"], False)
        applied = self.valid("apply", c.call("apply", {**call, "operation_id": "op_1"}))
        self.assertEqual((applied["change"], applied["persistence"]), ("not_applicable", "saved"))
        self.assertTrue(Path(out).is_file())
        self.assertEqual(applied["files"][0]["bytes"], Path(out).stat().st_size)
        self.assertEqual(c.call("preview", call)["changes"][0]["before"], True)

    def test_one_item_of_a_batch_fails(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "target": "R2", "action": "error", "error": {"code": "E_NATIVE_FAILURE"}})
        for obj, op in (("R1", "op_1"), ("R2", "op_2"), ("R3", "op_3")):
            item = {**MOVE, "inputs": {"items": [{"id": obj, "x_mm": 5.0}]}, "operation_id": op}
            if obj == "R2":
                with self.assertRaises(HostCallError) as ctx:
                    c.call("apply", item)
                self.assertEqual(ctx.exception.data, {"code": "E_NATIVE_FAILURE", "dispatch_state": "not_started"})
            else:
                c.call("apply", item)
        self.assertEqual([a["operation_id"] for a in self.state()["applied"]], ["op_1", "op_3"])

    def test_busy_and_blocked_instances(self):
        c = self.client()
        c.control("set_session", session="fake-1", state="busy")
        with self.assertRaises(HostCallError) as ctx:
            c.call("preview", MOVE)
        self.assertEqual(ctx.exception.code, "E_BUSY")
        self.assertEqual(ctx.exception.data["dispatch_state"], "not_started")
        self.assertIn("retry_after_ms", ctx.exception.data)
        c.control("set_session", session="fake-1", state="blocked", title="Board Setup")
        with self.assertRaises(HostCallError) as ctx:
            c.call("apply", {**MOVE, "operation_id": "op_1"})
        self.assertEqual((ctx.exception.code, ctx.exception.data["action"]), ("E_HUMAN_REQUIRED", "dismiss_dialog"))
        session = self.valid("sessions", c.call("sessions"))["items"][0]
        self.assertEqual(session["blocker"], {"action": "dismiss_dialog", "title": "Board Setup"})
        self.assertEqual(self.state()["applied"], [])

    def test_halt_passes_a_busy_device(self):
        c = self.client()
        c.control("set_device", device="dev-1", state="busy")
        with self.assertRaises(HostCallError) as ctx:
            c.call("apply", {"command": "axis move", "inputs": {"id": "x", "position_mm": 10.0}, "device": "dev-1", "operation_id": "op_1"})
        self.assertEqual(ctx.exception.code, "E_BUSY")
        result = c.call("apply", {"command": "stop", "inputs": {}, "device": "dev-1", "operation_id": "op_2"})
        self.assertEqual(result["delivery"], "delivered")
        self.assertEqual([a["operation_id"] for a in self.state()["applied"]], ["op_2"])

    def test_hang_and_lost_connection(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "hang"})
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            c.call("apply", {**MOVE, "operation_id": "op_1"}, deadline_ms=300)
        self.assertLess(time.monotonic() - started, 3)
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "close", "apply_first": True})
        with self.assertRaises(ConnectionClosed):
            c.call("apply", {**MOVE, "operation_id": "op_2"})
        state = self.state()
        self.assertEqual([a["operation_id"] for a in state["applied"]], ["op_2"])
        self.assertEqual([x["outcome"] for x in state["calls"] if x["method"] == "apply"], ["hang", "close"])

    def test_dialog_after_dispatch(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "error", "apply_first": True, "error": {"code": "E_HUMAN_REQUIRED"}})
        with self.assertRaises(HostCallError) as ctx:
            c.call("apply", {**MOVE, "operation_id": "op_1"})
        self.assertEqual(ctx.exception.data["dispatch_state"], "dispatched")
        self.assertEqual(len(self.state()["applied"]), 1)

    def test_stored_and_unreadable_values(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "store", "values": {"x_mm": 12.0}})
        c.call("apply", {**MOVE, "operation_id": "op_1"})
        observed = c.call("read_back", {**MOVE, "operation_id": "op_1"})["observed"]
        self.assertEqual(list(observed.values())[0]["x_mm"], 12.0)
        c.control("fault", rule={"method": "read_back", "action": "unreadable", "fields": ["x_mm"]})
        back = self.valid("read_back", c.call("read_back", {**MOVE, "operation_id": "op_1"}))
        self.assertEqual((list(back["observed"].values())[0], back["unreadable"]), ({"y_mm": 30.0}, ["x_mm"]))

    def test_person_edit_shows_in_the_save_preview(self):
        c = self.client()
        c.call("apply", {**MOVE, "operation_id": "op_1"})
        c.control("edit", document="doc-1", object="C3", field="value", value="10nF")
        preview = self.valid("preview", c.call("preview", {"command": "doc save", "inputs": {}, "session": "fake-1", "document": "doc-1"}))
        self.assertEqual({ch["origin"] for ch in preview["changes"]}, {"tool"})
        self.assertEqual([(ch["origin"], ch["after"]) for ch in preview["external_changes"]], [("external", "10nF")])
        saved = self.valid("save_doc", c.call("save_doc", {"session": "fake-1", "document": "doc-1", "operation_id": "op_2"}))
        self.assertEqual((saved["persistence"], saved["document"]["dirty"]), ("saved", False))
        preview = c.call("preview", {"command": "doc save", "inputs": {}, "session": "fake-1", "document": "doc-1"})
        self.assertEqual((preview["changes"], preview["external_changes"]), ([], []))

    def test_long_job_completes_and_cancels(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "job", "steps": 2, "times": 2})
        started = self.valid("apply", c.call("apply", {**MOVE, "operation_id": "op_1"}))
        job = started["job"]["id"]
        states = [self.valid("job_status", c.call("job_status", {"job": job}))["state"] for _ in range(2)]
        self.assertEqual(states, ["running", "completed"])
        second = c.call("apply", {**MOVE, "operation_id": "op_2"})["job"]["id"]
        c.call("cancel", {"job": second, "operation_id": "op_3"})
        states = [c.call("job_status", {"job": second})["state"] for _ in range(2)]
        self.assertEqual(states, ["running", "cancelled"])
        self.assertEqual([a["operation_id"] for a in self.state()["applied"]], ["op_1"])

    def test_missing_object_and_unknown_method(self):
        c = self.client()
        c.control("set_missing", document="doc-1", objects=["R9"])
        with self.assertRaises(HostCallError) as ctx:
            c.call("preview", {**MOVE, "inputs": {"id": "R9", "x_mm": 1.0}})
        self.assertEqual(ctx.exception.code, "E_NOT_FOUND")
        with self.assertRaises(HostCallError) as ctx:
            c.call("teleport")
        self.assertEqual(ctx.exception.code, "E_UNSUPPORTED")

    def test_protocol_violations_are_recorded(self):
        raw = self.client(handshake=False)
        raw.call("probe")
        with self.assertRaises(HostCallError) as ctx:
            raw.call("apply", MOVE)
        self.assertEqual(ctx.exception.data, {"code": "E_VALIDATION", "dispatch_state": "not_started"})
        raw.channel.write_message({"jsonrpc": "2.0", "id": 99, "method": "probe", "params": {}})
        raw.channel.read_message()
        violations = self.state()["violations"]
        self.assertTrue(any("before hello" in v for v in violations), violations)
        self.assertTrue(any("missing operation_id" in v for v in violations), violations)
        self.assertTrue(any("deadline_ms" in v for v in violations), violations)

    def test_restart_raises_the_generation(self):
        c = self.client()
        c.control("restart_session", session="fake-1")
        self.assertEqual(c.call("sessions")["items"][0]["generation"], 1)

    def test_new_ids_never_reuse_existing_ones(self):
        c = self.client()
        added = c.control("add_session")["session"]
        opened = self.valid("open_session", c.call("open_session", {"operation_id": "op_1"}))["session"]
        created = self.valid("create_doc", c.call("create_doc", {"session": "fake-1", "operation_id": "op_2"}))["document"]
        sessions = {s["id"]: s for s in c.call("sessions")["items"]}
        self.assertEqual(len(sessions), 3)
        self.assertFalse(sessions["fake-1"]["owned"])
        self.assertTrue(sessions[opened["id"]]["owned"])
        self.assertNotIn(added, ("fake-1", opened["id"]))
        self.assertEqual({d["id"] for d in sessions["fake-1"]["documents"]}, {"doc-1", created["id"]})

    def test_reads_change_nothing(self):
        c = self.client()
        c.call("preview", MOVE)
        c.call("read", MOVE)
        c.call("read_back", {**MOVE, "operation_id": "op_1"})
        c.call("preview", {"command": "axis move", "inputs": {"id": "x", "position_mm": 1.0}, "device": "dev-1"})
        state = self.state()
        self.assertEqual(next(d for d in state["documents"] if d["id"] == "doc-1")["objects"], {})
        self.assertEqual(state["devices"][0]["values"], {})
        self.assertEqual(state["applied"], [])

    def test_objects_of_an_untitled_document_have_their_own_keys(self):
        c = self.client()
        doc = c.call("create_doc", {"session": "fake-1", "operation_id": "op_1"})["document"]["id"]
        call = {"command": "footprint move", "session": "fake-1", "document": doc}
        preview = self.valid("preview", c.call("preview", {**call, "inputs": {"ids": ["R1", "R2"], "x_mm": 1.0}}))
        self.assertEqual(sorted({ch["target"] for ch in preview["changes"]}), ["untitled:fake-1/1#/R1", "untitled:fake-1/1#/R2"])

    def test_halt_previews_on_a_busy_device(self):
        c = self.client()
        c.control("set_device", device="dev-1", state="busy")
        self.valid("preview", c.call("preview", {"command": "stop", "inputs": {}, "device": "dev-1"}))

    def test_undo_and_save_as_keep_the_record_honest(self):
        c = self.client()
        c.call("apply", {**MOVE, "operation_id": "op_1"})
        c.control("edit", document="doc-1", object="C3", field="value", value="10nF")
        c.call("undo", {"session": "fake-1", "document": "doc-1", "operation_id": "op_2"})
        objects = next(d for d in self.state()["documents"] if d["id"] == "doc-1")["objects"]
        self.assertEqual((objects["R1"], objects["C3"]), ({}, {"value": "10nF"}))
        save = {"command": "doc save", "inputs": {}, "session": "fake-1", "document": "doc-1"}
        preview = c.call("preview", save)
        self.assertEqual((preview["changes"], len(preview["external_changes"])), ([], 1))
        target = str(Path(self.tmp.name) / "copy.fake")
        saved = self.valid("save_doc_as", c.call("save_doc_as", {"session": "fake-1", "document": "doc-1", "path": target, "operation_id": "op_3"}))
        self.assertFalse(saved["document"]["dirty"])
        preview = c.call("preview", save)
        self.assertEqual((preview["changes"], preview["external_changes"]), ([], []))

    def test_a_finished_job_keeps_its_facts(self):
        c = self.client()
        c.control("fault", rule={"method": "apply", "action": "job", "steps": 1})
        job = c.call("apply", {**MOVE, "operation_id": "op_1"})["job"]["id"]
        first, second = c.call("job_status", {"job": job}), c.call("job_status", {"job": job})
        self.assertEqual(first, second)
        self.assertEqual((first["state"], first["change"]), ("completed", "applied"))

    def test_a_failed_file_write_changes_nothing(self):
        c = self.client()
        path = Path(self.tmp.name) / "file-1.fake"
        path.unlink()
        path.mkdir()
        with self.assertRaises(HostCallError) as ctx:
            c.call("apply", {"command": "footprint move", "inputs": {"id": "R1", "x_mm": 1.0}, "document": "file-1", "operation_id": "op_1"})
        self.assertEqual(ctx.exception.data["code"], "E_NATIVE_FAILURE")
        state = self.state()
        self.assertEqual(next(d for d in state["documents"] if d["id"] == "file-1")["objects"], {})
        self.assertEqual(state["applied"], [])

    def test_undo_after_save_shows_in_the_next_save(self):
        c = self.client()
        c.call("apply", {**MOVE, "operation_id": "op_1"})
        c.call("save_doc", {"session": "fake-1", "document": "doc-1", "operation_id": "op_2"})
        c.call("undo", {"session": "fake-1", "document": "doc-1", "operation_id": "op_3"})
        preview = c.call("preview", {"command": "doc save", "inputs": {}, "session": "fake-1", "document": "doc-1"})
        self.assertEqual(sorted((ch["field"], ch["before"], ch["after"]) for ch in preview["changes"]),
                         [("x_mm", 12.5, None), ("y_mm", 30.0, None)])

    def test_reset_rewrites_files_and_open_session_loads_them(self):
        c = self.client()
        c.call("apply", {"command": "footprint move", "inputs": {"id": "R1", "x_mm": 1.0}, "document": "file-1", "operation_id": "op_1"})
        path = Path(self.tmp.name) / "file-1.fake"
        opened = c.call("open_session", {"path": str(path), "operation_id": "op_2"})["session"]
        doc = opened["documents"][0]["id"]
        self.assertEqual(c.call("read", {"command": "footprint move", "inputs": {"id": "R1"}, "session": opened["id"], "document": doc})["result"]["items"][0]["x_mm"], 1.0)
        c.control("reset", commands=COMMANDS)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["objects"], {})

    def test_a_silent_instance_answers_nothing_at_all(self):
        c = self.client()
        c.control("set_session", session="fake-1", state="unresponsive")
        with self.assertRaises(TimeoutError):
            c.call("preview", {**MOVE, "document": "no-such-doc"}, deadline_ms=300)

    def test_unregistered_inputs_and_commands_are_refused(self):
        c = self.client()
        for call in ({**MOVE, "inputs": {"id": "R1", "x": 1.0}}, {**MOVE, "command": "footprint teleport"}):
            with self.subTest(call=call):
                with self.assertRaises(HostCallError) as ctx:
                    c.call("preview", call)
                self.assertEqual(ctx.exception.code, "E_VALIDATION")
        self.assertEqual(len(self.state()["violations"]), 2)
        with self.assertRaises(HostCallError):
            c.control("fault", rule={"method": "apply", "action": "error", "error": {"code": "E_FORBIDDEN"}})


class HostComponentTest(HostTestCase):
    config = {"host_component": True}

    def discovery(self, session: str = "fake-1") -> dict:
        return json.loads((self.state_dir / "hosts" / f"{session}.json").read_text(encoding="utf-8"))

    def test_discovery_file_and_endpoint(self):
        found = self.discovery()
        self.assertEqual(sorted(found), sorted(CONTRACT["host_protocol"]["discovery_keys"]))
        self.assertEqual(list(VALIDATOR("host-protocol.schema.json").iter_errors(found)), [])
        c = self.client(found["address"])
        self.assertEqual(c.hello["session"], {"id": "fake-1", "generation": 0})
        call = {k: v for k, v in MOVE.items() if k != "session"}
        self.valid("preview", c.call("preview", call))
        with self.assertRaises(HostCallError) as ctx:
            c.call("probe")
        self.assertEqual(ctx.exception.code, "E_UNSUPPORTED")

    def test_unresponsive_instance_never_answers(self):
        self.client().control("set_session", session="fake-1", state="unresponsive")
        client = Client(self.discovery()["address"], timeout=0.3)
        self.addCleanup(client.close)
        with self.assertRaises(TimeoutError):
            client.connect()

    def test_lost_instance_keeps_its_discovery_file(self):
        address = self.discovery()["address"]
        self.client().control("set_session", session="fake-1", state="lost")
        self.assertEqual(self.discovery()["address"], address)
        with self.assertRaises(ConnectionError):
            Client(address, timeout=0.5).connect()

    def test_restart_moves_the_endpoint(self):
        before = self.discovery()["address"]
        self.client().control("restart_session", session="fake-1")
        after = self.discovery()["address"]
        self.assertNotEqual(before, after)
        self.assertEqual(self.client(after).hello["session"]["generation"], 1)

    def test_closing_the_instance_removes_its_discovery_file(self):
        c = self.client(self.discovery()["address"])
        c.call("close_session", {"operation_id": "op_1"})
        self.assertFalse((self.state_dir / "hosts" / "fake-1.json").exists())

    def test_protocol_major_mismatch(self):
        self.client().control("configure", protocol_version="2.0.0")
        self.assertEqual(self.discovery()["protocol_version"], "2.0.0")
        with self.assertRaises(ProtocolMismatch):
            Client(self.discovery()["address"]).connect()

    def test_concurrent_calls_while_instances_restart(self):
        import threading

        failures: list[str] = []

        def reader() -> None:
            try:
                with Client(self.host.address) as c:
                    for _ in range(20):
                        c.call("sessions")
            except Exception as exc:  # noqa: BLE001
                failures.append(repr(exc))

        threads = [threading.Thread(target=reader) for _ in range(6)]
        for thread in threads:
            thread.start()
        control = self.client()
        for _ in range(10):
            control.control("restart_session", session="fake-1")
        for thread in threads:
            thread.join(timeout=30)
        self.assertEqual(failures, [])
        self.assertEqual(self.client(self.discovery()["address"]).hello["session"]["generation"], 10)

    def test_instance_side_calls_belong_on_the_instance(self):
        c = self.client()
        c.call("preview", MOVE)
        self.assertTrue(any("main address" in v for v in self.state()["violations"]))

    def test_requests_on_a_hanging_connection_are_recorded(self):
        self.client().control("fault", rule={"method": "preview", "action": "hang"})
        c = self.client(self.discovery()["address"])
        c.channel.write_message({"jsonrpc": "2.0", "id": 7, "method": "preview", "params": {**MOVE, "deadline_ms": 100}})
        c.channel.write_message({"jsonrpc": "2.0", "id": 8, "method": "read", "params": {**MOVE, "deadline_ms": 100}})
        time.sleep(0.3)
        c.close()
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            outcomes = [x["outcome"] for x in self.state()["calls"] if x["method"] in ("preview", "read")]
            if outcomes == ["hang", "ignored"]:
                break
            time.sleep(0.05)
        self.assertEqual(outcomes, ["hang", "ignored"])


class ProcessTest(unittest.TestCase):
    def test_runs_as_its_own_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            env = {**os.environ, "PYTHONPATH": str(ROOT / "conformance")}
            proc = subprocess.Popen(
                [sys.executable, "-m", "fakehost", "--state-dir", tmp, "--workdir", tmp],
                stdout=subprocess.PIPE, env=env, creationflags=flags, text=True,
            )
            try:
                line = json.loads(proc.stdout.readline())
                with Client(line["address"]) as c:
                    self.assertEqual(c.call("probe")["found"], True)
                    c.control("shutdown")
                self.assertEqual(proc.wait(timeout=10), 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.stdout.close()


if __name__ == "__main__":
    unittest.main()
