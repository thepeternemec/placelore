.PHONY: test lint demo clean

test:
	python3 -m unittest discover -s tests -t . -v

lint:
	ruff check .
	ruff format --check .

demo:
	rm -f demo.sqlite demo.jsonl demo-places.json demo-photos.json
	python3 -m wikicrawl collect --category "Category:Colosseum" --depth 1 --limit 25 \
		--db demo.sqlite --user-agent "wikicrawl-demo/0.1 (https://github.com/; demo@example.org)"
	python3 -m wikicrawl photos --db demo.sqlite \
		--user-agent "wikicrawl-demo/0.1 (https://github.com/; demo@example.org)"
	python3 -m wikicrawl normalize --db demo.sqlite
	python3 -m wikicrawl stats --db demo.sqlite
	python3 -m wikicrawl export --db demo.sqlite --format google --out demo-places.json
	python3 -m wikicrawl export --db demo.sqlite --format photo-index --out demo-photos.json

clean:
	rm -rf __pycache__ wikicrawl/__pycache__ tests/__pycache__ .ruff_cache build dist *.egg-info
	rm -f demo.sqlite demo.jsonl demo-places.json demo-photos.json
