#!/bin/zsh
set -e
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"
exec .venv/bin/python -m clipmac.launch
