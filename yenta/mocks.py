import json
from pathlib import Path
from typing import Dict, Any, Optional


class MockRegistry:
    """Handle reading/writing mocks.json for record-replay testing"""
    
    def __init__(self, mock_file: str = "mocks.json"):
        self.mock_file = Path(mock_file)
        self.mocks: Dict[str, Any] = {}
        self._load()
    
    def _load(self):
        """Load existing mocks from disk"""
        if self.mock_file.exists():
            try:
                with open(self.mock_file, 'r') as f:
                    self.mocks = json.load(f)
            except json.JSONDecodeError:
                self.mocks = {}
    
    def _save(self):
        """Save mocks to disk"""
        with open(self.mock_file, 'w') as f:
            json.dump(self.mocks, f, indent=2, ensure_ascii=False)
    
    def get_mock_key(self, tool: str, args: Dict[str, Any]) -> str:
        """Generate unique key for tool + args combination"""
        return json.dumps({"tool": tool, "args": args}, sort_keys=True)
    
    def get(self, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Retrieve mock response if it exists"""
        key = self.get_mock_key(tool, args)
        return self.mocks.get(key)
    
    def record(self, tool: str, args: Dict[str, Any], response: Dict[str, Any]):
        """Record a response for future replay"""
        key = self.get_mock_key(tool, args)
        self.mocks[key] = response
        self._save()
    
    def has_mock(self, tool: str, args: Dict[str, Any]) -> bool:
        """Check if mock exists for this tool + args"""
        key = self.get_mock_key(tool, args)
        return key in self.mocks
