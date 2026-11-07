# Commission pipeline

Turns a client's request into working code with Claude Code, without letting any
one chat grow large. **Your job:** find leads, talk to the client, approve the spec.
**The pipeline's job:** turn the approved spec into code that passes a check.

Standard library Python 3.11+, no pip installs. Works on macOS and Linux.

## How one prompt becomes a project

```
request ──spec──► spec.md + reply to client     1 chat, 1 prompt, tools off
        ──reply─► revised spec (client answered) 1 chat, 1 prompt, tools off
        ──approve (you)
        ──plan──► plan.json: 2-8 components      1 chat, ≤2 prompts, tools off
        ──build─► for each component, in dependency order:
                    new chat ─ prompt 1: build it
                              └ check fails? prompt 2/3: fix it (with the check output)
                  final checks ─ fail? one "integrate" chat, ≤3 prompts
```

Why it stays cheap:

* **One chat per component.** A component's chat sees only the project summary,
  its own instructions, the *interfaces* of the components it depends on, and a
  file list. It reads other files only when it needs them.
* **Hard cap of 3 prompts per component** (`limits.max_prompts_per_component`,
  max 3). After 3 the component is marked `failed`, its dependents are
  `blocked`, and nothing else is spent until you act.
* **Tools are trimmed.** Spec, plan and pitch chats run with `--tools ""`. Build
  chats get only Read/Write/Edit/Glob/Grep. No Bash: the pipeline runs the checks
  itself and sends Claude only the last 60 lines of a failure. `--strict-mcp-config`
  keeps MCP servers out of every chat.
* **Plain text output** (JSON output came back empty before). The plan is parsed
  from a ```json block in the text reply.
* Every call is logged to `calls.jsonl`. `status <id>` shows the calls, characters
  in and out, and the number of separate chats.

## Setup (Mac)

1. Claude Code installed and signed in (`claude` works in a terminal).
2. Python 3.11+, git, Node.js (Chrome/Discord checks). For Minecraft/Hytale:
   a JDK (21; 17 for Forge) and `brew install gradle`. For FiveM: `brew install lua` (luac).
3. `python3 pipeline.py doctor --live` checks the tools and sends Claude one tiny prompt.
4. `python3 tests/test_flow.py` and `python3 tests/test_leads.py` should both pass.
   They use a fake `claude` and cost nothing.

Jobs and leads are stored in **`~/commission-data/`**, not in this folder, so
replacing the pipeline code never deletes them. Change this with `data_dir` in
`config.toml` or the `COMMISSION_DATA` env var. If you have jobs from the old
pipeline in `./jobs`, the new format is different; start fresh.

## Commands

One client job, start to finish:

```bash
python3 pipeline.py new "Tab counter" --type chrome_extension --brief "paste the client's message"
python3 pipeline.py spec 1                       # spec.md + the reply to send
python3 pipeline.py reply 1                      # print the reply again
python3 pipeline.py reply 1 --client "their answer"   # revise the spec
python3 pipeline.py approve 1
python3 pipeline.py plan 1                       # prints the components; edit plan.json if you like
python3 pipeline.py build 1
python3 pipeline.py status 1
python3 pipeline.py package 1                    # zip (and jars) in jobs/1/deliver/
```

Everything from one prompt (it stops for your approval unless you pass `--yes`):

```bash
python3 pipeline.py go "A Discord bot with /remind that DMs users later" --type discord_bot
```

When a build fails:

```bash
python3 pipeline.py status 1                 # which component, last error line
python3 pipeline.py build 1 --retry          # failed components get a NEW chat, new 3-prompt budget
python3 pipeline.py build 1 --component c2   # rebuild one component in a new chat
```

Each component is a git commit in `workspace/`, so `git diff` or `git log`
there shows exactly what each chat changed.

Lead log:

```bash
python3 leads.py add --source "Discord: #commissions" --title "..." --type paper --budget "$150" --seen 5m
python3 leads.py pitch 1            # short reply asking the ONE question that decides the quote
python3 leads.py replied 1          # after you send it yourself
python3 leads.py list --open
python3 leads.py status 1 won --price "$180"
python3 leads.py stats              # median reply time, win rate, $ toward the $50k goal
python3 leads.py job 1              # turn the lead into a pipeline job
```

`leads.py` never touches Discord. You copy the draft and send it yourself (no self-bots).

## Job types and their done-when checks

| type | for | final check |
|---|---|---|
| `paper` | Minecraft server plugins and bundles | plugin.yml valid, `gradle build` |
| `fabric` / `forge` | Minecraft mods | mod metadata valid, `gradle build` |
| `discord_bot` | discord.js v14 bots | `npm install`, `node --check`, `npm test` |
| `chrome_extension` | MV3 extensions | manifest + referenced files, `node --check`, `npm test` if present |
| `fivem` | FiveM Lua resources | fxmanifest + referenced files, `luac -p` |
| `hytale` | Hytale mods (experimental; put the API jar in `libs/`) | `gradle build` |
| `other` | scrapers, automations | Python syntax, `unittest`, `npm test` if present |

Every type also runs a **secrets scan**: a hardcoded Discord token, API key or
private key fails the build.

If a check tool isn't installed (e.g. no gradle), that check is skipped and the
job ends as `built_unverified` rather than `built`. Don't deliver an unverified
job without testing it yourself.

The planner can add one extra check per component, but only commands that start
with a program in `checks.allow`. There are no shell operators, and paths must
stay inside the project. Commands run without a shell.

## Files

```
pipeline.py          job CLI            leads.py         lead log CLI
config.toml          settings           pipelib/         internals
  claude.py   runs `claude -p`, logs usage     planner.py  splits spec, validates plan
  builder.py  component loop, prompt caps      checks.py   runs checks (no shell)
  prompts.py  all prompt text                  validators.py built-in checks
  jobtypes.py scaffolds + conventions per type jobs.py     job folders
tests/               test_flow.py, test_leads.py, fake_claude.py
```

A job folder (`~/commission-data/jobs/<id>/`) holds `brief.md`, `spec.md`,
`reply.md`, `client_replies.md`, `spec.approved.md`, `plan.json`/`plan.md`,
`build.json` (per-component status and prompts used), `calls.jsonl` and `workspace/`.

## Notes

* No spend-cap flag is passed: it emptied replies before. Usage is bounded by the
  prompt caps above. Check your usage after big jobs.
* To spend less on builds, set `model = "sonnet"` in `config.toml`.
* `fix_mode = "fresh"` makes each fix prompt a brand-new chat with a compact context
  instead of resuming the component's chat.
* The Gradle templates (Paper 1.21.1, Fabric 1.21.1, Forge 1.20.1) are starting
  points. If the client names another version, the spec says so and the first
  component updates the build file.
