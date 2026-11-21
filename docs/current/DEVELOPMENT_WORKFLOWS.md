# Superpowers and Spec Kit in this repository

Installed on 2026-11-05 for Codex, scoped to this repository:

- Superpowers 7.0.2: all 15 skills in `.agents/skills/`, copied without changes from `obra/superpowers` commit `22f0b46`.
- Spec Kit CLI 1.3.1.dev0: built from the local `github/spec-kit` clone at commit `ec9a6f3b`. This is the cloned development revision, not a pinned stable release.
- Spec Kit Codex skills, PowerShell scripts, templates and SDD workflow: `.agents/skills/speckit-*` and `.specify/`.
- CLI dependencies are isolated in ignored `.artifacts/spec-kit-venv/`; they are not application runtime dependencies. No global Codex configuration was changed.

## Use in Codex

Start Codex in the repository root. Newly installed skills are available on the next turn; if the list has not refreshed, reopen the session. Codex discovers repository skills in `.agents/skills/`. `AGENTS.md` directs session startup to the Superpowers bootstrap; this installation uses local skills rather than marketplace plugin hooks.

For a new bounded feature, use these prompts in sequence, supplying your feature description to the first:

```text
$speckit-specify <feature description and compatibility boundaries>
$speckit-clarify
$speckit-plan
$speckit-tasks
$speckit-analyze
$speckit-implement
$speckit-converge
```

Other available skills include `$speckit-checklist` and `$speckit-constitution`. The initial constitution summarizes existing project guidance; use the constitution skill when intentionally updating project principles.

For Superpowers, ask naturally or name a skill:

```text
$brainstorming Help design this feature using the existing project contracts.
$systematic-debugging Investigate <observed defect>.
$verification-before-completion Verify the affected journey and report evidence.
```

Spec Kit owns the feature's requirements, plan and task artifacts. Superpowers assists with design and execution of those artifacts. Reuse approved plans, respect existing ambiguity/approval rules, and keep product contracts, FR/AC/task IDs and release claims in their documented canonical owners. Installing these tools does not itself authorize a new feature, rewrite existing specifications or establish live Excel verification.

## Local CLI and maintenance

From the repository root in Windows PowerShell:

```powershell
.\tools\specify.ps1 version
.\tools\specify.ps1 integration status
.\tools\specify.ps1 workflow list
```

Recreate only the CLI environment if it is missing (requires `uv` and the local `spec-kit` clone):

```powershell
uv venv .artifacts/spec-kit-venv --python 3.13
uv pip install --python .artifacts/spec-kit-venv/Scripts/python.exe ./spec-kit
```

The application still uses its existing Python commands. The wrapper forwards CLI arguments and operates on the caller's working directory. Do not rerun `init --force` as a routine update: it can replace managed files. Review upstream changes and the Spec Kit upgrade documentation before upgrading installed assets. Pulling either cloned repository does not update the installed skill copies or CLI automatically.

References: [Superpowers](https://github.com/obra/superpowers), [Spec Kit existing-project adoption](https://github.github.com/spec-kit/how-to/existing-projects.html), [OpenAI local skill discovery](https://learn.chatgpt.com/docs/build-skills#where-to-save-skills).
