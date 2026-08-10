PY ?= python3
PLANS := examples/plans

.PHONY: help fixtures test lint demo clean

help:
	@echo "make fixtures  generate the synthetic plan PDFs"
	@echo "make test      run the test suite"
	@echo "make demo      extract every fixture into out/ and refresh docs/media"
	@echo "make lint      ruff, if installed"
	@echo "make clean     remove generated artefacts"

fixtures:
	$(PY) examples/make_fixtures.py $(PLANS)

test: fixtures
	PYTHONPATH=. $(PY) -m unittest discover -s tests

demo: fixtures
	$(PY) -m roomgraph.cli extract $(PLANS)/apartment.pdf -o out -f json,geojson,ifc,svg,gif
	$(PY) -m roomgraph.cli extract $(PLANS)/studio_lshape.pdf -o out -f json,svg
	$(PY) -c "from roomgraph.model import extract; from roomgraph.export import svg, anim; \
	m = extract('$(PLANS)/apartment.pdf'); svg.write(m, 'docs/media/apartment.svg'); anim.write(m, 'docs/media/apartment.gif'); \
	m2 = extract('$(PLANS)/studio_lshape.pdf'); svg.write(m2, 'docs/media/studio.svg'); \
	m3 = extract('$(PLANS)/hatched_plan.pdf'); anim.write(m3, 'docs/media/hatched.gif')"

lint:
	@command -v ruff >/dev/null 2>&1 && ruff check roomgraph examples tests || echo "ruff not installed, skipping"

clean:
	rm -rf out $(PLANS) .ruff_cache
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
