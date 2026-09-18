"""Crates: the orchestration layer that turns a Navidrome playlist into a DJ crate.

A crate is a playlist plus a promise: every track has a lossless file that meets the
crate policy, is analyzed, (later) stemmed, and is present on the designated devices.
This package holds the state (SQLite), the reconcile loop, and the small HTTP API +
web client that lets you toggle crates from the same screen you stream from."""
