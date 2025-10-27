"""
YAML schema validation for Yenta spec files.
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field, ValidationError
from pathlib import Path

class TestCase(BaseModel):
    """Individual test case schema"""
    name: str
    tool: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    timeout_sec: int = Field(default=45, ge=1, le=300)
    use_mocks: Optional[bool] = None
    record_mocks: Optional[bool] = None
    mock: Optional[Dict[str, Any]] = None
    expected_schema: Optional[str] = None
    expected_keywords: List[str] = Field(default_factory=list)
    expected_metrics: Dict[str, Any] = Field(default_factory=dict)

class SpecSchema(BaseModel):
    """Main spec file schema"""
    agent_name: str = Field(..., description="Name of the agent being tested")
    mcp_server: Optional[str] = Field(None, description="Single MCP server path")
    mcp_servers: Optional[List[str]] = Field(None, description="Multiple MCP server paths")
    custom_tests: List[TestCase] = Field(..., description="List of test cases to run")
    use_mocks: bool = Field(default=False, description="Global mock usage setting")
    record_mocks: bool = Field(default=False, description="Global mock recording setting")
    
    def model_post_init(self, __context) -> None:
        """Validate that either mcp_server or mcp_servers is provided"""
        if not self.mcp_server and not self.mcp_servers:
            raise ValueError("Either 'mcp_server' or 'mcp_servers' must be specified")
        
        if self.mcp_server and self.mcp_servers:
            raise ValueError("Cannot specify both 'mcp_server' and 'mcp_servers'")

def validate_spec(spec_data: Dict[str, Any]) -> SpecSchema:
    """
    Validate spec data against schema.
    
    Args:
        spec_data: Raw spec data from YAML
        
    Returns:
        Validated SpecSchema instance
        
    Raises:
        ValidationError: If spec data is invalid
    """
    try:
        return SpecSchema(**spec_data)
    except ValidationError as e:
        # Provide more helpful error messages
        error_details = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            message = error["msg"]
            error_details.append(f"Field '{field}': {message}")
        
        raise ValidationError(
            f"Spec validation failed:\n" + "\n".join(error_details),
            e.model
        )

def validate_spec_file(spec_file: Path) -> SpecSchema:
    """
    Validate a spec file.
    
    Args:
        spec_file: Path to spec file
        
    Returns:
        Validated SpecSchema instance
        
    Raises:
        FileNotFoundError: If spec file doesn't exist
        ValidationError: If spec data is invalid
    """
    if not spec_file.exists():
        raise FileNotFoundError(f"Spec file not found: {spec_file}")
    
    import yaml
    with open(spec_file) as f:
        spec_data = yaml.safe_load(f)
    
    return validate_spec(spec_data)
