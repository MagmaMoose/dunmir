# MikroTik Minder

## Positioning

MikroTik Minder is a boring, reliable maintenance orchestrator for MikroTik RouterOS and RouterBOARD fleets. It does not try to replace RouterOS, The Dude, Prometheus, or your existing automation stack; it makes sure the important maintenance jobs happened, were recorded, were reviewed, and can be trusted.

## Product philosophy

- Reuse native RouterOS features before building custom logic.
- Prefer orchestration, verification, and auditability over clever automation.
- Treat backups, exports, and update actions as sensitive operational events.
- Support homelabs first, but keep the design suitable for small MSP fleets.
- Avoid inbound access to routers where possible; run the agent from a trusted host.

## Existing-tool landscape

### Official RouterOS capabilities to build on

| Area | Native capability | Use in MikroTik Minder |
| --- | --- | --- |
| Backup | `/system backup save` binary backups | Use for same-device restore-oriented recovery artifacts; encrypt and store off-device |
| Config export | `/export` text exports | Use for Git history, drift review, and human diffing |
| Updates | `/system package update` | Use for check/download/install workflows instead of custom package logic |
| RouterBOARD firmware | `/system routerboard print` and `/system routerboard upgrade` | Detect and align board firmware with installed RouterOS |
| Scheduling | `/system scheduler` | Reuse for device-local tasks only when needed; prefer central scheduling by Minder |
| Reachability checks | Netwatch | Reuse for device-local probes, but centralize assurance/reporting in Minder |
| Recovery | Watchdog | Treat as last-resort native protection, not as a replacement for change verification |
| Remote automation | SSH, RouterOS API, RouterOS REST API | Use existing interfaces; do not invent a new on-device agent |
| Monitoring | Syslog, SNMP, health metrics, The Dude integrations | Integrate with existing monitoring instead of replacing it |

### Existing ecosystem and what it already solves well

| Tool / workflow | Solves well | Minder stance |
| --- | --- | --- |
| [MikroTik RouterOS automatic backup and update](https://github.com/beeyev/Mikrotik-RouterOS-automatic-backup-and-update) | Practical single-router or small-fleet backup/update scripting | Learn from the workflow, but wrap with inventory, verification, history, and alerting |
| [eworm-de/routeros-scripts](https://github.com/eworm-de/routeros-scripts) | Mature RouterOS-native scripts for backup, health, update, Netwatch, notifications | Reuse patterns and native hooks; do not recreate a scripting framework |
| [Ansible community.routeros](https://docs.ansible.com/ansible/latest/collections/community/routeros/) | Declarative/config push workflows | Integrate later for optional apply workflows; do not compete in v1 |
| [Terraform provider for MikroTik](https://github.com/ddelnano/terraform-provider-mikrotik) | Infrastructure-style config management | Treat as an upstream desired-state source, not a feature to replace |
| [librouteros](https://github.com/socialwifi/RouterOS-api) / RouterOS API clients | Programmatic control over RouterOS | Reuse existing client libraries where practical |
| [go-routeros/routeros](https://github.com/go-routeros/routeros) | Stable Go API client | Strong candidate if Minder is implemented in Go |
| [node-routeros](https://github.com/Trakkasure/node-routeros) | Node-based automation | Useful for integrations, not a differentiator |
| [nshttpd/mikrotik-exporter](https://github.com/nshttpd/mikrotik-exporter) and SNMP/syslog stacks | Metrics and observability | Integrate with existing monitoring; do not rebuild NMS features |
| The Dude / Zabbix / LibreNMS / Prometheus | Ongoing monitoring and alerting | Complement them with maintenance-state assurance |
| MUT-style upgrade workflows | Bulk update orchestration | Reuse workflow ideas, but focus on safer pre/post verification |

## What not to reinvent

### Reuse or wrap

- RouterOS binary backups for restore.
- RouterOS text exports for Git-backed review.
- RouterOS package channels and update checks.
- RouterBOARD firmware reporting and upgrade commands.
- SSH and RouterOS API/REST API connectivity.
- Native scheduler, Netwatch, and watchdog when local automation is appropriate.
- Existing secret stores such as environment-based secret injection, 1Password, Vault, SOPS, or platform secret managers.
- Existing notification sinks via generic webhooks, SMTP, Slack, Discord, or Teams-compatible webhook adapters.

### Explicitly avoid

- A new RouterOS scripting DSL.
- A full replacement for The Dude, Prometheus, Zabbix, or LibreNMS.
- A home-grown secrets manager.
- A custom topology mapper.
- A config templating engine in v1.
- Automatic remediation without human approval.

## The real product gap

RouterOS already knows how to back up, export config, check updates, upgrade firmware, and reboot. What is still missing in many MikroTik environments is assurance:

- Did the scheduled backup actually happen?
- Was the binary backup encrypted and copied off-box?
- Did the text export change, and can a human review the diff?
- Is the fleet on the intended RouterOS channel and version?
- Is RouterBOARD firmware lagging behind RouterOS?
- Was there a pre-change backup before a risky action?
- Did the router return after reboot and are critical services healthy?
- Did a risky config change occur outside the expected workflow?
- Can operators use a dry run or approval gate before touching production?

## Unique value proposition

MikroTik Minder is the thin operational layer between native RouterOS capabilities and human trust. It gives operators inventory, scheduling, backup verification, config history, update safety checks, post-change health validation, and auditable alerts without trying to become a full NMS or configuration platform.

## MVP

### Must-have features

1. Device inventory with tags, site/group metadata, and per-device connection settings.
2. Secure credential references with per-device credentials and read-only audit mode.
3. Scheduled encrypted binary backups stored off-device.
4. Scheduled plain-text exports stored in Git.
5. Diffing between the latest and previous exports.
6. Update availability checks by device and fleet.
7. RouterBOARD firmware mismatch detection.
8. Pre-update backup verification.
9. Post-update health checks for reachability and critical services.
10. Alerting via generic webhooks, email, Slack, and Discord-compatible webhooks.
11. Dry-run/report-only mode for update and drift workflows.
12. Simple CLI first, with an optional small read-only web dashboard later.

### Suggested MVP boundaries

- One trusted agent/container deployment.
- Outbound connections from the agent to routers over SSH and/or RouterOS API.
- Git as the source of truth for exported text history.
- Local state kept small: job metadata, device inventory, last-known status, approval records.
- No device-side persistent agent.

## Do not build yet

- Full-blown NMS replacement.
- Replacing The Dude, Prometheus, Zabbix, or LibreNMS.
- Complex multi-vendor config templating.
- Multi-tenant SaaS before single-instance reliability is proven.
- Automatic config remediation without approval.
- A full visual topology mapper.
- A custom RouterOS scripting framework.
- Fleet-wide automatic staged rollout logic beyond simple approval-gated batches.
- Deep compliance policy engines.

## Architecture proposal

### Deployment model

- A lightweight container or service running on a trusted host.
- The host initiates outbound connections to MikroTik devices over SSH and/or RouterOS API/REST API.
- No inbound access to customer routers required beyond what normal administration already needs.

### Core modules

| Module | Responsibility |
| --- | --- |
| Inventory | Devices, groups, tags, maintenance windows, credential references |
| Backup | Binary backup creation, encryption, off-device retention, verification |
| Export / Drift | Text export capture, normalization, Git commit, diff, drift review |
| Update | Update check, channel awareness, backup gate, reboot tracking, post-checks |
| Health | Ping/API/SSH reachability, service probes, post-change validation |
| Alerting | Webhook/email delivery, severity mapping, dedup/suppression basics |
| Approval | Manual approval for risky actions, change reason, operator identity |
| Audit | Immutable job log, timestamps, result summaries, linked Git commits |

### Preferred implementation shape

- CLI-centric application with provider-style modules.
- Storage:
  - Git repository for text exports and review history.
  - Small local database (SQLite is enough for v1) for inventory, run history, and approval metadata.
  - Secret references only; actual secrets stay in secret managers or injected runtime config.
- Execution:
  - Central scheduler in the Minder agent.
  - Optional use of router-local scheduler only for very simple fallback tasks.

## Security requirements

- Never store router passwords in plain text.
- Support SSH keys where possible.
- Support API credentials/tokens where available and keep them per-device.
- Principle of least privilege: read-only audit account for inventory/backup/export checks, elevated approval-gated credential only for updates or restore workflows.
- Avoid logging secrets, tokens, private keys, or backup passwords.
- Encrypt binary backups because they may contain credentials and device secrets.
- Prefer text exports for diffing and binary backups for restore.
- Support manual approval before risky actions.
- Support read-only audit mode that cannot change device state.
- Record who approved an update or restore rehearsal.

## Maintenance workflows

### 1. First device onboarding

1. Add device metadata and tags.
2. Validate SSH/API connectivity.
3. Confirm least-privilege credential scope.
4. Capture first text export and initial binary backup.
5. Record RouterOS version, board model, firmware, packages, and health baseline.
6. Mark the device as enrolled only after backup/export succeeds.

### 2. Scheduled backup

1. Connect to device.
2. Create encrypted binary backup.
3. Create text export.
4. Pull artifacts to the trusted host.
5. Commit export to Git if changed.
6. Rotate retained binary backups per policy.
7. Alert on failure, drift, or missing artifacts.

### 3. Config drift detection

1. Run export in read-only audit mode.
2. Normalize volatile fields where needed.
3. Compare with latest committed export.
4. Open a review item or send an alert if drift is detected.
5. Allow operators to acknowledge expected drift.

### 4. Update check only

1. Query channel and current version.
2. Compare available updates.
3. Report RouterBOARD firmware mismatch separately.
4. Do not download or install in dry-run mode.

### 5. Safe update flow

1. Verify maintenance window and approval.
2. Confirm recent successful backup/export.
3. Check free space, health baseline, and connectivity.
4. Download/install RouterOS update.
5. Track reboot and return-to-service.
6. Run post-update health checks.
7. Report success with before/after version data and any service regressions.

### 6. RouterBOARD firmware alignment

1. Detect mismatch between current and upgrade firmware versions.
2. Require explicit approval if alignment needs reboot or follows package update.
3. Run firmware upgrade action.
4. Reboot if required.
5. Verify firmware now matches expected state.

### 7. Post-reboot health verification

- Ping reachable.
- SSH or API reachable.
- Critical interfaces present and enabled.
- Route, VPN, DHCP, CAPsMAN, or BGP checks as configured per device role.
- Temperature, voltage, or storage warnings surfaced if relevant.

### 8. Failed update / device did not return

1. Raise critical alert with last successful contact time.
2. Mark device degraded and stop further risky actions.
3. Provide operator checklist: console/OOB access, power cycle, rollback path, latest backup reference.
4. Keep retry logic conservative to avoid masking a real outage.

### 9. Watchdog heartbeat / dead-man alert

1. Expect regular successful contact from each managed device.
2. Alert if the device misses its expected heartbeat window.
3. Distinguish between Minder host failure and device failure where possible.

### 10. Restore rehearsal / backup validation

1. Verify backup artifact exists, is encrypted, and is readable.
2. Verify associated text export exists and matches inventory metadata.
3. In future phases, restore into a lab CHR or spare device for rehearsal.
4. Record the last proven restore rehearsal date.

## Data model and config example

```yaml
app:
  state_db: /var/lib/mikrotik-minder/minder.db
  git_repo: /srv/mikrotik-minder-configs
  log_level: info
  dry_run: false

secrets:
  provider: env
  references:
    core-readonly: MINDER_SECRET_CORE_READONLY
    core-admin: MINDER_SECRET_CORE_ADMIN
    branch-readonly: MINDER_SECRET_BRANCH_READONLY

alerts:
  routes:
    - name: ops-webhook
      type: webhook
      url: https://alerts.example.net/mikrotik
      events: [backup_failed, drift_detected, update_failed, heartbeat_missed]
    - name: email
      type: smtp
      to: [netops@example.net]
      events: [update_failed, restore_rehearsal_due]

defaults:
  transport:
    primary: ssh
    fallback_api: true
  backup:
    encrypted: true
    retention: 14
  export:
    normalize: true
    git_commit: true
  health_checks:
    ping: true
    ssh: true
  update_policy:
    channel: stable
    require_approval: true
    require_recent_backup_hours: 24

devices:
  - id: core-rtr-01
    name: core-rtr-01
    address: 10.0.0.1
    platform: routeros
    site: dc1
    role: core
    tags: [production, core]
    credentials:
      readonly_ref: core-readonly
      admin_ref: core-admin
    maintenance_window: "Sun 02:00-04:00 UTC"
    health_checks:
      interfaces: [bond1, vlan10, vlan20]
      services:
        - type: bgp
        - type: dhcp-server
    alerts:
      profile: ops-webhook

  - id: branch-rtr-07
    name: branch-rtr-07
    address: 10.7.0.1
    site: branch-7
    role: edge
    tags: [branch]
    credentials:
      readonly_ref: branch-readonly
    update_policy:
      channel: long-term
      require_approval: false
```

## Example CLI commands

```bash
# Inventory
mikrotik-minder device add --file devices/core-rtr-01.yaml
mikrotik-minder device test-connect core-rtr-01
mikrotik-minder inventory list --tag production

# Backups and exports
mikrotik-minder backup run core-rtr-01
mikrotik-minder backup run --group dc1 --dry-run
mikrotik-minder export run --all
mikrotik-minder drift check core-rtr-01

# Updates
mikrotik-minder update check --all
mikrotik-minder update plan core-rtr-01
mikrotik-minder update apply core-rtr-01 --approve ticket-1234
mikrotik-minder firmware align core-rtr-01 --dry-run

# Operations and audit
mikrotik-minder job history core-rtr-01
mikrotik-minder alert test ops-webhook
mikrotik-minder restore validate core-rtr-01
```

## Example Git repo layout for backed-up configs

```text
configs/
  devices/
    core-rtr-01/
      inventory.yaml
      exports/
        2026-05-19T020000Z.rsc
        latest.rsc
      backups/
        2026-05-19T020000Z.backup.enc
      reports/
        2026-05-19T020000Z.json
    branch-rtr-07/
      inventory.yaml
      exports/
        2026-05-19T020000Z.rsc
        latest.rsc
  fleet/
    update-reports/
      2026-05-19-stable-check.json
  reviews/
    drift/
      core-rtr-01/
        2026-05-19T021500Z.diff
```

## Example alert messages

### Backup failed

```text
[critical] MikroTik Minder backup_failed
device=core-rtr-01 site=dc1
job=backup/2026-05-19T02:00:00Z
reason=SSH export succeeded but encrypted binary backup was not retrieved
last_successful_backup=2026-05-18T02:00:03Z
action=verify disk space, permissions, and backup password configuration
```

### Drift detected

```text
[warning] MikroTik Minder drift_detected
device=branch-rtr-07 site=branch-7
changes=3 commands modified
git_commit=abc1234
action=review exported diff before acknowledging
```

### Update succeeded

```text
[info] MikroTik Minder update_succeeded
device=core-rtr-01
routeros=7.17.2 -> 7.18.1
routerboard_firmware=7.17.2 -> 7.18.1
reboot_downtime=96s
post_checks=ping,ssh,bgp passed
```

## Risk register

| Risk | Why it matters | Mitigation |
| --- | --- | --- |
| Binary backups contain secrets | Backup theft can expose credentials | Encrypt backups, restrict access, short retention |
| False confidence from shallow health checks | Device may be reachable but service-broken | Role-based post-change checks, not just ping |
| RouterOS exports contain volatile fields | Noisy diffs reduce trust | Normalize or filter known volatile lines conservatively |
| API/SSH permissions are too broad | Tool compromise becomes device compromise | Separate read-only and admin credentials, approval gates |
| Automatic updates brick remote sites | Remote recovery may be hard | Require recent backup, health baseline, maintenance window, approval |
| Git repo becomes secret spill location | Config exports may include sensitive values | Mask/omit sensitive fields where practical, restrict repo access |
| Single Minder host failure blocks maintenance visibility | No assurance data during outage | External monitoring of the Minder host and dead-man alerting |
| Restore path is unproven | Backups may exist but not be usable | Track restore validation and add rehearsal workflow |

## Future feature list

- Optional read-only dashboard for job status, drift review, and update readiness.
- CHR-based restore rehearsal pipeline for selected devices.
- Integration with ticketing or change-management systems.
- Optional pull of desired state from Git/Ansible/Terraform sources.
- Batched rollout plans with staged approvals.
- Backup storage backends such as S3, SFTP, or object storage.
- Signed reports or tamper-evident audit exports.

## Open questions

- Should v1 target SSH only, or support both SSH and RouterOS API from the start?
- Which secret providers should be first-class in v1?
- How aggressively should export normalization filter volatile lines?
- Should Git commits be per-device run or grouped per scheduled job?
- Which role-based post-update checks are required for common router roles?
- Is SQLite sufficient for all intended small-MSP deployments, or should Postgres be optional early?
- How should approval records map to external ticket IDs?

## Phased implementation plan

### Phase 0: Specification and research

- Confirm target transport(s), secret provider strategy, and Git workflow.
- Validate the MVP against common homelab and small-MSP use cases.

### Phase 1: Core inventory and audit

- Device inventory.
- Secret references.
- Read-only connectivity test.
- Export capture.
- Git commit and diff reporting.
- Basic alert delivery.

### Phase 2: Backup assurance

- Encrypted binary backup workflow.
- Retention policy.
- Backup verification metadata.
- Restore-validation reporting.

### Phase 3: Update safety

- Update availability checks.
- Firmware mismatch detection.
- Approval-gated safe update flow.
- Post-reboot health validation.

### Phase 4: Operator polish

- Small dashboard.
- Better drift review UX.
- Maintenance windows and batching.
- More integrations for ticketing and storage.

## Reference points used for this design

- Official MikroTik RouterOS documentation for backups, configuration management, package updates, RouterBOARD firmware, scheduler, Netwatch, watchdog, API, REST API, and health monitoring.
- Existing community tooling and workflows:
  - beeyev automatic backup and update
  - eworm-de routeros-scripts
  - community.routeros for Ansible
  - Terraform MikroTik provider
  - librouteros / go-routeros / node-routeros clients
  - Prometheus exporter, syslog, SNMP, The Dude, and related monitoring stacks

The design goal is intentionally narrow: MikroTik Minder should not be the thing that does everything. It should be the thing that proves the important MikroTik maintenance tasks actually happened and can be trusted.
