## Admin Sidebar Static Handling Fix

- [ ] Define a `SERVE_STATIC_VIA_DJANGO` flag in `rd1web/rd1web/settings.py` with a sensible default.
- [ ] Update `rd1web/rd1web/asgi.py` to use the new flag when deciding to wrap the app with `ASGIStaticFilesHandler`.
- [ ] Verify settings to ensure the new flag keeps static assets working on all worker ports.

