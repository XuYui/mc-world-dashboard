#!/usr/bin/env bash
# Build DeathMarkers against the jars of an installed Paper server (no Gradle needed).
#   SERVER_DIR=/opt/minecraft ./build.sh      -> build/DeathMarkers-<version>.jar
# Needs JDK 25 (javac, jar) and a server with squaremap in plugins/.
set -euo pipefail
cd "$(dirname "$0")"
SERVER_DIR=${SERVER_DIR:-/opt/minecraft}

squaremap=$(ls "$SERVER_DIR"/plugins/squaremap-*.jar | head -n1)
cp=$(find "$SERVER_DIR/libraries" -name '*.jar' | tr '\n' ':')$squaremap
version=$(sed -n 's/^version: *//p' src/main/resources/plugin.yml)

rm -rf build/classes
mkdir -p build/classes
javac --release 25 -encoding UTF-8 -Xlint:deprecation -cp "$cp" -d build/classes $(find src/main/java -name '*.java')
cp src/main/resources/*.yml build/classes/
jar --create --file "build/DeathMarkers-$version.jar" -C build/classes .
echo "built build/DeathMarkers-$version.jar"
