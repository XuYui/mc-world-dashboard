#!/usr/bin/env bash
# Build the plugins against the jars of an installed Paper server (no Gradle needed).
#   SERVER_DIR=/opt/minecraft ./build.sh                 -> every plugin
#   SERVER_DIR=/opt/minecraft ./build.sh deathmarkers    -> just one
# Jars land in plugins/build/. Needs JDK 25 (javac, jar) and squaremap in the server's plugins/.
set -euo pipefail
cd "$(dirname "$0")"
SERVER_DIR=${SERVER_DIR:-/opt/minecraft}

squaremap=$(ls "$SERVER_DIR"/plugins/squaremap-*.jar | head -n1)
cp=$(find "$SERVER_DIR/libraries" -name '*.jar' | tr '
' ':')$squaremap
mkdir -p build

names=("$@")
if ((${#names[@]} == 0)); then
    for d in */src; do names+=("${d%/src}"); done
fi
for name in "${names[@]}"; do
    meta="$name/src/main/resources/plugin.yml"
    jarname=$(sed -n 's/^name: *//p' "$meta")
    version=$(sed -n 's/^version: *//p' "$meta")
    classes="build/$name-classes"
    rm -rf "$classes"
    mkdir -p "$classes"
    javac --release 25 -encoding UTF-8 -Xlint:deprecation -cp "$cp" -d "$classes" $(find "$name/src/main/java" -name '*.java')
    cp "$name"/src/main/resources/*.yml "$classes/"
    jar --create --file "build/$jarname-$version.jar" -C "$classes" .
    rm -rf "$classes"
    echo "built build/$jarname-$version.jar"
done
