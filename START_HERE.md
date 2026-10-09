# START HERE

This file is for you, not for the project. Delete it once you are set up.

---

## Where the files go

⚠️ **Your TeamTrack downloads live in `C:\dev\gaffer\data\teamtrack\` — do NOT delete that folder.** Just extract this pack into `C:\dev\` and let it **replace** the old files when Windows asks. If an old `FEEDBACK.md` (Nebius) is still in `C:\dev\gaffer\`, delete only that file.

The end result:

```
C:\dev\
├── gaffer-prompts.md          ← OUTSIDE the repo on purpose (Claude Code must not read ahead)
└── gaffer\                    ← the repo
    ├── CLAUDE.md              ← Claude Code reads this every session
    ├── START_HERE.md          ← this file, delete later
    ├── docs\
    │   ├── PLAN.md
    │   ├── DATA_CONTRACT.md
    │   ├── DATA_SOURCES.md
    │   └── FAILURE_LOG.md
    └── data\
        └── teamtrack\         ← your downloads (keep!)
            ├── soccer_top\   videos\ + annotations\
            └── soccer_side\  videos\ + annotations\
```

Not on the Desktop and not in OneDrive — OneDrive sync breaks git and Python environments.

---

## Done already ✅
- AWS account (Free plan, $100 credits) + IAM user + laptop connected
- TeamTrack data downloaded into `C:\dev\gaffer\data\teamtrack\`

## Still to do, in order

### 1. Devpost — 10 min
- Join: `opencv26.devpost.com` → **Join hackathon**
- Read the **Rules** page once and confirm Pakistan is not in the excluded countries
- Join the official Slack (link on the Resources page)

### 2. Python 3.12 — already installed ✅
`py list` shows Python 3.12.10 (plus 3.10, 3.13, 3.14). We use **3.12** — 3.14 is too new for many ML packages. Check:

```powershell
py -3.12 --version       # must print 3.12.x
```

### 3. AWS setup ✅ done (9 Oct)
- Free plan, region **Sydney (ap-southeast-2)** — locked, never "Activate advanced features"
- MFA on, `gaffer-budget` ($10 alert)
- IAM user **Gaffer-dev** with AmazonBedrockFullAccess; laptop connected via `aws configure` (`aws sts get-caller-identity` works)
- Model: **Amazon Nova 2 Lite**; AWS skills + MCP server installed for Claude Code
- ⏳ Bedrock quotas are 0 → increase requested. Check **Service Quotas → Quota request history**. When approved, re-run the Bedrock playground prompt (+$20 credit) and tell Claude Code to re-run the Bedrock smoke test.
- 🔒 Keys only live in `~\.aws`. Never paste them into Claude Code, chat, the repo or a screenshot.

### 4. Create the project — 5 min
The videos are big, so tell git to ignore them **before** the first commit:

```powershell
cd C:\dev\gaffer
"data/teamtrack/" | Out-File -Encoding utf8 .gitignore
git init
git add .
git status               # check: no .mp4 files in the list
git commit -m "Project scaffold: plan, data contract, data sources, Claude guidance"
```

### 5. Start Phase 0

```powershell
cd C:\dev\gaffer
claude
```

Open `C:\dev\gaffer-prompts.md` in Notepad (not through Claude Code), copy the **Phase 0** prompt, paste it in.

---

## Footage: sorted ✅

TeamTrack (MIT) is the main real footage. Own futsal footage is now optional — if it ever happens: high, wide, still camera, two clear shirt colours (bibs), one team switches formation halfway and tells you when.

---

## How to run the phases without burning tokens

- One phase per Claude Code session. `/clear` between phases.
- `CLAUDE.md` carries memory between sessions — make sure Claude updates **Current status** at the end of each phase.
- Commit after every phase.
- If a phase goes sideways, don't argue for 20 turns — `/clear` and re-paste the phase prompt with your correction.
- Every real failure you see → `docs/FAILURE_LOG.md` with a screenshot. You'll need them.

## Deadline

**26 Oct, 11:45 PM Pacific = 27 Oct, 11:45 AM Pakistan time.** No fixed dates per phase — finish as fast as you can, and submit at least two days before the deadline.
