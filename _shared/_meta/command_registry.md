---
title: "Command Registry"
date: 2026-03-18
machine: shared
assistant: shared
category: system
memoryType: registry
priority: critical
tags: [registry, commands, tools, scripts, zero-inference]
updated: 2026-04-21
source: internal
domain: operations
project: dil-active
status: active
owner: shared
due:
---

# Command Registry

Zero-inference lookup for agents: match user intent to the right script/tool.
Do NOT manually replicate what a script does — run the script.

## How to use this file

1. User says something (e.g. "morning brief", "create a task", "comment on the Jira ticket")
2. Match against the **trigger** column (case-insensitive, partial match OK)
3. Run the **command** — do not improvise an alternative
4. If no trigger matches, the task may genuinely require manual work

## DIL Scripts (all domains)

Scripts in `_shared/scripts/`. Available everywhere, no domain restriction.

| trigger | command | description |
|---|---|---|
| morning brief, daily brief, briefing | `morning_brief` | Generate daily task briefing, prepend to `_shared/reminders.md` |
| create jira task, new jira ticket, jira + dil task | `_shared/scripts/create_jira_task.sh --summary "<title>" --project "<slug>" --epic <EPIC> [opts]` | Create Jira ticket AND mirroring DIL task in one shot. **Preferred for all work-domain tasks.** |
| create task, new task (DIL only) | `create_task --domain <domain> --title "<title>" --project "<project>"` | Create a DIL-only task (no Jira). Use for personal domain or when Jira ticket already exists (pass `--task-id`). |
| create task (json) | `create_task json <manifest.json>` | Create task from JSON manifest |
| archive tasks | `archive_tasks` | Move terminal tasks to `archived/{year}/` |
| list archived, search archived | `list_archived [--domain DOMAIN] [--grep PATTERN]` | Search and filter archived tasks |
| create memory, remember this | `memory_tool create --type <type> --title "<title>" [--scope shared\|local] [--tags CSV] [--content-file PATH] [--category CAT]` | Create a DIL memory note with proper frontmatter. `--scope shared` writes directly to `_shared/`. Default is local (machine/assistant). Exit codes: 0=success, 1=error, 2=validation. |
| relocate memory, promote memory, move memory | `memory_tool relocate <path> --target-scope shared\|machine/assistant [--force]` | Move a memory note between scopes. Patches frontmatter (machine, assistant, owner, updated), updates source and target indexes, appends changelog. Use `shared` to promote or `machine/assistant` to demote. |
| mind meld, export to template, publish to template | `memory_tool mind_meld <path> [--template-repo PATH] [--model MODEL] [--skip-llm] [--force]` | Export a memory to the DIL template repo. Templatizes frontmatter, runs LLM (ollama) to redact PII/business info while preserving principles, shows diff for approval. Default model: gemma4:latest. Default template repo: ~/projects/ai_projects/distributed_intent_ledger. |
| remove memory | `_shared/scripts/remove_memory.sh` | Remove a DIL memory note |
| ingest source, ingest file, ingest url, import file, import url, store external asset, knowledge ingest | `_shared/scripts/ingest_source.sh <path-or-url>` | Ingest an external asset into the knowledge pipeline with manifest, provenance, registry write, and adapter routing |
| ingestion runbook, knowledge ingestion, should i ingest this, ingest or create memory | `_shared/runbooks/knowledge-ingestion-runbook.md` | Decision rule for when to use ingest_source.sh vs create_memory.sh |
| set task status, update status | `set_task_status <task_id> <status>` | Change task status |
| assign task | `assign_task` | Assign a task to an agent |
| search tasks, list tasks, show tasks, find task, task search | `task_tool search [--status STATUS] [--project SLUG] [--domain DOMAIN] [--latest N] [--count] [--json]` | Fast task discovery and filtering from index |
| review task, show task details | `task_tool review <TASK_ID> [--json]` | Show full task details for a single task |
| validate tasks | `validate_tasks` | Validate task files against schema |
| rebuild index, reindex | `rebuild_task_index` | Regenerate `_shared/_meta/task_index.md` from task files |
| import jira, jira import | `_shared/scripts/jira_import.sh` | Import Jira tickets as DIL work tasks |
| identify agent | `_shared/scripts/identify_agent.sh` | Resolve current agent identity from env/process tree |
| search dil, dil search, find in dil, search memory, search preferences, recall | `_shared/scripts/dil_search.sh "<query>" [--recall] [--scope SCOPE] [--domain DOMAIN] [--limit N] [--json]` | Hybrid search across DIL memory/tasks/preferences with keyword+temporal+status ranking. Use `--recall` for protocol-aligned multi-source retrieval. |
| x search, search bookmarks, search x, find bookmark | `_shared/scripts/x_tool search <query> [--author HANDLE] [--limit N] [--json]` | FTS5 full-text search across X bookmarks with BM25 ranking (SQLite). 242x faster than legacy JSONL scan. |
| x list, list bookmarks, x bookmarks by author | `_shared/scripts/x_tool list [--author HANDLE] [--category CAT] [--domain DOM] [--sort-by FIELD] [--limit N] [--json]` | List/filter X bookmarks by author, date, category, domain. |
| x show, show bookmark, bookmark detail | `_shared/scripts/x_tool show <id> [--json]` | Full bookmark detail: text, engagement metrics, quoted tweets, links, tags. |
| x stats, bookmark stats | `_shared/scripts/x_tool stats [--json]` | Aggregate bookmark statistics: total, unique authors, top authors, languages. |
| x categories, bookmark categories | `_shared/scripts/x_tool categories [--json]` | Category distribution across bookmarks. |
| x domains, bookmark domains | `_shared/scripts/x_tool domains [--json]` | Domain/subject distribution across bookmarks. |
| x compose, compose x post, draft x post, compose tweet | `_shared/scripts/x_tool compose --body "text" [--reply-to ID]` | Draft an X post via message_tool nozzle pipeline (xpost formatter, 280-char aware). |
| x post, post to x, send x post | `_shared/scripts/x_tool post [--send] [--send --yes]` | Dispatch draft to clipboard/CDP. Default: paste+screenshot. --send: confirm+post. --send --yes: full auto. |
| x drafts, x post drafts | `_shared/scripts/x_tool drafts [--limit N]` | List message_tool drafts. |
| x sync, sync x bookmarks, sync bookmarks | `_shared/scripts/x_tool sync [--browser NAME] [--agent-browser]` | Sync X bookmarks via Field Theory CLI. |
| x tag, tag bookmark | `_shared/scripts/x_tool tag (--url URL \| --id ID) --tag TEXT` | Add tag to a bookmark in JSONL cache and rebuild index. |
| x find, find x bookmark | `_shared/scripts/x_tool find <query> [--limit N]` | Legacy JSONL search (use `search` instead for FTS5). |
| create project | `_shared/scripts/create_project.sh` | Register a new project in the project registry |
| register session, session register, agent register | `_shared/scripts/signal_tool register --agent-name <NAME> --machine <MACHINE>` | Register this agent session in the session registry (bootstrap step 10) |
| deregister session, session close, agent deregister | `_shared/scripts/signal_tool deregister <SESSION_KEY>` | Close an agent session in the registry |
| list sessions, active sessions, who is online | `_shared/scripts/signal_tool sessions [--active-only]` | List registered agent sessions |
| session artifacts, list session artifacts, normalize session artifacts, rename session artifacts | `_shared/scripts/session_artifact_tool list\|plan\|rename [--apply]` | List and normalize `_shared/artifacts/sessions` filenames using the DIL session artifact convention; writes rename plans under `_shared/data/session_artifact_tool/` |
| dil agent loop, agent loop, local loop controller | `_shared/scripts/bin/dil_agent_loop validate\|run\|list\|status\|stop ...` | DIL-native local bounded loop controller. Canonical package: `_shared/projects/dil_agent_loop/`; state under `_shared/data/dil_agent_loop/`; logs under `_shared/logs/dil_agent_loop/`. |
| send signal, signal agent | `_shared/scripts/signal_tool send --to <AGENT@MACHINE> --subject "..."` | Send a signal to another agent via CSV ledger |
| check signals, pending signals | `_shared/scripts/signal_tool check` | Check for pending signals addressed to this agent |
| poll inbox, poll signals | `_shared/scripts/signal_tool poll --account <NAME>` | Poll email inbox for #TAG: signals and ingest to CSV ledger |
| broadcast signal, signal all | `_shared/scripts/signal_tool broadcast --subject "..."` | Broadcast a signal to all DIL agents |
| bump dil version, version bump | `_shared/scripts/signal_tool version-bump --reason "..."` | Bump DIL version and notify all agents |
| engineering notebook, eng note | `_shared/scripts/create_engineering_notebook_entry.sh` | Create an engineering notebook entry |
| execution note, task note | `append_task_note` | Append execution note to a task file |
| fleet inventory, agent models | `_shared/scripts/fleet_agent_model_inventory.sh` | Inventory agent models across fleet machines |
| git status, git summary, git diff, git log, git tool | `_shared/scripts/git_tool <subcommand> [--repo PATH] [--json]` | DIL-compliant, agent-safe wrapper for common Git operations with logs/data artifacts and destructive-command refusal |
| check mail, list mail, inbox, email list | `email_tool list [--account NAME] [--folder NAME] [--page N] [--page-size N]` | List email envelopes (inbox by default) |
| read mail, read email, read message | `email_tool read <ID> [--account NAME]` | Read a specific email message |
| search mail, search email, find email | `email_tool search <QUERY> [--account NAME] [--folder NAME] [--page-size N]` | Search emails by keyword |
| send mail, send email, compose email | `email_tool send --to ADDR --subject "..." --body "..." [--account NAME]` | Non-interactive email send with auto OAuth2 token refresh |
| reply email, reply to email | `email_tool reply <ID> --body "..." [--account NAME] [--all]` | Non-interactive reply with auto OAuth2 token refresh |
| email folders, mail folders | `email_tool folders [--account NAME]` | List email folders/labels |
| email accounts, mail accounts | `email_tool accounts` | List configured email accounts |

## Work Domain Tools (AutoZone)

Located in `/az/talend/scripts/bin/`. Only available in work context.

| trigger | command | description |
|---|---|---|
| jira comment, update jira, jira | `jira_tool comment DMDI-XXXXX "text"` | Post comment to Jira ticket |
| jira status | `jira_tool status DMDI-XXXXX` | One-line Jira ticket status |
| jira transition, move ticket | `jira_tool transition DMDI-XXXXX "In Progress"` | Transition Jira ticket (handles multi-step chaining) |
| jira create, create ticket | `jira_tool create --summary "Title"` | Create a Jira ticket |
| jira subtask | `jira_tool create-subtask DMDI-XXXXX --summary "Title"` | Create Jira subtask with watcher inheritance |
| jira json, jira manifest | `jira_tool json <manifest.json>` | Agent-first JSON mode for Jira |
| jira edit | `jira_tool edit DMDI-XXXXX --field value` | Edit Jira ticket fields |
| nozzle, format for, render as, pipe through | `nozzle <format> [--clipboard] [--wrap] [--title TITLE]` | Platform-aware content formatter — pipe content through a nozzle (jira, teams, html, email, smax, github, gitlab, obsidian, rtf, console, text). `--clipboard` copies to wl-copy with correct MIME type. `nozzle --list` for all formats. |
| markdown to jira | `md2jira` | Convert Markdown to Jira wiki markup |
| jira panel | `jira-panel` | Format Jira panel markup |
| get secret, secret | `getSecret <secret-name>` | Retrieve secret from GCP Secret Manager |
| teams notify, notify teams, send teams | `teams_tool webhook --url <URL> --title "..." --body "..."` | Send notification to MS Teams channel |
| smax status | `smax_tool status <REQUEST_ID>` | One-line SMAX request status |
| smax change, smax cr | `smax_tool change <CHANGE_ID>` | One-line SMAX change request status |
| smax create change, create cr | `smax_tool create-change --summary "..." --description "..." --reason "BusinessRequirement" --model 12543` | Create SMAX change request (for deployments, Control-M changes) |
| smax create request, consultation request, decomm request | `smax_tool create-request --summary "..." --description "..." --category 25453 --service-desk-group 37456` | Create SMAX consultation/service request (for TUG, server decomm). Category 25453 = Consultation, SDG 37456 = TUG/Infrastructure |
| smax comment | `smax_tool comment <TYPE> <ID> "text"` | Add comment to SMAX entity (Request, Change, Incident). Accepts plain text, HTML, or @filename |
| smax search | `smax_tool search --mine` | Search SMAX requests (--mine for own requests) |
| control-m, controlm | `controlMTool` | Control-M job management |
| gcp auth, gcp service account | `gcpam` | GCP auth/service account manager |
| deploy app | `deployApp` | Deploy Talend application |
| deploy config | `deployConfig` | Deploy Talend configuration |
| run talend job | `runTalendJob` | Execute a Talend job |
| talend status | `talendStatus` | Check Talend server/job status |
| excel tool | `excelTool` | Excel file manipulation |
| upload artifact | `uploadArtifact` | Upload to Artifactory |
| download artifact, get artifact | `downloadArtifact` / `getArtifact` | Download from Artifactory |
| validate ssl | `validate_ssl_chain` | Validate SSL certificate chain |
| gpg tool | `gpgTool` | GPG key operations |
| start dmdeployinator, deployinator start | `dmdeployinator_ctl start` | Build and start DMDeployinator in production mode (tmux session) |
| stop dmdeployinator, deployinator stop | `dmdeployinator_ctl stop` | Stop DMDeployinator and free port |
| restart dmdeployinator | `dmdeployinator_ctl restart` | Stop then start DMDeployinator |
| dmdeployinator status | `dmdeployinator_ctl status` | Check if DMDeployinator is running (PID, URL, log) |
| dmdeployinator dev | `dmdeployinator_ctl dev` | Start DMDeployinator in dev mode (turbopack) |
| ssh gcp, gcp ssh, ssh tool | `ssh_tool <host> [--cmd "command"]` | SSH to GCP VMs via CyberArk PSM with OTP relay |
| jira search | `jira_tool search '<JQL\|TEXT>' [--max N]` | Search Jira issues by JQL or text |
| jira search mine, my tickets | `jira_tool search --mine` | List my assigned Jira issues |
| jira updates, weekly report, updates report | `jira_tool updates [--days N] [--max N]` | N-day updates dashboard (assigned, watching, in-progress, resolved) |
| jira link | `jira_tool link DMDI-XXXXX <URL\|ISSUE_KEY> [TITLE\|TYPE]` | Add web or issue link to Jira ticket |
| jira find user | `jira_tool find-user <NAME\|EMAIL>` | Look up Jira user by name or email |
| ticket url, format url, link ticket | `url_tool ticket <TICKET_ID>` | Format clickable ticket URL (auto-detects system by prefix) |
| comment url | `url_tool comment <TICKET_ID> <COMMENT_ID>` | Format clickable Jira comment URL |
| smax url | `url_tool smax <REQUEST_ID>` | Format clickable SMAX request URL |
| gitlab mr url | `url_tool mr <MR_ID> --repo <REPO_PATH>` | Format clickable GitLab MR URL |
| gitlab mr, create mr | `gitlab_tool mr-create --title "..." [--repo PATH]` | Create GitLab merge request |
| gitlab mr list, list mrs | `gitlab_tool mr-list [--state STATE] [--mine]` | List GitLab merge requests |
| gitlab mr merge | `gitlab_tool mr-merge <MR_IID> [--repo PATH]` | Merge an approved GitLab MR |
| gitlab comment, mr comment | `gitlab_tool mr-comment <MR_IID> <BODY\|@file>` | Add comment to GitLab MR |
| atlantis unlock | `gitlab_tool atlantis-unlock <MR_IID> [--repo PATH]` | Unlock Atlantis plan locks |
| atlantis plan | `gitlab_tool atlantis-plan <MR_IID> [--repo PATH]` | Re-trigger Atlantis terraform plan |
| atlantis apply | `gitlab_tool atlantis-apply <MR_IID> [--repo PATH] [--project NAME]` | Apply Atlantis terraform changes |
| vpn, vpn connect, connect vpn | `vpn_tool` | Connect to VPN (smart default: status if connected, connect if not) |
| vpn disconnect, disconnect vpn | `vpn_tool disconnect` | Disconnect VPN |
| vpn status | `vpn_tool status` | Show VPN connection status, IP, zone |
| vpn nodes | `vpn_tool nodes` | Test VPN node availability |
| teams webhook | `teams_tool webhook --url <URL> --title "..." --body "..."` | Send MS Teams webhook notification |
| teams email | `teams_tool email --to <EMAIL> --subject "..." --body "..."` | Send MS Teams channel email notification |

## Notes

- **Script portability rule**: all DIL scripts must resolve base path in this order: `BASE_DIL` -> repo-relative from script location -> legacy `$HOME/Documents/dil_agentic_memory_0001`; fail clearly if unresolved.
- **Never hardcode user-specific paths** (for example `/home/moo/...`) as default DIL base resolution.
- **Work tools require VPN/network access** to AutoZone systems
- **Jira token**: cached at `/tmp/jira_token_temp.txt`, fallback: `getSecret z_az_jira_personal_access_token`
- **Jira formatters** (`md2jira`, `jira-panel`) are separate from `jira_tool`
- Agent manifests for jira_tool: `/az/talend/data/jira_tool/`
- Logs for jira_tool: `/az/talend/logs/jira_tool/`
- Full Jira sync policy: `_shared/preferences/jira-dil-bidirectional-sync-policy-2026-03-04.md`
- **SMAX auth**: SSO via PingFederate SAML, session cached at `/tmp/smax_token_temp.txt`
- **SMAX create-request vs create-change**: use `create-request` for consultation/service requests (e.g. ask TUG to decomm servers), use `create-change` for change requests (e.g. deploying ETL jobs, Control-M changes)
- **SMAX ChangeReason enum**: use `BusinessRequirement` (not free text)
- Logs for smax_tool: `/az/talend/logs/smax_tool/`
- **DMDeployinator paths**: App `/az/talend/scripts/node/apps/DMDeployinator/`, Data `/az/talend/data/DMDeployinator/`, Logs `/az/talend/logs/DMDeployinator/`
- **DMDeployinator port**: 3001 (env: `DMDI_PORT`), tmux session: `DMDeployinator`
- **url_tool**: zero-inference URL formatter — uses `domain_registry.json` ticket_systems templates. Outputs markdown (default), plain, or JSON.
- **vpn_tool**: config at `~/.config/vpn_tool/config`, logs at `/az/talend/logs/vpn_tool/`, tmux session: `vpn` (root-owned)
- **gitlab_tool**: project access tokens via 1Password, logs at `/az/talend/logs/gitlab_tool/`
- **ssh_tool**: CyberArk PSM proxy with OTP relay, hosts in `ssh_hosts.yml`
