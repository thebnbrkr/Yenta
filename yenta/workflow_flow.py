"""
Enhanced MCPWorkflowFlow with support for:
- Automatic parameter mapping (NEW!)
- Explicit parameter specification
- Custom ValidationNodes/RoutingNodes

KEY FEATURES:
1. Auto-mapping: node_a >> node_b (automatically matches parameter names)
2. Explicit: node_a >> node_b[param1,param2] (only pass specified params)
3. Custom nodes: Python ValidationNode/RoutingNode classes for complex logic
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
    Enhanced orchestration flow with intelligent parameter mapping.
    
    AUTOMATIC PARAMETER MAPPING:
    ----------------------------
    When you connect nodes with >>, the system automatically:
    1. Discovers what parameters the target tool accepts
    2. Matches output keys from source with input params of target
    3. Only passes the parameters that are needed
    
    Example:
        # scrape_url outputs: {"url": "...", "title": "...", "content": "...", "links": [...]}
        # extract_links accepts: (content: str, max_links: int = 10)
        
        workflow:
          - scrape_url >> extract_links
        
        # System automatically passes only {"content": "..."} to extract_links
        # Ignores url, title, links since extract_links doesn't need them
    
    EXPLICIT PARAMETER MAPPING:
    ---------------------------
    You can override auto-mapping by specifying exactly what to pass:
    
        workflow:
          - scrape_url >> extract_links[content]           # Only content
          - scrape_url >> process_page[url, title, content] # Multiple params
    
    CUSTOM NODES:
    -------------
    Mix MCP tools with custom Python logic:
    
        custom_nodes: "my_validators.py"
        workflow:
          - validate_input >> check_cache
          - check_cache - 'hit' >> return_cached
          - check_cache - 'miss' >> search_docs[query]
    
    Example YAML:
        workflow_name: "smart_search"
        mcp_server: "my_server.py"
        custom_nodes: "my_validators.py"  # Optional
        
        workflow:
          - scrape_url >> extract_links          # Auto-mapped
          - extract_links >> filter_links[urls]  # Explicit
          - filter_links >> save_results         # Auto-mapped
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
        Parse workflow and create nodes with automatic parameter mapping.
        
        For each node:
        1. Check if it's a custom node → instantiate custom class
        2. Otherwise → create MCPNode with:
           - Explicit params if specified: tool[param1,param2]
           - Auto-mapping otherwise: discovers and matches params automatically
        """
        parser = WorkflowParser()
        connections = parser.parse_workflow(self.workflow_spec)
        
        if not connections:
            raise ValueError("No valid workflow connections found")
        
        ordered_nodes = parser.get_ordered_nodes(connections)
        self.start_node_name = parser.get_start_node(connections)
        
        print(f"\n🔨 Building workflow with {len(ordered_nodes)} nodes:")
        print(f"   Mode: {'Explicit + Auto-mapping' if any(p for _, _, _, p in connections if p) else 'Auto-mapping'}")
        
        # Create nodes (MCP or Custom)
        for i, node_name in enumerate(ordered_nodes):
            next_node = ordered_nodes[i + 1] if i < len(ordered_nodes) - 1 else "complete"
            
            # Get explicit params if specified (e.g., tool[url,limit])
            explicit_params = parser.get_node_params(connections, node_name)
            
            # Decision: Custom node or MCP tool?
            if self._is_custom_node(node_name):
                # It's a custom ValidationNode/RoutingNode
                custom_class = self._get_custom_node_class(node_name)
                print(f"   Custom: {node_name} ({custom_class.__name__})")
                
                node = custom_class(
                    name=node_name,
                    audit_logger=self.audit_logger
                )
            else:
                # It's an MCP tool from FastMCP server
                if explicit_params:
                    param_info = f"[{','.join(explicit_params)}] (explicit)"
                else:
                    param_info = "(auto-mapped)"
                
                print(f"  🔧 MCP Tool: {node_name} {param_info}")
                
                node = MCPNode(
                    name=node_name,
                    audit_logger=self.audit_logger,
                    entity_type="tool",
                    entity_name=node_name,
                    server_path=self.server_path,
                    next_node=next_node,
                    explicit_params=explicit_params  # None for auto-mapping
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
        print(f"\n Workflow built! Starting at: {self.start_node_name}")
        print(f"   Parameters will be {'explicitly filtered or auto-mapped' if any(self.nodes[n].explicit_params for n in self.nodes if hasattr(self.nodes[n], 'explicit_params')) else 'auto-mapped'}\n")
    
    async def run_async(self, shared: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Run the workflow with intelligent parameter mapping."""
        if shared is None:
            shared = {}
        
        # Set initial input for the START NODE
        if self.initial_input and self.start_node_name:
            shared[f"{self.start_node_name}_input"] = self.initial_input
        
        await super().run_async(shared)
        
        return shared


# Backward compatibility
MCPWorkflowFlowEnhanced = MCPWorkflowFlow
