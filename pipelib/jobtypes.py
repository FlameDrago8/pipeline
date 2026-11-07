"""Job types: conventions given to Claude, scaffold files, and done-when checks.

`quick` checks run after every component prompt (lenient about files a later
component will create). `final` checks run once all components are done and
decide whether the job is built.
"""
from __future__ import annotations

import re

V = "{validators}"

GRADLE_IGNORE = ".gradle/\nbuild/\nrun/\n*.class\n.idea/\n"

PAPER = {
    "settings.gradle.kts": 'rootProject.name = "{slug}"\n',
    "build.gradle.kts": """plugins {{
    java
}}

group = "{package}"
version = "1.0.0"

repositories {{
    mavenCentral()
    maven("https://repo.papermc.io/repository/maven-public/")
}}

dependencies {{
    compileOnly("io.papermc.paper:paper-api:1.21.1-R0.1-SNAPSHOT")
}}

java {{
    toolchain.languageVersion.set(JavaLanguageVersion.of(21))
}}

tasks.processResources {{
    filesMatching("plugin.yml") {{ expand("version" to project.version) }}
}}
""",
    "src/main/resources/plugin.yml": """name: {Name}
version: '${{version}}'
main: {package}.{Name}Plugin
api-version: '1.21'
""",
    "src/main/java/{package_path}/{Name}Plugin.java": """package {package};

import org.bukkit.plugin.java.JavaPlugin;

public final class {Name}Plugin extends JavaPlugin {{
    @Override
    public void onEnable() {{
        saveDefaultConfig();
    }}
}}
""",
    "src/main/resources/config.yml": "# {Name} configuration\n",
    ".gitignore": GRADLE_IGNORE,
}

FABRIC = {
    "settings.gradle": """pluginManagement {{
    repositories {{
        maven {{ url = 'https://maven.fabricmc.net/' }}
        gradlePluginPortal()
    }}
}}
rootProject.name = '{slug}'
""",
    "gradle.properties": """org.gradle.jvmargs=-Xmx2G
minecraft_version=1.21.1
yarn_mappings=1.21.1+build.3
loader_version=0.16.5
fabric_version=0.105.0+1.21.1
mod_version=1.0.0
""",
    "build.gradle": """plugins {{
    id 'fabric-loom' version '1.7-SNAPSHOT'
}}

version = project.mod_version
group = '{package}'

dependencies {{
    minecraft "com.mojang:minecraft:${{project.minecraft_version}}"
    mappings "net.fabricmc:yarn:${{project.yarn_mappings}}:v2"
    modImplementation "net.fabricmc:fabric-loader:${{project.loader_version}}"
    modImplementation "net.fabricmc.fabric-api:fabric-api:${{project.fabric_version}}"
}}

processResources {{
    inputs.property 'version', project.version
    filesMatching('fabric.mod.json') {{ expand 'version': project.version }}
}}

java {{
    toolchain.languageVersion = JavaLanguageVersion.of(21)
}}
""",
    "src/main/resources/fabric.mod.json": """{{
  "schemaVersion": 1,
  "id": "{modid}",
  "version": "${{version}}",
  "name": "{Title}",
  "environment": "*",
  "entrypoints": {{ "main": ["{package}.{Name}Mod"] }},
  "depends": {{ "fabricloader": ">=0.16.0", "minecraft": "~1.21.1", "fabric-api": "*" }}
}}
""",
    "src/main/java/{package_path}/{Name}Mod.java": """package {package};

import net.fabricmc.api.ModInitializer;

public class {Name}Mod implements ModInitializer {{
    public static final String MOD_ID = "{modid}";

    @Override
    public void onInitialize() {{
    }}
}}
""",
    ".gitignore": GRADLE_IGNORE,
}

FORGE = {
    "settings.gradle": """pluginManagement {{
    repositories {{
        gradlePluginPortal()
        maven {{ url = 'https://maven.minecraftforge.net/' }}
    }}
}}
rootProject.name = '{slug}'
""",
    "build.gradle": """plugins {{
    id 'net.minecraftforge.gradle' version '[6.0,6.2)'
}}

version = '1.0.0'
group = '{package}'

java.toolchain.languageVersion = JavaLanguageVersion.of(17)

minecraft {{
    mappings channel: 'official', version: '1.20.1'
}}

dependencies {{
    minecraft 'net.minecraftforge:forge:1.20.1-47.3.0'
}}
""",
    "src/main/resources/META-INF/mods.toml": """modLoader="javafml"
loaderVersion="[47,)"
license="All rights reserved"

[[mods]]
modId="{modid}"
version="1.0.0"
displayName="{Title}"
""",
    "src/main/resources/pack.mcmeta": '{{"pack": {{"description": "{Title}", "pack_format": 15}}}}\n',
    "src/main/java/{package_path}/{Name}Mod.java": """package {package};

import net.minecraftforge.fml.common.Mod;

@Mod({Name}Mod.MOD_ID)
public class {Name}Mod {{
    public static final String MOD_ID = "{modid}";
}}
""",
    ".gitignore": GRADLE_IGNORE,
}

DISCORD = {
    "package.json": """{{
  "name": "{slug}",
  "version": "1.0.0",
  "private": true,
  "type": "commonjs",
  "main": "src/index.js",
  "scripts": {{
    "start": "node src/index.js",
    "deploy-commands": "node src/deploy-commands.js",
    "test": "node --test test/"
  }},
  "dependencies": {{
    "discord.js": "^14.16.3",
    "dotenv": "^16.4.5"
  }}
}}
""",
    ".env.example": "DISCORD_TOKEN=\nCLIENT_ID=\nGUILD_ID=\n",
    ".gitignore": "node_modules/\n.env\n",
    "test/smoke.test.js": """const test = require('node:test');
const assert = require('node:assert');

test('package.json loads', () => {{
  assert.ok(require('../package.json').name);
}});
""",
}

CHROME = {
    "manifest.json": """{{
  "manifest_version": 3,
  "name": "{Title}",
  "version": "1.0.0",
  "description": "{Title}"
}}
""",
    ".gitignore": "node_modules/\n*.zip\n",
}

FIVEM = {
    "fxmanifest.lua": """fx_version 'cerulean'
game 'gta5'
lua54 'yes'

name '{slug}'
version '1.0.0'
""",
    "config.lua": "Config = {{}}\n",
}

HYTALE = {
    "settings.gradle.kts": 'rootProject.name = "{slug}"\n',
    "build.gradle.kts": """plugins {{
    java
}}

group = "{package}"
version = "1.0.0"

repositories {{
    mavenCentral()
}}

dependencies {{
    // Put the Hytale server API jar the client uses in libs/.
    compileOnly(fileTree("libs") {{ include("*.jar") }})
}}

java {{
    toolchain.languageVersion.set(JavaLanguageVersion.of(21))
}}
""",
    "libs/README.md": "Drop the Hytale server API jar here (compileOnly).\n",
    ".gitignore": GRADLE_IGNORE,
}

OTHER = {
    "requirements.txt": "",
    "README.md": "# {Title}\n",
    ".gitignore": "__pycache__/\n.venv/\n.env\nnode_modules/\n",
    "tests/__init__.py": "",
}

JAVA_RULE = ("Java: every component must compile using only files that exist after it is "
             "built (earlier components plus its own). Never reference classes a later "
             "component will create; later components register themselves by editing the "
             "main class or registration files instead.")

TYPES: dict[str, dict] = {
    "paper": {
        "label": "Paper (Minecraft 1.21) server plugin",
        "notes": "Java 21, Gradle Kotlin DSL, paper-api 1.21.1. Register commands in plugin.yml "
                 "and in onEnable. Config defaults in config.yml. Use Adventure components for "
                 "messages. Never block the main thread with I/O. " + JAVA_RULE,
        "scaffold": PAPER,
        "quick": [f"{V} plugin_yml", f"{V} gradle compileJava"],
        "final": [f"{V} plugin_yml", f"{V} secrets", f"{V} gradle build"],
    },
    "fabric": {
        "label": "Fabric (Minecraft 1.21.1) mod",
        "notes": "Java 21, fabric-loom, Yarn mappings, Fabric API. Change versions in "
                 "gradle.properties only if the spec names another Minecraft version. " + JAVA_RULE,
        "scaffold": FABRIC,
        "quick": [f"{V} fabric_json --lenient", f"{V} gradle compileJava"],
        "final": [f"{V} fabric_json", f"{V} secrets", f"{V} gradle build"],
    },
    "forge": {
        "label": "Forge (Minecraft 1.20.1) mod",
        "notes": "Java 17, ForgeGradle 6, official mappings, Forge 47.x. Use DeferredRegister "
                 "for registries. " + JAVA_RULE,
        "scaffold": FORGE,
        "quick": [f"{V} mods_toml --lenient", f"{V} gradle compileJava"],
        "final": [f"{V} mods_toml", f"{V} secrets", f"{V} gradle build"],
    },
    "discord_bot": {
        "label": "Discord bot (Node.js, discord.js v14)",
        "notes": "CommonJS, discord.js v14, slash commands in src/commands/<name>.js exporting "
                 "{ data, execute }, loaded by src/index.js; src/deploy-commands.js registers them. "
                 "Token and ids come from .env via dotenv. A real bot account only: never a "
                 "self-bot or user token. Put pure logic in separate modules and test it with "
                 "node:test in test/*.test.js (tests must not log in to Discord).",
        "scaffold": DISCORD,
        "quick": [f"{V} npm_install", f"{V} jsyntax"],
        "final": [f"{V} npm_install", f"{V} jsyntax", f"{V} npm_test", f"{V} secrets"],
    },
    "chrome_extension": {
        "label": "Chrome extension (Manifest V3)",
        "notes": "Plain JavaScript, no build step unless the spec needs one. Manifest V3: "
                 "background.service_worker, 'action', host_permissions for sites. Ask for the "
                 "fewest permissions. No remote code. Keep logic that can be tested in plain "
                 "modules; optional node:test tests in test/ with a package.json test script.",
        "scaffold": CHROME,
        "quick": [f"{V} manifest --lenient", f"{V} jsyntax"],
        "final": [f"{V} manifest", f"{V} jsyntax", f"{V} npm_test", f"{V} secrets"],
    },
    "fivem": {
        "label": "FiveM resource (Lua)",
        "notes": "Lua 5.4 (lua54 'yes'), fxmanifest.lua lists every script. client/, server/, "
                 "shared/ folders. Validate everything server-side; never trust client events. "
                 "Framework (ESX/QBCore/standalone) as the spec says, standalone by default.",
        "scaffold": FIVEM,
        "quick": [f"{V} fxmanifest --lenient"],
        "final": [f"{V} fxmanifest", f"{V} secrets"],
    },
    "hytale": {
        "label": "Hytale server mod (Java, experimental)",
        "notes": "Java 21 Gradle project; the Hytale API jar goes in libs/ (compileOnly). If the "
                 "API jar is absent, keep the game-facing layer thin and put logic in plain Java "
                 "classes that compile on their own. " + JAVA_RULE,
        "scaffold": HYTALE,
        "quick": [f"{V} gradle compileJava"],
        "final": [f"{V} secrets", f"{V} gradle build"],
    },
    "other": {
        "label": "Script / scraper / small-business automation (Python 3.11 by default)",
        "notes": "Python 3.11+, standard library first; list third-party packages in "
                 "requirements.txt. Config from env vars or a config file, never hardcoded "
                 "secrets. CLI entry point in main.py. Tests with unittest in tests/test_*.py "
                 "that do not hit the network. Respect robots.txt and rate limits for scrapers. "
                 "If the spec asks for Node instead, use package.json with a test script.",
        "scaffold": OTHER,
        "quick": [f"{V} pysyntax", f"{V} jsyntax"],
        "final": [f"{V} pysyntax", f"{V} jsyntax", f"{V} unittest", f"{V} npm_test", f"{V} secrets"],
    },
}


def names(title: str) -> dict:
    words = re.findall(r"[A-Za-z0-9]+", title) or ["Project"]
    slug = "-".join(w.lower() for w in words)[:40].strip("-") or "project"
    name = "".join(w[:1].upper() + w[1:] for w in words)[:40]
    if name[0].isdigit():
        name = "P" + name
    pkg_tail = re.sub(r"[^a-z0-9]", "", name.lower()) or "project"
    if pkg_tail[0].isdigit():
        pkg_tail = "p" + pkg_tail
    package = f"com.commission.{pkg_tail}"
    return {"slug": slug, "Name": name, "Title": title.replace('"', "'"), "package": package,
            "package_path": package.replace(".", "/"), "modid": pkg_tail[:60]}


def scaffold_files(job_type: str, title: str) -> dict[str, str]:
    n = names(title)
    return {path.format(**n): body.format(**n) for path, body in TYPES[job_type]["scaffold"].items()}
