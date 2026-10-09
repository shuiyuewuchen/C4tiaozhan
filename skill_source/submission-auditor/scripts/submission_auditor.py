#!/usr/bin/env python3
"""
submission_auditor.py — Audit a challenge/assignment submission folder against a rubric.

One-liner:
    Input  = a submission folder path (+ optional challenge id / custom rubric)
    Output = a human-readable Markdown audit report + a machine-readable JSON result,
             plus a process exit code (0 = pass, 1 = warnings, 2 = critical failures).

Why this exists:
    Students drop files into a folder, then discover after submission that a required
    file was missing, a name was wrong, a file was 0 bytes, or a required section was
    missing. This script runs BEFORE submission and catches those problems deterministically.

Usage:
    python3 submission_auditor.py <FOLDER_PATH> [--challenge C4] [--rubric RUBRIC.yaml]
                                  [--json out.json] [--md out.md] [--strict]

Exit codes:
    0  All required checks passed (may still have warnings)
    1  Passed with warnings (e.g. demo file is suspiciously small)
    2  Critical failures (missing required deliverable, empty required file, etc.)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.stderr.write(
        "ERROR: PyYAML is required. Install with:  pip install pyyaml\n"
    )
    sys.exit(3)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Severity levels
CRITICAL = "CRITICAL"   # blocks submission
WARN = "WARN"           # suspicious, fix it if you can
INFO = "INFO"           # observation

# Files that should never ship in a submission (OS / editor cruft)
CRUFT_PATTERNS = [
    ".DS_Store", "Thumbs.db", "desktop.ini",
    "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ipynb_checkpoints", ".git", ".idea", ".vscode",
]


@dataclass
class Finding:
    severity: str
    code: str           # machine-readable code, e.g. MISSING_REQUIRED_FILE
    message: str        # human-readable explanation
    hint: str = ""      # how to fix it


@dataclass
class AuditResult:
    folder: str
    challenge: str
    total_files_scanned: int = 0
    findings: list = field(default_factory=list)

    def add(self, severity: str, code: str, message: str, hint: str = ""):
        self.findings.append(Finding(severity=severity, code=code, message=message, hint=hint))

    @property
    def criticals(self):
        return [f for f in self.findings if f.severity == CRITICAL]

    @property
    def warns(self):
        return [f for f in self.findings if f.severity == WARN]


# ---------------------------------------------------------------------------
# Rubric loading
# ---------------------------------------------------------------------------

SKILL_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RUBRIC = SKILL_DIR / "references" / "elite20_rubric.yaml"


def load_rubric(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"ERROR: rubric file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data


def detect_challenge(folder: Path, explicit: Optional[str]) -> str:
    """If no challenge id given, try to guess it from the folder/file names."""
    if explicit:
        return explicit.upper()
    candidates: dict = {}
    for p in [folder, *list(folder.rglob("*"))[:50]]:
        name = p.name if p.is_file() else p.name
        m = re.search(r"[_-](C\d)\b", name, re.IGNORECASE)
        if m:
            cid = m.group(1).upper()
            candidates[cid] = candidates.get(cid, 0) + 1
    if candidates:
        return max(candidates, key=candidates.get)
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def scan_files(folder: Path) -> list[Path]:
    files = []
    for f in sorted(folder.rglob("*")):
        if f.is_file() and not any(cruft in f.parts or cruft == f.name
                                   for cruft in CRUFT_PATTERNS):
            files.append(f)
    return files


def check_required_deliverables(folder: Path, files: list[Path],
                                challenge: str, rubric: dict,
                                result: AuditResult):
    """Every required glob pattern must match at least one non-empty file."""
    chal = rubric.get("challenges", {}).get(challenge, {})
    deliverables = chal.get("deliverables", [])
    if not deliverables:
        result.add(WARN, "NO_RUBRIC_FOR_CHALLENGE",
                   f"No deliverable spec found for challenge '{challenge}'. "
                   f"Checking against all files only.",
                   hint="Add an entry for this challenge to your rubric YAML.")
        return

    for spec in deliverables:
        pattern = spec["pattern"]
        required = spec.get("required", True)
        desc = spec.get("description", pattern)
        matches = [f for f in files if f.match(pattern) or f.name.lower().endswith(pattern.lower())]
        # glob support: pathlib.match is limited; also try fnmatch on name
        import fnmatch
        matches = [f for f in files if fnmatch.fnmatch(f.name, pattern)]

        if not matches:
            sev = CRITICAL if required else WARN
            result.add(sev, "MISSING_REQUIRED_FILE" if required else "MISSING_OPTIONAL_FILE",
                       f"Missing {desc}: pattern `{pattern}` matched 0 files.",
                       hint=f"Add a file whose name matches `{pattern}` "
                            f"(e.g. YourName_{challenge}_xxx{_ext_for(pattern)}).")
            continue

        # Each match should be non-trivially sized
        for m in matches:
            kb = m.stat().st_size / 1024
            if kb < 0.5:
                result.add(CRITICAL if required else WARN, "EMPTY_FILE",
                           f"`{m.name}` matches `{pattern}` but is only {kb:.1f} KB (near-empty).",
                           hint="Open the file and make sure content was actually written.")


def _ext_for(pattern: str) -> str:
    if ".skill" in pattern:
        return ".skill"
    if "demo" in pattern.lower():
        return ".mp4 / .png"
    if ".md" in pattern:
        return ".md"
    return ""


def check_naming_convention(folder: Path, files: list[Path],
                            challenge: str, rubric: dict,
                            result: AuditResult):
    chal = rubric.get("challenges", {}).get(challenge, {})
    naming = chal.get("naming", {})
    if not naming:
        return
    required_substr = naming.get("must_contain", f"_{challenge}_")
    skip_ext = set(naming.get("skip_extensions", []))
    skip_ext |= {".pyc", ".pyo"}

    for f in files:
        if f.suffix.lower() in skip_ext:
            continue
        if required_substr not in f.name:
            result.add(WARN, "NAMING_OFF",
                       f"`{f.name}` does not contain `{required_substr}`.",
                       hint=f"Rename to `YourName{required_substr}<topic><ext>` so graders can "
                            f"tell whose submission this is.")


def check_required_sections(files: list[Path], rubric: dict, result: AuditResult):
    """For each must_contain_sections rule, open the matching MD file and check headings."""
    import fnmatch
    rules = rubric.get("global_section_rules", [])
    for rule in rules:
        pattern = rule["file_pattern"]
        sections = rule.get("sections", [])
        for f in files:
            if not fnmatch.fnmatch(f.name, pattern):
                continue
            if f.suffix.lower() not in {".md", ".markdown"}:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            headings = {h.strip().lower() for h in
                        re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)}
            # also collect plain-text mentions for leniency
            lowered = text.lower()
            for sec in sections:
                sec_low = sec.lower()
                found = any(sec_low in h for h in headings) or sec_low in lowered
                if not found:
                    result.add(WARN, "MISSING_SECTION",
                               f"`{f.name}` is missing section `{sec}`.",
                               hint=f"Add a heading like `## {sec}` so reviewers can "
                                    f"find it quickly.")


def check_skill_frontmatter(files: list[Path], result: AuditResult):
    """If a .skill tarball exists, also unpack-check SKILL.md frontmatter (best-effort)."""
    import tarfile, tempfile
    for f in files:
        if f.suffix.lower() != ".skill":
            continue
        try:
            with tarfile.open(f, "r:gz") as tar:
                names = tar.getnames()
                skill_md = [n for n in names if n.endswith("SKILL.md")]
                if not skill_md:
                    result.add(CRITICAL, "SKILL_NO_SKILLMD",
                               f"`{f.name}` is missing SKILL.md at its root.",
                               hint="Repack with a top-level folder containing SKILL.md.")
                    continue
                fh = tar.extractfile(skill_md[0])
                if fh is None:
                    continue
                text = fh.read().decode("utf-8", errors="replace")
                if not text.startswith("---"):
                    result.add(CRITICAL, "SKILL_NO_FRONTMATTER",
                               f"`{f.name}` -> SKILL.md has no YAML frontmatter (must start with ---).",
                               hint="Add `---\\nname: ...\\ndescription: ...\\n---` at the top.")
                    continue
                # check name + description present
                fm = text.split("---", 2)[1]
                if not re.search(r"^\s*name\s*:", fm, re.MULTILINE):
                    result.add(WARN, "SKILL_NO_NAME",
                               f"`{f.name}` -> frontmatter missing `name:` field.")
                if not re.search(r"^\s*description\s*:", fm, re.MULTILINE):
                    result.add(WARN, "SKILL_NO_DESC",
                               f"`{f.name}` -> frontmatter missing `description:` field "
                               "(this is what triggers the skill — don't skip it).")
        except tarfile.TarError:
            result.add(CRITICAL, "SKILL_CORRUPT",
                       f"`{f.name}` is not a valid tar.gz archive.",
                       hint="Repackage with:  tar -czf your.skill your-folder/")


def check_red_flags(files: list[Path], rubric: dict, result: AuditResult):
    """Look for AI-log 'one-shot' smells and suspiciously small demo media."""
    import fnmatch
    # demo media too small
    for f in files:
        if fnmatch.fnmatch(f.name, "*demo*"):
            kb = f.stat().st_size / 1024
            if f.suffix.lower() in {".mp4", ".mov", ".webm"} and kb < 30:
                result.add(WARN, "DEMO_TINY",
                           f"Demo video `{f.name}` is only {kb:.0f} KB — likely a stub.",
                           hint="Record a 20-60 second clip showing the skill actually running.")
            if f.suffix.lower() in {".png", ".jpg", ".jpeg"} and kb < 20:
                result.add(WARN, "DEMO_TINY",
                           f"Demo screenshot `{f.name}` is only {kb:.0f} KB — may be illegible.")

    # AI log should mention iteration, not just one prompt
    for f in files:
        if fnmatch.fnmatch(f.name, "*AI日志*") or fnmatch.fnmatch(f.name, "*ai*log*"):
            try:
                text = f.read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            tokens = ["迭代", "轮", "修改", "返工", "失败", "调整", "v2", "第", "prompt", "iteration", "revise"]
            hits = sum(1 for t in tokens if t in text)
            if hits < 2:
                result.add(WARN, "AI_LOG_ONE_SHOT",
                           f"`{f.name}` does not read like a multi-round log "
                           f"(found only {hits}/9 iteration markers).",
                           hint="Record: which AI, how many rounds, what failed, what you changed.")


def check_cruft(files: list[Path], folder: Path, result: AuditResult):
    for cruft in CRUFT_PATTERNS:
        hits = list(folder.rglob(cruft))
        hits = [h for h in hits if h.is_file()] or [h for h in hits if h.is_dir()]
        for h in hits:
            result.add(INFO, "CRUFT",
                       f"Found `{h.relative_to(folder)}` — usually should not be submitted.")


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

SEVERITY_ICON = {CRITICAL: "🔴", WARN: "🟡", INFO: "⚪"}
EXIT_FOR = [(CRITICAL, 2), (WARN, 1), (INFO, 0)]


def render_markdown(result: AuditResult) -> str:
    lines = []
    lines.append(f"# Submission Audit — {result.challenge}")
    lines.append("")
    lines.append(f"- Folder: `{result.folder}`")
    lines.append(f"- Files scanned: **{result.total_files_scanned}**")
    lines.append(f"- Critical: **{len(result.criticals)}**  |  "
                 f"Warnings: **{len(result.warns)}**  |  "
                 f"Info: **{len([f for f in result.findings if f.severity==INFO])}**")
    lines.append("")

    verdict = ("✅ READY TO SUBMIT" if not result.criticals and not result.warns
               else "⚠️ SUBMIT WITH FIXES" if not result.criticals
               else "❌ DO NOT SUBMIT YET")
    lines.append(f"## Verdict: {verdict}")
    lines.append("")

    for sev in [CRITICAL, WARN, INFO]:
        bucket = [f for f in result.findings if f.severity == sev]
        if not bucket:
            continue
        lines.append(f"## {SEVERITY_ICON[sev]} {sev} ({len(bucket)})")
        for f in bucket:
            lines.append(f"- **[{f.code}]** {f.message}")
            if f.hint:
                lines.append(f"  - 💡 {f.hint}")
        lines.append("")

    if not result.findings:
        lines.append("No issues found.")
    return "\n".join(lines)


def decide_exit_code(result: AuditResult, strict: bool) -> int:
    if result.criticals:
        return 2
    if result.warns and strict:
        return 1
    if result.warns:
        return 1
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Audit a challenge submission folder against a rubric.")
    ap.add_argument("folder", help="Path to the submission folder.")
    ap.add_argument("--challenge", help="Challenge id, e.g. C4. Auto-detected if omitted.")
    ap.add_argument("--rubric", default=str(DEFAULT_RUBRIC),
                    help=f"Path to rubric YAML (default: {DEFAULT_RUBRIC.name})")
    ap.add_argument("--json", help="Optional path to write machine-readable JSON.")
    ap.add_argument("--md", help="Optional path to write the Markdown report.")
    ap.add_argument("--strict", action="store_true",
                    help="Treat warnings as failures (exit 1 on any WARN).")
    args = ap.parse_args()

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        sys.exit(f"ERROR: not a folder: {folder}")

    rubric = load_rubric(Path(args.rubric))
    challenge = detect_challenge(folder, args.challenge)

    result = AuditResult(folder=str(folder), challenge=challenge)
    files = scan_files(folder)
    result.total_files_scanned = len(files)

    check_required_deliverables(folder, files, challenge, rubric, result)
    check_naming_convention(folder, files, challenge, rubric, result)
    check_required_sections(files, rubric, result)
    check_skill_frontmatter(files, result)
    check_red_flags(files, rubric, result)
    check_cruft(files, folder, result)

    md = render_markdown(result)
    print(md)

    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
        print(f"\n[report written to {args.md}]")
    if args.json:
        payload = {
            "folder": result.folder,
            "challenge": result.challenge,
            "total_files_scanned": result.total_files_scanned,
            "criticals": len(result.criticals),
            "warnings": len(result.warns),
            "findings": [asdict(f) for f in result.findings],
        }
        Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
        print(f"[json written to {args.json}]")

    sys.exit(decide_exit_code(result, args.strict))


if __name__ == "__main__":
    main()
