#!/usr/bin/env bash
# Build the WorldDashboard plugin against the jars of an installed Paper server (no Gradle needed).
#   SERVER_DIR=/opt/minecraft ./build.sh      -> build/WorldDashboard-<version>.jar
# Needs JDK 25 (javac, jar). The plugin only uses the Paper API.
set -euo pipefail
cd "$(dirname "$0")"
SERVER_DIR=${SERVER_DIR:-/opt/minecraft}
cp=$(find "$SERVER_DIR/libraries" -name '*.jar' | tr '\n' ':')
version=$(sed -n 's/^version: *//p' src/main/resources/plugin.yml)
rm -rf build/classes
mkdir -p build/classes
javac --release 25 -encoding UTF-8 -Xlint:deprecation -cp "$cp" -d build/classes $(find src/main/java -name '*.java')
cp src/main/resources/*.yml build/classes/
jar --create --file "build/WorldDashboard-$version.jar" -C build/classes .
rm -rf build/classes
echo "built build/WorldDashboard-$version.jar"
