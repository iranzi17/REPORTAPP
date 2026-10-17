"""One established Windows notification identity for REPORTAPP field monitoring.

Clean-activity digests previously appeared under "REPORTAPP Surveyor Activity"
while quality-gap toasts used another Windows identity. Since Windows banner
permissions are per app identity, use the already-working identity for BOTH.
This does not override Windows Do not disturb or prove a banner was viewed.
"""

DESKTOP_APP_ID = "REPORTAPP Surveyor Activity"
