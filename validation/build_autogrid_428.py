"""Build pinned unmodified AutoGrid 4.2.8 with its documented serial profile."""
import argparse
import os
from pathlib import Path
import subprocess

SOURCES = '''main.cpp bondmanager.cpp bhtree.cpp check_size.cpp setflags.cpp
ad4_shared/timesys.cc ad4_shared/timesyshms.cc ad4_shared/printhms.cc prHMSfixed.cpp
ad4_shared/printdate.cc strindex.cpp banner.cpp gpfparser.cpp parsetypes.cpp
atom_parameter_manager.cpp ad4_shared/read_parameter_library.cc ad4_shared/parse_param_line.cc
distdepdiel.cpp ad4_shared/memalloc.cc ad4_shared/mingw_getrusage.cc calc_vina_potential.cpp
ad4_shared/threadlog.cc ad4_shared/targetfile.cc ad4_shared/stop.cc'''.split()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    env = {**os.environ, 'DEVELOPER_DIR': '/Library/Developer/CommandLineTools'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (args.source / 'default_parameters.h').open('wb') as stream:
        subprocess.run(['/bin/csh', 'ad4_shared/paramdat2h.csh', 'ad4_shared/AD4_parameters.dat',
                        'ad4_shared/AD4.1_bound.dat'], cwd=args.source, stdout=stream, check=True)
    command = ['/usr/bin/clang++', '-O3', '-I.', '-I./ad4_shared', '-Wno-write-strings',
               '-DUSE_8A_NBCUTOFF', '-DUSE_DOUBLE', '-DPACKAGE_VERSION="4.2.8"',
               '-DPACKAGE_BUGREPORT="autodock@scripps.edu"',
               '-DHAVE_SYSCONF', '-DHAVE_GETRUSAGE', '-DHAVE_TIMES', '-DHAVE_GETHOSTNAME',
               '-DHAVE_GETPID', '-DHAVE_FCHMOD', '-DHAVE_SETLINEBUF',
               '-mmacosx-version-min=15.0', *SOURCES, '-o', str(args.output.resolve())]
    print('Command:', repr(command), flush=True)
    subprocess.run(command, cwd=args.source, env=env, check=True)


if __name__ == '__main__':
    main()
