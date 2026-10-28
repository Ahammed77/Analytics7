# Engine checkpoints

Recorded by `python -m a7chat.approved_runner --checkpoint <label>`.

Decision rule (spec, 13 Nov checkpoint): if every approved question passes end to end with the real query model, the text-to-SQL engine stays the primary path. Otherwise the fallback is raw SQL from the model behind a validator (SELECT only, catalogue tables only, limit and timeout).

**13 Nov 2026 engine checkpoint: not run yet.** Run it on 13 Nov with the real query model:

```bash
python -m a7chat.approved_runner --model claude --checkpoint "13 Nov 2026 engine checkpoint"
```

The runner appends a section for the run below, with the result and the decision.
