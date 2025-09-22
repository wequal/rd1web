# Task: Fix RMA Log Page Timeout Issues

## Analysis
The RMA log page is experiencing timeout issues after some period of time. Investigation shows several root causes:

### 1. **Heavy Remote Operations (Primary Cause)**
In `get_rma_directories()` function (lines 200-208), for each RMA directory:
- **File counting**: `find {RMA_BASE_DIR}/{item} -type f | wc -l` 
- **Size calculation**: `find {RMA_BASE_DIR}/{item} -type f -exec stat -c "%s" {} + | awk "{sum += $1} END {print sum}"`

These operations can be extremely slow when:
- RMA directories contain thousands of files
- Network latency to RMA host (10.4.4.80) is high
- Multiple directories are processed sequentially

### 2. **No Connection Timeouts**
The Fabric connections in `remote_config.py` have no timeout settings:
```python
'rma': Connection(host="root@10.4.4.80", connect_kwargs={"password": "superrd1"})
```

### 3. **No Caching**
Every page load triggers full directory scanning, even for unchanged data.

### 4. **Sequential Processing**
All operations happen synchronously in the main request thread.

## Plan

### Phase 1: Quick Fixes (Immediate) - ✅ COMPLETED
- [x] Add connection timeouts to prevent indefinite hangs
- [x] Add timeout wrapper for heavy operations
- [x] Improve error handling and logging

### Phase 2: Performance Optimization (Short-term) - ✅ COMPLETED  
- [x] Implement caching for directory metadata
- [x] Make file counting and size calculation optional/lazy
- [x] Add timeout controls and fallback values

### Phase 3: Architecture Improvement (Medium-term) - ⏭️ FUTURE
- [ ] Implement background task processing for heavy operations
- [ ] Add progress indicators for long-running operations
- [ ] Consider pagination improvements

## Benefits
- Prevents page timeouts and improves user experience
- Reduces server load and network traffic
- Better error handling and recovery
- Scalable for large RMA directory structures