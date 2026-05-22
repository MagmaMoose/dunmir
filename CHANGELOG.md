# CHANGELOG

<!-- version list -->

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
