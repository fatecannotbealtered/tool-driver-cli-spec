"""The two conformance suites: general (G00 to G10, R01 to R05) and driver (D01 to D26).

They treat the tool as a black box: they start its CLI as a process with the fake host in
place of the application, and judge only the exit code, the envelope on stdout and what the
fake host received (DVER-011). Their results are simulated results and never count as
evidence (DVER-021).
"""
