"""otai CLI entrypoint (typer app).

Every subcommand emits the JSON envelope by default, or a human-readable
table when `--format table` is passed (PRD §7).
"""

from __future__ import annotations

import json

import typer

from otai import commands, config, croissant, formatting
from otai import releases as releases_mod
from otai.logging_setup import configure_logging

app = typer.Typer(
    name="otai",
    help="Open Targets Agentic Query Tool.",
    no_args_is_help=True,
)

VALID_FORMATS = ("json", "table")


@app.callback()
def _root() -> None:
    """Open Targets Agentic Query Tool.

    Also configures logging (stderr only, never stdout - see
    logging_setup.py) before any subcommand runs. A Typer app with only a
    single registered command otherwise collapses to a single top-level
    command instead of keeping subcommands (list-releases, list-datasets,
    describe-dataset, run-sql) named, which this callback also prevents.
    """
    configure_logging()


def _validate_format(value: str) -> str:
    if value not in VALID_FORMATS:
        raise typer.BadParameter(
            f"Unsupported format {value!r}; expected one of {VALID_FORMATS}."
        )
    return value


def _emit_error(result: dict, output_format: str) -> None:
    error = result["error"]
    if output_format == "table":
        typer.echo(f"Error [{error['type']}]: {error['message']}")
    else:
        typer.echo(json.dumps(result))
    raise typer.Exit(code=1)


def _emit(result: dict, output_format: str, table_rows=None) -> None:
    """Emit `result` as JSON or `--format table`, the tail every command shares.

    `table_rows` extracts the list of row-dicts to render from `result["data"]`
    when `output_format == "table"`; omit it when `data` is already that list.
    """
    if not result["ok"]:
        _emit_error(result, output_format)
    elif output_format == "table":
        rows = table_rows(result["data"]) if table_rows else result["data"]
        typer.echo(formatting.render_table(rows))
    else:
        typer.echo(json.dumps(result))


@app.command("list-releases")
def list_releases_cmd(
    format: str = typer.Option(
        "json",
        "--format",
        callback=_validate_format,
        help="Output format: json (default) or table.",
    ),
) -> None:
    """List releases available in the Open Targets S3 bucket."""
    cache_dir = config.get_cache_dir()
    # Look up the fetch function fresh on every call (rather than relying on
    # commands.list_releases's bound-at-import-time default) so tests that
    # patch otai.releases.default_fetch_listing_xml are honored here too -
    # every command below does the same for the same reason.
    result = commands.list_releases(
        cache_dir, fetch_xml=releases_mod.default_fetch_listing_xml
    )
    _emit(result, format, lambda data: data["releases"])


@app.command("list-datasets")
def list_datasets_cmd(
    release: str | None = typer.Option(
        None,
        "--release",
        help="Release to list datasets for (default: latest).",
    ),
    format: str = typer.Option(
        "json",
        "--format",
        callback=_validate_format,
        help="Output format: json (default) or table.",
    ),
) -> None:
    """List datasets (croissant recordSets) for one release."""
    cache_dir = config.get_cache_dir()
    base_uri = config.get_base_uri()
    result = commands.list_datasets(
        cache_dir,
        release=release,
        fetch_xml=releases_mod.default_fetch_listing_xml,
        fetch_croissant=croissant.default_fetch_croissant,
        base_uri=base_uri,
    )
    _emit(result, format, lambda data: data["datasets"])


@app.command("describe-dataset")
def describe_dataset_cmd(
    name: str = typer.Argument(..., help="Dataset (recordSet) name to describe."),
    release: str | None = typer.Option(
        None,
        "--release",
        help="Release to describe the dataset for (default: latest).",
    ),
    format: str = typer.Option(
        "json",
        "--format",
        callback=_validate_format,
        help="Output format: json (default) or table.",
    ),
) -> None:
    """Describe one dataset's fields: names, types, descriptions, relationships."""
    cache_dir = config.get_cache_dir()
    result = commands.describe_dataset(
        cache_dir,
        name,
        release=release,
        fetch_xml=releases_mod.default_fetch_listing_xml,
        fetch_croissant=croissant.default_fetch_croissant,
    )
    _emit(result, format, lambda data: data["fields"])


@app.command("run-sql")
def run_sql_cmd(
    query: str = typer.Argument(..., help="Read-only SQL query to execute."),
    format: str = typer.Option(
        "json",
        "--format",
        callback=_validate_format,
        help="Output format: json (default) or table.",
    ),
) -> None:
    """Run a guarded, read-only SQL query against the `latest` release.

    No `--release` flag (PRD §7): unqualified table names resolve against
    `latest` via DuckDB's search_path.
    """
    cache_dir = config.get_cache_dir()
    base_uri = config.get_base_uri()
    result = commands.run_sql(
        cache_dir,
        query,
        fetch_xml=releases_mod.default_fetch_listing_xml,
        fetch_croissant=croissant.default_fetch_croissant,
        base_uri=base_uri,
    )
    _emit(
        result,
        format,
        lambda data: [
            dict(zip(data["columns"], row, strict=False)) for row in data["rows"]
        ],
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()
