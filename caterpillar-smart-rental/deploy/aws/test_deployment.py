"""Local CIDR and mocked setup safety checks. Run from any directory with Python and Docker.

Disk checks run only in a disposable container with tmpfs test paths; no host
devices are passed through. Disk commands, formatting, mounts and services are stubbed.
"""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]


def check_cidrs():
    template = (ROOT / 'deploy/aws/cloudformation.yaml').read_text(encoding='utf-8')
    pattern = re.compile(re.search(r"^    AllowedPattern: '(.*)'$", template, re.MULTILINE)[1])
    accepted = ('', '10.0.0.0/32', '10.255.255.255/32', '172.16.0.0/32',
                '172.31.255.255/32', '192.168.0.0/32', '192.168.255.255/32')
    rejected = ('10.999.1.1/32', '10.1.999.1/32', '10.1.1.999/32', '10.256.0.0/32',
                '172.16.256.0/32', '172.31.0.256/32', '192.168.999.1/32',
                '192.168.1.256/32', '10.-1.0.0/32', '10.01.0.0/32',
                '172.15.0.1/32', '172.32.0.1/32', '192.169.0.1/32',
                '8.8.8.8/32', '127.0.0.1/32', '0.0.0.0/0', '10.0.0.1/31',
                '10.0.0.1', '::1/128', '10.0.0.1/32\n')
    for value in accepted:
        assert pattern.fullmatch(value), f'Valid private /32 rejected: {value!r}'
    for value in rejected:
        assert not pattern.fullmatch(value), f'Invalid CIDR accepted: {value!r}'
    print(f'PASS: {len(accepted) + len(rejected)} CIDR acceptance/rejection cases', flush=True)


def check_disk_guards():
    mounts = {fields[1]: fields[2] for line in Path('/proc/mounts').read_text().splitlines()
              if len(fields := line.split()) >= 3}
    assert Path('/.dockerenv').exists() and os.geteuid() == 0, 'Use the Docker launcher.'
    assert all(mounts.get(path) == 'tmpfs' for path in ('/etc', '/srv', '/tmp')), \
        'Refusing to modify paths outside the disposable tmpfs mounts.'
    with tempfile.TemporaryDirectory() as temporary:
        scratch = Path(temporary)
        device = scratch / 'ebs'
        os.mknod(device, stat.S_IFBLK | 0o600, os.makedev(7, 199))
        marker = scratch / 'formatted'
        mount_marker = scratch / 'mounts'
        activity_marker = scratch / 'app-commands'
        commands = scratch / 'bin'
        commands.mkdir()
        # /etc is tmpfs, so Debian's /usr/bin/awk -> /etc/alternatives/awk is hidden.
        (commands / 'awk').symlink_to('/usr/bin/mawk')
        stub = '''#!/bin/bash
case "$(basename "$0")" in
  lsblk)
    if [[ $* == *PATH,SERIAL* ]]; then
      printf '%s %s\\n' "$TEST_DEVICE" "${TEST_SERIAL:-vol1234567890abcdef0}"
    else printf '%b\\n' "${TEST_PARTITIONS:-disk}"; fi ;;
  blkid)
    if [[ $* == *TYPE* ]]; then printf '%s' "${TEST_FS-ext4}"; exit "${TEST_PROBE_EXIT:-0}"
    else echo 12345678-1234-1234-1234-123456789abc; fi ;;
  wipefs) printf '%s' "${TEST_SIGNATURE:-}"; exit "${TEST_WIPE_EXIT:-0}" ;;
  mkfs.ext4) echo formatted >> "$TEST_MARKER" ;;
  mountpoint) exit "${TEST_MOUNTPOINT_EXIT:-1}" ;;
  findmnt) echo "${TEST_MOUNT_UUID:-12345678-1234-1234-1234-123456789abc}" ;;
  mount) echo "$*" >> "$TEST_MOUNT_MARKER" ;;
  docker|systemctl) echo "$(basename "$0") $*" >> "$TEST_ACTIVITY_MARKER" ;;
esac
'''
        for name in ('lsblk', 'blkid', 'wipefs', 'mkfs.ext4', 'mountpoint', 'findmnt', 'mount', 'docker', 'systemctl'):
            executable = commands / name
            executable.write_text(stub, encoding='utf-8')
            executable.chmod(0o755)
        Path('/etc/systemd/system').mkdir(parents=True, exist_ok=True)
        cases = [
            ('wrong serial', {'TEST_SERIAL': 'volfffffffffffffffff'}, True, False, False),
            ('partitioned disk', {'TEST_PARTITIONS': 'disk\\npart'}, True, False, False),
            ('unsupported existing filesystem', {'TEST_FS': 'xfs'}, True, False, False),
            ('blank without opt-in', {'TEST_FS': '', 'TEST_PROBE_EXIT': '2'}, False, False, False),
            ('ambiguous probe', {'TEST_FS': '', 'TEST_PROBE_EXIT': '8'}, True, False, False),
            ('existing signatures', {'TEST_FS': '', 'TEST_PROBE_EXIT': '2', 'TEST_SIGNATURE': 'gpt'}, True, False, False),
            ('signature probe failure', {'TEST_FS': '', 'TEST_PROBE_EXIT': '2', 'TEST_WIPE_EXIT': '1'}, True, False, False),
            ('new blank volume with opt-in', {'TEST_FS': '', 'TEST_PROBE_EXIT': '2'}, True, True, True),
            ('reuse ext4 with opt-in', {}, True, True, False),
            ('reuse ext4 without opt-in', {}, False, True, False),
            ('already mounted matching UUID', {
                'TEST_MOUNTPOINT_EXIT': '0',
                'TEST_FSTAB': 'UUID=12345678-1234-1234-1234-123456789abc /srv/fleetsignal ext4 defaults 0 2\n',
            }, False, True, False),
            ('already mounted wrong UUID', {
                'TEST_MOUNTPOINT_EXIT': '0', 'TEST_MOUNT_UUID': '00000000-0000-0000-0000-000000000000',
            }, False, False, False),
            ('non-empty unmounted data directory', {'TEST_STRAY_DATA': 'retained data'}, False, False, False),
            ('conflicting fstab entry', {
                'TEST_FSTAB': 'UUID=00000000-0000-0000-0000-000000000000 /srv/fleetsignal ext4 defaults 0 2\n',
            }, False, False, False),
        ]
        expected_errors = {
            'already mounted wrong UUID': 'Mount path already uses another filesystem.',
            'non-empty unmounted data directory': 'Unmounted data path is not empty;',
            'conflicting fstab entry': 'Conflicting /etc/fstab entry;',
        }
        for name, values, opt_in, success, formats in cases:
            for observed in (marker, mount_marker, activity_marker):
                observed.unlink(missing_ok=True)
            initial_fstab = values.get('TEST_FSTAB', '')
            Path('/etc/fstab').write_text(initial_fstab, encoding='utf-8')
            data_path = Path('/srv/fleetsignal/db')
            if data_path.exists():
                data_path.rmdir()
            stray_path = Path('/srv/fleetsignal/retained.db')
            stray_path.unlink(missing_ok=True)
            if 'TEST_STRAY_DATA' in values:
                stray_path.parent.mkdir(parents=True, exist_ok=True)
                stray_path.write_text(values['TEST_STRAY_DATA'], encoding='utf-8')
            environment = {**os.environ, 'PATH': f'{commands}:{os.environ["PATH"]}',
                           'TEST_DEVICE': str(device), 'TEST_MARKER': str(marker),
                           'TEST_MOUNT_MARKER': str(mount_marker),
                           'TEST_ACTIVITY_MARKER': str(activity_marker), **values}
            result = subprocess.run(['bash', 'deploy/aws/setup.sh', 'vol-1234567890abcdef0'] +
                                    (['--initialize-empty-volume'] if opt_in else []),
                                    cwd=ROOT, env=environment, capture_output=True, text=True)
            assert (result.returncode == 0) == success, (name, result.stdout, result.stderr)
            assert marker.exists() == formats, (name, 'unexpected formatting', result.stdout, result.stderr)
            assert activity_marker.exists() == success, (name, 'unexpected app commands')
            if name in expected_errors:
                assert expected_errors[name] in result.stderr, (name, result.stderr)
            if values.get('TEST_MOUNTPOINT_EXIT') == '0' or 'TEST_STRAY_DATA' in values:
                assert not mount_marker.exists(), (name, 'unexpected mount attempt')
            if not success or initial_fstab:
                assert Path('/etc/fstab').read_text() == initial_fstab, (name, 'fstab changed')
            if 'TEST_STRAY_DATA' in values:
                assert stray_path.read_text() == values['TEST_STRAY_DATA'], (name, 'retained data changed')
            print(f'PASS: {name}', flush=True)
    print(f'{len(cases)} mocked storage safety checks passed; no real EBS or filesystem format was performed.')


if __name__ == '__main__':
    if sys.argv[1:] == ['--container-checks']:
        check_disk_guards()
    elif not sys.argv[1:]:
        check_cidrs()
        subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--read-only',
            '--cap-drop', 'ALL', '--cap-add', 'MKNOD',
            '--tmpfs', '/etc:rw,noexec,nosuid,size=16m',
            '--tmpfs', '/srv:rw,noexec,nosuid,size=16m',
            '--tmpfs', '/tmp:rw,exec,nosuid,size=16m',
            '--mount', f'type=bind,source={ROOT},target=/workspace,readonly',
            '--workdir', '/workspace', 'python:3.11-slim',
            'python', 'deploy/aws/test_deployment.py', '--container-checks',
        ], check=True)
    else:
        raise SystemExit('Usage: python deploy/aws/test_deployment.py')
