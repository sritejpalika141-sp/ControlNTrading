"""Asset-class specialization configs (multi-asset-expansion Phase 2+).

Each module here defines and registers one specialized AssetClass entry (e.g. CRUDE_OIL_OPTIONS)
into engine.asset_classes.registry via register(). Importing the module performs the registration
as a side effect — nothing here is auto-imported by the app until the corresponding asset-class
order path is wired, so registering has zero effect on live NIFTY behavior until then.
"""
