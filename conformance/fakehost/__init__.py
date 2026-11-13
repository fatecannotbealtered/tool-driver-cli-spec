"""The fake host: a small program that stands in for the application in tests (DVER-020).

It is also the reference implementation of the host protocol (DCLI-270 to DCLI-281). It uses
only the Python standard library.

Start it in the test process::

    from fakehost import FakeHost, Client

    with FakeHost(state_dir, commands=registrations) as host:
        env[f"{PREFIX}_FAKE_HOST"] = host.address      # the tool now talks to the fake host
        with Client(host.address) as control:
            control.control("set_session", session="fake-1", state="blocked")
            ...                                         # run the tool's CLI as a process
            state = control.control("state")            # what arrived, and how often

or as its own process with ``python -m fakehost --state-dir DIR``.

The world starts with one instance ``fake-1`` holding document ``doc-1``, one file-mode
document ``file-1`` and one simulated device ``dev-1``; pass ``config`` to change it, and
``host_component: true`` to serve each instance on its own endpoint with a discovery file;
``missing_methods`` lists instance-side methods that host component does not have, such as
``["undo"]``.
A document is of the kind it is created or its instance is opened with (``kind``), else of the
kind ``config["kinds"]`` gives its file extension, such as ``{".prj": "project"}``, else of the
kind ``set_kind`` set, ``board`` at first.

Control methods, called as ``fake.<name>`` on the main address:

``state``                       everything: instances, documents with objects, devices, jobs,
                                calls, applied changes, protocol violations, faults
``reset``                       ``config``, ``commands``: start over
``fault``                       ``rule``: inject a fault, see below
``clear_faults``
``set_session``                 ``session``, ``state`` (ready, busy, blocked, unresponsive, lost,
                                unreachable, closed), ``title``, ``action``, ``knowledge``
``restart_session``             ``session``: the generation goes up by one
``add_session``                 ``session``: one more instance, with one document
``set_device``                  ``device``, ``state``
``edit``                        ``document``, ``object``, ``field``, ``value``: a person edits;
                                a ``field`` ending in ``[*]`` holds a list
``set_disk``                    ``document``, ``disk`` (in_sync, changed, missing)
``set_kind``                    ``kind``: every open document, and every later one without a kind
                                of its own, is of this kind
``set_missing``                 ``document``, ``objects``: these object IDs do not exist
``set_job``                     ``job``, ``state``, ``action``
``configure``                   ``protocol_version``, ``plugin``
``shutdown``

A fault rule matches the next call of ``method``, optionally only for one ``command``,
``session`` or ``target`` (an object ID, so one item of a batch can fail), ``times`` times
(default 1; 0 means every time). Its ``action``:

``error``       reply with the host error in ``error`` (``code``, ``dispatch_state``, ...)
``hang``        never reply
``close``       close the connection without a reply
``result``      merge ``result`` into the normal result
``store``       apply: the application stores ``values`` instead of the requested ones
``unreadable``  read_back: ``fields`` cannot be read back
``job``         apply: the work continues as a long job of ``steps`` polls
``slow``        take ``ms`` milliseconds (default 1000) before the call runs, as a slow
                application does

With ``apply_first: true``, ``error``, ``hang`` and ``close`` happen after the change was
applied, as when a dialog appears or the connection drops after dispatch.

Each instance runs one instance-side call at a time, as on the application's main thread. A call
that finds the main thread running another call waits for it up to ``host_protocol.busy_wait_ms``
of the contract and never past its own deadline, then gets ``E_BUSY`` (DCLI-276); a ``slow`` call
holds the main thread meanwhile. ``hello``, ``cancel`` and the apply of a halt command never wait.
"""
from .client import Client, ConnectionClosed, HostCallError, ProtocolMismatch
from .server import FakeHost
from .world import PROTOCOL_VERSION, World

__all__ = ["Client", "ConnectionClosed", "FakeHost", "HostCallError", "PROTOCOL_VERSION", "ProtocolMismatch", "World"]
