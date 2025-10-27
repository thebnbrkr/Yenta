"""
Enhanced Yenta CLI with workflow registry, auto-discovery, and custom nodes.

New commands:
- yenta discover <server.py>     # Discover MCP entities
- yenta workflows list            # List all workflows
- yenta workflows run <name>      # Run workflow by name
- yenta workflows register        # Register workflows from directory
- yenta nodes list               # List custom nodes
- yenta metrics <session_id>     # Show detailed metrics
"""

import asyncio
import typer
import yaml
import json
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich import print as rprint
from yenta.registry import get_shared_registry

from agora.telemetry import AuditLogger
from yenta.workflow_registry import (
    get_global_registry, 
    print_registry_summary,
    discover_workflows_from_file,
    discover_yaml_workflows
)
from yenta.autodiscovery import (
    discover_mcp_entities,
    print_registry_summary as print_mcp_summary
)

# Keep existing CLI app
from yenta.cli import app, _run_flow, _run_workflow

console = Console()


# ======================================================================
# NEW COMMAND GROUP: DISCOVER
# ======================================================================

@app.command()
def discover(
    server_file: str = typer.Argument(..., help="Path to FastMCP server file"),
    method: str = typer.Option("ast", "--method", "-m", help="Discovery method: 'ast' or 'runtime'"),
    save: bool = typer.Option(False, "--save", "-s", help="Save discovered entities to registry")
):
    """
    🔍 Discover MCP entities from a FastMCP server file.
    
    Scans @mcp.tool(), @mcp.prompt(), @mcp.resource() decorators and shows
    available entities with their schemas.
    
    Example:
        yenta discover my_server.py
        yenta discover my_server.py --method runtime
        yenta discover my_server.py --save
    """
    server_path = Path(server_file)
    
    if not server_path.exists():
        rprint(f"[red]❌ File not found: {server_file}[/red]")
        raise typer.Exit(1)
    
    rprint(f"\n🔍 [bold cyan]Discovering MCP entities from:[/bold cyan] {server_file}\n")
    
    try:
        registry = discover_mcp_entities(str(server_path), method=method)
        print_mcp_summary(registry)
        
        if save:
            # Save to data/capabilities/
            from yenta.registry import JsonRegistry
            from yenta.models import Capabilities
            
            json_registry = get_shared_registry()
            capabilities = Capabilities(
                server=str(server_path),
                tools=[
                    {"name": e.name, "description": e.description, "schema": e.input_schema}
                    for e in registry.list_by_category("tools")
                ],
                prompts=[
                    {"name": e.name, "description": e.description}
                    for e in registry.list_by_category("prompts")
                ],
                resources=[
                    {"name": e.name, "description": e.description}
                    for e in registry.list_by_category("resources")
                ]
            )
            json_registry.save_capabilities(capabilities)
            rprint("\n[green]✅ Saved to data/capabilities/manifest.json[/green]")
        
    except Exception as e:
        rprint(f"[red]❌ Discovery failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


# ======================================================================
# NEW COMMAND GROUP: WORKFLOWS
# ======================================================================

workflows_app = typer.Typer(
    name="workflows",
    help="📋 Manage and run workflows"
)
app.add_typer(workflows_app, name="workflows")


@workflows_app.command("list")
def workflows_list(
    tag: Optional[str] = typer.Option(None, "--tag", "-t", help="Filter by tag")
):
    """
    📋 List all registered workflows.
    
    Example:
        yenta workflows list
        yenta workflows list --tag search
    """
    registry = get_global_registry()
    
    if tag:
        workflows = registry.list_by_tag(tag)
        if not workflows:
            rprint(f"[yellow]No workflows found with tag '{tag}'[/yellow]")
            return
    else:
        workflows = registry.list_all()
    
    if not workflows:
        rprint("[yellow]No workflows registered yet[/yellow]")
        rprint("\nRegister workflows with:")
        rprint("  yenta workflows register --python my_workflows.py")
        rprint("  yenta workflows register --yaml workflows/")
        return
    
    print_registry_summary(registry)


@workflows_app.command("run")
def workflows_run(
    name: str = typer.Argument(..., help="Workflow name"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Custom session ID"),
    input: Optional[str] = typer.Option(None, "--input", "-i", help="Initial input as JSON string")
):
    """
    🚀 Run a registered workflow by name.
    
    Example:
        yenta workflows run search_workflow
        yenta workflows run embedding_flow --input '{"text": "hello"}'
    """
    registry = get_global_registry()
    
    if not registry.exists(name):
        rprint(f"[red]❌ Workflow '{name}' not found[/red]")
        rprint("\nAvailable workflows:")
        for w in registry.list_all():
            rprint(f"  • {w.name}")
        raise typer.Exit(1)
    
    # Parse input JSON if provided
    input_data = None
    if input:
        try:
            input_data = json.loads(input)
        except json.JSONDecodeError as e:
            rprint(f"[red]❌ Invalid JSON input: {e}[/red]")
            raise typer.Exit(1)
    
    # Create workflow instance
    logger = AuditLogger(session_id=session_id or f"workflow-{name}")
    
    try:
        flow = registry.create_instance(name, logger)
        if not flow:
            rprint(f"[red]❌ Could not create workflow instance[/red]")
            raise typer.Exit(1)
        
        rprint(f"\n🚀 [bold cyan]Running workflow:[/bold cyan] {name}\n")
        
        # Run workflow
        shared = input_data or {}
        asyncio.run(flow.run_async(shared))
        
        # Print summary
        rprint("\n" + "=" * 70)
        rprint("✅ [bold green]WORKFLOW COMPLETED[/bold green]")
        rprint("=" * 70)
        
        summary = logger.get_summary()
        rprint(f"Session ID: {summary['session_id']}")
        rprint(f"Total Events: {summary['total_events']}")
        rprint(f"Duration: {summary.get('duration_seconds', 0):.2f}s")
        
    except Exception as e:
        rprint(f"[red]❌ Workflow execution failed: {e}[/red]")
        import traceback
        traceback.print_exc()
        raise typer.Exit(1)


@workflows_app.command("register")
def workflows_register(
    python: Optional[str] = typer.Option(None, "--python", "-p", help="Python file with workflow classes"),
    yaml_dir: Optional[str] = typer.Option(None, "--yaml", "-y", help="Directory with YAML workflows"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Custom name for workflow")
):
    """
    📝 Register workflows from Python files or YAML directory.
    
    Example:
        yenta workflows register --python my_workflows.py
        yenta workflows register --yaml workflows/
    """
    registry = get_global_registry()
    registered = 0
    
    if python:
        python_path = Path(python)
        if not python_path.exists():
            rprint(f"[red]❌ File not found: {python}[/red]")
            raise typer.Exit(1)
        
        rprint(f"\n📝 [bold]Discovering workflows from:[/bold] {python}\n")
        
        workflows = discover_workflows_from_file(str(python_path))
        for class_name, workflow_class in workflows.items():
            workflow_name = name or class_name
            registry.register_class(workflow_name, workflow_class)
            rprint(f"  ✅ Registered: {workflow_name}")
            registered += 1
    
    if yaml_dir:
        yaml_path = Path(yaml_dir)
        if not yaml_path.exists():
            rprint(f"[red]❌ Directory not found: {yaml_dir}[/red]")
            raise typer.Exit(1)
        
        rprint(f"\n📝 [bold]Discovering YAML workflows from:[/bold] {yaml_dir}\n")
        
        yaml_workflows = discover_yaml_workflows(str(yaml_path))
        for workflow_name, filepath in yaml_workflows.items():
            registry.register_yaml(workflow_name, filepath)
            rprint(f"  ✅ Registered: {workflow_name} ({Path(filepath).name})")
            registered += 1
    
    if registered == 0:
        rprint("[yellow]⚠️  No workflows to register. Specify --python or --yaml[/yellow]")
    else:
        rprint(f"\n[green]✅ Registered {registered} workflow(s)[/green]")


@workflows_app.command("info")
def workflows_info(
    name: str = typer.Argument(..., help="Workflow name")
):
    """
    ℹ️  Show detailed information about a workflow.
    
    Example:
        yenta workflows info search_workflow
    """
    registry = get_global_registry()
    workflow = registry.get(name)
    
    if not workflow:
        rprint(f"[red]❌ Workflow '{name}' not found[/red]")
        raise typer.Exit(1)
    
    rprint(f"\n[bold cyan]Workflow:[/bold cyan] {workflow.name}")
    rprint(f"[bold]Type:[/bold] {workflow.workflow_type}")
    rprint(f"[bold]Source:[/bold] {workflow.source}")
    
    if workflow.description:
        rprint(f"[bold]Description:[/bold] {workflow.description}")
    
    if workflow.tags:
        rprint(f"[bold]Tags:[/bold] {', '.join(workflow.tags)}")
    
    if workflow.yaml_spec:
        rprint("\n[bold]YAML Spec:[/bold]")
        rprint(yaml.dump(workflow.yaml_spec, default_flow_style=False))


# ======================================================================
# NEW COMMAND: METRICS
# ======================================================================

@app.command()
def metrics(
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Session ID"),
    latest: bool = typer.Option(False, "--latest", "-l", help="Show latest run"),
    format: str = typer.Option("table", "--format", "-f", help="Output format: table or json")
):
    """
    📊 Show detailed metrics for a workflow run.
    
    Example:
        yenta metrics --latest
        yenta metrics --session my-session-123
        yenta metrics --latest --format json
    """
    #from yenta.registry import JsonRegistry
    
    registry = get_shared_registry()
    
    if latest:
        run = registry.load_latest_run()
        if not run:
            rprint("[yellow]No runs found[/yellow]")
            return
    elif session_id:
        # Load from audit logs
        log_file = Path(f"./logs/{session_id}.json")
        if not log_file.exists():
            rprint(f"[red]❌ Session not found: {session_id}[/red]")
            raise typer.Exit(1)
        
        with open(log_file) as f:
            data = json.load(f)
        
        rprint(f"\n[bold cyan]Session:[/bold cyan] {data['session_id']}")
        rprint(f"[bold]Duration:[/bold] {data.get('duration_seconds', 0):.2f}s")
        rprint(f"[bold]Total Events:[/bold] {data['total_events']}")
        
        if format == "json":
            rprint(json.dumps(data, indent=2))
        else:
            # Show event breakdown
            rprint("\n[bold]Event Breakdown:[/bold]")
            for event_type, count in data['event_counts'].items():
                rprint(f"  {event_type}: {count}")
        
        return
    else:
        rprint("[yellow]Specify --latest or --session <id>[/yellow]")
        return
    
    # Show run details
    if format == "json":
        import json
        rprint(json.dumps(run.model_dump(), indent=2, default=str))
    else:
        table = Table(title=f"📊 Run Details: {run.session_id}")
        table.add_column("Test", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Latency", style="yellow")
        table.add_column("Mode", style="magenta")
        
        for result in run.results:
            status_icon = "✅" if result.status == "PASS" else "❌"
            
            table.add_row(
                result.test_name,
                f"{status_icon} {result.status}",
                f"{result.latency_ms:.0f}ms",
                result.mode
            )
        
        console.print(table)
        
        rprint(f"\n[bold]Summary:[/bold]")
        passed = sum(1 for r in run.results if r.status == "PASS")
        rprint(f"  Pass Rate: {passed}/{len(run.results)}")
        rprint(f"  Duration: {run.duration_ms:.0f}ms")


# ======================================================================
# NEW COMMAND: VISUALIZE
# ======================================================================

@app.command()
def visualize(
    name: Optional[str] = typer.Option(None, "--workflow", "-w", help="Workflow name to visualize"),
    yaml_file: Optional[str] = typer.Option(None, "--yaml", "-y", help="YAML file to visualize"),
    output: str = typer.Option("workflow.mmd", "--output", "-o", help="Output Mermaid file")
):
    """
    🎨 Generate Mermaid diagram for a workflow.
    
    Example:
        yenta visualize --workflow search_flow
        yenta visualize --yaml workflow.yaml --output diagram.mmd
    """
    if name:
        registry = get_global_registry()
        workflow = registry.get(name)
        
        if not workflow:
            rprint(f"[red]❌ Workflow '{name}' not found[/red]")
            raise typer.Exit(1)
        
        # Create instance and generate diagram
        logger = AuditLogger(session_id="visualize")
        flow = registry.create_instance(name, logger)
        
        if flow:
            mermaid = flow.to_mermaid()
            Path(output).write_text(mermaid)
            rprint(f"[green]✅ Diagram saved to {output}[/green]")
            rprint("\nPreview:")
            rprint(mermaid)
    
    elif yaml_file:
        rprint("[yellow]YAML visualization not yet implemented[/yellow]")
    else:
        rprint("[yellow]Specify --workflow or --yaml[/yellow]")


if __name__ == "__main__":
    app()
