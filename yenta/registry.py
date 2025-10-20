import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime

from .models import Mock, TestRun, Capabilities

class JsonRegistry:
    """JSON-based registry (future SQLite-compatible)"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.mocks_dir = self.data_dir / "mocks"
        self.capabilities_dir = self.data_dir / "capabilities"
        
        # Create structure
        for dir in [self.runs_dir, self.mocks_dir / "tools", 
                    self.mocks_dir / "resources", self.mocks_dir / "prompts",
                    self.capabilities_dir]:
            dir.mkdir(parents=True, exist_ok=True)
        
        # Load index for fast lookups
        self.index_file = self.mocks_dir / "index.json"
        self.index = self._load_index()
        
        # Handle legacy migration
        self._migrate_legacy_if_needed()
    
    # ============================================================
    # MOCK OPERATIONS (tools/resources/prompts)
    # ============================================================
    
    def save_mock(self, category: str, tool: str, args: Dict[str, Any], 
                  response: Dict[str, Any]):
        """Save mock to category directory"""
        mock = Mock(
            category=category,
            name=tool,
            arguments=args,
            response=response
        )
        
        # Generate unique filename based on tool + args
        args_hash = self._hash_args(args)
        filename = f"{tool}_{args_hash}.json"
        
        file_path = self.mocks_dir / category / filename
        file_path.write_text(json.dumps(mock.dict(), indent=2, default=str))
        
        # Update index
        key = self._get_mock_key(category, tool, args)
        self.index[key] = str(file_path.relative_to(self.data_dir))
        self._save_index()
        
        print(f"📁 Saved to {file_path.relative_to(Path.cwd())}")
    
    def load_mock(self, category: str, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Load mock from category directory"""
        key = self._get_mock_key(category, tool, args)
        
        if key not in self.index:
            return None
        
        file_path = self.data_dir / self.index[key]
        if not file_path.exists():
            return None
        
        mock_data = json.loads(file_path.read_text())
        return mock_data.get("response")
    
    def has_mock(self, category: str, tool: str, args: Dict[str, Any]) -> bool:
        """Check if mock exists"""
        key = self._get_mock_key(category, tool, args)
        return key in self.index
    
    # ============================================================
    # RUN OPERATIONS (test history)
    # ============================================================
    
    def save_run(self, run: TestRun):
        """Save test run"""
        timestamp = run.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{run.spec_name.replace('.yaml', '')}.json"
        
        file_path = self.runs_dir / filename
        file_path.write_text(json.dumps(run.dict(), indent=2, default=str))
        
        # Update 'latest' symlink
        latest = self.runs_dir / "latest.json"
        if latest.exists():
            latest.unlink()
        latest.symlink_to(filename)
        
        print(f"💾 Run saved to {file_path.relative_to(Path.cwd())}")
    
    def load_latest_run(self) -> Optional[TestRun]:
        """Load most recent run"""
        latest = self.runs_dir / "latest.json"
        if not latest.exists():
            return None
        
        data = json.loads(latest.read_text())
        return TestRun(**data)
    
    def list_runs(self, limit: int = 10) -> List[TestRun]:
        """List recent runs"""
        run_files = sorted(self.runs_dir.glob("*.json"), reverse=True)
        runs = []
        
        for file in run_files[:limit]:
            if file.name == "latest.json":
                continue
            data = json.loads(file.read_text())
            runs.append(TestRun(**data))
        
        return runs
    
    # ============================================================
    # CAPABILITIES OPERATIONS
    # ============================================================
    
    def save_capabilities(self, capabilities: Capabilities):
        """Save server capabilities"""
        file_path = self.capabilities_dir / "manifest.json"
        file_path.write_text(json.dumps(capabilities.dict(), indent=2, default=str))
        print(f"📋 Capabilities saved to {file_path.relative_to(Path.cwd())}")
    
    def load_capabilities(self) -> Optional[Capabilities]:
        """Load server capabilities"""
        file_path = self.capabilities_dir / "manifest.json"
        if not file_path.exists():
            return None
        
        data = json.loads(file_path.read_text())
        return Capabilities(**data)
    
    # ============================================================
    # UTILITIES
    # ============================================================
    
    def _get_mock_key(self, category: str, tool: str, args: Dict[str, Any]) -> str:
        """Generate unique key for mock lookup"""
        args_json = json.dumps(args, sort_keys=True)
        return f"{category}:{tool}:{args_json}"
    
    def _hash_args(self, args: Dict[str, Any]) -> str:
        """Generate short hash of arguments"""
        args_json = json.dumps(args, sort_keys=True)
        return hashlib.md5(args_json.encode()).hexdigest()[:8]
    
    def _load_index(self) -> Dict[str, str]:
        """Load mock index for fast lookups"""
        if not self.index_file.exists():
            return {}
        return json.loads(self.index_file.read_text())
    
    def _save_index(self):
        """Save mock index"""
        self.index_file.write_text(json.dumps(self.index, indent=2))
    
    def _migrate_legacy_if_needed(self):
        """Migrate from old mocks.json to new structure"""
        legacy_file = Path("mocks.json")
        if not legacy_file.exists():
            return
        
        print("🔄 Migrating from legacy mocks.json...")
        
        legacy_data = json.loads(legacy_file.read_text())
        
        for key, response in legacy_data.items():
            try:
                data = json.loads(key)
                tool = data.get("tool", "unknown")
                args = data.get("args", {})
                
                # Assume all legacy mocks are tools
                self.save_mock("tools", tool, args, response)
            except:
                print(f"⚠️  Skipped invalid legacy entry: {key[:50]}...")
        
        # Rename old file
        legacy_file.rename("mocks.json.old")
        print(f"✅ Migration complete! Old file renamed to mocks.json.old")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        stats = {
            "total_mocks": len(self.index),
            "tools": len(list((self.mocks_dir / "tools").glob("*.json"))),
            "resources": len(list((self.mocks_dir / "resources").glob("*.json"))),
            "prompts": len(list((self.mocks_dir / "prompts").glob("*.json"))),
            "total_runs": len(list(self.runs_dir.glob("*.json"))) - 1,  # Exclude latest.json
            "data_dir": str(self.data_dir)
        }
        return stats
