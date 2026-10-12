# Commands run as text in the viewer

The exporter ships command strings untouched, as the objects' string properties it already exports, and
the viewer's `CommandMgr` (`TronViewer/Assets/Tron/Scripts/Commands.cs`) tokenizes them when they run,
with the engine's tokenizer. We didn't pre-parse them in the exporter because the engine itself handles
commands as text all the way: a delayed command is stored as text and parsed again when it fires, a
receiver splits its message into statements again, and a group rebuilds a message from its words and
sends the new text on. A pre-parsed form would have to reproduce each of these re-parses, so it would
be no simpler and it would need a level format change.

`tools/commands.py` is the same tokenizer in Python, for the exporter's own reading of commands (keyframer
self-commands) and for the tests, which check that both tokenizers give the same result for every
command string in the levels.
