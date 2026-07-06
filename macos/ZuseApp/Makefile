# Zuse.app — build without Xcode (Swift CLT only).
.PHONY: app build run clean

app: ## default: release build + .app bundle in dist/
	./build-app.sh

build:
	swift build

run:
	swift run

clean:
	rm -rf .build dist
