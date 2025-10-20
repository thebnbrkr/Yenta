# yenta/registry.py
import json
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List

from .models import Mock, TestRun, Capabilities


class JsonRegistry:
    """JSON-based registry for mocks, runs, and capabilities"""
    
    def __init__(self, data_dir: str = "data"):
        self.data_dir = Path(data_dir)
        self.runs_dir = self.data_dir / "runs"
        self.mocks_dir = self.data_dir / "mocks"
        self.capabilities_dir = self.data_dir / "capabilities"
        
        for dir_path in [self.runs_dir, 
                         self.mocks_dir / "tools", 
                         self.mocks_dir / "resources", 
                         self.mocks_dir / "prompts",
                         self.capabilities_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        self.index_file = self.mocks_dir / "index.json"
        self.index = self._load_index()
        
        self._migrate_legacy_if_needed()
    
    # ============================================================
    # MOCK OPERATIONS
    # ============================================================
    
    def record(self, tool: str, args: Dict[str, Any], response: Dict[str, Any]):
        """Record a mock (backward compatible with old API)"""
        self.save_mock("tools", tool, args, response)
    
    def get(self, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get a mock (backward compatible with old API)"""
        return self.load_mock("tools", tool, args)
    
    def has_mock(self, tool: str, args: Dict[str, Any]) -> bool:
        """Check if mock exists (backward compatible with old API)"""
        return self.has_mock_in_category("tools", tool, args)
    
    def save_mock(self, category: str, tool: str, args: Dict[str, Any], 
                  response: Dict[str, Any]):
        """Save mock to organized directory"""
        mock = Mock(
            category=category,
            name=tool,
            arguments=args,
            response=response
        )
        
        args_hash = self._hash_args(args)
        filename = f"{tool}_{args_hash}.json"
        
        file_path = self.mocks_dir / category / filename
        # ✅ FIXED: Use model_dump() instead of dict()
        file_path.write_text(json.dumps(mock.model_dump(), indent=2, default=str, ensure_ascii=False))
        
        key = self._get_mock_key(category, tool, args)
        self.index[key] = str(file_path.relative_to(self.data_dir))
        self._save_index()
        
        # ✅ FIXED: Simple print without relative_to issues
        print(f"📁 Saved to {file_path}")
    
    def load_mock(self, category: str, tool: str, args: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Load mock from organized directory"""
        key = self._get_mock_key(category, tool, args)
        
        if key not in self.index:
            return None
        
        file_path = self.data_dir / self.index[key]
        if not file_path.exists():
            return None
        
        try:
            mock_data = json.loads(file_path.read_text())
            return mock_data.get("response")
        except:
            return None
    
    def has_mock_in_category(self, category: str, tool: str, args: Dict[str, Any]) -> bool:
        """Check if mock exists"""
        key = self._get_mock_key(category, tool, args)
        return key in self.index
    
    def list_mocks(self, category: Optional[str] = None) -> List[Mock]:
        """List all mocks, optionally filtered by category"""
        mocks = []
        
        categories = [category] if category else ["tools", "resources", "prompts"]
        
        for cat in categories:
            cat_dir = self.mocks_dir / cat
            if not cat_dir.exists():
                continue
            for mock_file in cat_dir.glob("*.json"):
                try:
                    data = json.loads(mock_file.read_text())
                    mocks.append(Mock(**data))
                except:
                    pass
        
        return mocks
    
    def clear_mocks(self, category: Optional[str] = None):
        """Clear mocks, optionally filtered by category"""
        if category:
            cat_dir = self.mocks_dir / category
            if cat_dir.exists():
                for mock_file in cat_dir.glob("*.json"):
                    mock_file.unlink()
        else:
            for cat in ["tools", "resources", "prompts"]:
                cat_dir = self.mocks_dir / cat
                if cat_dir.exists():
                    for mock_file in cat_dir.glob("*.json"):
                        mock_file.unlink()
        
        self.index = {}
        self._save_index()
    
    # ============================================================
    # RUN OPERATIONS
    # ============================================================
    
    def save_run(self, run: TestRun):
        """Save test run history"""
        timestamp = run.timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{run.spec_name.replace('.yaml', '').replace('/', '_')}.json"
        
        file_path = self.runs_dir / filename
        # ✅ FIXED: Use model_dump() instead of dict()
        file_path.write_text(json.dumps(run.model_dump(), indent=2, default=str, ensure_ascii=False))
        
        latest = self.runs_dir / "latest.json"
        try:
            if latest.exists():
                latest.unlink()
            latest.symlink_to(filename)
        except (OSError, NotImplementedError):
            latest.write_text(file_path.read_text())
        
        # ✅ FIXED: Simple print without relative_to issues
        print(f"💾 Run saved to {file_path}")
    
    def load_latest_run(self) -> Optional[TestRun]:
        """Load most recent run"""
        latest = self.runs_dir / "latest.json"
        if not latest.exists():
            return None
        
        try:
            data = json.loads(latest.read_text())
            return TestRun(**data)
        except:
            return None
    
    def list_runs(self, limit: int = 10) -> List[TestRun]:
        """List recent runs"""
        run_files = sorted(self.runs_dir.glob("*.json"), reverse=True)
        runs = []
        
        for file in run_files:
            if file.name == "latest.json":
                continue
            if len(runs) >= limit:
                break
            try:
                data = json.loads(file.read_text())
                runs.append(TestRun(**data))
            except:
                pass
        
        return runs
    
    # ============================================================
    # CAPABILITIES OPERATIONS
    # ============================================================
    
    def save_capabilities(self, capabilities: Capabilities):
        """Save server capabilities manifest"""
        file_path = self.capabilities_dir / "manifest.json"
        # ✅ FIXED: Use model_dump() instead of dict()
        file_path.write_text(json.dumps(capabilities.model_dump(), indent=2, default=str, ensure_ascii=False))
        print(f"📋 Capabilities saved to {file_path}")
    
    def load_capabilities(self) -> Optional[Capabilities]:
        """Load server capabilities"""
        file_path = self.capabilities_dir / "manifest.json"
        if not file_path.exists():
            return None
        
        try:
            data = json.loads(file_path.read_text())
            return Capabilities(**data)
        except:
            return None
    
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
        try:
            return json.loads(self.index_file.read_text())
        except:
            return {}
    
    def _save_index(self):
        """Save mock index"""
        self.index_file.write_text(json.dumps(self.index, indent=2, ensure_ascii=False))
    
    def _migrate_legacy_if_needed(self):
        """Migrate from old mocks.json if it exists"""
        legacy_file = Path("mocks.json")
        if not legacy_file.exists():
            return
        
        print("🔄 Migrating from legacy mocks.json...")
        
        try:
            legacy_data = json.loads(legacy_file.read_text())
            
            migrated = 0
            for key, response in legacy_data.items():
                try:
                    data = json.loads(key)
                    tool = data.get("tool", "unknown")
                    args = data.get("args", {})
                    
                    self.save_mock("tools", tool, args, response)
                    migrated += 1
                except Exception as e:
                    print(f"⚠️  Skipped invalid entry: {str(e)[:50]}...")
            
            legacy_file.rename("mocks.json.old")
            print(f"✅ Migrated {migrated} mocks! Old file renamed to mocks.json.old")
        except Exception as e:
            print(f"❌ Migration failed: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get registry statistics"""
        stats = {
            "total_mocks": len(self.index),
            "tools": len(list((self.mocks_dir / "tools").glob("*.json"))) if (self.mocks_dir / "tools").exists() else 0,
            "resources": len(list((self.mocks_dir / "resources").glob("*.json"))) if (self.mocks_dir / "resources").exists() else 0,
            "prompts": len(list((self.mocks_dir / "prompts").glob("*.json"))) if (self.mocks_dir / "prompts").exists() else 0,
            "total_runs": len([f for f in self.runs_dir.glob("*.json") if f.name != "latest.json"]) if self.runs_dir.exists() else 0,
            "data_dir": str(self.data_dir.absolute())
        }
        return stats


# Backward compatibility alias
MockRegistry = JsonRegistry
