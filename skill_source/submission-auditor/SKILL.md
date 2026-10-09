---
name: submission-auditor
description: >
  Pre-submission auditor for challenge / assignment / homework folders. Takes a folder path
  (+ optional challenge id like C4) and checks it against a YAML rubric: required deliverables
  exist, filenames follow the naming convention, no file is 0 bytes, required sections are
  present in Markdown docs, any bundled .skill tarball has valid YAML frontmatter, demo media
  isn't a stub, no OS/editor cruft sneaks in. Emits a Markdown report + JSON and a process
  exit code (0 = pass, 1 = warnings, 2 = critical). Think of it as the "did I actually submit
  everything?" check you run before hitting send.
  Use whenever someone says "check my submission", "did I miss anything", "帮我检查一下交作业",
  "提交包检查", "作业齐了吗", "pre-flight check", "submission audit", "rubric check",
  "before I submit", "帮我过一遍", or points at a folder and asks "is this ready to turn in?".
---

# Submission Auditor — 提交包质检员

## Purpose

Every challenge in a cohort has a fixed deliverables list: certain files, certain naming,
certain sections inside the docs. But right up until the deadline, people assemble their
folder by hand, and the mistakes are always the same ones:

- a required file didn't get saved (0 bytes)
- the filename forgot the `_C4_` segment, so the grader can't tell whose it is
- the AI log was one paragraph, no iteration recorded
- the demo screenshot is 5 KB and illegible
- a `.skill` tarball's `SKILL.md` has no YAML frontmatter, so the skill never triggers
- `.DS_Store` / `__pycache__` got packaged in by accident

This skill catches all of those **deterministically, in one command, before submission**.
It is the "pre-flight checklist" you run when you think you're done.

## Input

- **Required:** a folder path (the submission folder).
- **Optional:** `--challenge C4` (auto-detected from filenames if omitted).
- **Optional:** `--rubric path/to/custom.yaml` (defaults to the bundled Elite20 rubric).
- **Optional:** `--md report.md` / `--json result.json` to persist outputs.

## Output

- A Markdown report printed to stdout with a verdict (`✅ READY` / `⚠️ FIXES` / `❌ DO NOT SUBMIT`).
- A process exit code: **0** = clean, **1** = warnings, **2** = critical failures.
- Optional JSON sidecar for CI / automation.

## Workflow

### Step 1 — Resolve inputs

```python
from pathlib import Path
folder = Path(args.folder).expanduser().resolve()
assert folder.is_dir(), f"not a folder: {folder}"
```

If no `--challenge` is passed, scan the folder + top-level filenames for a token like
`_C4_` or `-C4-` and take the most common one. If nothing is found, the audit falls back
to folder-level checks (naming, empties, cruft) without per-challenge deliverables.

### Step 2 — Load the rubric

```python
import yaml
rubric = yaml.safe_load(open(references/elite20_rubric.yaml, encoding="utf-8"))
chal = rubric["challenges"][challenge]
```

The rubric is data: to audit a new assignment, append an entry — no code change.
See `references/elite20_rubric.yaml` for the schema.

### Step 3 — Run the checks in order

The bundled script `scripts/submission_auditor.py` already implements all of them:

1. **Required deliverables** — every glob in `deliverables:` must match ≥ 1 non-trivial file.
2. **Empty / stub files** — any matched required file under 0.5 KB is flagged.
3. **Naming convention** — every file must contain `naming.must_contain` (e.g. `_C4_`),
   except extensions listed in `skip_extensions`.
4. **Required sections** — for `global_section_rules:`, open matching `.md` files and
   check each required heading/text fragment is present.
5. **.skill integrity** — open every `*.skill` tar.gz, confirm a `SKILL.md` exists inside,
   confirm it starts with YAML frontmatter containing `name:` and `description:`.
6. **Red flags** — demo media under 30 KB (video) or 20 KB (image) is flagged as a stub;
   AI-log files that don't mention iteration keywords are flagged as "one-shot".
7. **Cruft** — `.DS_Store`, `Thumbs.db`, `__pycache__`, `.git`, etc. reported at INFO.

### Step 4 — Render report and exit

```
# Submission Audit — C4
- Files scanned: 7
- Critical: 0 | Warnings: 2 | Info: 1
## Verdict: ⚠️ SUBMIT WITH FIXES
## 🟡 WARN (2)
- [NAMING_OFF] `notes.md` does not contain `_C4_`.
```

Exit code drives automation:
- **0** — clean, submit.
- **1** — warnings; a human should look, but submission is probably OK.
- **2** — critical; **do not submit** until fixed.

## Running it yourself

```bash
# Basic — auto-detects challenge from filenames
python3 scripts/submission_auditor.py /path/to/my_submission/

# Explicit challenge, persist report + JSON
python3 scripts/submission_auditor.py ./my_sub --challenge C4 \
    --md report.md --json result.json

# Treat warnings as failures (good for CI / pre-submit hook)
python3 scripts/submission_auditor.py ./my_sub --strict
```

Dependencies: Python 3.9+ and `pip install pyyaml`. Nothing else.

## Edge Cases

- **Empty folder:** report 0 files scanned, verdict ❌, exit 2.
- **Challenge not in rubric:** warn (not error) and run only global/cruft checks.
- **`.skill` file is actually a .tar.gz renamed:** handled — the tar opener auto-detects.
- **Filenames with non-ASCII (Chinese):** Python 3 handles them; on Windows, run
  `chcp 65001` first if the console garbles output.
- **Files > 50 MB:** skipped silently from size heuristics, still counted.
- **Symlinks:** not followed (avoids walking outside the submission folder).
- **Missing PyYAML:** the script exits with code 3 and a one-line install hint.

## Extending the rubric

Drop a YAML like this next to your project and pass `--rubric`:

```yaml
challenges:
  MYASSIGN:
    deliverables:
      - pattern: "report.pdf"
        required: true
        description: Final report
      - pattern: "*.csv"
        required: false
        description: Raw data
    naming:
      must_contain: "_MyAssn_"
```

No script changes needed.

## Examples

**Example 1 — a broken folder (what we test against):**
Input: a folder with only `张三_C4_skill说明.md` (40 bytes) and no `.skill` file.
Output: 2 CRITICAL (missing `.skill`, missing `AI日志`), 10 WARN (missing sections,
naming, tiny files), verdict ❌, exit code 2.

**Example 2 — a clean folder:**
Input: 5 files all matching C4 patterns, all > 1 KB, all containing `_C4_`,
SKILL.md frontmatter valid. Output: 0 findings, verdict ✅, exit code 0.

## Design Notes

- Deterministic checks live in the Python script; judgment calls live in this SKILL.md.
  If the LLM needs to decide something (e.g. "is this section actually substantive?"),
  it reads the report and adds commentary — it doesn't re-implement file walking.
- The rubric is intentionally YAML, not hard-coded, so one skill serves every challenge.
- Exit codes are part of the public interface: CI and pre-commit hooks rely on them.
