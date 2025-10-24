"""
Enhanced MCPWorkflowFlow with support for custom ValidationNodes/RoutingNodes.

This enables "Option 3": YAML workflows that reference both MCP tools AND custom Python nodes.
"""

from typing import Dict, Any, List, Optional
from pathlib import Path
import importlib.util
import inspect
from agora.telemetry import AuditedAsyncFlow, AuditLogger
from yenta.workflow_nodes import MCPNode
from yenta.parser import WorkflowParser


class MCPWorkflowFlow(AuditedAsyncFlow):
    """
    Enhanced orchestration flow that supports:
    - MCP tools (from FastMCP server)
    - Custom ValidationNodes and RoutingNodes (from Python file)
    - Explicit parameter passing (tool[param1,param2])
    - Auto-discovery of tool parameters
    - Mixed workflows in YAML
    
    Example YAML:
        workflow_name: "smart_search"
        mcp_server: "my_server.py"
        custom_nodes: "my_validators.py"
        
        workflow:
          - validate_input >> check_cache
          - check_cache - 'hit' >> return_cached
          - check_cache - 'miss' >> search_docs[query]  # ✨ Only pass 'query'
    """
    
    def __init__(
        self,
        workflow_name: str,
        server_path: str,
        workflow_spec: List[str],
        logger: AuditLogger,
        initial_input: Optional[Dict[str, Any]] = None,
        custom_nodes_file: Optional[str] = None
    ):
        super().__init__(workflow_name, logger)
        self.server_path = server_path
        self.workflow_spec = workflow_spec
        self.initial_input = initial_input or {}
        self.custom_nodes_file = custom_nodes_file
        self.nodes: Dict[str, Any] = {}
        self.start_node_name = None
        
        # Load custom nodes if provided
        self.custom_node_classes = {}
        if custom_nodes_file:
            self.custom_node_classes = self._load_custom_nodes(custom_nodes_file)
        
        self._build_workflow()
    
    def _load_custom_nodes(self, filepath: str) -> Dict[str, type]:
        """
        Load custom ValidationNode/RoutingNode classes from Python file.
        """
        print(f"📦 Loading custom nodes from: {filepath}")
        
        if not Path(filepath).exists():
            raise FileNotFoundError(f"Custom nodes file not found: {filepath}")
        
        # Import the module
        spec = importlib.util.spec_from_file_location("custom_nodes", filepath)
        if not spec or not spec.loader:
            raise ImportError(f"Could not load module from {filepath}")
        
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        # Find all custom node classes
        try:
            from yenta.custom_nodes import ValidationNode, RoutingNode, TransformNode
        except ImportError:
            from custom_nodes import ValidationNode, RoutingNode, TransformNode
        
        custom_classes = {}
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if issubclass(obj, (ValidationNode, RoutingNode, TransformNode)):
                if obj not in [ValidationNode, RoutingNode, TransformNode]:
                    custom_classes[name] = obj
                    print(f"  ✅ Found custom node: {name}")
        
        if not custom_classes:
            print(f"  ⚠️  No custom nodes found in {filepath}")
        
        return custom_classes
    
    def _is_custom_node(self, node_name: str) -> bool:
        """
        Check if a node name refers to a custom node class.
        
        Supports both exact class name match and snake_case conversion.
        """
        if node_name in self.custom_node_classes:
            return True
        
        # Try converting snake_case to PascalCase
        pascal_case = ''.join(word.capitalize() for word in node_name.split('_'))
        return pascal_case in self.custom_node_classes
    
    def _get_custom_node_class(self, node_name: str) -> Optional[type]:
        """Get the custom node class for a given node name."""
        if node_name in self.custom_node_classes:
            return self.custom_node_classes[node_name]
        
        pascal_case = ''.join(word.capitalize() for word in node_name.split('_'))
        return self.custom_node_classes.get(pascal_case)
    
    def _build_workflow(self):
        """
        Parse workflow and create nodes.
        
        For each node:
        1. Check if it's a custom node → instantiate custom class
        2. Otherwise → create MCPNode with optional explicit params
        """
        parser = WorkflowParser()
        connections = parser.parse_workflow(self.workflow_spec)
        
        if not connections:
            raise ValueError("No valid workflow connections found")
        
        ordered_nodes = parser.get_ordered_nodes(connections)
        self.start_node_name = parser.get_start_node(connections)
        
        print(f"\n🔨 Building workflow with {len(ordered_nodes)} nodes:")
        
        # Create nodes (MCP or Custom)
        for i, node_name in enumerate(ordered_nodes):
            next_node = ordered_nodes[i + 1] if i < len(ordered_nodes) - 1 else "complete"
            
            # ✨ Get explicit params if specified (e.g., tool[url,limit])
            explicit_params = parser.get_node_params(connections, node_name)
            
            # Decision: Custom node or MCP tool?
            if self._is_custom_node(node_name):
                # It's a custom ValidationNode/RoutingNode
                custom_class = self._get_custom_node_class(node_name)
                print(f"  🎨 Custom: {node_name} ({custom_class.__name__})")
                
                node = custom_class(
                    name=node_name,
                    audit_logger=self.audit_logger
                )
            else:
                # It's an MCP tool from FastMCP server
                param_info = f"[{','.join(explicit_params)}]" if explicit_params else ""
                print(f"  🔧 MCP Tool: {node_name}{param_info}")
                
                node = MCPNode(
                    name=node_name,
                    audit_logger=self.audit_logger,
                    entity_type="tool",
                    entity_name=node_name,
                    server_path=self.server_path,
                    next_node=next_node,
                    explicit_params=explicit_params  # ✨ Pass explicit params
                )
            
            self.nodes[node_name] = node
        
        # Wire nodes using Agora's >> operator
        print(f"\n🔗 Wiring {len(connections)} connections:")
        for source_name, action, target_name, _ in connections:
            source_node = self.nodes[source_name]
            
            if target_name == "complete":
                continue
            
            target_node = self.nodes[target_name]
            
            if action:
                print(f"  {source_name} - '{action}' >> {target_name}")
                source_node - action >> target_node
            else:
                print(f"  {source_name} >> {target_name}")
                source_node >> target_node
        
        self.start(self.nodes[self.start_node_name])
        print(f"\n✅ Workflow built! Starting at: {self.start_node_name}\n")
    
    async def run_async(self, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the workflow."""
        if shared is None:
            shared = {}
        
        # Set initial input for the START NODE
        if self.initial_input and self.start_node_name:
            shared[f"{self.start_node_name}_input"] = self.initial_input
        
        await super().run_async(shared)
        
        return shared


# Backward compatibility
MCPWorkflowFlowEnhanced = MCPWorkflowFlow
