#!/bin/sh
# Legacy compatibility guard. There is exactly one executable Render entrypoint.
echo "legacy_render_entrypoint_rejected=true use=python_-m_scripts.integral_render_entrypoint" >&2
exit 64
