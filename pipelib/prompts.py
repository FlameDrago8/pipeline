"""Prompt text. Each prompt carries only what its chat needs."""
from __future__ import annotations

from .jobtypes import TYPES

SPEC_FORMAT = """Answer in exactly this format, nothing before or after:
=== SPEC ===
# <project name>
## Summary
(2-3 sentences)
## Features
(numbered; each one testable)
## Out of scope
## Tech and versions
## Done when
(observable checks: builds, tests, what the client will see)
## Open questions
=== REPLY ===
(the message to send the client)

Rules for the spec: no code. Do not invent requirements; label guesses "Assumption:".
Rules for the reply: under 80 words, friendly, plain. Ask only the ONE question that most
changes the price or scope. Never ask for tokens, passwords, API keys or account logins.
Do not quote a price unless the client named a budget."""


def spec(job_type: str, brief: str) -> str:
    t = TYPES[job_type]
    return f"""You draft specs for a freelance developer's paid commissions.
Job type: {t['label']}. House conventions: {t['notes']}

Client's request:
<<<
{brief.strip()}
>>>

{SPEC_FORMAT}"""


def revise(job_type: str, current_spec: str, client_msg: str) -> str:
    t = TYPES[job_type]
    return f"""You maintain the spec for a freelance commission. Job type: {t['label']}.

Current spec:
<<<
{current_spec.strip()}
>>>

The client just replied:
<<<
{client_msg.strip()}
>>>

Update the spec with what the client said (remove answered questions) and write the next reply.
If nothing important is left to ask, the reply confirms the scope and says work starts once they
approve it.

{SPEC_FORMAT}"""


def plan(job_type: str, spec_text: str, scaffold: list[str], max_components: int, allow: list[str]) -> str:
    t = TYPES[job_type]
    return f"""You split an approved software spec into components. Each component will be built
by a SEPARATE Claude session that sees only: the project summary, that component's own
instructions, and the "provides" notes of components it depends on (it can read files on disk).
So instructions must be self-contained and specific: file names, function/class names,
command names, data formats.

Job type: {t['label']}
Conventions: {t['notes']}
Files that already exist (scaffold): {', '.join(scaffold)}

Approved spec:
<<<
{spec_text.strip()}
>>>

Rules:
- 2 to {max_components} components, built in dependency order. Small jobs: 2-3.
- Each component is buildable in one focused session: at most ~5 files, ~400 lines.
- Every file is owned by exactly one component ("files"). A component may make small edits
  (e.g. registering itself) to files owned by others only if listed in "touches".
- A component must work when only it and its dependencies exist.
- "provides": the exact interfaces later components may rely on (exports, signatures, events).
- "check" (optional): one extra command proving the component works, run in the project root.
  Allowed programs: {', '.join(allow)}. No pipes, redirects or absolute paths. Leave "" if the
  standard checks are enough.
- If the spec has tests in "Done when", put them in the component that owns that logic.
- Build only what the spec asks for. No components for packaging, zipping, CI, deployment or
  publishing: the pipeline packages the delivery itself. A short README goes in the last component.
- Fewer, meatier components beat many tiny ones: every component costs a new chat.

Reply with ONLY a JSON object in a ```json block:
{{
  "project_summary": "3-5 sentences: what it is, main parts, key data flow",
  "components": [
    {{"id": "c1", "title": "...", "depends_on": [], "files": ["..."], "touches": [],
      "instructions": "...", "provides": "...", "check": ""}}
  ]
}}"""


def plan_fix(errors: list[str]) -> str:
    return ("That plan is invalid:\n- " + "\n- ".join(errors) +
            "\nReply with the corrected JSON only, in a ```json block.")


def _deps_block(deps: list[dict]) -> str:
    if not deps:
        return "None (this is a foundation component)."
    return "\n".join(f"- {d['id']} {d['title']} (files: {', '.join(d['files'])}): {d.get('provides', '')}"
                     for d in deps)


def build(job_type: str, summary: str, comp: dict, deps: list[dict], tree: list[str],
          checks: list[str], max_prompts: int) -> str:
    t = TYPES[job_type]
    touches = ", ".join(comp.get("touches") or []) or "none"
    return f"""You are building ONE component of a {t['label']} project in the current directory.
Other components are built in separate sessions, so stay inside your scope.

Project: {summary}
Conventions: {t['notes']}

Component {comp['id']}: {comp['title']}
Instructions:
{comp['instructions']}

Files you own (create or complete them): {', '.join(comp['files'])}
Files owned by others you may make small edits to: {touches}

Components already built that you can rely on (read their files only if you need details):
{_deps_block(deps)}

Files on disk now:
{chr(10).join(tree) or '(none)'}

After you finish, the pipeline runs these checks: {'; '.join(checks)}
You get at most {max_prompts} prompts for this component, so get it right the first time.

Rules: complete, working code, no placeholder stubs or TODOs. No secrets in code (read them from
env/config). Do not install packages or run long commands. When done, reply with a 1-3 line
summary, no code."""


def fix(comp: dict, attempt: int, max_prompts: int, failed_cmd: str, output: str,
        context: str = "") -> str:
    head = context + "\n\n" if context else ""
    return f"""{head}The check for component {comp['id']} failed (prompt {attempt} of {max_prompts}).
Command: {failed_cmd}
Output (tail):
{output}

Fix the cause with the smallest change. Stay within your files unless the error is clearly in a
file you may edit. Reply with one line saying what you changed."""


def integrate(job_type: str, summary: str, tree: list[str], failed_cmd: str, output: str,
              max_prompts: int) -> str:
    t = TYPES[job_type]
    return f"""All components of this {t['label']} project are built, but the final check fails.
Project: {summary}
Conventions: {t['notes']}

Files on disk:
{chr(10).join(tree)}

Command: {failed_cmd}
Output (tail):
{output}

Find the cause (read only the files the error points to) and fix it with the smallest change.
You get at most {max_prompts} prompts. Reply with one line saying what you changed."""


def pitch(lead: dict) -> str:
    return f"""Write a first reply to a commission request a freelance developer just saw.
Where: {lead.get('source', '')}
Title: {lead.get('title', '')}
Type: {lead.get('type', '')}
Budget: {lead.get('budget') or 'not stated'}
Their post / notes:
<<<
{lead.get('notes') or '(only the title)'}
>>>

Rules: 2-4 short sentences, casual and confident, no long pitch, no bullet lists. Say you can
build it, then ask the ONE question that most decides the quote. Never ask for tokens,
passwords, API keys or logins. Do not promise dates or prices. Output only the message."""
