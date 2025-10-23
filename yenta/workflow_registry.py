"""
Workflow registry for managing reusable workflows.

Allows users to define workflows in YAML or Python and reference them by name.
"""

import yaml
import importlib.util
import inspect
from pathlib import Path
from typing import Dict, Any, Optional, Type, Callable, Union
from dataclasses import dataclass

from agora.telemetry import AuditedAsyncFlow, AuditLogger


@dataclass
class WorkflowDefinition:
    """Metadata for a registered workflow"""
    name: str
    description: Optional[str]
    workflow_type: str  # 'yaml' or 'python'
    source: str  # File path or class name
    flow_class: Optional[Type[AuditedAsyncFlow]] = None
    yaml_spec: Optional[Dict[str, Any]] = None
    tags: list = None
    
    def __post_init__(self):
        if self.tags is None:
            self.tags = []


class WorkflowRegistry:
    """
    Central registry for all workflows.
    
    Allows workflows to be:
    1. Defined in YAML files
    2. Defined as Python classes
    3. Referenced by name in other workflows
    4. Listed and inspected via CLI
    
    Example:
        >>> registry = WorkflowRegistry()
        >>> 
        >>> # Register from YAML
        >>> registry.register_yaml("search_workflow", "workflows/search.yaml")
        >>> 
        >>> # Register from Python
        >>> @registry.register("embedding_flow")
        >>> class EmbeddingFlow(AuditedAsyncFlow):
        >>>     ...
        >>> 
        >>> # Get workflow by name
        >>> flow_class = registry.get("search_workflow")
    """
    
    def __init__(self):
        self.workflows: Dict[str, WorkflowDefinition] = {}
    
    def register(
        self, 
        name: str, 
        description: Optional[str] = None,
        tags: Optional[list] = None
    ):
        """
        Decorator to register a Python workflow class.
        
        Example:
            @registry.register("my_workflow", "Does something cool")
            class MyWorkflow(AuditedAsyncFlow):
                def __init__(self, logger):
                    super().__init__("my_workflow", logger)
                    # ... define nodes
        """
        def decorator(cls: Type[AuditedAsyncFlow]):
            self.workflows[name] = WorkflowDefinition(
                name=name,
                description=description or cls.__doc__,
                workflow_type="python",
                source=f"{cls.__module__}.{cls.__name__}",
                flow_class=cls,
                tags=tags or []
            )
            return cls
        return decorator
    
    def register_yaml(
        self,
        name: str,
        filepath: str,
        description: Optional[str] = None,
        tags: Optional[list] = None
    ):
        """
        Register a YAML workflow definition.
        
        Args:
            name: Workflow name
            filepath: Path to YAML file
            description: Optional description
            tags: Optional tags for categorization
        
        Example:
            registry.register_yaml(
                "search_workflow", 
                "workflows/search.yaml",
                tags=["search", "rag"]
            )
        """
        with open(filepath) as f:
            spec = yaml.safe_load(f)
        
        self.workflows[name] = WorkflowDefinition(
            name=name,
            description=description or spec.get("description"),
            workflow_type="yaml",
            source=filepath,
            yaml_spec=spec,
            tags=tags or spec.get("tags", [])
        )
    
    def register_class(
        self,
        name: str,
        flow_class: Type[AuditedAsyncFlow],
        description: Optional[str] = None,
        tags: Optional[list] = None
    ):
        """
        Register a workflow class directly (without decorator).
        
        Example:
            registry.register_class(
                "my_flow", 
                MyFlowClass,
                "Does something"
            )
        """
        self.workflows[name] = WorkflowDefinition(
            name=name,
            description=description or flow_class.__doc__,
            workflow_type="python",
            source=f"{flow_class.__module__}.{flow_class.__name__}",
            flow_class=flow_class,
            tags=tags or []
        )
    
    def get(self, name: str) -> Optional[WorkflowDefinition]:
        """Get workflow definition by name"""
        return self.workflows.get(name)
    
    def exists(self, name: str) -> bool:
        """Check if workflow exists"""
        return name in self.workflows
    
    def list_all(self) -> list[WorkflowDefinition]:
        """List all registered workflows"""
        return list(self.workflows.values())
    
    def list_by_tag(self, tag: str) -> list[WorkflowDefinition]:
        """List workflows by tag"""
        return [w for w in self.workflows.values() if tag in w.tags]
    
    def create_instance(
        self, 
        name: str, 
        logger: AuditLogger,
        **kwargs
    ) -> Optional[AuditedAsyncFlow]:
        """
        Create a workflow instance by name.
        
        Args:
            name: Workflow name
            logger: AuditLogger instance
            **kwargs: Additional arguments passed to workflow constructor
        
        Returns:
            Workflow instance or None if not found
        
        Example:
            logger = AuditLogger()
            flow = registry.create_instance("search_workflow", logger)
            await flow.run_async({"query": "test"})
        """
        workflow_def = self.get(name)
        if not workflow_def:
            return None
        
        if workflow_def.workflow_type == "python":
            if workflow_def.flow_class:
                return workflow_def.flow_class(logger, **kwargs)
        
        elif workflow_def.workflow_type == "yaml":
            # For YAML workflows, we need to build them dynamically
            # This would use MCPWorkflowFlow
            from yenta.workflow_flow import MCPWorkflowFlow
            
            spec = workflow_def.yaml_spec
            return MCPWorkflowFlow(
                workflow_name=spec.get("workflow_name", name),
                server_path=spec.get("mcp_server"),
                workflow_spec=spec.get("workflow", []),
                logger=logger,
                initial_input=spec.get("initial_input", {})
            )
        
        return None
    
    def remove(self, name: str) -> bool:
        """Remove a workflow from registry"""
        if name in self.workflows:
            del self.workflows[name]
            return True
        return False
    
    def search(self, query: str) -> list[WorkflowDefinition]:
        """Search workflows by name or description"""
        query_lower = query.lower()
        results = []
        
        for workflow in self.workflows.values():
            if query_lower in workflow.name.lower():
                results.append(workflow)
            elif workflow.description and query_lower in workflow.description.lower():
                results.append(workflow)
        
        return results


# ======================================================================
# FILE-BASED DISCOVERY
# ======================================================================

def discover_workflows_from_file(filepath: str) -> Dict[str, Type[AuditedAsyncFlow]]:
    """
    Discover all workflow classes from a Python file.
    
    Scans for classes that inherit from AuditedAsyncFlow.
    
    Args:
        filepath: Path to Python file
    
    Returns:
        Dict mapping class names to workflow classes
    
    Example:
        workflows = discover_workflows_from_file("my_workflows.py")
        for name, cls in workflows.items():
            registry.register_class(name, cls)
    """
    spec = importlib.util.spec_from_file_location("workflows", filepath)
    if not spec or not spec.loader:
        return {}
    
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    workflows = {}
    for name, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, AuditedAsyncFlow) and obj != AuditedAsyncFlow:
            workflows[name] = obj
    
    return workflows


def discover_yaml_workflows(directory: str) -> Dict[str, str]:
    """
    Discover all YAML workflow files in a directory.
    
    Args:
        directory: Path to directory containing YAML files
    
    Returns:
        Dict mapping workflow names to file paths
    
    Example:
        yaml_workflows = discover_yaml_workflows("workflows/")
        for name, filepath in yaml_workflows.items():
            registry.register_yaml(name, filepath)
    """
    workflows = {}
    dir_path = Path(directory)
    
    for yaml_file in dir_path.glob("*.yaml"):
        with open(yaml_file) as f:
            spec = yaml.safe_load(f)
        
        workflow_name = spec.get("workflow_name", yaml_file.stem)
        workflows[workflow_name] = str(yaml_file)
    
    return workflows


# ======================================================================
# GLOBAL REGISTRY
# ======================================================================

# Global singleton registry
_global_registry = WorkflowRegistry()


def get_global_registry() -> WorkflowRegistry:
    """Get the global workflow registry"""
    return _global_registry


def register_workflow(name: str, description: Optional[str] = None, tags: Optional[list] = None):
    """
    Decorator to register a workflow in the global registry.
    
    Example:
        @register_workflow("my_flow", "Does cool stuff")
        class MyFlow(AuditedAsyncFlow):
            ...
    """
    return _global_registry.register(name, description, tags)


# ======================================================================
# CLI HELPERS
# ======================================================================

def print_registry_summary(registry: Optional[WorkflowRegistry] = None):
    """Pretty-print workflow registry"""
    from rich.console import Console
    from rich.table import Table
    
    if registry is None:
        registry = get_global_registry()
    
    console = Console()
    
    table = Table(title="📋 Registered Workflows")
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Description", style="yellow")
    table.add_column("Tags", style="magenta")
    
    for workflow in registry.list_all():
        desc = (workflow.description or "")[:60]
        tags = ", ".join(workflow.tags) if workflow.tags else ""
        
        table.add_row(
            workflow.name,
            workflow.workflow_type,
            desc,
            tags
        )
    
    console.print(table)
    console.print(f"\n📊 Total workflows: {len(registry.list_all())}")


if __name__ == "__main__":
    # Example usage
    registry = WorkflowRegistry()
    
    # Register from decorator
    @registry.register("example_flow", "Example workflow")
    class ExampleFlow(AuditedAsyncFlow):
        """An example workflow"""
        pass
    
    # Register YAML workflow
    # registry.register_yaml("search", "workflows/search.yaml")
    
    # List all
    print_registry_summary(registry)