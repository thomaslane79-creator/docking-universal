"""Shell-free launch of the pinned P2Rank Java application.

Matches the upstream prank launcher: 2048 MB heap, identical jar/classpath and
main class, with INSTALL_DIR retained for models/configuration. In particular,
Windows paths and user-selected coordinates are never passed through prank.bat.
"""
from __future__ import annotations

import os
from pathlib import Path
import struct
import subprocess
from uuid import uuid4
from typing import Mapping, Sequence


# Only transports strings into the SAME Main.main(String[]) on the existing
# application classpath. No classloader replacement, model or science changes.
JAVA_ARGUMENT_SOURCE = '''import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.lang.reflect.InvocationTargetException;
public final class NativeArguments {
    public static void main(String[] input) throws Throwable {
        if (input.length != 1) throw new IllegalArgumentException("One argument file required");
        String[] args;
        try (DataInputStream data = new DataInputStream(Files.newInputStream(Paths.get(input[0])))) {
            if (data.readInt() != 0x44554a31) throw new IOException("Invalid argument transport");
            int count = data.readInt();
            if (count < 0 || count > 128) throw new IOException("Invalid argument count");
            args = new String[count];
            for (int i = 0; i < count; i++) {
                int size = data.readInt();
                if (size < 0 || size > 1048576) throw new IOException("Invalid argument length");
                byte[] bytes = new byte[size]; data.readFully(bytes);
                args[i] = new String(bytes, StandardCharsets.UTF_8);
            }
            if (data.read() != -1) throw new IOException("Trailing argument data");
        }
        try {
            Class.forName("cz.siret.prank.program.Main").getMethod("main", String[].class)
                .invoke(null, (Object)args);
        } catch (InvocationTargetException error) { throw error.getCause(); }
    }
}
'''


def write_argument_file(directory: Path, arguments: Sequence[str]) -> Path:
    if len(arguments) > 128:
        raise ValueError("Too many Java transport arguments")
    values = [str(value).encode("utf-8") for value in arguments]
    if any(len(value) > 1048576 for value in values):
        raise ValueError("Java transport argument is too long")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (uuid4().hex + ".bin")
    with path.open("xb") as stream:
        stream.write(b"DUJ1" + struct.pack(">I", len(values)))
        for value in values:
            stream.write(struct.pack(">I", len(value)) + value)
    return path


def prefix_java(prefix: Path) -> Path:
    """Select the Java installed in this scientific prefix, never system PATH."""
    candidates = [prefix / relative for relative in (
        "Library/lib/jvm/bin/java.exe", "Library/bin/java.exe", "Library/openjdk/bin/java.exe",
        "lib/jvm/bin/java", "bin/java",
    )]
    found = [path.resolve() for path in candidates if path.is_file()]
    if not found:
        raise FileNotFoundError("Pinned Java executable was not found inside the scientific prefix")
    return found[0]


def java_invocation(installation: Path, java: Path, arguments: Sequence[str], *,
                    environment: Mapping[str, str] | None = None,
                    windows: bool | None = None) -> tuple[tuple[str, ...], dict[str, str]]:
    installation, java = installation.resolve(), java.resolve()
    if not java.is_file():
        raise FileNotFoundError(f"Pinned Java runtime is unavailable: {java}")
    jar, libraries = installation / "bin/p2rank.jar", installation / "bin/lib"
    if not jar.is_file() or not libraries.is_dir():
        raise FileNotFoundError(f"P2Rank installation is incomplete: {installation}")
    values = dict(os.environ if environment is None else environment)
    values["INSTALL_DIR"] = str(installation)
    # Preserve the Windows prank.bat defaults, not arbitrary shell expansion.
    # The version/model remains the installed, checksum-verified P2Rank asset.
    command = (str(java), "-Xmx2048m", "-cp", str(jar) + os.pathsep + str(libraries / "*"),
               "cz.siret.prank.program.Main", *(str(value) for value in arguments))
    bridge = installation / "docking-universal-launcher"
    if (os.name == "nt" if windows is None else windows) and (bridge / "NativeArguments.class").is_file():
        if not str(bridge).isascii() or not str(java).isascii():
            raise ValueError("Pinned Windows Java/P2Rank requires an ASCII-safe owned runtime directory")
        # Java 17's native Windows launcher cannot transport every Unicode
        # codepoint in argv/classpath. The private ASCII path is the only argv;
        # study strings are decoded as UTF-8 inside Java, without a shell.
        argument_file = write_argument_file(bridge / "arguments", arguments)
        command = (str(java), "-Xmx2048m", "-cp", str(bridge) + os.pathsep + command[3],
                   "NativeArguments", str(argument_file))
    return command, values


def run_p2rank(installation: Path, java: Path, arguments: Sequence[str], *,
               environment: Mapping[str, str] | None = None, **options):
    command, values = java_invocation(installation, java, arguments, environment=environment)
    return subprocess.run(command, env=values, shell=False, **options)
