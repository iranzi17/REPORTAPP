# Data-quality v2: phase/type consistency

This first change introduces a **pure, read-only** phase/type validator and focused unit tests.

**Important:** Example asset-type codes in the tests are fictional. No live codes have
been configured or activated. The current watcher is unchanged until real ASSETGROUP /
ASSETTYPE expectations have been verified against the production subtype domains.

Rules:
- Only a verified mapping of `ASSETGROUP:ASSETTYPE` to expected phase count enables checking.
- Stored coded-domain phase values are decoded before comparison.
- Missing or unrecognized phases are left to the existing domain validator.
- Unknown asset types are not treated as conflicts.
- No data is edited in the utility-network service.

Next: verify actual codes and incorporate the check into `quality_watcher.py`,
then extend the same approach to distribution transformers, excluding Branch and
power-plant devices.
