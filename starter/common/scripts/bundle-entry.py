from importlib import import_module

raise SystemExit(import_module("{{PACKAGE}}.cli").main())
