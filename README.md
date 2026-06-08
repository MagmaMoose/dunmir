# Dunmir

Dunmir is MagmaMoose's headless MikroTik maintenance platform. This repository is
intentionally lean: it is the public distribution shell for release-facing
documentation, license, and changelog history, not the implementation workspace.

## Use Dunmir

The supported public runtime is the hosted control plane plus the published
agent chart.

```bash
helm repo add calebsargeant https://charts.calebsargeant.com
helm repo update
helm install minder calebsargeant/mikrotik-minder-agent \
  --namespace minder --create-namespace \
  -f values.yaml
```

A minimal `values.yaml`:

```yaml
config:
  server:
    url: https://mikrotik-minder.sargeant.workers.dev
    agent_token_env: MTM_AGENT_TOKEN
  defaults:
    heartbeat_interval_seconds: 300
  devices:
    - name: core-rtr-01
      address: 10.0.0.1
      username: minder
      password_env: CORE_RTR_01_PASSWORD

secrets:
  create: true
  data:
    MTM_AGENT_TOKEN: mtm_...
    CORE_RTR_01_PASSWORD: ...
```

During the preview, agent tokens are issued manually. Open an issue or contact
`caleb@magmamoose.com` with the operator name and desired alert sink.

## Source Of Truth

Implementation changes belong in the MagmaMoose platform monorepo:

- Public implementation: [`platform/apps/dunmir` at `0acafb2cb991d84e772be412a60c08b7dda3a44e`](https://github.com/MagmaMoose/platform/tree/0acafb2cb991d84e772be412a60c08b7dda3a44e/apps/dunmir)
- Proprietary product code: `platform-pro/apps/dunmir-pro` in the private `platform-pro` repository

Do not copy worker, agent, chart, generated, or private/pro code back into this
repository. If public distribution text needs to mention implementation details,
link to a stable platform commit, release tag, or artifact.

## GitHub Action Status

This repository currently does not publish a GitHub Marketplace Action. There is
no root `action.yml` or `action.yaml` in the current tree or in this repository's
history, so there are no action inputs, outputs, permissions, or examples to
preserve here.

If Dunmir later ships as a Marketplace Action, that must be introduced as an
explicit action contract: exactly one root `action.yml` or `action.yaml`, thin
wrapper behavior, pinned implementation references, and Marketplace metadata kept
in the action repository rather than in `platform` or `platform-pro`.

## Release Notes

Historical source-era releases are preserved in [`CHANGELOG.md`](CHANGELOG.md).
Future source changes should land in `platform/apps/dunmir`; update this shell
only for release-facing copy, stable source links, or publishing notes.

## License

Apache-2.0. See [`LICENSE`](LICENSE).
