import asyncio
from typing import Any, Dict, Optional, List
from agora.telemetry import AuditedAsyncNode

try:
    from fastmcp import Client
    FASTMCP_AVAILABLE = True
except ImportError:
    FASTMCP_AVAILABLE = False
    Client = None


class MCPNode(AuditedAsyncNode):
    """Agora node that calls an MCP entity (tool/prompt/resource)."""
    
    def __init__(
        self, 
        name: str, 
        audit_logger, 
        entity_type: str,
        entity_name: str, 
        server_path: str,
        next_node: Optional[str] = None,
        explicit_params: Optional[List[str]] = None  # ✨ NEW: User-specified params
    ):
        super().__init__(name, audit_logger)
        self.entity_type = entity_type
        self.entity_name = entity_name
        self.server_path = server_path
        self.next_node = next_node
        self.explicit_params = explicit_params  # ✨ From YAML [param1,param2]
        self.discovered_params = None  # ✨ Auto-discovered tool params
    
    async def _discover_tool_params(self) -> Optional[List[str]]:
        """
        Auto-discover what parameters this tool accepts.
        
        Returns:
            List of parameter names, or None if discovery fails
        """
        if not FASTMCP_AVAILABLE:
            return None
        
        try:
            async with Client(self.server_path) as client:
                tools_result = await client.list_tools()
                
                for tool in tools_result.tools:
                    if tool.name == self.entity_name:
                        # Extract parameter names from JSON schema
                        schema = tool.inputSchema
                        if schema and 'properties' in schema:
                            return list(schema['properties'].keys())
                        break
        except Exception as e:
            # If discovery fails, we'll pass all params
            print(f"⚠️  Could not discover params for {self.entity_name}: {e}")
        
        return None
    
    async def prep_async(self, shared: Dict[str, Any]) -> Any:
        """
        Get input from previous node's output and filter parameters.
        
        Priority:
        1. Explicit params from YAML (e.g., tool[url,limit])
        2. Auto-discovered params from tool schema
        3. Pass everything if both fail
        """
        # Get input from previous node
        if f"{self.name}_input" in shared:
            input_data = shared[f"{self.name}_input"]
        else:
            prev_output_key = shared.get("_prev_output_key")
            if prev_output_key:
                prev_output = shared.get(prev_output_key, {})
                
                # ✅ Convert MCP response objects to dict
                if hasattr(prev_output, 'model_dump'):
                    input_data = prev_output.model_dump()
                elif hasattr(prev_output, 'content') and prev_output.content:
                    # Extract from CallToolResult
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
        
        # If input is not a dict, can't filter
        if not isinstance(input_data, dict):
            return input_data
        
        # ✨ OPTION 3: Use explicit params if specified
        if self.explicit_params:
            filtered = {k: v for k, v in input_data.items() if k in self.explicit_params}
            print(f"  🎯 Filtering to explicit params: {self.explicit_params}")
            return filtered
        
        # ✨ OPTION 2: Auto-discover and filter
        if self.discovered_params is None and self.entity_type == "tool":
            self.discovered_params = await self._discover_tool_params()
        
        if self.discovered_params:
            filtered = {k: v for k, v in input_data.items() if k in self.discovered_params}
            print(f"  🔍 Auto-filtered to: {list(filtered.keys())}")
            return filtered
        
        # Fallback: pass everything
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
        return self.next_node if self.next_node else "complete"
