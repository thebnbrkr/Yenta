import asyncio
import typer
import yaml
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from rich.console import Console
from rich.table import Table
from rich import print as rprint

from agora.telemetry import AuditLogger
from yenta.flow import MCPTestFlow
from yenta.workflow_flow import MCPWorkflowFlow
from yenta.registry import JsonRegistry

app = typer.Typer(
    name="yenta",
    help="🎭 Yenta - MCP Testing & Workflow Orchestration Framework",
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


async def _run_workflow(
    workflow_file: Path, 
    session_id: Optional[str] = None,
    input_data: Optional[Dict[str, Any]] = None
):
    """Internal helper to run workflow orchestration"""
    
    if not workflow_file.exists():
        rprint(f"[red]❌ Workflow file not found: {workflow_file}[/red]")
        raise typer.Exit(1)
    
    # Load workflow YAML
    with open(workflow_file) as f:
        spec = yaml.safe_load(f)
    
    # Extract required fields
    workflow_name = spec.get("workflow_name", workflow_file.stem)
    server_path = spec.get("mcp_server")
    workflow_lines = spec.get("workflow", [])
    initial_input = spec.get("initial_input", {})
    
    # Merge CLI input with YAML input
    if input_data:
        initial_input.update(input_data)
    
    if not server_path:
        rprint("[red]❌ Missing 'mcp_server' in workflow YAML[/red]")
        raise typer.Exit(1)
    
    if not workflow_lines:
        rprint("[red]❌ Missing 'workflow' in workflow YAML[/red]")
        raise typer.Exit(1)
    
    # Create logger and flow
    logger = AuditLogger(session_id=session_id or f"workflow-{workflow_name}")
    
    try:
        flow = MCPWorkflowFlow(
            workflow_name=workflow_name,
            server_path=server_path,
            workflow_spec=workflow_lines,
            logger=logger,
            initial_input=initial_input
        )
        
        # Run workflow
        rprint(f"\n🔄 [bold cyan]Running workflow:[/bold cyan] {workflow_name}\n")
        result = await flow.run_async()
        
        # Print results
        rprint("\n" + "=" * 70)
        rprint("✅ [bold green]WORKFLOW COMPLETED[/bold green]")
        rprint("=" * 70)
        
        # Show outputs from each node
        rprint("\n[bold]Node Outputs:[/bold]")
        for key, value in result.items():
            if key.endswith("_output"):
                node_name = key.replace("_output", "")
                rprint(f"\n[cyan]{node_name}:[/cyan]")
                # Pretty print the output
                import json
                try:
                    rprint(f"  {json.dumps(value, indent=2)[:500]}")
                except:
                    rprint(f"  {str(value)[:500]}")
        
        # Print telemetry summary
        rprint("\n" + "=" * 70)
        rprint("📊 [bold cyan]TELEMETRY SUMMARY[/bold cyan]")
        rprint("=" * 70)
        summary = logger.get_summary()
        rprint(f"Session ID: {summary['session_id']}")
        rprint(f"Total Events: {summary['total_events']}")
        rprint(f"Duration: {summary.get('duration_seconds', 0):.2f}s")
        
        rprint("\n[bold]Event Breakdown:[/bold]")
        for event, count in summary['event_counts'].items():
            rprint(f"  {event}: {count}")
        
        return result
        
    except Exception as e:
        rprint(f"\n[red]❌ Workflow failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


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
            rprint(f"\n[green]✅ Recordings saved to data/mocks/[/green]")
    except Exception as e:
        rprint(f"[red]❌ Test run failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def workflow(
    workflow_file: str = typer.Argument(..., help="Workflow YAML file to run"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Custom session ID"),
    input: Optional[str] = typer.Option(None, "--input", "-i", help="Initial input as JSON string")
):
    """🔗 Run MCP workflow orchestration"""
    
    workflow_path = Path(workflow_file)
    
    # Parse input JSON if provided
    input_data = None
    if input:
        import json
        try:
            input_data = json.loads(input)
        except json.JSONDecodeError as e:
            rprint(f"[red]❌ Invalid JSON input: {e}[/red]")
            raise typer.Exit(1)
    
    try:
        asyncio.run(_run_workflow(workflow_path, session_id, input_data))
    except Exception as e:
        if not isinstance(e, typer.Exit):
            rprint(f"[red]❌ Workflow execution failed: {e}[/red]")
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
        rprint(f"\n[green]✅ Recordings saved to data/mocks/[/green]")
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
    
    registry = JsonRegistry()
    stats = registry.get_stats()
    if stats["total_mocks"] == 0:
        rprint("[yellow]⚠️  No mocks found. Run 'yenta record' first.[/yellow]")
    
    # Override: use_mocks=true, record_mocks=false
    override = {"use_mocks": True, "record_mocks": False}
    
    try:
        asyncio.run(_run_flow(spec_path, session_id, override))
    except Exception as e:
        rprint(f"[red]❌ Replay failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def status():
    """📊 Show registry status"""
    
    registry = JsonRegistry()
    stats = registry.get_stats()
    
    table = Table(title="🎭 Yenta Registry Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Data Directory", stats["data_dir"])
    table.add_row("Total Mocks", str(stats["total_mocks"]))
    table.add_row("  ├─ Tools", str(stats["tools"]))
    table.add_row("  ├─ Resources", str(stats["resources"]))
    table.add_row("  └─ Prompts", str(stats["prompts"]))
    table.add_row("Total Runs", str(stats["total_runs"]))
    
    if stats["total_mocks"] > 0:
        table.add_row("Status", "✅ Ready for replay")
    else:
        table.add_row("Status", "No recordings yet")
    
    console.print(table)
    
    # Show recorded tools
    if stats["total_mocks"] > 0:
        rprint("\n[bold]Recorded Tools:[/bold]")
        mocks = registry.list_mocks()
        tools = set(m.name for m in mocks)
        for tool in sorted(tools):
            rprint(f"  • {tool}")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of runs to show")
):
    """📜 Show test run history"""
    
    registry = JsonRegistry()
    runs = registry.list_runs(limit=limit)
    
    if not runs:
        rprint("[yellow]No test runs found[/yellow]")
        return
    
    table = Table(title=f"📜 Recent Test Runs (last {len(runs)})")
    table.add_column("Timestamp", style="cyan")
    table.add_column("Spec", style="green")
    table.add_column("Status", style="yellow")
    table.add_column("Duration", style="magenta")
    table.add_column("Pass/Total", style="blue")
    
    for run in runs:
        passed = sum(1 for r in run.results if r.status == "PASS")
        total = len(run.results)
        status_icon = "✅" if run.status == "completed" else "❌"
        
        table.add_row(
            run.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            run.spec_name,
            f"{status_icon} {run.status}",
            f"{run.duration_ms:.0f}ms",
            f"{passed}/{total}"
        )
    
    console.print(table)


@app.command()
def clear(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Clear specific category (tools/resources/prompts)"),
    confirm: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """🧹 Clear recorded mocks"""
    
    registry = JsonRegistry()
    stats = registry.get_stats()
    
    if stats["total_mocks"] == 0:
        rprint("[yellow]ℹ️  No mocks found. Nothing to clear.[/yellow]")
        return
    
    if category:
        count = stats.get(category, 0)
        if count == 0:
            rprint(f"[yellow]ℹ️  No {category} mocks found.[/yellow]")
            return
        if not confirm:
            rprint(f"⚠️  This will delete [bold]{count}[/bold] {category} mock(s).")
            confirm = typer.confirm("Are you sure?")
    else:
        if not confirm:
            rprint(f"⚠️  This will delete [bold]{stats['total_mocks']}[/bold] total mock(s).")
            confirm = typer.confirm("Are you sure?")
    
    if confirm:
        registry.clear_mocks(category)
        rprint("[green]✅ Mocks cleared successfully[/green]")
    else:
        rprint("[yellow]Cancelled[/yellow]")


@app.command()
def inspect(
    tool: Optional[str] = typer.Option(None, "--tool", "-t", help="Filter by tool name"),
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category (tools/resources/prompts)")
):
    """🔍 Inspect recorded mocks"""
    
    registry = JsonRegistry()
    mocks = registry.list_mocks(category=category)
    
    if not mocks:
        rprint("[yellow]❌ No mocks found[/yellow]")
        return
    
    # Filter by tool if specified
    if tool:
        mocks = [m for m in mocks if m.name == tool]
        if not mocks:
            rprint(f"[yellow]❌ No mocks found for tool '{tool}'[/yellow]")
            return
    
    import json
    
    rprint(f"\n[bold cyan]📋 Recorded Mocks ({len(mocks)} total)[/bold cyan]\n")
    
    for i, mock in enumerate(mocks, 1):
        rprint(f"[bold]{i}. {mock.name}[/bold] [dim]({mock.category})[/dim]")
        rprint(f"   Args: {mock.arguments}")
        rprint(f"   Response: {json.dumps(mock.response, indent=2)[:200]}...")
        rprint(f"   Recorded: {mock.recorded_at.strftime('%Y-%m-%d %H:%M:%S')}")
        rprint()


if __name__ == "__main__":
    app()
