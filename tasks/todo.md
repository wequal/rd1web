# RMA Logs Performance Optimization Plan

## Overview
Optimize RMA logs page for faster loading by implementing lazy loading, cache pre-warming, and async operations.

## Current Issues
- Loading test_status.txt, gpu_model.txt, and golden number (DB query) for ALL directories upfront is slow
- No background caching - every page load requires fresh data
- Synchronous file I/O and database queries block the request

## Optimization Strategy

### Phase 1: Separate Basic and Detailed Data Loading
**Goal:** Load only essential data (name, base_sn, rma_number, mtime) for all directories, then load expensive details only for visible page items.

#### Task 1.1: Refactor get_rma_directories() for Lazy Loading
- [ ] Split `get_rma_directories()` into two functions:
  - `get_rma_directories_basic()` - Fast: name, base_sn, rma_number, mtime only
  - `load_directory_details()` - Slow: test_status, gpu_model, golden_number
- [ ] Update cache strategy:
  - Cache basic directory listing separately (30s timeout)
  - Cache individual directory details (1 min timeout)
- [ ] Remove test_status, gpu_model, golden_number from initial directory scan
- [ ] Keep basic directory structure fast and lightweight

#### Task 1.2: Create Detail Loading API Endpoint
- [ ] Add new view `rma_log_details_ajax()` in `rma_logs.py`
- [ ] Endpoint: `/rma/logs/details/` accepts list of directory names
- [ ] Returns JSON with test_status, gpu_model, golden_number for requested directories
- [ ] Uses caching to avoid redundant file reads/DB queries

#### Task 1.3: Update Main View to Load Only Visible Details
- [ ] Modify `rma_log()` to call `get_rma_directories_basic()` first
- [ ] Load details only for current page items (20 directories)
- [ ] Update AJAX endpoint `rma_log_ajax()` similarly
- [ ] Ensure pagination doesn't reload all data

### Phase 2: Setup Celery for Background Cache Pre-warming
**Goal:** Keep cache warm with periodic background tasks so users always get cached data.

#### Task 2.1: Install and Configure Celery
- [ ] Add to `requirements.txt`:
  - `celery>=5.3.0`
  - `redis>=5.0.0` (message broker)
- [ ] Create `rd1web/rd1web/celery.py` with Celery app configuration
- [ ] Configure Celery settings in `settings.py`:
  - Broker URL (Redis)
  - Result backend
  - Task serialization
  - Timezone settings
- [ ] Update `rd1web/rd1web/__init__.py` to import Celery app

#### Task 2.2: Create Celery Tasks Module
- [ ] Create `rd1web/pxe/tasks.py` for RMA-related Celery tasks
- [ ] Implement `prewarm_rma_directory_cache()` task:
  - Scan basic directory info every 30s
  - Store in cache with proper keys
  - Log cache refresh stats
- [ ] Implement `prewarm_rma_details_cache()` task:
  - Load details for frequently accessed directories
  - Run every 1 minute
  - Prioritize recently modified directories

#### Task 2.3: Setup Celery Beat for Periodic Tasks
- [ ] Configure Celery Beat schedule in `settings.py`
- [ ] Schedule `prewarm_rma_directory_cache` every 30 seconds
- [ ] Schedule `prewarm_rma_details_cache` every 1 minute
- [ ] Add task monitoring/logging

#### Task 2.4: Create Celery Management Scripts
- [ ] Create startup script for Celery worker
- [ ] Create startup script for Celery beat scheduler
- [ ] Update deployment documentation
- [ ] Add Celery health check endpoint

### Phase 3: Async File I/O and Database Queries
**Goal:** Make file reads and DB queries non-blocking for better concurrency.

#### Task 3.1: Create Async Helper Functions
- [ ] Create `async_get_test_status()` - async file read for test_status.txt
- [ ] Create `async_get_gpu_model()` - async file read for gpu_model.txt
- [ ] Create `async_get_golden_number()` - async DB query + file read
- [ ] Use `asyncio.to_thread()` for file I/O
- [ ] Use Django's `sync_to_async()` for ORM queries

#### Task 3.2: Create Async Batch Loading Function
- [ ] Implement `async_load_directory_details_batch()`:
  - Accept list of directory names
  - Use `asyncio.gather()` to load all details concurrently
  - Return dict mapping directory names to details
  - Handle errors gracefully (return partial results)
- [ ] Add proper error handling and timeouts
- [ ] Add concurrent operation limiting (max 10 concurrent)

#### Task 3.3: Integrate Async Functions
- [ ] Update `load_directory_details()` to use async batch loading
- [ ] Convert detail loading to async where possible
- [ ] Ensure compatibility with Celery tasks (run in sync mode)
- [ ] Add fallback to sync operations if async fails

#### Task 3.4: Update Views for Async Support
- [ ] Evaluate if views should be async (Django 5.x supports async views)
- [ ] If using sync views, wrap async calls with `asyncio.run()`
- [ ] Ensure thread-safe cache access
- [ ] Test concurrent request handling

### Phase 4: Frontend Updates
**Goal:** Update UI to handle lazy loading gracefully.

#### Task 4.1: Update JavaScript for Progressive Loading
- [ ] Show placeholders for test_status, gpu_model, golden_number initially
- [ ] Add loading indicators for detail columns
- [ ] Fetch details after initial page load completes
- [ ] Update table cells with fetched details
- [ ] Handle detail loading errors gracefully

#### Task 4.2: Optimize AJAX Requests
- [ ] Batch detail requests for all visible directories
- [ ] Add request debouncing for pagination
- [ ] Cache details in browser localStorage
- [ ] Add retry logic for failed detail loads

### Phase 5: Testing and Validation
**Goal:** Ensure optimization doesn't break functionality and improves performance.

#### Task 5.1: Performance Testing
- [ ] Measure initial page load time (before vs after)
- [ ] Test with large directory counts (100+, 500+, 1000+)
- [ ] Verify cache hit rates
- [ ] Monitor memory usage
- [ ] Check Celery task execution times

#### Task 5.2: Functional Testing
- [ ] Verify all columns display correctly
- [ ] Test pagination with lazy loading
- [ ] Test search functionality
- [ ] Test refresh button
- [ ] Test error scenarios (missing files, DB errors)
- [ ] Test concurrent user access

#### Task 5.3: Edge Case Testing
- [ ] Empty RMA directory
- [ ] Directories with missing files
- [ ] Invalid file formats
- [ ] Database connection failures
- [ ] Redis connection failures
- [ ] Celery worker offline

## Files to Create/Modify

### New Files
1. `/home/devin/rd1web-dev/rd1web/rd1web/celery.py` - Celery app configuration
2. `/home/devin/rd1web-dev/rd1web/pxe/tasks.py` - Celery task definitions
3. `/home/devin/rd1web-dev/celery_worker.sh` - Celery worker startup script
4. `/home/devin/rd1web-dev/celery_beat.sh` - Celery beat startup script

### Modified Files
1. `/home/devin/rd1web-dev/rd1web/requirements.txt` - Add Celery and Redis
2. `/home/devin/rd1web-dev/rd1web/rd1web/settings.py` - Celery configuration
3. `/home/devin/rd1web-dev/rd1web/rd1web/__init__.py` - Import Celery app
4. `/home/devin/rd1web-dev/rd1web/pxe/views/rma_logs.py` - Refactor for lazy loading + async
5. `/home/devin/rd1web-dev/rd1web/pxe/urls.py` - Add detail endpoint
6. `/home/devin/rd1web-dev/rd1web/templates/features/rma_logs.html` - Progressive loading UI

## Performance Targets
- Initial page load: < 500ms (from ~2-5s currently)
- Detail loading: < 200ms per page
- Cache hit rate: > 90% after warm-up
- Concurrent users: Support 10+ without degradation

## Rollback Plan
- Keep original functions as fallbacks
- Feature flag for lazy loading vs eager loading
- Monitor error rates and roll back if issues

## Implementation Order
1. Phase 1 (Lazy Loading) - Immediate impact, no dependencies
2. Phase 2 (Celery Setup) - Background caching infrastructure
3. Phase 3 (Async) - Further optimization with async I/O
4. Phase 4 (Frontend) - Enhanced UX
5. Phase 5 (Testing) - Validation and tuning

## Estimated Completion Time
- Phase 1: 2-3 hours
- Phase 2: 2-3 hours (includes Celery setup)
- Phase 3: 2-3 hours
- Phase 4: 1-2 hours
- Phase 5: 1-2 hours
**Total: 8-13 hours**

## Notes
- Use Redis for both Django cache and Celery broker (already installed: django_redis)
- Maintain backward compatibility during migration
- Add comprehensive logging for debugging
- Document all configuration changes
- Consider database connection pooling for async queries
