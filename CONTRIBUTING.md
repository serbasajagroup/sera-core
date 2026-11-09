# Contributing

Thanks for helping. Contributions in English or Bahasa Indonesia are welcome.

1. Fork and create a branch.
2. `pip install -e ".[dev]"`
3. Add tests for every behaviour change, especially anything that touches approval rules.
4. Run `pytest -q` and `node --test js/whatsapp-protocol.test.mjs`.
5. Open a pull request describing the change and its security impact.

Rules for changes to the approval layer:

- Default to deny. A new path must never approve without a literal `allow=True`.
- Never widen "Always allow" without a test that shows what it does **not** match.
- Never persist grants to disk or edit Codex configuration.
