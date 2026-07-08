"""otai CLI entrypoint (typer app).

Every subcommand emits the JSON envelope by default, or a human-readable
table when `--format table` is passed (PRD §7).
"""

from __future__ import annotations

import json

import typer

from otai import commands, config, formatting

app = typer.Typer(
    name="otai",
    help="Open Targets Agentic Query Tool.",
    no_args_is_help=True,
)

VALID_FORMATS = ("json", "table")


@app.callback()
def _root() -> None:
    """Open Targets Agentic Query Tool.

    Empty callback so typer keeps treating subcommands (like list-releases)
    as named subcommands even while only one is registered; more land in
    later issues (list-datasets, describe-dataset, run-sql).
    """


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
    result = commands.list_releases(cache_dir)

    if not result["ok"]:
        _emit_error(result, format)
    elif format == "table":
        typer.echo(formatting.render_table(result["data"]["releases"]))
    else:
        typer.echo(json.dumps(result))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
