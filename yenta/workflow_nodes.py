import asyncio
from typing import Any, Dict, Optional, List, Set
from agora.telemetry import AuditedAsyncNode

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    Client = None


class MCPNode(AuditedAsyncNode):
    """Agora node that calls an MCP entity (tool/prompt/resource) with automatic parameter mapping."""
    
    def __init__(
        self, 
        name: str, 
        audit_logger, 
        entity_type: str,
        entity_name: str, 
        server_path: str,
        next_node: Optional[str] = None,
        explicit_params: Optional[List[str]] = None  # User-specified params
    ):
        super().__init__(name, audit_logger)
        self.entity_type = entity_type
        self.entity_name = entity_name
        self.server_path = server_path
        self.next_node = next_node
        self.explicit_params = explicit_params  # From YAML [param1,param2]
        self.discovered_params = None  # Auto-discovered tool params
        self.required_params = None  # Required params (no defaults)
        self.optional_params = None  # Optional params (have defaults)
    
    async def _discover_tool_params(self) -> Optional[Dict[str, Any]]:
        """
        Auto-discover what parameters this tool accepts.
        
        Returns:
            Dict with 'required' and 'optional' param lists, or None if discovery fails
        """
        if not FASTMCP_AVAILABLE:
            return None
        
        try:
            async with Client(self.server_path) as client:
                tools_result = await client.list_tools()
                
                # Find the matching tool
                for tool in tools_result:
                    if tool.name == self.entity_name:
                        # Extract parameter names from JSON schema
                        schema = tool.inputSchema
                        if schema and 'properties' in schema:
                            all_params = list(schema['properties'].keys())
                            required = schema.get('required', [])
                            optional = [p for p in all_params if p not in required]
                            
                            return {
                                'all': all_params,
                                'required': required,
                                'optional': optional
                            }
                        break
        except Exception as e:
            # If discovery fails, we'll pass all params
            print(f"⚠️  Could not discover params for {self.entity_name}: {e}")
        
        return None
    
    def _auto_map_params(self, input_data: Dict[str, Any], available_params: List[str]) -> Dict[str, Any]:
        """
        Automatically map input data to tool parameters.
        
        Strategy:
        1. Find intersection of input keys and required params → MUST include
        2. Find intersection of input keys and optional params → include if present
        3. Warn if required params are missing
        
        Args:
            input_data: Data from previous node
            available_params: All params this tool accepts
        
        Returns:
            Filtered dict with only relevant params
        """
        if not available_params:
            # No schema info, pass everything
            return input_data
        
        input_keys = set(input_data.keys())
        available_set = set(available_params)
        
        # Find matching params
        matching_params = input_keys & available_set
        
        if not matching_params:
            print(f"⚠️  No matching params found for {self.entity_name}")
            print(f"    Available: {available_params}")
            print(f"    Input keys: {list(input_keys)}")
            # Return everything and let MCP handle it
            return input_data
        
        # Check for missing required params
        if self.required_params:
            required_set = set(self.required_params)
            missing_required = required_set - input_keys
            
            if missing_required:
                print(f"⚠️  Missing required params for {self.entity_name}: {missing_required}")
        
        # Build filtered dict
        filtered = {k: v for k, v in input_data.items() if k in matching_params}
        
        print(f"  ✨ Auto-mapped params for {self.entity_name}: {list(filtered.keys())}")
        if self.required_params:
            required_present = [k for k in filtered.keys() if k in self.required_params]
            optional_present = [k for k in filtered.keys() if k in self.optional_params]
            if required_present:
                print(f"     Required: {required_present}")
            if optional_present:
                print(f"     Optional: {optional_present}")
        
        return filtered
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """
        Get input from previous node's output and intelligently filter parameters.
        
        Priority:
        1. Explicit params from YAML (e.g., tool[url,limit]) → use exactly these
        2. Auto-discovered params from tool schema → smart intersection mapping
        3. Pass everything if both fail (fallback)
        """
        # Get input from previous node
        if f"{self.name}_input" in shared:
            input_data = shared[f"{self.name}_input"]
        else:
            prev_output_key = shared.get("_prev_output_key")
            if prev_output_key:
                prev_output = shared.get(prev_output_key, {})
                
                # FIX: Handle custom node output format
                # Custom nodes (ValidationNode/RoutingNode) store:
                # {"input": {...}, "routing_key": "..."}
                if isinstance(prev_output, dict) and 'input' in prev_output and 'routing_key' in prev_output:
                    # This came from a ValidationNode/RoutingNode - extract the actual input
                    input_data = prev_output['input']
                
                # Convert MCP response objects to dict
                elif hasattr(prev_output, 'model_dump'):
                    input_data = prev_output.model_dump()
                
                # Extract from CallToolResult content
                elif hasattr(prev_output, 'content') and prev_output.content:
                    try:
                        # Try to get text from content
                        content_item = prev_output.content[0]
                        if hasattr(content_item, 'text'):
                            input_data = {"result": content_item.text}
                        else:
                            input_data = {"result": str(content_item)}
                    except:
                        input_data = {}
                
                else:
                    input_data = prev_output
            else:
                input_data = {}
        
        # If input is not a dict, can't filter - return as-is
        if not isinstance(input_data, dict):
            return input_data
        
        # ===================================================================
        # SMART PARAMETER MAPPING
        # ===================================================================
        
        # OPTION 1: Explicit params specified (highest priority)
        if self.explicit_params:
            filtered = {k: v for k, v in input_data.items() if k in self.explicit_params}
            print(f"  🎯 Using explicit params: {self.explicit_params}")
            
            # Warn if explicitly requested params are missing
            missing = set(self.explicit_params) - set(filtered.keys())
            if missing:
                print(f"     ⚠️  Missing explicitly requested params: {missing}")
            
            return filtered
        
        # OPTION 2: Auto-discover and intelligently map (NEW!)
        if self.discovered_params is None and self.entity_type == "tool":
            param_info = await self._discover_tool_params()
            if param_info:
                self.discovered_params = param_info['all']
                self.required_params = param_info['required']
                self.optional_params = param_info['optional']
        
        if self.discovered_params:
            return self._auto_map_params(input_data, self.discovered_params)
        
        # OPTION 3: Fallback - pass everything (when discovery fails)
        print(f"  ⚠️  No param info available for {self.entity_name}, passing all input")
        return input_data
    
    async def exec_async(self, input_data: Any) -> Any:
        """Execute MCP entity call - return RAW result."""
        if not FASTMCP_AVAILABLE:
            raise RuntimeError("FastMCP not installed")
        
        async with Client(self.server_path) as client:
            if self.entity_type == "tool":
                result = await client.call_tool(self.entity_name, input_data)
                return result  # RAW CallToolResult object
            
            elif self.entity_type == "prompt":
                result = await client.get_prompt(self.entity_name, input_data)
                return result  # RAW
            
            elif self.entity_type == "resource":
                result = await client.read_resource(input_data.get("uri"))
                return result  # RAW
            
            else:
                raise ValueError(f"Unknown entity type: {self.entity_type}")
    
    async def post_async(self, shared: Dict[str, Any], _, result: Any) -> str:
        """Store RAW output and return routing key."""
        # Store result for next node - EXACTLY AS RECEIVED
        output_key = f"{self.name}_output"
        shared[output_key] = result
        shared["_prev_output_key"] = output_key
        
        # Return routing key for Agora
        # For default (no action) routing, return empty string
        # For conditional routing, return the action key
        return ""  # Default route - let Agora handle >> wiring
