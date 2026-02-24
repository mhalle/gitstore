.PHONY: test-py test-ts test-rs test-deno test-interop test-all

test-py:
	uv run python -m pytest tests/ -v

test-ts:
	cd ts && npm test

test-rs:
	cd rs && cargo test

test-deno:
	cd ts && npm run build && npm run test:deno

test-interop:
	bash interop/run.sh

test-all: test-py test-ts test-rs test-deno test-interop
