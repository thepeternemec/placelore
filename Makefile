.PHONY: test lint demo clean verify-google bulk-demo bundle

test:
	python3 -m unittest discover -s tests -t . -v

bulk-demo:
	rm -f bulk-demo.sqlite bulk-demo.json
	python3 -m placelore bulk fetch --db bulk-demo.sqlite --country Q215 \
		--limit 200 --user-agent "placelore-demo/0.3 (demo@example.org)"
	python3 -m placelore bulk enrich --db bulk-demo.sqlite --limit 100 \
		--user-agent "placelore-demo/0.3 (demo@example.org)"
	python3 -m placelore bulk status --db bulk-demo.sqlite
	python3 -m placelore export --db bulk-demo.sqlite --format google --out bulk-demo.json

bundle:
	rm -rf dist/demo && python3 -m placelore publish --db data/world-slovenia.sqlite \
		--out dist/demo --name placelore-demo

verify-google:
	python3 -m placelore verify --file tests/fixtures/google-payload.json \
		--photo-index tests/fixtures/google-photo-index.json

lint:
	ruff check .
	ruff format --check .

demo:
	rm -f demo.sqlite demo.jsonl demo-places.json demo-photos.json
	python3 -m placelore collect --category "Category:Colosseum" --depth 1 --limit 25 \
		--db demo.sqlite --user-agent "placelore-demo/0.1 (https://github.com/; demo@example.org)"
	python3 -m placelore photos --db demo.sqlite \
		--user-agent "placelore-demo/0.1 (https://github.com/; demo@example.org)"
	python3 -m placelore normalize --db demo.sqlite
	python3 -m placelore stats --db demo.sqlite
	python3 -m placelore export --db demo.sqlite --format google --out demo-places.json
	python3 -m placelore export --db demo.sqlite --format photo-index --out demo-photos.json

clean:
	rm -rf __pycache__ placelore/__pycache__ tests/__pycache__ .ruff_cache build dist *.egg-info
	rm -f demo.sqlite demo.jsonl demo-places.json demo-photos.json
