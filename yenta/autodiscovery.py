"""
Auto-discovery system for FastMCP servers.

Scans Python files for @mcp.tool(), @mcp.prompt(), @mcp.resource() decorators
and builds a registry of available MCP entities with their schemas.
"""

import ast
import inspect
import importlib.util
from pathlib import Path
from typing import Dict, List, Any, Optional, Type
from dataclasses import dataclass


@dataclass
class MCPEntity:
    """Represents a discovered MCP entity (tool/prompt/resource)"""
    name: str
    category: str  # 'tool', 'prompt', 'resource'
    description: Optional[str] = None
    input_schema: Optional[Dict[str, Any]] = None
    output_type: Optional[str] = None
    function_name: Optional[str] = None
    

class MCPRegistry:
    """Registry of discovered MCP entities"""
    
    def __init__(self):
        self.entities: Dict[str, MCPEntity] = {}  # name -> entity
        self.by_category: Dict[str, List[MCPEntity]] = {
            "tools": [],
            "prompts": [],
            "resources": []
        }
    
    def register(self, entity: MCPEntity):
        """Register an MCP entity"""
        self.entities[entity.name] = entity
        self.by_category[entity.category + "s"].append(entity)
    
    def get(self, name: str) -> Optional[MCPEntity]:
        """Get entity by name"""
        return self.entities.get(name)
    
    def list_all(self) -> List[MCPEntity]:
        """List all entities"""
        return list(self.entities.values())
    
    def list_by_category(self, category: str) -> List[MCPEntity]:
        """List entities by category (tools/prompts/resources)"""
        return self.by_category.get(category, [])
    
    def exists(self, name: str) -> bool:
        """Check if entity exists"""
        return name in self.entities


class ASTDiscovery:
    """Discover MCP entities using AST parsing (without importing)"""
    
    @staticmethod
    def discover_from_file(filepath: str) -> List[MCPEntity]:
        """
        Parse Python file and extract @mcp.tool/@mcp.prompt/@mcp.resource decorators.
        
        Example FastMCP file:
            @mcp.tool()
            def search_docs(query: str) -> dict:
                '''Search documentation'''
                return {"results": [...]}
        
        Returns:
            List of MCPEntity objects
        """
        entities = []
        
        with open(filepath, 'r') as f:
            tree = ast.parse(f.read(), filename=filepath)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                entity = ASTDiscovery._extract_entity_from_function(node)
                if entity:
                    entities.append(entity)
        
        return entities
    
    @staticmethod
    def _extract_entity_from_function(func_node: ast.FunctionDef) -> Optional[MCPEntity]:
        """Extract MCP entity from a function definition"""
        
        # Check for @mcp.tool/@mcp.prompt/@mcp.resource decorators
        category = None
        for decorator in func_node.decorator_list:
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute):
                    if decorator.func.attr in ['tool', 'prompt', 'resource']:
                        category = decorator.func.attr
                        break
        
        if not category:
            return None
        
        # Extract function metadata
        name = func_node.name
        description = ast.get_docstring(func_node)
        
        # Extract input schema from type hints
        input_schema = ASTDiscovery._extract_input_schema(func_node)
        
        # Extract output type from return annotation
        output_type = None
        if func_node.returns:
            output_type = ast.unparse(func_node.returns)
        
        return MCPEntity(
            name=name,
            category=category,
            description=description,
            input_schema=input_schema,
            output_type=output_type,
            function_name=name
        )
    
    @staticmethod
    def _extract_input_schema(func_node: ast.FunctionDef) -> Dict[str, Any]:
        """Extract input schema from function arguments"""
        schema = {}
        
        for arg in func_node.args.args:
            if arg.arg == 'self':
                continue
            
            arg_name = arg.arg
            arg_type = None
            
            # Extract type annotation
            if arg.annotation:
                arg_type = ast.unparse(arg.annotation)
            
            schema[arg_name] = {
                "type": arg_type or "any",
                "required": True  # Assume all args are required unless they have defaults
            }
        
        # Check for defaults
        defaults_offset = len(func_node.args.args) - len(func_node.args.defaults)
        for i, default in enumerate(func_node.args.defaults):
            arg_index = defaults_offset + i
            if arg_index < len(func_node.args.args):
                arg_name = func_node.args.args[arg_index].arg
                if arg_name in schema:
                    schema[arg_name]["required"] = False
                    schema[arg_name]["default"] = ast.unparse(default)
        
        return schema


class RuntimeDiscovery:
    """Discover MCP entities by importing and inspecting the module"""
    
    @staticmethod
    def discover_from_file(filepath: str) -> List[MCPEntity]:
        """
        Import Python module and extract MCP entities from FastMCP server instance.
        
        This is more robust than AST parsing but requires importing the module.
        """
        entities = []
        
        # Load module
        spec = importlib.util.spec_from_file_location("mcp_server", filepath)
        if not spec or not spec.loader:
            return entities
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Find FastMCP server instance
        mcp_server = None
        for name, obj in inspect.getmembers(module):
            if hasattr(obj, '__class__') and obj.__class__.__name__ == 'FastMCP':
                mcp_server = obj
                break
        
        if not mcp_server:
            return entities
        
        # Extract tools
        if hasattr(mcp_server, '_tools'):
            for tool_name, tool_func in mcp_server._tools.items():
                entity = RuntimeDiscovery._extract_from_function(
                    tool_name, tool_func, 'tool'
                )
                entities.append(entity)
        
        # Extract prompts
        if hasattr(mcp_server, '_prompts'):
            for prompt_name, prompt_func in mcp_server._prompts.items():
                entity = RuntimeDiscovery._extract_from_function(
                    prompt_name, prompt_func, 'prompt'
                )
                entities.append(entity)
        
        # Extract resources
        if hasattr(mcp_server, '_resources'):
            for resource_name, resource_func in mcp_server._resources.items():
                entity = RuntimeDiscovery._extract_from_function(
                    resource_name, resource_func, 'resource'
                )
                entities.append(entity)
        
        return entities
    
    @staticmethod
    def _extract_from_function(name: str, func: Any, category: str) -> MCPEntity:
        """Extract entity metadata from function object"""
        
        # Get signature
        sig = inspect.signature(func)
        
        # Extract input schema
        input_schema = {}
        for param_name, param in sig.parameters.items():
            param_type = "any"
            if param.annotation != inspect.Parameter.empty:
                param_type = param.annotation.__name__ if hasattr(param.annotation, '__name__') else str(param.annotation)
            
            input_schema[param_name] = {
                "type": param_type,
                "required": param.default == inspect.Parameter.empty
            }
            
            if param.default != inspect.Parameter.empty:
                input_schema[param_name]["default"] = param.default
        
        # Extract output type
        output_type = None
        if sig.return_annotation != inspect.Signature.empty:
            output_type = sig.return_annotation.__name__ if hasattr(sig.return_annotation, '__name__') else str(sig.return_annotation)
        
        # Get docstring
        description = inspect.getdoc(func)
        
        return MCPEntity(
            name=name,
            category=category,
            description=description,
            input_schema=input_schema,
            output_type=output_type,
            function_name=func.__name__
        )


def discover_mcp_entities(
    filepath: str, 
    method: str = "ast"
) -> MCPRegistry:
    """
    Discover MCP entities from a FastMCP server file.
    
    Args:
        filepath: Path to FastMCP server Python file
        method: Discovery method - "ast" (safer) or "runtime" (more accurate)
    
    Returns:
        MCPRegistry with discovered entities
    
    Example:
        >>> registry = discover_mcp_entities("my_server.py")
        >>> print(registry.list_by_category("tools"))
        [MCPEntity(name='search_docs', category='tool', ...)]
    """
    registry = MCPRegistry()
    
    if method == "ast":
        entities = ASTDiscovery.discover_from_file(filepath)
    elif method == "runtime":
        entities = RuntimeDiscovery.discover_from_file(filepath)
    else:
        raise ValueError(f"Unknown method: {method}. Use 'ast' or 'runtime'")
    
    for entity in entities:
        registry.register(entity)
    
    return registry


# ======================================================================
# CLI HELPER
# ======================================================================

def print_registry_summary(registry: MCPRegistry):
    """Pretty-print registry summary"""
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    table = Table(title="🔍 Discovered MCP Entities")
    table.add_column("Name", style="cyan")
    table.add_column("Category", style="green")
    table.add_column("Inputs", style="yellow")
    table.add_column("Output", style="magenta")
    table.add_column("Description", style="dim")
    
    for entity in registry.list_all():
        input_str = ", ".join(entity.input_schema.keys()) if entity.input_schema else "none"
        output_str = entity.output_type or "any"
        desc = (entity.description or "")[:50] + "..." if entity.description and len(entity.description) > 50 else (entity.description or "")
        
        table.add_row(
            entity.name,
            entity.category,
            input_str,
            output_str,
            desc
        )
    
    console.print(table)
    console.print(f"\n📊 Total: {len(registry.list_all())} entities")
    console.print(f"  Tools: {len(registry.list_by_category('tools'))}")
    console.print(f"  Prompts: {len(registry.list_by_category('prompts'))}")
    console.print(f"  Resources: {len(registry.list_by_category('resources'))}")


if __name__ == "__main__":
    # Example usage
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python autodiscovery.py <mcp_server.py>")
        sys.exit(1)
    
    filepath = sys.argv[1]
    registry = discover_mcp_entities(filepath, method="ast")
    print_registry_summary(registry)