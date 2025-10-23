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
    - Mixed workflows in YAML
    
    Example YAML:
        workflow_name: "smart_search"
        mcp_server: "my_server.py"
        custom_nodes: "my_validators.py"  # ✨ Point to custom nodes
        
        workflow:
          - validate_input >> check_cache
          - check_cache - 'hit' >> return_cached  # ← check_cache is custom
          - check_cache - 'miss' >> search_docs   # ← others are MCP tools
    
    Example Python (my_validators.py):
        from yenta.custom_nodes import ValidationNode
        
        class CheckCache(ValidationNode):
            def validate(self, input_data):
                if cache_hit:
                    return "hit"
                return "miss"
    """
    
    def __init__(
        self,
        workflow_name: str,
        server_path: str,
        workflow_spec: List[str],
        logger: AuditLogger,
        initial_input: Optional[Dict[str, Any]] = None,
        custom_nodes_file: Optional[str] = None  # ✨ NEW PARAMETER
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
        
        Args:
            filepath: Path to Python file with custom node classes
        
        Returns:
            Dict mapping class names to their classes
        
        Example:
            # my_nodes.py
            class CacheCheck(ValidationNode):
                ...
            class RetryHandler(ValidationNode):
                ...
            
            # Returns: {
            #   "CacheCheck": <class CacheCheck>,
            #   "RetryHandler": <class RetryHandler>
            # }
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
            # Fallback for testing
            from custom_nodes import ValidationNode, RoutingNode, TransformNode
        
        custom_classes = {}
        for name, obj in inspect.getmembers(module, inspect.isclass):
            # Check if it's a subclass of our custom nodes
            if issubclass(obj, (ValidationNode, RoutingNode, TransformNode)):
                # Don't include the base classes themselves
                if obj not in [ValidationNode, RoutingNode, TransformNode]:
                    custom_classes[name] = obj
                    print(f"  ✅ Found custom node: {name}")
        
        if not custom_classes:
            print(f"  ⚠️  No custom nodes found in {filepath}")
        
        return custom_classes
    
    def _is_custom_node(self, node_name: str) -> bool:
        """
        Check if a node name refers to a custom node class.
        
        Supports both exact class name match and snake_case conversion:
        - "CacheCheck" → matches CacheCheck class
        - "check_cache" → matches CacheCheck class (auto-converts)
        
        Args:
            node_name: Node name from YAML (e.g., "check_cache")
        
        Returns:
            True if this is a custom node, False if it's an MCP tool
        """
        # Direct match (e.g., "CacheCheck")
        if node_name in self.custom_node_classes:
            return True
        
        # Try converting snake_case to PascalCase
        # "check_cache" → "CheckCache"
        pascal_case = ''.join(word.capitalize() for word in node_name.split('_'))
        return pascal_case in self.custom_node_classes
    
    def _get_custom_node_class(self, node_name: str) -> Optional[type]:
        """
        Get the custom node class for a given node name.
        
        Supports both exact match and snake_case → PascalCase conversion.
        """
        # Direct match
        if node_name in self.custom_node_classes:
            return self.custom_node_classes[node_name]
        
        # Try snake_case to PascalCase conversion
        pascal_case = ''.join(word.capitalize() for word in node_name.split('_'))
        return self.custom_node_classes.get(pascal_case)
    
    def _build_workflow(self):
        """
        Parse workflow and create nodes.
        
        For each node in the workflow:
        1. Check if it's a custom node (from custom_nodes_file)
           → If yes: Instantiate the custom class
        2. Otherwise, assume it's an MCP tool
           → Create an MCPNode that calls the tool via FastMCP
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
            
            # ✨ DECISION POINT: Custom node or MCP tool?
            if self._is_custom_node(node_name):
                # It's a custom ValidationNode/RoutingNode
                custom_class = self._get_custom_node_class(node_name)
                print(f"  🎨 Custom: {node_name} ({custom_class.__name__})")
                
                # Instantiate custom node
                # Note: Custom nodes handle their own routing in post_async()
                node = custom_class(
                    name=node_name,
                    audit_logger=self.audit_logger
                )
            else:
                # It's an MCP tool from FastMCP server
                print(f"  🔧 MCP Tool: {node_name}")
                node = MCPNode(
                    name=node_name,
                    audit_logger=self.audit_logger,
                    entity_type="tool",
                    entity_name=node_name,
                    server_path=self.server_path,
                    next_node=next_node
                )
            
            self.nodes[node_name] = node
        
        # Wire nodes using Agora's >> operator
        print(f"\n🔗 Wiring {len(connections)} connections:")
        for source_name, action, target_name in connections:
            source_node = self.nodes[source_name]
            
            # Skip if target is "complete" (end of workflow)
            if target_name == "complete":
                continue
            
            target_node = self.nodes[target_name]
            
            if action:
                # Conditional edge (branching)
                print(f"  {source_name} - '{action}' >> {target_name}")
                source_node - action >> target_node
            else:
                # Default edge (sequential)
                print(f"  {source_name} >> {target_name}")
                source_node >> target_node
        
        # Set start node
        self.start(self.nodes[self.start_node_name])
        print(f"\n✅ Workflow built! Starting at: {self.start_node_name}\n")
    
    async def run_async(self, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Run the workflow.
        
        Args:
            shared: Shared state dict (optional)
        
        Returns:
            Updated shared state with workflow results
        """
        if shared is None:
            shared = {}
        
        # Set initial input for the START NODE
        if self.initial_input and self.start_node_name:
            shared[f"{self.start_node_name}_input"] = self.initial_input
        
        await super().run_async(shared)
        
        return shared


# Backward compatibility: keep original class name
MCPWorkflowFlowEnhanced = MCPWorkflowFlow