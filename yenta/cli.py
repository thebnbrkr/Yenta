import asyncio
import typer
import yaml
import tempfile
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from agora.telemetry import AuditLogger
from yenta.flow import MCPTestFlow
from yenta.mocks import MockRegistry

app = typer.Typer(
    name="yenta",
    help="🎭 Yenta - MCP Testing Framework with Record/Replay",
    add_completion=False
)
console = Console()


async def _run_flow(spec_file: Path, session_id: Optional[str] = None, override_mode: Optional[dict] = None):
    """Internal helper to run the test flow with optional mode overrides"""
    
    # Load and potentially modify the spec
    if override_mode:
        with open(spec_file) as f:
            spec_data = yaml.safe_load(f)
        
        # Apply overrides
        spec_data.update(override_mode)
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(spec_data, tmp)
            tmp_path = tmp.name
        
        actual_spec_file = Path(tmp_path)
    else:
        actual_spec_file = spec_file
        tmp_path = None
    
    try:
        logger = AuditLogger(session_id=session_id or f"yenta-{spec_file.stem}")
        flow = MCPTestFlow(logger)
        
        result = await flow.run_async({"spec_file": str(actual_spec_file)})
        
        # Print summary
        rprint("\n" + "=" * 70)
        rprint("📊 [bold cyan]AUDIT SUMMARY[/bold cyan]")
        rprint("=" * 70)
        summary = logger.get_summary()
        rprint(f"Session ID: {summary['session_id']}")
        rprint(f"Total Events: {summary['total_events']}")
        rprint(f"Duration: {summary.get('duration_seconds', 0):.2f}s")
        
        rprint("\n[bold]Event Breakdown:[/bold]")
        for event, count in summary['event_counts'].items():
            rprint(f"  {event}: {count}")
        
        return result
    finally:
        # Cleanup temp file if created
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


@app.command()
def run(
    spec_file: str = typer.Argument(..., help="YAML spec file to run"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Custom session ID"),
    record: bool = typer.Option(False, "--record", "-r", help="Enable recording mode"),
    replay: bool = typer.Option(False, "--replay", "-p", help="Enable replay mode (use mocks)")
):
    """🚀 Run MCP tests from a YAML spec"""
    
    spec_path = Path(spec_file)
    if not spec_path.exists():
        rprint(f"[red]❌ Spec file not found: {spec_file}[/red]")
        raise typer.Exit(1)
    
    # Determine override mode
    override = None
    if record and replay:
        rprint("[yellow]⚠️  Both --record and --replay specified. Using --record.[/yellow]")
        override = {"use_mocks": False, "record_mocks": True}
    elif record:
        override = {"use_mocks": False, "record_mocks": True}
    elif replay:
        override = {"use_mocks": True, "record_mocks": False}
    
    mode = "🎬 RECORD" if record else ("🔄 REPLAY" if replay else "▶️  RUN")
    rprint(f"\n{mode}: [bold]{spec_file}[/bold]\n")
    
    try:
        asyncio.run(_run_flow(spec_path, session_id, override))
        if record:
            rprint(f"\n[green]✅ Recordings saved to mocks.json[/green]")
    except Exception as e:
        rprint(f"[red]❌ Test run failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def record(
    spec_file: str = typer.Argument(..., help="YAML spec file to record"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Custom session ID")
):
    """📝 Record MCP calls for future replay"""
    
    rprint(f"📝 [bold red]Recording[/bold red]: {spec_file}\n")
    
    spec_path = Path(spec_file)
    if not spec_path.exists():
        rprint(f"[red]❌ Spec file not found: {spec_file}[/red]")
        raise typer.Exit(1)
    
    # Override: use_mocks=false, record_mocks=true
    override = {"use_mocks": False, "record_mocks": True}
    
    try:
        asyncio.run(_run_flow(spec_path, session_id, override))
        rprint(f"\n[green]✅ Recordings saved to mocks.json[/green]")
    except Exception as e:
        rprint(f"[red]❌ Recording failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def replay(
    spec_file: str = typer.Argument(..., help="YAML spec file to replay"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Custom session ID")
):
    """🔄 Replay tests using recorded mocks"""
    
    rprint(f"🔄 [bold blue]Replaying[/bold blue]: {spec_file}\n")
    
    spec_path = Path(spec_file)
    if not spec_path.exists():
        rprint(f"[red]❌ Spec file not found: {spec_file}[/red]")
        raise typer.Exit(1)
    
    registry = MockRegistry()
    if not registry.mock_file.exists():
        rprint("[yellow]⚠️  No mocks.json found. Run 'yenta record' first.[/yellow]")
    
    # Override: use_mocks=true, record_mocks=false
    override = {"use_mocks": True, "record_mocks": False}
    
    try:
        asyncio.run(_run_flow(spec_path, session_id, override))
    except Exception as e:
        rprint(f"[red]❌ Replay failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status():
    """📊 Show recording status and statistics"""
    
    registry = MockRegistry()
    
    table = Table(title="🎭 Yenta Mock Registry Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    if registry.mock_file.exists():
        num_mocks = len(registry.mocks)
        file_size = registry.mock_file.stat().st_size
        
        table.add_row("Mock File", str(registry.mock_file))
        table.add_row("Total Recordings", str(num_mocks))
        table.add_row("File Size", f"{file_size:,} bytes")
        table.add_row("Status", "✅ Ready for replay")
        
        if num_mocks > 0:
            rprint("\n[bold]Recorded Tools:[/bold]")
            tools = set()
            for key in registry.mocks.keys():
                import json
                try:
                    data = json.loads(key)
                    tools.add(data.get("tool", "unknown"))
                except:
                    pass
            for tool in sorted(tools):
                rprint(f"  • {tool}")
    else:
        table.add_row("Mock File", "❌ Not found")
        table.add_row("Status", "No recordings yet")
        table.add_row("Next Step", "Run 'yenta record <spec.yaml>'")
    
    console.print(table)


@app.command()
def clear(
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """🧹 Clear all recorded mocks"""
    
    registry = MockRegistry()
    
    if not registry.mock_file.exists():
        rprint("[yellow]ℹ️  No mocks.json file found. Nothing to clear.[/yellow]")
        return
    
    if not confirm:
        num_mocks = len(registry.mocks)
        rprint(f"⚠️  This will delete [bold]{num_mocks}[/bold] recorded mock(s).")
        confirm = typer.confirm("Are you sure?")
    
    if confirm:
        registry.mock_file.unlink()
        rprint("[green]✅ Mocks cleared successfully[/green]")
    else:
        rprint("[yellow]Cancelled[/yellow]")


@app.command()
def inspect(
    tool: Optional[str] = typer.Option(None, "--tool", "-t", help="Filter by tool name")
):
    """🔍 Inspect recorded mocks"""
    
    registry = MockRegistry()
    
    if not registry.mock_file.exists():
        rprint("[yellow]❌ No mocks.json found[/yellow]")
        return
    
    if not registry.mocks:
        rprint("[yellow]ℹ️  mocks.json is empty[/yellow]")
        return
    
    import json
    
    rprint(f"\n[bold cyan]📋 Recorded Mocks ({len(registry.mocks)} total)[/bold cyan]\n")
    
    for i, (key, response) in enumerate(registry.mocks.items(), 1):
        try:
            data = json.loads(key)
            tool_name = data.get("tool", "unknown")
            args = data.get("args", {})
            
            # Filter by tool if specified
            if tool and tool_name != tool:
                continue
            
            rprint(f"[bold]{i}. {tool_name}[/bold]")
            rprint(f"   Args: {args}")
            rprint(f"   Response: {json.dumps(response, indent=2)[:200]}...")
            rprint()
        except:
            rprint(f"[red]{i}. Invalid mock entry[/red]")


if __name__ == "__main__":
    app()
