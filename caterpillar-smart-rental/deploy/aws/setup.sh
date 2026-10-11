#!/bin/bash
# Run via SSM on Amazon Linux 2023, from the checked-out application root.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo 'Run with sudo.' >&2; exit 1; }
[[ $# -ge 1 && $# -le 2 && $1 =~ ^vol-[0-9a-f]+$ ]] || {
    echo 'Usage: sudo bash deploy/aws/setup.sh vol-ID [--initialize-empty-volume]' >&2; exit 1;
}
[[ $# -eq 1 || $2 == --initialize-empty-volume ]] || exit 1
volume_id=$1
app_dir=$(pwd -P)
[[ -f $app_dir/deploy/aws/compose.yaml && $app_dir != *[[:space:]]* ]] || {
    echo 'Run from the application root at a path without spaces.' >&2; exit 1;
}

# Nitro device numbers change across boots. Match the EBS serial, never a disk index.
device=$(lsblk -dnro PATH,SERIAL | awk -v serial="${volume_id//-/}" '$2 == serial {print $1}')
[[ -b $device ]] || { echo "EBS device for $volume_id is not attached." >&2; exit 1; }
[[ $(lsblk -nr -o TYPE "$device") == disk ]] || {
    echo 'Refusing a partitioned volume; this deployment uses one whole-disk ext4 filesystem.' >&2; exit 1;
}
if filesystem=$(blkid -p -s TYPE -o value "$device"); then
    :
else
    probe_status=$?
    [[ $probe_status -eq 2 ]] || { echo 'Filesystem probe failed.' >&2; exit 1; }
fi
if [[ -z $filesystem ]]; then
    [[ ${2:-} == --initialize-empty-volume ]] || {
        echo 'Blank volume: explicitly pass --initialize-empty-volume for a new stack only.' >&2; exit 1;
    }
    signatures=$(wipefs --no-act --noheadings --output TYPE "$device")
    [[ -z $signatures ]] || {
        echo 'Refusing to format a volume with existing signatures.' >&2; exit 1;
    }
    mkfs.ext4 "$device"
elif [[ $filesystem != ext4 ]]; then
    echo "Refusing existing $filesystem filesystem; no data was formatted." >&2; exit 1
fi

uuid=$(blkid -s UUID -o value "$device")
[[ -n $uuid ]] || exit 1
mkdir -p /srv/fleetsignal
if mountpoint -q /srv/fleetsignal; then
    [[ $(findmnt -n -o UUID --target /srv/fleetsignal) == "$uuid" ]] || {
        echo 'Mount path already uses another filesystem.' >&2; exit 1;
    }
else
    # Refuse to hide stray root-disk data beneath the EBS mount.
    [[ -z $(find /srv/fleetsignal -mindepth 1 -maxdepth 1 -print -quit) ]] || {
        echo 'Unmounted data path is not empty; inspect it before mounting.' >&2; exit 1;
    }
    mount "$device" /srv/fleetsignal
fi
if ! awk -v uuid="UUID=$uuid" '$1 == uuid && $2 == "/srv/fleetsignal" {found=1} END {exit !found}' /etc/fstab; then
    ! awk '$2 == "/srv/fleetsignal" {found=1} END {exit !found}' /etc/fstab || {
        echo 'Conflicting /etc/fstab entry; inspect it before proceeding.' >&2; exit 1;
    }
    printf 'UUID=%s /srv/fleetsignal ext4 defaults,nofail,x-systemd.device-timeout=30s 0 2\n' "$uuid" >> /etc/fstab
fi
mkdir -p /srv/fleetsignal/db

docker compose -f deploy/aws/compose.yaml config --quiet
docker compose -f deploy/aws/compose.yaml build
cat > /etc/systemd/system/fleetsignal.service <<EOF
[Unit]
Description=FleetSignal single-instance demo
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target
RequiresMountsFor=/srv/fleetsignal

[Service]
Type=simple
WorkingDirectory=$app_dir
ExecStartPre=/usr/bin/mountpoint -q /srv/fleetsignal
ExecStart=/usr/bin/docker compose -f deploy/aws/compose.yaml up --no-build --abort-on-container-exit
ExecStop=/usr/bin/docker compose -f deploy/aws/compose.yaml down --timeout 30
Restart=always
RestartSec=10
TimeoutStopSec=90

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable fleetsignal.service
systemctl restart fleetsignal.service
echo 'Check: systemctl status fleetsignal; curl --fail http://127.0.0.1:8080/api/ready'
