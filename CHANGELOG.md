# CHANGELOG

<!-- version list -->

## v1.5.1 (2026-05-29)

### Bug Fixes

- **agent**: Serialise shared git repo and stagger device startup
  ([#27](https://github.com/MagmaMoose/mikrotik-minder/pull/27),
  [`495a770`](https://github.com/MagmaMoose/mikrotik-minder/commit/495a770732b8726f28281eb6088cdba0c24bab12))

### Build System

- **deps**: Bump actions/checkout from 4.3.1 to 6.0.2
  ([#7](https://github.com/MagmaMoose/mikrotik-minder/pull/7),
  [`20d31fc`](https://github.com/MagmaMoose/mikrotik-minder/commit/20d31fc427ea118be0d9764a9b9fe74649855a48))

- **deps**: Bump cloudflare/wrangler-action from 3.15.0 to 4.0.0
  ([#10](https://github.com/MagmaMoose/mikrotik-minder/pull/10),
  [`4680ff5`](https://github.com/MagmaMoose/mikrotik-minder/commit/4680ff5433ddc3ba00db41a6ec14811b0c2d574b))

- **deps**: Bump docker/build-push-action from 6.19.2 to 7.2.0
  ([#9](https://github.com/MagmaMoose/mikrotik-minder/pull/9),
  [`b8e30f9`](https://github.com/MagmaMoose/mikrotik-minder/commit/b8e30f95f0b4335357367a06bcf3d58d14fff0dc))

- **deps**: Bump docker/setup-qemu-action from 3.7.0 to 4.0.0
  ([#8](https://github.com/MagmaMoose/mikrotik-minder/pull/8),
  [`190e47c`](https://github.com/MagmaMoose/mikrotik-minder/commit/190e47c837b4b723bc099b4d29de550c60bfb3f1))

- **deps**: Bump the npm_and_yarn group across 1 directory with 2 updates
  ([#4](https://github.com/MagmaMoose/mikrotik-minder/pull/4),
  [`9e23f7c`](https://github.com/MagmaMoose/mikrotik-minder/commit/9e23f7c2b24412916eb6dd4165db4e1e303d825a))

### Continuous Integration

- Move runners to Node 24 and finish action deprecation cleanup
  ([#17](https://github.com/MagmaMoose/mikrotik-minder/pull/17),
  [`570423b`](https://github.com/MagmaMoose/mikrotik-minder/commit/570423b7c69d85b46f5d05887e42bd3d7f411b83))


## v1.5.0 (2026-05-23)

### Bug Fixes

- **admin**: Add anti-caching headers to artifact download endpoint
  ([`437a766`](https://github.com/MagmaMoose/mikrotik-minder/commit/437a766e00fee565eacc019631ee9c78ffb0e7b0))

- **admin**: Derive requested_by from authenticated user instead of request body
  ([`a4c125c`](https://github.com/MagmaMoose/mikrotik-minder/commit/a4c125cacf1fde04069221877c124a4a5d5dd1c1))

- **admin**: Make artifact download atomic with UPDATE ... RETURNING
  ([`5d6f998`](https://github.com/MagmaMoose/mikrotik-minder/commit/5d6f998607c1b1c498dc0e0f2b91bcb041313a13))

- **admin**: Populate requested_by from X-Auth-Email header
  ([`83ceff7`](https://github.com/MagmaMoose/mikrotik-minder/commit/83ceff7cf65558b00b5a417a92208cf098dae45d))

- **admin**: Return pre-update artifact in one-shot download endpoint
  ([`5669bdd`](https://github.com/MagmaMoose/mikrotik-minder/commit/5669bdd17ed56c010d554a8b46c6ac6a83577d7d))

- **admin**: Validate X-Auth-Email header for commands endpoint
  ([`f0d11fa`](https://github.com/MagmaMoose/mikrotik-minder/commit/f0d11fa3dfa95794f2f1b5d9ded7faca2eea2a1e))

- **agent**: Align sensitive export docstring with CRLF normalization
  ([`4024100`](https://github.com/MagmaMoose/mikrotik-minder/commit/4024100df6150b82b8ff949763ee8a19c3017de7))

- **agent**: Enforce artifact size limit in sensitive export command
  ([`5ed94b7`](https://github.com/MagmaMoose/mikrotik-minder/commit/5ed94b7dad5aef47ae632e6d93959ecd6214314e))

- **agent**: Report command results for export/backup commands
  ([`8d47efb`](https://github.com/MagmaMoose/mikrotik-minder/commit/8d47efb6dc224a750d7811704ece018527820cfc))

- **agent**: Satisfy ruff (unused noqa + line length)
  ([`aefd605`](https://github.com/MagmaMoose/mikrotik-minder/commit/aefd6058b1dbfeaa3013c29fdce437081ec5177d))

- **agent**: Stream backup upload and URL-encode device/name
  ([`059f3b5`](https://github.com/MagmaMoose/mikrotik-minder/commit/059f3b52bcb1104c6f3789c036709210e3b13dff))

- **agent**: Wrap E501 in sensitive export size-limit message
  ([`ada14d8`](https://github.com/MagmaMoose/mikrotik-minder/commit/ada14d8084ae6d96bce77c2178efb869e237fe68))

- **agent**: Wrap long MinderError lines added by status_code refactor
  ([`f1965a6`](https://github.com/MagmaMoose/mikrotik-minder/commit/f1965a6619b1ccca5e89240fe08404518b312911))

- **commands**: Restrict artifact to sensitive_export kind + add agent tests
  ([`db9861d`](https://github.com/MagmaMoose/mikrotik-minder/commit/db9861d6128ce8b2911818546207517e9ddc4395))

- **daemon**: Accept CommandRef in _execute_command_via_daemon
  ([`f1f8c54`](https://github.com/MagmaMoose/mikrotik-minder/commit/f1f8c54d00a74bf08e29eec2fdabce292a5f23db))

- **daemon**: Only update last_backup on successful backup command
  ([`0fc8574`](https://github.com/MagmaMoose/mikrotik-minder/commit/0fc857440ac3ebcac33a70a1a17b143cb8dfd58c))

- **daemon**: Update device timestamps after command execution
  ([`d6fe667`](https://github.com/MagmaMoose/mikrotik-minder/commit/d6fe667de3062c4be42603187319c86261a3d30a))

- **ingest**: Fix invalid SQL in command claim query
  ([`4d4ea7f`](https://github.com/MagmaMoose/mikrotik-minder/commit/4d4ea7fa153fb6fbaae5e1ffd3f2ce952741c015))

- **ingest**: Handle concurrent backup upload race with upsert
  ([`7bfa5e6`](https://github.com/MagmaMoose/mikrotik-minder/commit/7bfa5e6657bbc105803c6185afc9e9600622252e))

- **ingest**: Preserve artifact payload verbatim without trimming
  ([`98df997`](https://github.com/MagmaMoose/mikrotik-minder/commit/98df99707b94a310a27fd82757408cc5f8379812))

- **ingest**: Verify sha256 on backup dedupe to prevent silent overwrite
  ([`b452e1c`](https://github.com/MagmaMoose/mikrotik-minder/commit/b452e1c4e55e1139de780506b85835331a7894a5))

- **migrations**: Add device_id to backup_files_agent_idx
  ([`88e9833`](https://github.com/MagmaMoose/mikrotik-minder/commit/88e9833f84987f481f2d4bba36c056f8b4bd732a))

- **worker**: Align backup upload comment with 404 response
  ([`3f67f68`](https://github.com/MagmaMoose/mikrotik-minder/commit/3f67f687fe64b9cb1c924aebb1e985b73b5d2a7d))

- **worker**: Guard JSON.parse of command params in poll endpoint
  ([`f3bb389`](https://github.com/MagmaMoose/mikrotik-minder/commit/f3bb389f98e6515bfc193e49f1aa8ad4870a7814))

- **worker**: Null-check artifact before returning the download body
  ([`fef2059`](https://github.com/MagmaMoose/mikrotik-minder/commit/fef2059d5707157b8a3174de7549d2daa45204b5))

- **worker**: Reject arrays in command result validation
  ([`79f93c1`](https://github.com/MagmaMoose/mikrotik-minder/commit/79f93c19dec200f6686d1c85a534226c4734ba7d))

- **worker**: Restore SLACK_INFO_CHANNEL dropped in the #13 merge
  ([`2b11914`](https://github.com/MagmaMoose/mikrotik-minder/commit/2b1191427819df9fb45f5ad6d8a8dd9a25aaccef))

- **worker**: Return 202 for pending/claimed commands on artifact endpoint
  ([`8a26256`](https://github.com/MagmaMoose/mikrotik-minder/commit/8a262565f0fa4002e6e76894e47a911564151c54))

### Chores

- **chart**: Mikrotik-minder-agent 0.1.3 (appVersion 0.0.2)
  ([`d5077a5`](https://github.com/MagmaMoose/mikrotik-minder/commit/d5077a5e6111525f4a386d58ea029a2dcd37ec0e))

### Features

- Stream encrypted backups to R2 + Pro UI download endpoints
  ([`401417b`](https://github.com/MagmaMoose/mikrotik-minder/commit/401417bb5d8afa624908637a0efdba5d50331041))

- **agent**: Poll for operator-triggered commands and execute them
  ([`1d73490`](https://github.com/MagmaMoose/mikrotik-minder/commit/1d73490585ed7e5afb1fe1b39a4e0bbf93488a85))

- **worker**: Command-dispatch endpoints + commands table
  ([`74f18b1`](https://github.com/MagmaMoose/mikrotik-minder/commit/74f18b1aa7aec715d9c8de99fbb7ba971cda2821))

### Performance Improvements

- **ingest**: Eliminate N+1 query in GET /commands by joining device name
  ([`9b14323`](https://github.com/MagmaMoose/mikrotik-minder/commit/9b14323b33fc041e8490cdedefe1389a135072e7))

- **worker**: Add composite index for command claim query
  ([`3b7b130`](https://github.com/MagmaMoose/mikrotik-minder/commit/3b7b1309be5b1a1613bead74c6fafda9d3695df3))

### Refactoring

- **db**: Remove redundant commands_agent_idx index
  ([`4160ffa`](https://github.com/MagmaMoose/mikrotik-minder/commit/4160ffa5f50cc5eb1864a66521b75ac21fec4618))

- **minder**: Include HTTP status code in MinderError for robust 404 handling
  ([`ce58a3a`](https://github.com/MagmaMoose/mikrotik-minder/commit/ce58a3a21028ca97dc538154b56679f0e70d62b4))


## v1.4.0 (2026-05-23)

### Bug Fixes

- **admin**: Add anti-caching headers to artifact download endpoint
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **admin**: Derive requested_by from authenticated user instead of request body
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **admin**: Make artifact download atomic with UPDATE ... RETURNING
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **admin**: Populate requested_by from X-Auth-Email header
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **admin**: Return pre-update artifact in one-shot download endpoint
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **admin**: Validate X-Auth-Email header for commands endpoint
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Align sensitive export docstring with CRLF normalization
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Enforce artifact size limit in sensitive export command
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Report command results for export/backup commands
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Satisfy ruff (unused noqa + line length)
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Wrap E501 in sensitive export size-limit message
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **agent**: Wrap long MinderError lines added by status_code refactor
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **daemon**: Accept CommandRef in _execute_command_via_daemon
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **daemon**: Update device timestamps after command execution
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **ingest**: Fix invalid SQL in command claim query
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **ingest**: Preserve artifact payload verbatim without trimming
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Guard JSON.parse of command params in poll endpoint
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Null-check artifact before returning the download body
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Reject arrays in command result validation
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Restore SLACK_INFO_CHANNEL dropped in the #13 merge
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Return 202 for pending/claimed commands on artifact endpoint
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

### Chores

- **chart**: Mikrotik-minder-agent 0.1.3 (appVersion 0.0.2)
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

### Features

- **agent**: Poll for operator-triggered commands and execute them
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Command-dispatch endpoints + commands table
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Command-dispatch foundation (commands table + endpoints)
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

### Performance Improvements

- **ingest**: Eliminate N+1 query in GET /commands by joining device name
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **worker**: Add composite index for command claim query
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

### Refactoring

- **db**: Remove redundant commands_agent_idx index
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))

- **minder**: Include HTTP status code in MinderError for robust 404 handling
  ([#15](https://github.com/MagmaMoose/mikrotik-minder/pull/15),
  [`6b0c86d`](https://github.com/MagmaMoose/mikrotik-minder/commit/6b0c86d60a87fac92c827b78893f0e58e1b28f48))


## v1.3.0 (2026-05-22)

### Bug Fixes

- **worker**: Align Slack env doc with severity-based routing
  ([`b504eef`](https://github.com/MagmaMoose/mikrotik-minder/commit/b504eef14c3225c8d33ebb160623c560a0dda154))

### Documentation

- **agent-protocol**: Clarify alert_deliveries scope for Slack bot
  ([`d7b0367`](https://github.com/MagmaMoose/mikrotik-minder/commit/d7b0367d232dd29cbf78be81b2a08abf7f1bc6ec))

- **agent-protocol**: Fix Slack bot env var table to match implementation
  ([`33c4e3f`](https://github.com/MagmaMoose/mikrotik-minder/commit/33c4e3f5dde440324cfdd5f0ba4edea698ff2c99))

### Features

- **worker**: Route Slack alerts to 3 channels by kind + announce wins
  ([`e81a81b`](https://github.com/MagmaMoose/mikrotik-minder/commit/e81a81b953392934356633e726a746e7b55ab100))

- **worker**: Slack bot-token alert delivery
  ([`08d06c3`](https://github.com/MagmaMoose/mikrotik-minder/commit/08d06c3e254a29ea1de18e04fbc0733f88093155))


## v1.2.1 (2026-05-22)

### Bug Fixes

- **chart**: Keep the git deploy key's trailing newline
  ([`073f16e`](https://github.com/MagmaMoose/mikrotik-minder/commit/073f16ef11e2ee3b84418501596f582976734f86))


## v1.2.0 (2026-05-21)

### Bug Fixes

- **agent**: Default serviceAccountName to 'default' when create is false
  ([`dc74c81`](https://github.com/MagmaMoose/mikrotik-minder/commit/dc74c81b3cc5ac77b1a90d8569188b487c6ff4f2))

### Features

- Bump agent to 0.0.1 + restore chart's image/secret helpers
  ([`8d72c7d`](https://github.com/MagmaMoose/mikrotik-minder/commit/8d72c7d20834d1ed267b33aae3e9c29a88baccb4))


## v1.1.1 (2026-05-21)

### Bug Fixes

- Complete env.prod wrangler config + opt deploy into prod environment
  ([`118bfb9`](https://github.com/MagmaMoose/mikrotik-minder/commit/118bfb94703437c25dd3134ea84f93b7976a1ddf))


## v1.1.0 (2026-05-21)

### Bug Fixes

- Address review feedback on secrets, prod env isolation, wrangler pin
  ([`ca22381`](https://github.com/MagmaMoose/mikrotik-minder/commit/ca22381d4756742e1d052e071606e592cde38a20))


## v1.0.0 (2026-05-21)

### Bug Fixes

- Address PR #3 CodeQL findings and Copilot review comments
  ([`5a1cf24`](https://github.com/MagmaMoose/mikrotik-minder/commit/5a1cf2470cb6de057bf7e79b18282e2864e71834))

### Features

- MVP scaffold — worker, agent, Helm chart, real-router validation
  ([`945f615`](https://github.com/MagmaMoose/mikrotik-minder/commit/945f6157ef0b7c9ae343f48b00366de4a330bac6))


## v0.0.1 (2026-05-19)

- Initial Release
