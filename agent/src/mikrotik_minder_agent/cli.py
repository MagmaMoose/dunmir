"""Command-line interface for the agent."""

from __future__ import annotations

import logging
import sys

import click

from .apply import ApplyAborted, ApplyError, ApplyResult, apply_summary, apply_update
from .backup import BackupError, BackupRunner, backup_summary
from .config import ConfigError, load_config
from .daemon import Daemon
from .export import ExportError, ExportRunner
from .minder import JobReport, MinderClient, MinderError
from .transports import TransportError, build_transports
from .updates import UpdateCheckError, run_update_check, update_summary

log = logging.getLogger("mikrotik_minder_agent")

_LOG_FORMAT = "%(asctime)s %(levelname)-5s %(name)s — %(message)s"


def _configure_logging(verbose: int) -> None:
    level = logging.WARNING - (10 * verbose)
    logging.basicConfig(level=max(level, logging.DEBUG), format=_LOG_FORMAT)


@click.group()
@click.version_option(package_name="mikrotik-minder-agent")
def main() -> None:
    """Mikrotik Minder agent — probe RouterOS devices and report to the control plane."""


@main.command()
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.option("--once", is_flag=True, help="Run one pass over all devices and exit.")
@click.option("--dry-run", is_flag=True, help="Skip RouterOS; post synthetic heartbeats only.")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def run(config_path: str, once: bool, dry_run: bool, verbose: int) -> None:
    """Run the daemon (or one pass with --once)."""
    _configure_logging(verbose)
    config = _load(config_path)
    daemon = Daemon(config, dry_run=dry_run)
    if once:
        failures = daemon.run_once()
        if failures:
            click.echo(f"{failures} probe(s) failed", err=True)
            sys.exit(1)
        return
    daemon.run()


@main.command()
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.argument("device_name")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def check(config_path: str, device_name: str, verbose: int) -> None:
    """Probe a single device locally, print the result, do NOT call the worker."""
    _configure_logging(verbose)
    config = _load(config_path, require_server_token=False)
    device = next((d for d in config.devices if d.name == device_name), None)
    if device is None:
        click.echo(f"device '{device_name}' not in config", err=True)
        sys.exit(2)

    transports = build_transports(device, config.defaults)
    for t in transports:
        click.echo(f"trying {t.kind}…", err=True)
        try:
            result = t.probe()
        except TransportError as exc:
            click.echo(f"  {t.kind} failed: {exc}", err=True)
            continue
        click.echo(
            f"  {t.kind} OK · {result.identity} · ROS {result.version} · {result.latency_ms}ms",
        )
        return
    click.echo("all transports failed", err=True)
    sys.exit(1)


@main.command("export-once")
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.argument("device_name")
@click.option(
    "--skip-push",
    is_flag=True,
    help="Commit locally only; do not push to git.remote (useful while iterating on configs).",
)
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def export_once(config_path: str, device_name: str, skip_push: bool, verbose: int) -> None:
    """Capture `/export` for one device, commit to Git. Does NOT call the worker."""
    _configure_logging(verbose)
    config = _load(config_path, require_server_token=False)
    device = next((d for d in config.devices if d.name == device_name), None)
    if device is None:
        click.echo(f"device '{device_name}' not in config", err=True)
        sys.exit(2)
    try:
        runner = ExportRunner(config)
    except ExportError as exc:
        click.echo(f"export: {exc}", err=True)
        sys.exit(2)
    try:
        result = runner.run(device, skip_push=skip_push)
    except ExportError as exc:
        click.echo(f"export failed: {exc}", err=True)
        sys.exit(1)

    if not result.changed:
        click.echo(
            f"  no changes · {result.bytes_captured} bytes · path {result.relative_path}",
        )
    else:
        sha = (result.commit_sha or "")[:7]
        click.echo(
            f"  drift · +{result.lines_added}/-{result.lines_removed} lines · "
            f"commit {sha} · path {result.relative_path}",
        )
    if result.push_error:
        click.echo(f"  push FAILED: {result.push_error}", err=True)
        sys.exit(1)
    if result.pushed:
        click.echo("  pushed to remote")


@main.command("backup-once")
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.argument("device_name")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def backup_once(config_path: str, device_name: str, verbose: int) -> None:
    """Run an encrypted backup for one device and pull it locally. Local-only."""
    _configure_logging(verbose)
    config = _load(config_path, require_server_token=False)
    device = next((d for d in config.devices if d.name == device_name), None)
    if device is None:
        click.echo(f"device '{device_name}' not in config", err=True)
        sys.exit(2)
    try:
        runner = BackupRunner(config)
    except BackupError as exc:
        click.echo(f"backup: {exc}", err=True)
        sys.exit(2)
    try:
        result = runner.run(device)
    except BackupError as exc:
        click.echo(f"backup failed: {exc}", err=True)
        sys.exit(1)
    click.echo(f"  {backup_summary(result)}")
    click.echo(f"  saved to {result.file_path}")


@main.command("update-check")
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.argument("device_name")
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def update_check_cmd(config_path: str, device_name: str, verbose: int) -> None:
    """Ask one device about pending RouterOS / firmware updates. Local-only."""
    _configure_logging(verbose)
    config = _load(config_path, require_server_token=False)
    device = next((d for d in config.devices if d.name == device_name), None)
    if device is None:
        click.echo(f"device '{device_name}' not in config", err=True)
        sys.exit(2)
    try:
        result = run_update_check(device, config.defaults)
    except UpdateCheckError as exc:
        click.echo(f"update check failed: {exc}", err=True)
        sys.exit(1)

    click.echo(f"  {update_summary(result)}")
    upd = result.update
    if upd.available:
        click.echo(f"  channel={upd.channel} status={upd.status!r}")
    fw = result.firmware
    if not fw.has_routerboard:
        click.echo("  routerboard: n/a (CHR or similar)")
    elif fw.mismatch:
        click.echo(f"  firmware mismatch: {fw.current_firmware} vs upgrade {fw.upgrade_firmware}")


@main.group()
def update() -> None:
    """RouterOS update commands."""


@update.command("apply")
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
@click.argument("device_name")
@click.option("--approve", required=True, help="Approval ticket / reason. Recorded in the job.")
@click.option("--yes", is_flag=True, help="Skip the interactive confirmation prompt.")
@click.option(
    "--skip-backup-check",
    is_flag=True,
    help="Bypass the 'recent backup required' precondition. NOT recommended.",
)
@click.option("--max-wait", type=int, default=600, show_default=True,
              help="Seconds to wait for the router to return after reboot.")
@click.option("--min-free-mib", type=float, default=100.0, show_default=True,
              help="Minimum free disk space before attempting the install.")
@click.option(
    "--max-backup-age-hours",
    type=int, default=24, show_default=True,
    help="A backup newer than this many hours must exist locally (unless --skip-backup-check).",
)
@click.option("-v", "--verbose", count=True, help="Increase log verbosity (repeatable).")
def update_apply(
    config_path: str,
    device_name: str,
    approve: str,
    yes: bool,
    skip_backup_check: bool,
    max_wait: int,
    min_free_mib: float,
    max_backup_age_hours: int,
    verbose: int,
) -> None:
    """Download + install the RouterOS update and reboot. Approval-gated."""
    _configure_logging(verbose)
    config = _load(config_path)
    device = next((d for d in config.devices if d.name == device_name), None)
    if device is None:
        click.echo(f"device '{device_name}' not in config", err=True)
        sys.exit(2)

    if not yes:
        click.echo(
            f"This will reboot '{device.name}' ({device.address}). "
            f"Ticket: {approve}",
        )
        click.confirm("Proceed?", abort=True)

    started = int(__import__("time").time())
    try:
        result: ApplyResult = apply_update(
            config,
            device,
            ticket=approve,
            min_free_mib=min_free_mib,
            max_backup_age_seconds=max_backup_age_hours * 3600,
            max_wait_seconds=max_wait,
            require_backup=not skip_backup_check,
        )
    except ApplyAborted as exc:
        click.echo(f"aborted: {exc}", err=True)
        _report_apply_failure(config, device, started, str(exc), approve, aborted=True)
        sys.exit(2)
    except ApplyError as exc:
        click.echo(f"apply failed: {exc}", err=True)
        _report_apply_failure(config, device, started, str(exc), approve, aborted=False)
        sys.exit(1)

    click.echo(f"  {apply_summary(result)}")
    _report_apply_success(config, device, result)


def _report_apply_success(config, device, result: ApplyResult) -> None:
    try:
        with MinderClient(config.server) as client:
            client.send_job(
                JobReport(
                    device=device.name,
                    kind="update_apply",
                    status="success",
                    started_at=result.started_at,
                    finished_at=result.finished_at,
                    summary=apply_summary(result),
                    details={
                        "ticket": result.ticket,
                        "before_version": result.before.version,
                        "after_version": result.after.version,
                        "downtime_seconds": result.downtime_seconds,
                        "before_free": result.before.free_hdd_space,
                        "after_free": result.after.free_hdd_space,
                    },
                ),
            )
    except MinderError as exc:
        click.echo(f"warning: could not report success to worker: {exc}", err=True)


def _report_apply_failure(
    config,
    device,
    started: int,
    error: str,
    ticket: str,
    *,
    aborted: bool,
) -> None:
    finished = int(__import__("time").time())
    try:
        with MinderClient(config.server) as client:
            client.send_job(
                JobReport(
                    device=device.name,
                    kind="update_apply",
                    status="failed",
                    started_at=started,
                    finished_at=finished,
                    summary=("aborted: " if aborted else "failed: ") + error[:200],
                    details={
                        "ticket": ticket,
                        "error": error[:500],
                        "aborted_pre_install": aborted,
                    },
                ),
            )
    except MinderError as exc:
        click.echo(f"warning: could not report failure to worker: {exc}", err=True)


@main.command("test-connection")
@click.option("--config", "-c", "config_path", required=True, help="Path to YAML config file.")
def test_connection(config_path: str) -> None:
    """Verify the worker URL + agent token by firing a manual heartbeat for each device."""
    _configure_logging(verbose=1)
    config = _load(config_path)
    failures = 0
    with MinderClient(config.server) as minder:
        for d in config.devices:
            try:
                minder.send_heartbeat(d.name, status="unknown")
                click.echo(f"  {d.name}: heartbeat ok")
            except MinderError as exc:
                click.echo(f"  {d.name}: FAILED — {exc}", err=True)
                failures += 1
    if failures:
        sys.exit(1)


def _load(path: str, *, require_server_token: bool = True):
    try:
        return load_config(path, require_server_token=require_server_token)
    except ConfigError as exc:
        click.echo(f"config error: {exc}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
